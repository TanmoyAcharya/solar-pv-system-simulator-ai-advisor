from __future__ import annotations

import math
from calendar import monthrange
from datetime import date
from datetime import datetime
from typing import Dict, Optional, Union

from .models import SimulationResult, SystemInputs, WeatherProfile


MONTH_NAMES = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def optimal_tilt(latitude: float) -> float:
    return round(clamp(abs(latitude) * 0.76 + 3.0, 8.0, 38.0), 1)


def optimal_azimuth(latitude: float) -> float:
    return 180.0 if latitude >= 0 else 0.0


def shortest_angle_distance(angle_a: float, angle_b: float) -> float:
    delta = abs((angle_a - angle_b) % 360)
    return min(delta, 360 - delta)


def seasonal_profile(latitude: float) -> list[float]:
    base_north = [0.74, 0.79, 0.91, 1.01, 1.10, 1.16, 1.20, 1.15, 1.03, 0.92, 0.81, 0.74]
    blend = clamp(abs(latitude) / 35.0, 0.15, 1.0)
    shaped = [1.0 + (value - 1.0) * blend for value in base_north]
    if latitude < 0:
        return shaped[6:] + shaped[:6]
    return shaped


def monthly_days() -> list[int]:
    year = date.today().year
    return [monthrange(year, month)[1] for month in range(1, 13)]


def roof_capacity_panels(panel_area_m2: float, roof_area_m2: float) -> int:
    usable_roof_area = roof_area_m2 * 0.82
    return max(1, math.floor(usable_roof_area / panel_area_m2))


def panel_area(panel_wattage: float, panel_efficiency_pct: float) -> float:
    efficiency = clamp(panel_efficiency_pct / 100.0, 0.12, 0.30)
    return panel_wattage / (efficiency * 1000.0)


def performance_ratio(inputs: SystemInputs) -> float:
    losses = 1.0 - clamp(inputs.system_losses_pct / 100.0, 0.0, 0.35)
    shade = 1.0 - clamp(inputs.shade_loss_pct / 100.0, 0.0, 0.35)
    inverter = clamp(inputs.inverter_efficiency_pct / 100.0, 0.85, 0.99)
    return clamp(losses * shade * inverter, 0.52, 0.96)


def orientation_factor(inputs: SystemInputs, optimal_tilt_deg: float, optimal_azimuth_deg: float) -> float:
    tilt_delta = abs(inputs.tilt_deg - optimal_tilt_deg)
    azimuth_delta = shortest_angle_distance(inputs.azimuth_deg, optimal_azimuth_deg)
    tilt_factor = clamp(1.0 - 0.18 * (tilt_delta / 45.0), 0.80, 1.0)
    azimuth_factor = clamp(0.62 + 0.38 * ((math.cos(math.radians(azimuth_delta)) + 1.0) / 2.0), 0.62, 1.0)
    return clamp(tilt_factor * azimuth_factor, 0.55, 1.0)


def monthly_load_profile(annual_load_kwh: float, latitude: float) -> list[float]:
    base_profile = [1.03, 1.02, 1.00, 0.98, 0.96, 0.95, 0.95, 0.96, 0.98, 1.00, 1.03, 1.04]
    blend = clamp(abs(latitude) / 50.0, 0.08, 0.30)
    shaped = [1.0 + (value - 1.0) * blend for value in base_profile]
    if latitude < 0:
        shaped = shaped[6:] + shaped[:6]
    normalization = sum(shaped)
    return [annual_load_kwh * (factor / normalization) for factor in shaped]


def temperature_factor(ambient_temp_c: float) -> float:
    return clamp(1.0 - (ambient_temp_c - 25.0) * 0.0035, 0.84, 1.06)


def iter_datetimes_for_year(year: int) -> list[datetime]:
    datetimes: list[datetime] = []
    for month in range(1, 13):
        for day in range(1, monthrange(year, month)[1] + 1):
            for hour in range(24):
                datetimes.append(datetime(year, month, day, hour))
    return datetimes


