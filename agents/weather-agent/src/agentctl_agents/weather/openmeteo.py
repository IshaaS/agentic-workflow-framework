"""Open-Meteo geocoding and hourly forecast client, standard library only.

https://open-meteo.com/en/docs and https://open-meteo.com/en/docs/geocoding-api
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = ("temperature_2m", "weather_code", "precipitation_probability", "wind_speed_10m")
DEFAULT_TIMEOUT_SECONDS = 10.0

# Every value WeatherAgent can put in weather["condition"].
CONDITIONS = ("clear", "cloudy", "rainy", "snowy", "stormy", "unknown")

# WMO weather interpretation codes, as listed in the Open-Meteo forecast docs.
# Fog (45, 48) is reported as cloudy; any code not listed maps to "unknown".
_WMO_CONDITIONS: dict[int, str] = {
    0: "clear", 1: "clear",
    2: "cloudy", 3: "cloudy", 45: "cloudy", 48: "cloudy",
    51: "rainy", 53: "rainy", 55: "rainy", 56: "rainy", 57: "rainy",
    61: "rainy", 63: "rainy", 65: "rainy", 66: "rainy", 67: "rainy",
    80: "rainy", 81: "rainy", 82: "rainy",
    71: "snowy", 73: "snowy", 75: "snowy", 77: "snowy", 85: "snowy", 86: "snowy",
    95: "stormy", 96: "stormy", 99: "stormy",
}

FetchJson = Callable[[str, dict[str, Any]], Any]


class WeatherAPIError(RuntimeError):
    """The weather service could not be reached or returned unusable data."""


@dataclass
class Location:
    name: str
    country: str
    latitude: float
    longitude: float


def get_json(url: str, params: dict[str, Any], timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Any:
    """GET ``url`` with query ``params`` and decode the JSON body."""
    request = Request(
        f"{url}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": "agentctl-weather-agent"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        raise WeatherAPIError(f"{url} returned HTTP {exc.code}{_error_reason(exc)}") from exc
    except (URLError, OSError) as exc:  # includes timeouts
        raise WeatherAPIError(f"request to {url} failed: {getattr(exc, 'reason', exc)}") from exc

    try:
        return json.loads(body)
    except ValueError as exc:
        raise WeatherAPIError(f"{url} returned a response that is not valid JSON") from exc


def _error_reason(exc: HTTPError) -> str:
    # Open-Meteo reports request errors as {"error": true, "reason": "..."}.
    try:
        reason = json.loads(exc.read()).get("reason")
    except Exception:
        return ""
    return f": {reason}" if isinstance(reason, str) else ""


def geocode(city: str, fetch_json: FetchJson) -> Location:
    payload = fetch_json(
        GEOCODING_URL, {"name": city, "count": 1, "language": "en", "format": "json"}
    )
    if not isinstance(payload, dict):
        raise WeatherAPIError("geocoding response is not a JSON object")
    results = payload.get("results")
    if not results:
        raise WeatherAPIError(f"no location found for city {city!r}")
    if not isinstance(results, list) or not isinstance(results[0], dict):
        raise WeatherAPIError("geocoding response has malformed 'results'")

    first = results[0]
    return Location(
        name=str(first.get("name", city)),
        country=str(first.get("country", "")),
        latitude=_number(first, "latitude", "geocoding result"),
        longitude=_number(first, "longitude", "geocoding result"),
    )


def fetch_forecast(location: Location, fetch_json: FetchJson) -> dict[str, Any]:
    payload = fetch_json(
        FORECAST_URL,
        {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "hourly": ",".join(HOURLY_VARIABLES),
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "timezone": "auto",
            "forecast_days": 1,
        },
    )
    if not isinstance(payload, dict):
        raise WeatherAPIError("forecast response is not a JSON object")
    return payload


def current_hour_weather(forecast: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Pick the hourly row for the current hour in the forecast location's timezone.

    With ``timezone=auto``, hourly times are local wall-clock strings such as
    ``2026-10-11T14:00`` and ``utc_offset_seconds`` gives the location's offset.
    ``now`` must be timezone-aware.
    """
    offset = forecast.get("utc_offset_seconds")
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise WeatherAPIError("forecast response is missing 'utc_offset_seconds'")
    hourly = forecast.get("hourly")
    if not isinstance(hourly, dict):
        raise WeatherAPIError("forecast response is missing 'hourly' data")
    _check_units(forecast.get("hourly_units"))

    times = hourly.get("time")
    if not isinstance(times, list):
        raise WeatherAPIError("forecast response is missing 'hourly.time'")
    columns = {}
    for name in HOURLY_VARIABLES:
        values = hourly.get(name)
        if not isinstance(values, list) or len(values) != len(times):
            raise WeatherAPIError(f"forecast response has missing or misaligned 'hourly.{name}'")
        columns[name] = values

    local_now = now.astimezone(timezone.utc) + timedelta(seconds=offset)
    hour_key = local_now.strftime("%Y-%m-%dT%H:00")
    try:
        index = times.index(hour_key)
    except ValueError:
        raise WeatherAPIError(
            f"forecast has no entry for local hour {hour_key} "
            f"(timezone {forecast.get('timezone', 'unknown')})"
        ) from None

    row = {name: values[index] for name, values in columns.items()}
    precipitation = _number(row, "precipitation_probability", f"forecast hour {hour_key}")
    if not 0 <= precipitation <= 100:
        raise WeatherAPIError(f"precipitation probability {precipitation} is outside 0-100")
    wind = _number(row, "wind_speed_10m", f"forecast hour {hour_key}")
    if wind < 0:
        raise WeatherAPIError(f"wind speed {wind} is negative")

    return {
        "temperature_c": _number(row, "temperature_2m", f"forecast hour {hour_key}"),
        "condition": condition_for_code(_number(row, "weather_code", f"forecast hour {hour_key}")),
        "precipitation_probability": round(precipitation),
        "wind_speed_kmh": wind,
    }


def condition_for_code(code: float) -> str:
    return _WMO_CONDITIONS.get(int(code), "unknown") if code == int(code) else "unknown"


def _check_units(units: Any) -> None:
    if not isinstance(units, dict):
        return
    for name, expected in (("temperature_2m", "°C"), ("wind_speed_10m", "km/h")):
        if name in units and units[name] != expected:
            raise WeatherAPIError(f"expected {name} in {expected}, got {units[name]!r}")


def _number(data: dict[str, Any], key: str, where: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeatherAPIError(f"{where} has missing or non-numeric {key!r}: {value!r}")
    return float(value)
