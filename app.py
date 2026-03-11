from __future__ import annotations

import os
from datetime import date
from typing import cast

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from solar_simulator import (
    LLMAdvisorConfig,
    MONTH_NAMES,
    SystemInputs,
    fetch_weather_profile,
    generate_advisor_report,
    generate_llm_advisor_report,
    search_locations,
    simulate_system,
    tariff_rate_for_hour,
    tariff_tier_for_hour,
)
from solar_simulator.models import LoadProfile


st.set_page_config(
    page_title="Solar PV System Simulator + AI Advisor",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&display=swap');

    :root {
        --sand: #f6f0e8;
        --paper: #fff8f1;
        --ink: #1d2a32;
        --muted: #60717d;
        --solar: #e56b1f;
        --sun: #f0b33f;
        --teal: #227c7f;
        --line: rgba(29, 42, 50, 0.12);
    }

    html, body, [class*="css"]  {
        font-family: 'Space Grotesk', sans-serif;
    }

    .stApp {
        background:
            radial-gradient(circle at top right, rgba(240, 179, 63, 0.28), transparent 24%),
            radial-gradient(circle at left 20%, rgba(34, 124, 127, 0.12), transparent 20%),
            linear-gradient(180deg, #f5ede4 0%, #f6f0e8 48%, #f9f4ed 100%);
        color: var(--ink);
    }

    [data-testid="stSidebar"] {
        background: rgba(255, 248, 241, 0.82);
        border-right: 1px solid var(--line);
    }

    .hero {
        padding: 1.4rem 1.6rem;
        border: 1px solid rgba(229, 107, 31, 0.18);
        border-radius: 24px;
        background: linear-gradient(135deg, rgba(255, 248, 241, 0.95), rgba(248, 233, 210, 0.92));
        box-shadow: 0 18px 38px rgba(54, 39, 20, 0.08);
        margin-bottom: 1.1rem;
    }

    .hero .eyebrow {
        color: var(--teal);
        font-size: 0.78rem;
        letter-spacing: 0.18rem;
        text-transform: uppercase;
        margin-bottom: 0.35rem;
        font-weight: 700;
    }

    .hero h1 {
        margin: 0;
        font-size: 2.4rem;
        line-height: 1.02;
    }

    .hero p {
        color: var(--muted);
        margin-top: 0.65rem;
        max-width: 54rem;
    }

    .metric-card {
        background: rgba(255, 251, 246, 0.9);
        border: 1px solid rgba(29, 42, 50, 0.08);
        border-radius: 20px;
        padding: 1rem 1rem 0.85rem;
        min-height: 7rem;
        box-shadow: 0 12px 24px rgba(30, 37, 40, 0.05);
    }

    .metric-label {
        color: var(--muted);
        font-size: 0.82rem;
        letter-spacing: 0.04rem;
        text-transform: uppercase;
    }

    .metric-value {
        color: var(--ink);
        font-size: 1.8rem;
        font-weight: 700;
        margin-top: 0.35rem;
    }

    .metric-note {
        color: var(--muted);
        margin-top: 0.25rem;
        font-size: 0.88rem;
    }

    .advisor-card {
        background: rgba(255, 248, 241, 0.88);
        border-left: 6px solid var(--solar);
        border-radius: 16px;
        padding: 1rem 1.1rem;
        margin-bottom: 0.85rem;
        box-shadow: 0 8px 22px rgba(30, 37, 40, 0.04);
    }

    .advisor-card h4 {
        margin: 0 0 0.35rem 0;
        color: var(--ink);
    }

    .advisor-impact {
        color: var(--teal);
        font-weight: 700;
        text-transform: uppercase;
        font-size: 0.75rem;
        letter-spacing: 0.08rem;
    }

    .subtle {
        color: var(--muted);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def fmt_number(value: float, decimals: int = 0) -> str:
    return f"{value:,.{decimals}f}"


def fmt_years(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} yrs"


def metric_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def cached_location_search(query: str) -> list[dict[str, str | float]]:
    return search_locations(query)


@st.cache_data(show_spinner="Loading hourly weather data...")
def cached_weather_profile(
    resolved_name: str,
    latitude: float,
    longitude: float,
    year: int,
    tilt_deg: float,
    azimuth_deg: float,
):
    return fetch_weather_profile(resolved_name, latitude, longitude, year, tilt_deg, azimuth_deg)


def first_secret_or_env(secret_name: str, env_name: str, default: str = "") -> str:
    try:
        if secret_name in st.secrets:
            return str(st.secrets[secret_name])
    except StreamlitSecretNotFoundError:
        pass
    return os.getenv(env_name, default)


current_year = date.today().year
default_weather_year = current_year - 1


with st.sidebar:
    st.markdown("## Project Inputs")
    st.caption("All currency fields are treated as local currency units.")

    with st.expander("Site and Weather", expanded=True):
        site_name = st.text_input("Site label", value="Site Alpha")
        location_query = st.text_input("Location search", value="New Delhi")
        use_weather_data = st.toggle("Use real weather data", value=True)
        weather_year = st.slider("Weather year", min_value=2019, max_value=default_weather_year, value=default_weather_year, step=1)

        location_results: list[dict[str, str | float]] = []
        selected_location: dict[str, str | float] | None = None
        weather_lookup_error: str | None = None
        if use_weather_data and len(location_query.strip()) >= 2:
            try:
                location_results = cached_location_search(location_query)
            except Exception as exc:
                weather_lookup_error = str(exc)

        if weather_lookup_error:
            st.warning(f"Location lookup failed: {weather_lookup_error}")

        selected_label = ""
        if location_results:
            labels = [str(item["label"]) for item in location_results]
            selected_label = st.selectbox("Resolved location", options=labels, index=0)
            selected_location = next(item for item in location_results if str(item["label"]) == selected_label)

        latitude_default = float(selected_location["latitude"]) if selected_location else 28.6
        longitude_default = float(selected_location["longitude"]) if selected_location else 77.2
        latitude = st.number_input("Latitude", min_value=-90.0, max_value=90.0, value=latitude_default, step=0.1)
        longitude = st.number_input("Longitude", min_value=-180.0, max_value=180.0, value=longitude_default, step=0.1)
        avg_sun_hours = st.number_input("Average daily sun hours", min_value=2.0, max_value=8.5, value=5.6, step=0.1)
        peak_irradiance = st.number_input("Peak irradiance (W/m2)", min_value=700, max_value=1200, value=950, step=10)

    with st.expander("Tariff and Load", expanded=True):
        monthly_bill = st.number_input("Monthly electricity bill", min_value=10.0, max_value=5000.0, value=220.0, step=10.0)
        electricity_rate = st.number_input("Blended bill rate", min_value=0.05, max_value=1.0, value=0.18, step=0.01)
        feed_in_tariff = st.number_input("Feed-in tariff", min_value=0.00, max_value=1.0, value=0.07, step=0.01)
        peak_import_rate = st.number_input("Peak import rate", min_value=0.05, max_value=1.5, value=0.28, step=0.01)
        shoulder_import_rate = st.number_input("Shoulder import rate", min_value=0.05, max_value=1.5, value=0.18, step=0.01)
        offpeak_import_rate = st.number_input("Off-peak import rate", min_value=0.03, max_value=1.5, value=0.11, step=0.01)
        peak_start_hour = st.slider("Peak window start", min_value=0, max_value=23, value=17, step=1)
        peak_end_hour = st.slider("Peak window end", min_value=0, max_value=23, value=22, step=1)
        shoulder_start_hour = st.slider("Shoulder window start", min_value=0, max_value=23, value=7, step=1)
        shoulder_end_hour = st.slider("Shoulder window end", min_value=0, max_value=23, value=17, step=1)
        load_profile = cast(LoadProfile, st.selectbox("Load profile", options=["Balanced", "Daytime heavy", "Evening heavy"], index=0))
        target_offset_pct = st.slider("Target load coverage %", min_value=40, max_value=120, value=90, step=5)

    with st.expander("PV Array", expanded=True):
        roof_area_m2 = st.number_input("Usable roof area (m2)", min_value=20.0, max_value=2000.0, value=120.0, step=5.0)
        panel_wattage = st.number_input("Panel wattage", min_value=300, max_value=800, value=550, step=5)
        panel_efficiency_pct = st.number_input("Panel efficiency %", min_value=15.0, max_value=25.0, value=21.3, step=0.1)
        panel_count = st.slider("Panel count", min_value=2, max_value=80, value=14, step=1)
        tilt_deg = st.slider("Tilt (degrees)", min_value=0, max_value=60, value=20, step=1)
        azimuth_deg = st.slider("Azimuth (0 = north, 180 = south)", min_value=0, max_value=359, value=180, step=1)
        system_losses_pct = st.slider("System losses %", min_value=5, max_value=25, value=12, step=1)
        shade_loss_pct = st.slider("Shade losses %", min_value=0, max_value=30, value=5, step=1)
        inverter_efficiency_pct = st.slider("Inverter efficiency %", min_value=90, max_value=99, value=96, step=1)

    with st.expander("Battery and Finance", expanded=True):
        battery_capacity_kwh = st.number_input("Battery capacity (kWh)", min_value=0.0, max_value=60.0, value=8.0, step=0.5)
        battery_power_kw = st.number_input("Battery power (kW)", min_value=0.0, max_value=40.0, value=5.0, step=0.5)
        battery_roundtrip_efficiency_pct = st.slider("Battery roundtrip efficiency %", min_value=75, max_value=98, value=90, step=1)
        grid_charge_enabled = st.toggle("Allow off-peak grid charging", value=True)
        installed_cost_per_watt = st.number_input("Installed cost per watt", min_value=0.30, max_value=5.0, value=1.05, step=0.05)
        battery_cost_per_kwh = st.number_input("Battery cost per kWh", min_value=50.0, max_value=1500.0, value=380.0, step=10.0)
        project_years = st.slider("Project horizon (years)", min_value=10, max_value=35, value=25, step=1)
        module_degradation_pct = st.slider("Module degradation % / year", min_value=0.1, max_value=1.0, value=0.45, step=0.05)
        grid_co2_kg_per_kwh = st.number_input("Grid CO2 factor (kg/kWh)", min_value=0.05, max_value=1.2, value=0.42, step=0.01)

    with st.expander("Advisor API", expanded=False):
        advisor_mode = st.radio("Advisor engine", options=["Heuristic", "LLM API"], horizontal=True)
        llm_base_url = st.text_input("LLM base URL", value=first_secret_or_env("OPENAI_BASE_URL", "OPENAI_BASE_URL", "https://api.openai.com/v1"))
        llm_model = st.text_input("LLM model", value=first_secret_or_env("OPENAI_MODEL", "OPENAI_MODEL", "gpt-4.1-mini"))
        llm_api_key = st.text_input("LLM API key", value=first_secret_or_env("OPENAI_API_KEY", "OPENAI_API_KEY"), type="password")


inputs = SystemInputs(
    site_name=site_name,
    location_query=selected_label or location_query,
    latitude=latitude,
    longitude=longitude,
    weather_mode="Open-Meteo historical" if use_weather_data else "Synthetic",
    weather_year=weather_year,
    avg_sun_hours=avg_sun_hours,
    peak_irradiance_w_m2=float(peak_irradiance),
    roof_area_m2=roof_area_m2,
    monthly_bill=monthly_bill,
    electricity_rate=electricity_rate,
    feed_in_tariff=feed_in_tariff,
    peak_import_rate=peak_import_rate,
    shoulder_import_rate=shoulder_import_rate,
    offpeak_import_rate=offpeak_import_rate,
    peak_start_hour=peak_start_hour,
    peak_end_hour=peak_end_hour,
    shoulder_start_hour=shoulder_start_hour,
    shoulder_end_hour=shoulder_end_hour,
    panel_wattage=float(panel_wattage),
    panel_efficiency_pct=panel_efficiency_pct,
    panel_count=panel_count,
    tilt_deg=float(tilt_deg),
    azimuth_deg=float(azimuth_deg),
    system_losses_pct=float(system_losses_pct),
    shade_loss_pct=float(shade_loss_pct),
    inverter_efficiency_pct=float(inverter_efficiency_pct),
    battery_capacity_kwh=battery_capacity_kwh,
    battery_power_kw=battery_power_kw,
    battery_roundtrip_efficiency_pct=float(battery_roundtrip_efficiency_pct),
    grid_charge_enabled=grid_charge_enabled,
    installed_cost_per_watt=installed_cost_per_watt,
    battery_cost_per_kwh=battery_cost_per_kwh,
    project_years=project_years,
    module_degradation_pct=module_degradation_pct,
    load_profile=load_profile,
    target_offset_pct=float(target_offset_pct),
    grid_co2_kg_per_kwh=grid_co2_kg_per_kwh,
)

weather_profile = None
weather_status = "Using synthetic irradiance based on the monthly model."
weather_error: str | None = None
if inputs.weather_mode == "Open-Meteo historical":
    try:
        resolved_name = selected_label or location_query
        weather_profile = cached_weather_profile(resolved_name, latitude, longitude, weather_year, tilt_deg, azimuth_deg)
        weather_status = f"{weather_profile.source} for {weather_profile.resolved_name} ({weather_profile.year}, {weather_profile.timezone})"
    except Exception as exc:
        weather_error = str(exc)
        weather_status = "Weather API unavailable, falling back to the synthetic irradiance model."

result = simulate_system(inputs, weather_profile=weather_profile)
report = generate_advisor_report(inputs, result, weather_profile=weather_profile)

llm_status: str | None = None
if advisor_mode == "LLM API":
    report, llm_status = generate_llm_advisor_report(
        inputs,
        result,
        report,
        LLMAdvisorConfig(
            enabled=True,
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=llm_model,
        ),
    )

st.markdown(
    f"""
    <section class="hero">
        <div class="eyebrow">Solar Design Workbench</div>
        <h1>Solar PV System Simulator + AI Advisor</h1>
        <p>
            Model yearly production for <strong>{inputs.site_name}</strong>, stress the economics against tariff assumptions,
            and use the advisor to tighten system size, orientation, and storage decisions.
        </p>
    </section>
    """,
    unsafe_allow_html=True,
)

if weather_error:
    st.warning(f"Weather data fetch failed: {weather_error}")
if llm_status:
    st.info(f"LLM advisor fallback: {llm_status}")

if inputs.panel_count > result.max_panels_by_roof:
    st.error(
        f"Current panel count exceeds practical roof capacity. Estimated maximum for this roof is {result.max_panels_by_roof} panels."
    )

metric_cols = st.columns(5)
with metric_cols[0]:
    metric_card("Annual generation", f"{fmt_number(result.annual_generation_kwh)} kWh", f"{result.array_kw:.2f} kW DC array")
with metric_cols[1]:
    metric_card("Load coverage", f"{result.solar_offset_pct:.0f}%", f"Target: {inputs.target_offset_pct:.0f}%")
with metric_cols[2]:
    metric_card("Annual savings", fmt_number(result.annual_savings), f"Baseline bill: {fmt_number(result.baseline_annual_cost)}")
with metric_cols[3]:
    metric_card("Simple payback", fmt_years(result.payback_years), f"Capex: {fmt_number(result.estimated_capex)}")
with metric_cols[4]:
    metric_card("Advisor score", f"{report.score}/100", f"{report.source} | Peak cover {result.peak_period_coverage_pct:.0f}%")

st.caption(weather_status)

tab_overview, tab_dispatch, tab_advisor, tab_scenarios = st.tabs(["Energy Model", "Battery Dispatch", "AI Advisor", "Scenario Bench"])

with tab_overview:
    chart_df = pd.DataFrame(
        {
            "Month": MONTH_NAMES,
            "Generation": result.monthly_generation_kwh,
            "Load": result.monthly_load_kwh,
            "Self-consumed": result.monthly_self_consumed_kwh,
            "Export": result.monthly_export_kwh,
            "Net savings": result.monthly_net_savings,
        }
    )

    energy_fig = go.Figure()
    energy_fig.add_bar(name="Generation", x=chart_df["Month"], y=chart_df["Generation"], marker_color="#E56B1F")
    energy_fig.add_bar(name="Self-consumed", x=chart_df["Month"], y=chart_df["Self-consumed"], marker_color="#227C7F")
    energy_fig.add_bar(name="Export", x=chart_df["Month"], y=chart_df["Export"], marker_color="#F0B33F")
    energy_fig.add_scatter(name="Load", x=chart_df["Month"], y=chart_df["Load"], mode="lines+markers", line={"color": "#1D2A32", "width": 3})
    energy_fig.update_layout(
        barmode="group",
        height=470,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.68)",
        legend={"orientation": "h", "y": 1.1},
        yaxis_title="kWh / month",
    )
    st.plotly_chart(energy_fig, use_container_width=True)

    detail_cols = st.columns(4)
    detail_cols[0].metric("Self-consumption", f"{result.self_consumption_pct:.1f}%")
    detail_cols[1].metric("Production vs load", f"{result.production_vs_load_pct:.1f}%")
    detail_cols[2].metric("Roof utilization", f"{result.roof_utilization_pct:.1f}%")
    detail_cols[3].metric("Annual CO2 offset", f"{result.co2_offset_tons:.2f} t")

    summary_col, assumptions_col = st.columns([1.2, 0.8])
    with summary_col:
        st.subheader("System summary")
        st.write(
            f"The current design allocates {result.total_panel_area_m2:.1f} m2 of module area across {inputs.panel_count} panels and is expected to produce about {fmt_number(result.annual_generation_kwh)} kWh each year. "
            f"Of that energy, roughly {fmt_number(result.annual_self_consumed_kwh)} kWh is consumed on-site and {fmt_number(result.annual_export_kwh)} kWh is exported."
        )
        st.write(
            f"Projected lifetime generation over {inputs.project_years} years is {fmt_number(result.lifetime_generation_kwh)} kWh, with estimated lifetime value around {fmt_number(result.lifetime_savings)} under constant tariff assumptions."
        )
        st.write(
            f"Weather source: {result.weather_source}. Resolved location: {result.resolved_location_name}. Import cost after solar is about {fmt_number(result.annual_import_cost)} per year, while export revenue is about {fmt_number(result.annual_export_revenue)}."
        )

    with assumptions_col:
        st.subheader("Design assumptions")
        st.write(f"Performance ratio: {result.performance_ratio:.2f}")
        st.write(f"Orientation factor: {result.orientation_factor:.2f}")
        st.write(f"Optimal tilt / azimuth: {result.optimal_tilt_deg:.0f} deg / {result.optimal_azimuth_deg:.0f} deg")
        st.write(f"Estimated roof max: {result.max_panels_by_roof} panels")
        st.write(f"Grid import after solar: {fmt_number(result.annual_grid_import_kwh)} kWh/year")
        st.write(f"Battery cycles per year: {result.battery_cycles:.1f}")

    savings_fig = go.Figure()
    savings_fig.add_bar(name="Net savings", x=chart_df["Month"], y=chart_df["Net savings"], marker_color="#227C7F")
    savings_fig.update_layout(
        height=320,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.68)",
        yaxis_title="Savings / month",
    )
    st.plotly_chart(savings_fig, use_container_width=True)

with tab_dispatch:
    dispatch_hours = list(range(24))
    dispatch_df = pd.DataFrame(
        {
            "Hour": dispatch_hours,
            "Generation": result.avg_hourly_generation_kwh,
            "Load": result.avg_hourly_load_kwh,
            "Grid import": result.avg_hourly_grid_import_kwh,
            "Export": result.avg_hourly_export_kwh,
            "Battery SOC": result.avg_hourly_soc_kwh,
            "Tariff": [tariff_rate_for_hour(inputs, hour) for hour in dispatch_hours],
            "Tier": [tariff_tier_for_hour(inputs, hour) for hour in dispatch_hours],
        }
    )

    dispatch_fig = go.Figure()
    dispatch_fig.add_scatter(name="Load", x=dispatch_df["Hour"], y=dispatch_df["Load"], mode="lines+markers", line={"color": "#1D2A32", "width": 3})
    dispatch_fig.add_scatter(name="Generation", x=dispatch_df["Hour"], y=dispatch_df["Generation"], mode="lines+markers", line={"color": "#E56B1F", "width": 3})
    dispatch_fig.add_scatter(name="Grid import", x=dispatch_df["Hour"], y=dispatch_df["Grid import"], mode="lines+markers", line={"color": "#7A4E3A", "width": 2, "dash": "dot"})
    dispatch_fig.add_scatter(name="Battery SOC", x=dispatch_df["Hour"], y=dispatch_df["Battery SOC"], mode="lines+markers", yaxis="y2", line={"color": "#227C7F", "width": 3})
    dispatch_fig.update_layout(
        height=460,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.68)",
        yaxis={"title": "kWh / hour"},
        yaxis2={"title": "Battery SOC (kWh)", "overlaying": "y", "side": "right"},
        legend={"orientation": "h", "y": 1.1},
    )
    st.plotly_chart(dispatch_fig, use_container_width=True)

    dispatch_metrics = st.columns(4)
    dispatch_metrics[0].metric("Peak-period coverage", f"{result.peak_period_coverage_pct:.1f}%")
    dispatch_metrics[1].metric("Battery charge from solar", f"{result.annual_battery_charge_from_solar_kwh:,.0f} kWh")
    dispatch_metrics[2].metric("Grid charging", f"{result.annual_grid_charge_kwh:,.0f} kWh")
    dispatch_metrics[3].metric("Battery discharge", f"{result.annual_battery_discharge_kwh:,.0f} kWh")

    st.dataframe(dispatch_df, use_container_width=True, hide_index=True)