def daylight_hours(latitude: float, day_of_year: int) -> float:
    latitude_rad = math.radians(clamp(latitude, -66.0, 66.0))
    declination = math.radians(23.44) * math.sin(math.radians((360.0 / 365.0) * (day_of_year - 81)))
    cosine_hour_angle = -math.tan(latitude_rad) * math.tan(declination)
    cosine_hour_angle = clamp(cosine_hour_angle, -1.0, 1.0)
    return 24.0 * math.acos(cosine_hour_angle) / math.pi


def synthetic_hourly_generation(inputs: SystemInputs, monthly_generation_kwh: list[float]) -> tuple[list[datetime], list[float]]:
    datetimes = iter_datetimes_for_year(inputs.weather_year)
    hourly_weights: list[float] = []
    month_totals = [0.0] * 12

    for timestamp in datetimes:
        day_of_year = timestamp.timetuple().tm_yday
        daylight = max(0.0, daylight_hours(inputs.latitude, day_of_year))
        sunrise = 12.0 - daylight / 2.0
        sunset = 12.0 + daylight / 2.0
        solar_midpoint = timestamp.hour + 0.5
        if sunrise <= solar_midpoint <= sunset and daylight > 0:
            normalized = (solar_midpoint - sunrise) / daylight
            weight = max(math.sin(math.pi * normalized), 0.0) ** 1.7
        else:
            weight = 0.0
        hourly_weights.append(weight)
        month_totals[timestamp.month - 1] += weight

    hourly_generation: list[float] = []
    for timestamp, weight in zip(datetimes, hourly_weights):
        month_index = timestamp.month - 1
        denominator = month_totals[month_index]
        if denominator <= 0:
            hourly_generation.append(0.0)
        else:
            hourly_generation.append(monthly_generation_kwh[month_index] * (weight / denominator))
    return datetimes, hourly_generation


def hourly_generation_from_weather(inputs: SystemInputs, weather_profile: WeatherProfile) -> tuple[list[datetime], list[float]]:
    array_kw = inputs.panel_count * inputs.panel_wattage / 1000.0
    system_pr = performance_ratio(inputs)
    datetimes = [datetime.fromisoformat(value) for value in weather_profile.hourly_time]

    hourly_generation: list[float] = []
    for irradiance, ambient_temp in zip(
        weather_profile.hourly_irradiance_w_m2,
        weather_profile.hourly_temperature_c,
    ):
        hourly_generation.append(array_kw * (irradiance / 1000.0) * system_pr * temperature_factor(ambient_temp))
    return datetimes, hourly_generation


def hourly_load_shape(load_profile: str) -> list[float]:
    shapes = {
        "Balanced": [0.62, 0.58, 0.56, 0.56, 0.60, 0.74, 0.95, 1.08, 1.00, 0.92, 0.90, 0.92, 0.96, 1.00, 1.02, 1.04, 1.08, 1.18, 1.26, 1.34, 1.28, 1.05, 0.84, 0.70],
        "Daytime heavy": [0.50, 0.47, 0.45, 0.45, 0.48, 0.60, 0.82, 1.04, 1.18, 1.25, 1.30, 1.34, 1.33, 1.28, 1.22, 1.16, 1.08, 1.00, 0.94, 0.88, 0.82, 0.72, 0.62, 0.55],
        "Evening heavy": [0.54, 0.50, 0.48, 0.48, 0.52, 0.62, 0.78, 0.88, 0.86, 0.80, 0.78, 0.80, 0.84, 0.88, 0.94, 1.02, 1.14, 1.32, 1.52, 1.66, 1.56, 1.24, 0.92, 0.68],
    }
    return shapes[load_profile]


def build_hourly_load_profile(inputs: SystemInputs, datetimes: list[datetime], annual_load_kwh: float) -> list[float]:
    monthly_factors = monthly_load_profile(annual_load_kwh, inputs.latitude)
    hourly_factors = hourly_load_shape(inputs.load_profile)

    raw_weights: list[float] = []
    for timestamp in datetimes:
        month_weight = monthly_factors[timestamp.month - 1]
        hour_weight = hourly_factors[timestamp.hour]
        weekend_factor = 0.94 if timestamp.weekday() >= 5 and inputs.load_profile == "Daytime heavy" else 1.0
        weekend_factor = 1.03 if timestamp.weekday() >= 5 and inputs.load_profile == "Evening heavy" else weekend_factor
        raw_weights.append(month_weight * hour_weight * weekend_factor)

    normalization = sum(raw_weights)
    return [annual_load_kwh * (weight / normalization) for weight in raw_weights]


def hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def tariff_tier_for_hour(inputs: SystemInputs, hour: int) -> str:
    if hour_in_window(hour, inputs.peak_start_hour, inputs.peak_end_hour):
        return "Peak"
    if hour_in_window(hour, inputs.shoulder_start_hour, inputs.shoulder_end_hour):
        return "Shoulder"
    return "Off-peak"


def tariff_rate_for_hour(inputs: SystemInputs, hour: int) -> float:
    tier = tariff_tier_for_hour(inputs, hour)
    if tier == "Peak":
        return inputs.peak_import_rate
    if tier == "Shoulder":
        return inputs.shoulder_import_rate
    return inputs.offpeak_import_rate


def aggregate_by_month(datetimes: list[datetime], values: list[float]) -> list[float]:
    monthly = [0.0] * 12
    for timestamp, value in zip(datetimes, values):
        monthly[timestamp.month - 1] += value
    return [round(value, 1) for value in monthly]


def average_by_hour(datetimes: list[datetime], values: list[float]) -> list[float]:
    totals = [0.0] * 24
    counts = [0] * 24
    for timestamp, value in zip(datetimes, values):
        totals[timestamp.hour] += value
        counts[timestamp.hour] += 1
    return [round(totals[hour] / max(counts[hour], 1), 2) for hour in range(24)]


