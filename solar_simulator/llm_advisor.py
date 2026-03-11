from __future__ import annotations

import json
from dataclasses import dataclass, replace
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import AdviceItem, AdvisorReport, SimulationResult, SystemInputs
from .simulator import clamp


@dataclass(frozen=True)
class LLMAdvisorConfig:
    enabled: bool
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 45.0


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _extract_message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part)
    return ""


def _normalize_items(raw_items: object, fallback_items: list[AdviceItem]) -> list[AdviceItem]:
    if not isinstance(raw_items, list):
        return fallback_items

    normalized: list[AdviceItem] = []
    for item in raw_items[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        detail = str(item.get("detail", "")).strip()
        action = str(item.get("action", "")).strip()
        if not title or not detail or not action:
            continue
        impact = str(item.get("impact", "Medium")).strip().title() or "Medium"
        normalized.append(AdviceItem(title=title, impact=impact, detail=detail, action=action))

    return normalized or fallback_items


def _request_completion(config: LLMAdvisorConfig, context: dict[str, object]) -> dict:
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": config.model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "developer",
                "content": (
                    "You are a senior solar PV design advisor. Return JSON only with keys: "
                    "summary, score, recommended_panel_count, recommended_battery_kwh, recommended_tilt_deg, "
                    "recommended_azimuth_deg, items. The items field must be a list of 3 to 5 objects, each with "
                    "title, impact, detail, action. Keep all recommendations grounded strictly in the supplied data."
                ),
            },
            {"role": "user", "content": json.dumps(context)},
        ],
    }

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlopen(request, timeout=config.timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def generate_llm_advisor_report(
    inputs: SystemInputs,
    result: SimulationResult,
    base_report: AdvisorReport,
    config: LLMAdvisorConfig,
) -> tuple[AdvisorReport, str | None]:
    if not config.enabled:
        return base_report, None

    if not config.api_key.strip():
        return replace(base_report, note="LLM advisor is enabled but no API key is configured."), "Missing API key"

    context = {
        "site": {
            "name": inputs.site_name,
            "location_query": inputs.location_query,
            "latitude": inputs.latitude,
            "longitude": inputs.longitude,
            "weather_mode": inputs.weather_mode,
            "weather_year": inputs.weather_year,
        },
        "design": {
            "array_kw": result.array_kw,
            "panel_count": inputs.panel_count,
            "battery_kwh": inputs.battery_capacity_kwh,
            "battery_power_kw": inputs.battery_power_kw,
            "tilt_deg": inputs.tilt_deg,
            "azimuth_deg": inputs.azimuth_deg,
        },
        "economics": {
            "estimated_capex": result.estimated_capex,
            "annual_import_cost": result.annual_import_cost,
            "annual_export_revenue": result.annual_export_revenue,
            "annual_savings": result.annual_savings,
            "baseline_annual_cost": result.baseline_annual_cost,
            "payback_years": result.payback_years,
            "peak_rate": inputs.peak_import_rate,
            "shoulder_rate": inputs.shoulder_import_rate,
            "offpeak_rate": inputs.offpeak_import_rate,
            "feed_in_tariff": inputs.feed_in_tariff,
        },
        "performance": {
            "annual_generation_kwh": result.annual_generation_kwh,
            "annual_load_kwh": result.annual_load_kwh,
            "annual_self_consumed_kwh": result.annual_self_consumed_kwh,
            "annual_export_kwh": result.annual_export_kwh,
            "annual_grid_import_kwh": result.annual_grid_import_kwh,
            "solar_offset_pct": result.solar_offset_pct,
            "self_consumption_pct": result.self_consumption_pct,
            "export_ratio_pct": result.export_ratio_pct,
            "peak_period_coverage_pct": result.peak_period_coverage_pct,
            "orientation_factor": result.orientation_factor,
            "roof_utilization_pct": result.roof_utilization_pct,
        },
        "heuristic_reference": {
            "score": base_report.score,
            "summary": base_report.summary,
            "recommended_panel_count": base_report.recommended_panel_count,
            "recommended_battery_kwh": base_report.recommended_battery_kwh,
            "recommended_tilt_deg": base_report.recommended_tilt_deg,
            "recommended_azimuth_deg": base_report.recommended_azimuth_deg,
            "items": [item.__dict__ for item in base_report.items],
        },
    }

    try:
        payload = _request_completion(config, context)
        choices = payload.get("choices", [])
        if not choices:
            raise RuntimeError("No completion choices were returned.")
        message = choices[0].get("message", {})
        raw_text = _extract_message_text(message.get("content", ""))
        if not raw_text:
            raise RuntimeError("The LLM response did not include text content.")

        parsed = json.loads(_strip_code_fences(raw_text))
        report = replace(
            base_report,
            score=int(clamp(float(parsed.get("score", base_report.score)), 0, 100)),
            summary=str(parsed.get("summary", base_report.summary)).strip() or base_report.summary,
            recommended_panel_count=int(parsed.get("recommended_panel_count", base_report.recommended_panel_count)),
            recommended_battery_kwh=round(float(parsed.get("recommended_battery_kwh", base_report.recommended_battery_kwh)), 1),
            recommended_tilt_deg=round(float(parsed.get("recommended_tilt_deg", base_report.recommended_tilt_deg)), 1),
            recommended_azimuth_deg=round(float(parsed.get("recommended_azimuth_deg", base_report.recommended_azimuth_deg)), 1),
            items=_normalize_items(parsed.get("items"), base_report.items),
            source="LLM API",
            model_name=config.model,
            note="Recommendations generated by a live chat completions API.",
        )
        return report, None
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        return replace(base_report, note=f"LLM advisor fallback: {exc}"), str(exc)