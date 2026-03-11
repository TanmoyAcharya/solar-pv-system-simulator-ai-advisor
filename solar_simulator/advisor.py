from __future__ import annotations

from dataclasses import replace
from math import ceil
from typing import Dict, Optional, Union

from .models import AdviceItem, AdvisorReport, SimulationResult, SystemInputs, WeatherProfile
from .simulator import clamp, simulate_system


def recommendation_score(inputs: SystemInputs, result: SimulationResult) -> int:
    economics = 8
    if result.payback_years is not None:
        if result.payback_years <= 6:
            economics = 35
        elif result.payback_years <= 8:
            economics = 31
        elif result.payback_years <= 10:
            economics = 26
        elif result.payback_years <= 12:
            economics = 20
        else:
            economics = 14

    energy_fit = int(clamp(result.solar_offset_pct / max(inputs.target_offset_pct, 1.0), 0.2, 1.05) * 35)
    design_fit = int(((result.orientation_factor * 0.65) + ((100.0 - min(result.roof_utilization_pct, 100.0)) / 100.0) * 0.35) * 20)
    resilience = 5
    if result.peak_period_coverage_pct >= 75.0:
        resilience = 12
    elif inputs.load_profile == "Evening heavy" and inputs.battery_capacity_kwh >= result.array_kw * 1.0:
        resilience = 10
    elif result.export_ratio_pct < 18.0:
        resilience = 8

    return int(clamp(economics + energy_fit + design_fit + resilience, 25, 98))


def recommended_panel_count(inputs: SystemInputs, result: SimulationResult) -> int:
    annual_target_kwh = result.annual_load_kwh * (inputs.target_offset_pct / 100.0)
    annual_kwh_per_panel = result.annual_generation_kwh / max(inputs.panel_count, 1)
    raw_recommendation = ceil(annual_target_kwh / max(annual_kwh_per_panel, 1.0))
    bounded = max(1, min(raw_recommendation, result.max_panels_by_roof))
    return bounded


def recommended_battery_kwh(inputs: SystemInputs, result: SimulationResult) -> float:
    if result.export_ratio_pct < 18.0 and result.peak_period_coverage_pct >= 70.0:
        return round(inputs.battery_capacity_kwh, 1)

    suggested = min(result.array_kw * 2.0, result.annual_export_kwh / 365.0 * 1.1)
    if inputs.load_profile == "Evening heavy":
        suggested *= 1.2
    if inputs.peak_import_rate > inputs.offpeak_import_rate * 1.5:
        suggested = max(suggested, result.array_kw * 1.4)
    return round(max(inputs.battery_capacity_kwh, suggested), 1)


def build_advice_items(inputs: SystemInputs, result: SimulationResult, panel_target: int, battery_target: float) -> list[AdviceItem]:
    items: list[AdviceItem] = []

    if inputs.panel_count > result.max_panels_by_roof:
        items.append(
            AdviceItem(
                title="Roof capacity exceeded",
                impact="High",
                detail=f"The current layout uses more module area than the roof can realistically host. Max practical count is {result.max_panels_by_roof} panels.",
                action=f"Reduce the design to {result.max_panels_by_roof} panels or increase usable roof area.",
            )
        )

    if result.solar_offset_pct + 8.0 < inputs.target_offset_pct and panel_target > inputs.panel_count:
        items.append(
            AdviceItem(
                title="Array is undersized for the stated target",
                impact="High",
                detail=f"The current design covers {result.solar_offset_pct:.0f}% of annual demand against a {inputs.target_offset_pct:.0f}% target.",
                action=f"Increase the array from {inputs.panel_count} to about {panel_target} panels if roof area and budget allow.",
            )
        )

    if result.orientation_factor < 0.9:
        items.append(
            AdviceItem(
                title="Module orientation is leaving yield on the table",
                impact="Medium",
                detail=f"Current tilt/azimuth performance factor is {result.orientation_factor:.2f}, below a well-aligned layout.",
                action=f"Move tilt toward {result.optimal_tilt_deg:.0f} degrees and azimuth toward {result.optimal_azimuth_deg:.0f} degrees.",
            )
        )

    if result.export_ratio_pct > 28.0 and inputs.feed_in_tariff < inputs.electricity_rate * 0.6:
        items.append(
            AdviceItem(
                title="Too much energy is being exported cheaply",
                impact="Medium",
                detail=f"About {result.export_ratio_pct:.0f}% of annual production is exported while the feed-in tariff is well below retail power cost.",
                action=f"Add or increase storage toward about {battery_target:.1f} kWh, or trim the array to focus on self-consumption.",
            )
        )

    if result.peak_period_coverage_pct < 55.0 and inputs.peak_import_rate > inputs.offpeak_import_rate * 1.35:
        items.append(
            AdviceItem(
                title="Peak tariff exposure remains high",
                impact="High",
                detail=f"Only about {result.peak_period_coverage_pct:.0f}% of peak-period demand is being covered after storage dispatch.",
                action="Increase storage power or capacity, shift flexible loads into solar hours, and review peak window settings.",
            )
        )

    if result.payback_years is not None and result.payback_years > 11.0:
        items.append(
            AdviceItem(
                title="Economics are currently soft",
                impact="Medium",
                detail=f"Simple payback is about {result.payback_years:.1f} years, which is long for a straightforward rooftop PV project.",
                action="Lower installed cost, improve self-consumption, or reduce oversizing to tighten payback.",
            )
        )

    if inputs.shade_loss_pct >= 12.0:
        items.append(
            AdviceItem(
                title="Shade losses are material",
                impact="Medium",
                detail=f"Shade assumptions remove roughly {inputs.shade_loss_pct:.0f}% of output before other losses are counted.",
                action="Revisit string layout, trimming, or MLPE selection to recover yield.",
            )
        )

    if result.roof_utilization_pct > 92.0:
        items.append(
            AdviceItem(
                title="Roof density is aggressive",
                impact="Low",
                detail="The design is using nearly all practical roof space, leaving little room for access, spacing, and maintenance setbacks.",
                action="Reserve margin for setbacks and maintenance routes before finalizing the layout.",
            )
        )

    if not items:
        items.append(
            AdviceItem(
                title="Design is broadly in range",
                impact="Low",
                detail="The system is reasonably aligned with the stated target, roof area, and tariff structure.",
                action="Use the scenario table to compare whether a slightly smaller or slightly larger array improves value.",
            )
        )

    return items