def run_battery_dispatch(inputs: SystemInputs, datetimes: list[datetime], generation: list[float], load: list[float]) -> Dict[str, Union[list[float], float]]:
    battery_capacity = max(0.0, inputs.battery_capacity_kwh)
    battery_power = max(0.0, inputs.battery_power_kw)
    reserve_soc = battery_capacity * 0.05
    roundtrip_efficiency = clamp(inputs.battery_roundtrip_efficiency_pct / 100.0, 0.70, 0.98)
    charge_efficiency = math.sqrt(roundtrip_efficiency)
    discharge_efficiency = math.sqrt(roundtrip_efficiency)

    self_consumed_solar: list[float] = []
    export: list[float] = []
    grid_import_total: list[float] = []
    load_grid_import: list[float] = []
    import_cost: list[float] = []
    export_revenue: list[float] = []
    soc_trace: list[float] = []

    solar_charge_input_total = 0.0
    grid_charge_input_total = 0.0
    battery_discharge_output_total = 0.0

    soc_solar = 0.0
    soc_grid = 0.0
    index = 0
    while index < len(datetimes):
        current_day = datetimes[index].date()
        day_indices: list[int] = []
        while index < len(datetimes) and datetimes[index].date() == current_day:
            day_indices.append(index)
            index += 1

        direct_deficits = [max(load[position] - generation[position], 0.0) for position in day_indices]
        future_peak_load_after = [0.0] * len(day_indices)
        running_peak_load = 0.0
        for offset in range(len(day_indices) - 1, -1, -1):
            future_peak_load_after[offset] = running_peak_load
            position = day_indices[offset]
            if tariff_tier_for_hour(inputs, datetimes[position].hour) == "Peak":
                running_peak_load += direct_deficits[offset]

        for offset, position in enumerate(day_indices):
            timestamp = datetimes[position]
            rate = tariff_rate_for_hour(inputs, timestamp.hour)
            tier = tariff_tier_for_hour(inputs, timestamp.hour)

            soc_total = soc_solar + soc_grid
            direct_pv_to_load = min(load[position], generation[position])
            remaining_load = load[position] - direct_pv_to_load
            excess_solar = max(generation[position] - direct_pv_to_load, 0.0)

            if battery_capacity > 0 and battery_power > 0 and excess_solar > 0:
                max_charge_input = min(battery_power, max((battery_capacity - soc_total) / charge_efficiency, 0.0))
                solar_charge_input = min(excess_solar, max_charge_input)
            else:
                solar_charge_input = 0.0
            stored_from_solar = solar_charge_input * charge_efficiency
            soc_solar += stored_from_solar
            solar_charge_input_total += solar_charge_input
            excess_solar -= solar_charge_input

            desired_future_soc = reserve_soc
            if battery_capacity > 0:
                desired_future_soc += min(battery_capacity - reserve_soc, future_peak_load_after[offset] / discharge_efficiency)

            soc_total = soc_solar + soc_grid
            available_output = min(battery_power, max(soc_total - reserve_soc, 0.0) * discharge_efficiency)
            if tier == "Peak":
                discharge_cap = available_output
            elif tier == "Shoulder" and future_peak_load_after[offset] > 0:
                discharge_cap = min(available_output, max(soc_total - desired_future_soc, 0.0) * discharge_efficiency)
            elif tier == "Shoulder":
                discharge_cap = available_output
            else:
                discharge_cap = 0.0

            battery_to_load = min(remaining_load, discharge_cap)
            energy_drawn_from_battery = battery_to_load / discharge_efficiency if discharge_efficiency > 0 else 0.0
            solar_draw = min(soc_solar, energy_drawn_from_battery)
            grid_draw = max(energy_drawn_from_battery - solar_draw, 0.0)
            soc_solar -= solar_draw
            soc_grid -= grid_draw
            solar_battery_to_load = solar_draw * discharge_efficiency
            battery_discharge_output_total += battery_to_load
            remaining_load -= battery_to_load

            soc_total = soc_solar + soc_grid
            if inputs.grid_charge_enabled and tier == "Off-peak" and battery_capacity > 0 and battery_power > 0 and desired_future_soc > soc_total:
                max_grid_charge_input = min(battery_power, max((desired_future_soc - soc_total) / charge_efficiency, 0.0))
                grid_charge_input = max_grid_charge_input
            else:
                grid_charge_input = 0.0
            stored_from_grid = grid_charge_input * charge_efficiency
            soc_grid += stored_from_grid
            grid_charge_input_total += grid_charge_input

            total_grid_import = remaining_load + grid_charge_input
            self_consumed_solar.append(direct_pv_to_load + solar_battery_to_load)
            export.append(excess_solar)
            load_grid_import.append(remaining_load)
            grid_import_total.append(total_grid_import)
            import_cost.append(total_grid_import * rate)
            export_revenue.append(excess_solar * inputs.feed_in_tariff)
            soc_trace.append(soc_solar + soc_grid)

    peak_baseline_load = sum(
        load[position]
        for position, timestamp in enumerate(datetimes)
        if tariff_tier_for_hour(inputs, timestamp.hour) == "Peak"
    )
    peak_grid_after = sum(
        load_grid_import[position]
        for position, timestamp in enumerate(datetimes)
        if tariff_tier_for_hour(inputs, timestamp.hour) == "Peak"
    )
    peak_period_coverage_pct = clamp(1.0 - peak_grid_after / max(peak_baseline_load, 1.0), 0.0, 1.0) * 100.0
    battery_cycles = battery_discharge_output_total / max(battery_capacity, 1.0) if battery_capacity > 0 else 0.0

    return {
        "self_consumed_solar": self_consumed_solar,
        "export": export,
        "grid_import_total": grid_import_total,
        "load_grid_import": load_grid_import,
        "import_cost": import_cost,
        "export_revenue": export_revenue,
        "soc_trace": soc_trace,
        "peak_period_coverage_pct": peak_period_coverage_pct,
        "solar_charge_input_total": solar_charge_input_total,
        "grid_charge_input_total": grid_charge_input_total,
        "battery_discharge_output_total": battery_discharge_output_total,
        "battery_cycles": battery_cycles,
    }


