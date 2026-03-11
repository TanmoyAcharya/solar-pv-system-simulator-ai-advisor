from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import urlopen

from .models import WeatherProfile


GEOCODING_ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"


def _request_json(endpoint: str, params: dict[str, str | int | float]) -> dict:
    url = f"{endpoint}?{urlencode(params)}"
    with urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(str(payload.get("reason", "Remote API error")))
    return payload


def format_location_label(result: dict) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for key in ("name", "admin1", "country"):
        value = str(result.get(key, "")).strip()
        if value and value not in seen:
            seen.add(value)
            parts.append(value)
    return ", ".join(parts)


def search_locations(query: str, count: int = 5) -> list[dict[str, str | float]]:
    query = query.strip()
    if len(query) < 2:
        return []

    payload = _request_json(
        GEOCODING_ENDPOINT,
        {"name": query, "count": count, "language": "en", "format": "json"},
    )

    results: list[dict[str, str | float]] = []
    for item in payload.get("results", []):
        results.append(
            {
                "label": format_location_label(item),
                "name": str(item.get("name", query)),
                "latitude": float(item["latitude"]),
                "longitude": float(item["longitude"]),
                "timezone": str(item.get("timezone", "GMT")),
                "country": str(item.get("country", "")),
                "admin1": str(item.get("admin1", "")),
            }
        )
    return results


def app_azimuth_to_open_meteo(azimuth_deg: float) -> float:
    return ((azimuth_deg - 180.0 + 540.0) % 360.0) - 180.0


def fetch_weather_profile(
    resolved_name: str,
    latitude: float,
    longitude: float,
    year: int,
    tilt_deg: float,
    azimuth_deg: float,
) -> WeatherProfile:
    payload = _request_json(
        ARCHIVE_ENDPOINT,
        {
            "latitude": round(latitude, 5),
            "longitude": round(longitude, 5),
            "start_date": f"{year}-01-01",
            "end_date": f"{year}-12-31",
            "hourly": "global_tilted_irradiance,temperature_2m",
            "timezone": "auto",
            "tilt": round(tilt_deg, 1),
            "azimuth": round(app_azimuth_to_open_meteo(azimuth_deg), 1),
        },
    )
    hourly = payload.get("hourly", {})
    hourly_time = hourly.get("time", [])
    hourly_irradiance_w_m2 = hourly.get("global_tilted_irradiance", [])
    hourly_temperature_c = hourly.get("temperature_2m", [])

    if not hourly_time:
        raise RuntimeError("Weather API returned no hourly data for the selected location and year.")

    if len(hourly_time) != len(hourly_irradiance_w_m2) or len(hourly_time) != len(hourly_temperature_c):
        raise RuntimeError("Weather API returned mismatched hourly arrays.")

    return WeatherProfile(
        resolved_name=resolved_name,
        source="Open-Meteo historical",
        latitude=float(payload.get("latitude", latitude)),
        longitude=float(payload.get("longitude", longitude)),
        timezone=str(payload.get("timezone", "GMT")),
        year=year,
        hourly_time=[str(value) for value in hourly_time],
        hourly_irradiance_w_m2=[float(value or 0.0) for value in hourly_irradiance_w_m2],
        hourly_temperature_c=[float(value or 0.0) for value in hourly_temperature_c],
        notes="Uses Open-Meteo global tilted irradiance for the selected fixed tilt and azimuth.",
    )