def scenario_row(name: str, result: SimulationResult) -> Dict[str, Union[float, int, str]]:
    return {
        "Scenario": name,
        "Array kW": result.array_kw,
        "Load coverage %": result.solar_offset_pct,
        "Self-consumption %": result.self_consumption_pct,
        "Savings / year": round(result.annual_savings, 0),
        "Net bill / year": round(result.annual_import_cost - result.annual_export_revenue, 0),
        "Payback years": result.payback_years if result.payback_years is not None else "n/a",
        "Export %": result.export_ratio_pct,
        "Peak coverage %": result.peak_period_coverage_pct,
    }


def build_scenarios(
    inputs: SystemInputs,
    result: SimulationResult,
    panel_target: int,
    battery_target: float,
    weather_profile: Optional[WeatherProfile] = None,
) -> list[Dict[str, Union[float, int, str]]]:
    scenarios = [scenario_row("Current", result)]

    demand_match_inputs = replace(
        inputs,
        panel_count=panel_target,
        battery_capacity_kwh=max(inputs.battery_capacity_kwh, battery_target if inputs.load_profile != "Daytime heavy" else inputs.battery_capacity_kwh),
    )
    demand_match_result = simulate_system(demand_match_inputs, weather_profile=weather_profile)
    scenarios.append(scenario_row("Demand-match", demand_match_result))

    self_use_inputs = replace(
        inputs,
        panel_count=max(1, min(inputs.panel_count, panel_target)),
        battery_capacity_kwh=max(inputs.battery_capacity_kwh, battery_target),
    )
    self_use_result = simulate_system(self_use_inputs, weather_profile=weather_profile)
    scenarios.append(scenario_row("Self-use boost", self_use_result))

    roof_max_inputs = replace(inputs, panel_count=result.max_panels_by_roof)
    roof_max_result = simulate_system(roof_max_inputs, weather_profile=weather_profile)
    scenarios.append(scenario_row("Roof max", roof_max_result))

    return scenarios


def generate_advisor_report(
    inputs: SystemInputs,
    result: SimulationResult,
    weather_profile: Optional[WeatherProfile] = None,
) -> AdvisorReport:
    panel_target = recommended_panel_count(inputs, result)
    battery_target = recommended_battery_kwh(inputs, result)
    items = build_advice_items(inputs, result, panel_target, battery_target)
    score = recommendation_score(inputs, result)

    lead_action = items[0].action if items else "Review the scenario table and refine array size."
    summary = (
        f"The current design delivers about {result.annual_generation_kwh:,.0f} kWh/year, covers {result.solar_offset_pct:.0f}% of site demand, "
        f"and returns roughly {result.annual_savings:,.0f} in annual value. Primary next move: {lead_action}"
    )

    return AdvisorReport(
        score=score,
        summary=summary,
        recommended_panel_count=panel_target,
        recommended_battery_kwh=battery_target,
        recommended_tilt_deg=result.optimal_tilt_deg,
        recommended_azimuth_deg=result.optimal_azimuth_deg,
        items=items,
        scenarios=build_scenarios(inputs, result, panel_target, battery_target, weather_profile=weather_profile),
    )