with tab_advisor:
    advisor_cols = st.columns([0.38, 0.62])
    with advisor_cols[0]:
        gauge = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=report.score,
                number={"suffix": "/100"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"color": "#E56B1F"},
                    "steps": [
                        {"range": [0, 50], "color": "#F7D8B7"},
                        {"range": [50, 75], "color": "#F2C98E"},
                        {"range": [75, 100], "color": "#C7E6DD"},
                    ],
                },
            )
        )
        gauge.update_layout(height=280, margin={"l": 20, "r": 20, "t": 20, "b": 20}, paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(gauge, use_container_width=True)
        st.subheader("Advisor summary")
        st.write(report.summary)
        st.caption(report.note or f"Advisor source: {report.source}")
        st.write(f"Recommended panel count: {report.recommended_panel_count}")
        st.write(f"Recommended battery size: {report.recommended_battery_kwh:.1f} kWh")
        st.write(f"Recommended tilt / azimuth: {report.recommended_tilt_deg:.0f} deg / {report.recommended_azimuth_deg:.0f} deg")
        if report.model_name:
            st.write(f"LLM model: {report.model_name}")

    with advisor_cols[1]:
        st.subheader("Action list")
        for item in report.items:
            st.markdown(
                f"""
                <div class="advisor-card">
                    <div class="advisor-impact">{item.impact} impact</div>
                    <h4>{item.title}</h4>
                    <p>{item.detail}</p>
                    <p><strong>Action:</strong> {item.action}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

with tab_scenarios:
    scenario_df = pd.DataFrame(report.scenarios)
    st.subheader("Scenario comparison")
    st.dataframe(scenario_df, use_container_width=True, hide_index=True)

    scenario_fig = go.Figure()
    scenario_fig.add_bar(name="Savings / year", x=scenario_df["Scenario"], y=scenario_df["Savings / year"], marker_color="#227C7F")
    scenario_fig.add_scatter(
        name="Load coverage %",
        x=scenario_df["Scenario"],
        y=scenario_df["Load coverage %"],
        mode="lines+markers",
        yaxis="y2",
        line={"color": "#E56B1F", "width": 3},
    )
    scenario_fig.update_layout(
        height=430,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.68)",
        yaxis={"title": "Savings / year"},
        yaxis2={"title": "Load coverage %", "overlaying": "y", "side": "right"},
        legend={"orientation": "h", "y": 1.1},
    )
    st.plotly_chart(scenario_fig, use_container_width=True)
    st.caption("Demand-match pushes toward the selected coverage target. Self-use boost prioritizes storage-backed consumption under TOU tariffs. Roof max shows the yield ceiling for the available roof area.")