def simulate_system(inputs: SystemInputs, weather_profile: Optional[WeatherProfile] = None) -> SimulationResult:
    monthly_shape = seasonal_profile(inputs.latitude)
    day_counts = monthly_days()
    system_pr = performance_ratio(inputs)
    best_tilt = optimal_tilt(inputs.latitude)
    best_azimuth = optimal_azimuth(inputs.latitude)
    facing_factor = orientation_factor(inputs, best_tilt, best_azimuth)
    panel_area_m2 = panel_area(inputs.panel_wattage, inputs.panel_efficiency_pct)
    total_panel_area_m2 = panel_area_m2 * inputs.panel_count
    max_panels = roof_capacity_panels(panel_area_m2, inputs.roof_area_m2)
    roof_utilization_pct = clamp(total_panel_area_m2 / max(inputs.roof_area_m2 * 0.82, 0.1), 0.0, 1.5) * 100.0
    array_kw = inputs.panel_count * inputs.panel_wattage / 1000.0
    irradiance_factor = clamp(inputs.peak_irradiance_w_m2 / 1000.0, 0.75, 1.15)

    baseline_monthly_generation_kwh: list[float] = []
    for days, month_factor in zip(day_counts, monthly_shape):
        generation = array_kw * inputs.avg_sun_hours * days * month_factor * irradiance_factor * system_pr * facing_factor
        baseline_monthly_generation_kwh.append(round(generation, 1))

    annual_load_kwh = (inputs.monthly_bill / max(inputs.electricity_rate, 0.01)) * 12.0
    if weather_profile is not None:
        datetimes, hourly_generation_kwh = hourly_generation_from_weather(inputs, weather_profile)
        weather_source = weather_profile.source
        resolved_location_name = weather_profile.resolved_name
        weather_year = weather_profile.year
    else:
        datetimes, hourly_generation_kwh = synthetic_hourly_generation(inputs, baseline_monthly_generation_kwh)
        weather_source = "Synthetic irradiance profile"
        resolved_location_name = inputs.location_query or inputs.site_name
        weather_year = inputs.weather_year

    hourly_load_kwh = build_hourly_load_profile(inputs, datetimes, annual_load_kwh)
    dispatch = run_battery_dispatch(inputs, datetimes, hourly_generation_kwh, hourly_load_kwh)

    monthly_generation_kwh = aggregate_by_month(datetimes, hourly_generation_kwh)
    monthly_load_kwh = aggregate_by_month(datetimes, hourly_load_kwh)
    monthly_self_consumed_kwh = aggregate_by_month(datetimes, dispatch["self_consumed_solar"])
    monthly_export_kwh = aggregate_by_month(datetimes, dispatch["export"])
    monthly_import_cost = aggregate_by_month(datetimes, dispatch["import_cost"])
    monthly_export_revenue = aggregate_by_month(datetimes, dispatch["export_revenue"])
    monthly_net_savings = [
        round(baseline - import_cost + export_revenue, 1)
        for baseline, import_cost, export_revenue in zip(
            aggregate_by_month(
                datetimes,
                [load * tariff_rate_for_hour(inputs, timestamp.hour) for load, timestamp in zip(hourly_load_kwh, datetimes)],
            ),
            monthly_import_cost,
            monthly_export_revenue,
        )
    ]

    annual_generation_kwh = round(sum(monthly_generation_kwh), 1)
    annual_load_kwh = round(sum(monthly_load_kwh), 1)
    annual_self_consumed_kwh = round(sum(monthly_self_consumed_kwh), 1)
    annual_export_kwh = round(sum(monthly_export_kwh), 1)
    annual_grid_import_kwh = round(sum(dispatch["grid_import_total"]), 1)
    annual_import_cost = round(sum(dispatch["import_cost"]), 2)
    annual_export_revenue = round(sum(dispatch["export_revenue"]), 2)
    baseline_annual_cost = round(
        sum(load * tariff_rate_for_hour(inputs, timestamp.hour) for load, timestamp in zip(hourly_load_kwh, datetimes)),
        2,
    )

    solar_offset_pct = clamp(annual_self_consumed_kwh / max(annual_load_kwh, 1.0), 0.0, 1.5) * 100.0
    production_vs_load_pct = clamp(annual_generation_kwh / max(annual_load_kwh, 1.0), 0.0, 2.5) * 100.0
    self_consumption_pct = clamp(annual_self_consumed_kwh / max(annual_generation_kwh, 1.0), 0.0, 1.0) * 100.0
    export_ratio_pct = clamp(annual_export_kwh / max(annual_generation_kwh, 1.0), 0.0, 1.0) * 100.0

    annual_savings = round(baseline_annual_cost - annual_import_cost + annual_export_revenue, 2)
    estimated_capex = round(
        array_kw * 1000.0 * inputs.installed_cost_per_watt + inputs.battery_capacity_kwh * inputs.battery_cost_per_kwh,
        2,
    )
    payback_years = round(estimated_capex / annual_savings, 1) if annual_savings > 0 else None

    annual_degradation = clamp(inputs.module_degradation_pct / 100.0, 0.0, 0.02)
    lifetime_generation_kwh = 0.0
    lifetime_savings = 0.0
    for year in range(inputs.project_years):
        degradation_factor = (1.0 - annual_degradation) ** year
        lifetime_generation_kwh += annual_generation_kwh * degradation_factor
        lifetime_savings += annual_savings * degradation_factor

    return SimulationResult(
        monthly_generation_kwh=monthly_generation_kwh,
        monthly_load_kwh=monthly_load_kwh,
        monthly_self_consumed_kwh=monthly_self_consumed_kwh,
        monthly_export_kwh=monthly_export_kwh,
        monthly_import_cost=monthly_import_cost,
        monthly_export_revenue=monthly_export_revenue,
        monthly_net_savings=monthly_net_savings,
        avg_hourly_generation_kwh=average_by_hour(datetimes, hourly_generation_kwh),
        avg_hourly_load_kwh=average_by_hour(datetimes, hourly_load_kwh),
        avg_hourly_soc_kwh=average_by_hour(datetimes, dispatch["soc_trace"]),
        avg_hourly_grid_import_kwh=average_by_hour(datetimes, dispatch["grid_import_total"]),
        avg_hourly_export_kwh=average_by_hour(datetimes, dispatch["export"]),
        array_kw=round(array_kw, 2),
        panel_area_m2=round(panel_area_m2, 2),
        total_panel_area_m2=round(total_panel_area_m2, 1),
        max_panels_by_roof=max_panels,
        performance_ratio=round(system_pr, 3),
        orientation_factor=round(facing_factor, 3),
        annual_generation_kwh=annual_generation_kwh,
        annual_load_kwh=annual_load_kwh,
        annual_self_consumed_kwh=annual_self_consumed_kwh,
        annual_export_kwh=annual_export_kwh,
        annual_grid_import_kwh=annual_grid_import_kwh,
        annual_import_cost=annual_import_cost,
        annual_export_revenue=annual_export_revenue,
        solar_offset_pct=round(solar_offset_pct, 1),
        production_vs_load_pct=round(production_vs_load_pct, 1),
        self_consumption_pct=round(self_consumption_pct, 1),
        export_ratio_pct=round(export_ratio_pct, 1),
        roof_utilization_pct=round(roof_utilization_pct, 1),
        annual_savings=annual_savings,
        baseline_annual_cost=baseline_annual_cost,
        estimated_capex=estimated_capex,
        payback_years=payback_years,
        lifetime_savings=round(lifetime_savings, 0),
        lifetime_generation_kwh=round(lifetime_generation_kwh, 0),
        co2_offset_tons=round(annual_generation_kwh * inputs.grid_co2_kg_per_kwh / 1000.0, 2),
        optimal_tilt_deg=best_tilt,
        optimal_azimuth_deg=best_azimuth,
        weather_source=weather_source,
        resolved_location_name=resolved_location_name,
        weather_year=weather_year,
        peak_period_coverage_pct=round(float(dispatch["peak_period_coverage_pct"]), 1),
        annual_battery_charge_from_solar_kwh=round(float(dispatch["solar_charge_input_total"]), 1),
        annual_grid_charge_kwh=round(float(dispatch["grid_charge_input_total"]), 1),
        annual_battery_discharge_kwh=round(float(dispatch["battery_discharge_output_total"]), 1),
        battery_cycles=round(float(dispatch["battery_cycles"]), 1),
    )
