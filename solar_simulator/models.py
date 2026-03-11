from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional, Union


LoadProfile = Literal["Balanced", "Daytime heavy", "Evening heavy"]
WeatherMode = Literal["Synthetic", "Open-Meteo historical"]


@dataclass(frozen=True)
class SystemInputs:
    site_name: str
    location_query: str
    latitude: float
    longitude: float
    weather_mode: WeatherMode
    weather_year: int
    avg_sun_hours: float
    peak_irradiance_w_m2: float
    roof_area_m2: float
    monthly_bill: float
    electricity_rate: float
    feed_in_tariff: float
    peak_import_rate: float
    shoulder_import_rate: float
    offpeak_import_rate: float
    peak_start_hour: int
    peak_end_hour: int
    shoulder_start_hour: int
    shoulder_end_hour: int
    panel_wattage: float
    panel_efficiency_pct: float
    panel_count: int
    tilt_deg: float
    azimuth_deg: float
    system_losses_pct: float
    shade_loss_pct: float
    inverter_efficiency_pct: float
    battery_capacity_kwh: float
    battery_power_kw: float
    battery_roundtrip_efficiency_pct: float
    grid_charge_enabled: bool
    installed_cost_per_watt: float
    battery_cost_per_kwh: float
    project_years: int
    module_degradation_pct: float
    load_profile: LoadProfile
    target_offset_pct: float
    grid_co2_kg_per_kwh: float


@dataclass(frozen=True)
class WeatherProfile:
    resolved_name: str
    source: str
    latitude: float
    longitude: float
    timezone: str
    year: int
    hourly_time: list[str]
    hourly_irradiance_w_m2: list[float]
    hourly_temperature_c: list[float]
    notes: Optional[str] = None


@dataclass(frozen=True)
class SimulationResult:
    monthly_generation_kwh: list[float]
    monthly_load_kwh: list[float]
    monthly_self_consumed_kwh: list[float]
    monthly_export_kwh: list[float]
    monthly_import_cost: list[float]
    monthly_export_revenue: list[float]
    monthly_net_savings: list[float]
    avg_hourly_generation_kwh: list[float]
    avg_hourly_load_kwh: list[float]
    avg_hourly_soc_kwh: list[float]
    avg_hourly_grid_import_kwh: list[float]
    avg_hourly_export_kwh: list[float]
    array_kw: float
    panel_area_m2: float
    total_panel_area_m2: float
    max_panels_by_roof: int
    performance_ratio: float
    orientation_factor: float
    annual_generation_kwh: float
    annual_load_kwh: float
    annual_self_consumed_kwh: float
    annual_export_kwh: float
    annual_grid_import_kwh: float
    annual_import_cost: float
    annual_export_revenue: float
    solar_offset_pct: float
    production_vs_load_pct: float
    self_consumption_pct: float
    export_ratio_pct: float
    roof_utilization_pct: float
    annual_savings: float
    baseline_annual_cost: float
    estimated_capex: float
    payback_years: Optional[float]
    lifetime_savings: float
    lifetime_generation_kwh: float
    co2_offset_tons: float
    optimal_tilt_deg: float
    optimal_azimuth_deg: float
    weather_source: str
    resolved_location_name: str
    weather_year: Optional[int]
    peak_period_coverage_pct: float
    annual_battery_charge_from_solar_kwh: float
    annual_grid_charge_kwh: float
    annual_battery_discharge_kwh: float
    battery_cycles: float


@dataclass(frozen=True)
class AdviceItem:
    title: str
    impact: str
    detail: str
    action: str


@dataclass(frozen=True)
class AdvisorReport:
    score: int
    summary: str
    recommended_panel_count: int
    recommended_battery_kwh: float
    recommended_tilt_deg: float
    recommended_azimuth_deg: float
    items: list[AdviceItem]
    scenarios: list[Dict[str, Union[float, int, str]]]
    source: str = "Heuristic"
    model_name: Optional[str] = None
    note: Optional[str] = None
