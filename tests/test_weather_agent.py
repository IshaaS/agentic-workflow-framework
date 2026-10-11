"""Sprint 03 weather agent tests. All HTTP is faked; nothing touches the network."""

import io
import json
import logging
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

import pytest

from agentctl_agents.weather import openmeteo
from agentctl_agents.weather.agent import WeatherAgent
from agentctl_agents.weather.openmeteo import (
    CONDITIONS,
    FORECAST_URL,
    GEOCODING_URL,
    WeatherAPIError,
    condition_for_code,
    get_json,
)

# 2026-10-11 19:30 UTC is 14:30 in Dallas (UTC-5 during daylight time).
NOW_UTC = datetime(2026, 10, 11, 19, 30, tzinfo=timezone.utc)

GEOCODE_DALLAS = {
    "results": [
        {"name": "Dallas", "country": "United States", "latitude": 32.78, "longitude": -96.81}
    ]
}


def forecast_payload(**overrides):
    payload = {
        "timezone": "America/Chicago",
        "utc_offset_seconds": -18000,
        "hourly_units": {"temperature_2m": "°C", "wind_speed_10m": "km/h"},
        "hourly": {
            "time": ["2026-10-11T13:00", "2026-10-11T14:00", "2026-10-11T15:00"],
            "temperature_2m": [20.5, 22.0, 23.4],
            "weather_code": [0, 61, 3],
            "precipitation_probability": [5, 65, 20],
            "wind_speed_10m": [8.0, 15.0, 12.5],
        },
    }
    payload.update(overrides)
    return payload


class FakeOpenMeteo:
    """Stands in for get_json and records the requests made."""

    def __init__(self, geocode=GEOCODE_DALLAS, forecast=None):
        self.responses = {GEOCODING_URL: geocode, FORECAST_URL: forecast or forecast_payload()}
        self.calls = []

    def __call__(self, url, params):
        self.calls.append((url, params))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def make_agent(fake=None, now=NOW_UTC):
    return WeatherAgent(fetch_json=fake or FakeOpenMeteo(), clock=lambda: now)


# Successful lookups ---------------------------------------------------------


def test_returns_normalized_weather_for_current_local_hour(context):
    result = make_agent().run({"city": "Dallas"}, context)

    assert result == {
        "weather": {
            "temperature_c": 22.0,
            "condition": "rainy",
            "precipitation_probability": 65,
            "wind_speed_kmh": 15.0,
        }
    }


def test_value_types(context):
    weather = make_agent().run({"city": "Dallas"}, context)["weather"]

    assert type(weather["temperature_c"]) is float
    assert type(weather["condition"]) is str
    assert type(weather["precipitation_probability"]) is int
    assert type(weather["wind_speed_kmh"]) is float


def test_requests_metric_units_and_local_timezone(context):
    fake = FakeOpenMeteo()
    make_agent(fake).run({"city": "  Dallas "}, context)

    (geo_url, geo_params), (fc_url, fc_params) = fake.calls
    assert geo_url == GEOCODING_URL
    assert geo_params["name"] == "Dallas"
    assert geo_params["count"] == 1
    assert fc_url == FORECAST_URL
    assert (fc_params["latitude"], fc_params["longitude"]) == (32.78, -96.81)
    assert fc_params["timezone"] == "auto"
    assert fc_params["temperature_unit"] == "celsius"
    assert fc_params["wind_speed_unit"] == "kmh"
    assert fc_params["hourly"] == "temperature_2m,weather_code,precipitation_probability,wind_speed_10m"


@pytest.mark.parametrize(
    "now, expected_temperature",
    [
        (datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc), 20.5),   # 13:00 local
        (datetime(2026, 10, 11, 19, 59, tzinfo=timezone.utc), 22.0),  # 14:59 local
        (datetime(2026, 10, 11, 20, 1, tzinfo=timezone.utc), 23.4),   # 15:01 local
    ],
)
def test_selects_current_local_hour_not_first_row(context, now, expected_temperature):
    weather = make_agent(now=now).run({"city": "Dallas"}, context)["weather"]

    assert weather["temperature_c"] == expected_temperature


def test_uses_destination_offset_not_utc(context):
    # 05:15 UTC is 10:45 in India (UTC+5:30); hourly times are local.
    forecast = forecast_payload(
        timezone="Asia/Kolkata",
        utc_offset_seconds=19800,
        hourly={
            "time": ["2026-10-11T05:00", "2026-10-11T10:00"],
            "temperature_2m": [10.0, 31.0],
            "weather_code": [0, 2],
            "precipitation_probability": [0, 10],
            "wind_speed_10m": [3.0, 9.0],
        },
    )
    now = datetime(2026, 10, 11, 5, 15, tzinfo=timezone.utc)

    weather = make_agent(FakeOpenMeteo(forecast=forecast), now).run({"city": "Delhi"}, context)

    assert weather["weather"]["temperature_c"] == 31.0
    assert weather["weather"]["condition"] == "cloudy"


def test_logs_location_without_payload(context, caplog):
    with caplog.at_level(logging.INFO, logger="agentctl"):
        make_agent().run({"city": "Dallas"}, context)

    assert "Dallas" in caplog.text and "America/Chicago" in caplog.text
    assert "hourly" not in caplog.text


# Weather code mapping -------------------------------------------------------


@pytest.mark.parametrize(
    "code, condition",
    [
        (0, "clear"), (1, "clear"), (2, "cloudy"), (3, "cloudy"), (45, "cloudy"),
        (51, "rainy"), (61, "rainy"), (67, "rainy"), (80, "rainy"), (82, "rainy"),
        (71, "snowy"), (77, "snowy"), (86, "snowy"),
        (95, "stormy"), (99, "stormy"),
        (4, "unknown"), (100, "unknown"), (61.5, "unknown"),
    ],
)
def test_condition_for_code(code, condition):
    assert condition_for_code(code) == condition


def test_mapping_only_produces_documented_conditions():
    produced = {condition_for_code(code) for code in range(0, 120)}
    assert produced <= set(CONDITIONS)


# Input validation -----------------------------------------------------------


@pytest.mark.parametrize("inputs", [{}, {"city": ""}, {"city": "   "}, {"city": None}, {"city": 42}])
def test_blank_or_invalid_city_raises_value_error(context, inputs):
    fake = FakeOpenMeteo()

    with pytest.raises(ValueError, match="city"):
        make_agent(fake).run(inputs, context)
    assert fake.calls == []


# Upstream failures ----------------------------------------------------------


@pytest.mark.parametrize("geocode", [{}, {"results": []}])
def test_unknown_city(context, geocode):
    with pytest.raises(WeatherAPIError, match="no location found for city 'Atlantis'"):
        make_agent(FakeOpenMeteo(geocode=geocode)).run({"city": "Atlantis"}, context)


def test_geocode_missing_coordinates(context):
    fake = FakeOpenMeteo(geocode={"results": [{"name": "Dallas"}]})

    with pytest.raises(WeatherAPIError, match="latitude"):
        make_agent(fake).run({"city": "Dallas"}, context)


def test_network_failure_propagates(context):
    fake = FakeOpenMeteo(forecast=WeatherAPIError("request to forecast failed: timed out"))

    with pytest.raises(WeatherAPIError, match="timed out"):
        make_agent(fake).run({"city": "Dallas"}, context)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"utc_offset_seconds": None}, "utc_offset_seconds"),
        ({"hourly": None}, "hourly"),
        ({"hourly": {"temperature_2m": [1.0]}}, "hourly.time"),
        (
            {"hourly": {**forecast_payload()["hourly"], "weather_code": [0, 61]}},
            "hourly.weather_code",
        ),
        (
            {"hourly": {**forecast_payload()["hourly"], "temperature_2m": [20.5, None, 23.4]}},
            "temperature_2m",
        ),
        (
            {"hourly": {**forecast_payload()["hourly"], "precipitation_probability": [5, 140, 20]}},
            "outside 0-100",
        ),
        ({"hourly_units": {"temperature_2m": "°F"}}, "°C"),
    ],
)
def test_malformed_forecast(context, overrides, message):
    fake = FakeOpenMeteo(forecast=forecast_payload(**overrides))

    with pytest.raises(WeatherAPIError, match=message):
        make_agent(fake).run({"city": "Dallas"}, context)


def test_current_hour_missing_from_forecast(context):
    later = datetime(2026, 10, 12, 19, 30, tzinfo=timezone.utc)

    with pytest.raises(WeatherAPIError, match="no entry for local hour 2026-10-12T14:00"):
        make_agent(now=later).run({"city": "Dallas"}, context)


def test_non_object_response(context):
    with pytest.raises(WeatherAPIError, match="not a JSON object"):
        make_agent(FakeOpenMeteo(forecast=["not", "a", "dict"])).run({"city": "Dallas"}, context)


# get_json, with urlopen replaced ---------------------------------------------


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_get_json_builds_query_and_passes_timeout(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"], seen["timeout"] = request.full_url, timeout
        return FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(openmeteo, "urlopen", fake_urlopen)

    assert get_json("https://example.test/api", {"name": "New York", "count": 1}, timeout=3) == {"ok": True}
    assert seen == {"url": "https://example.test/api?name=New+York&count=1", "timeout": 3}


@pytest.mark.parametrize(
    "error, message",
    [
        (
            HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b'{"error": true, "reason": "bad latitude"}')),
            "HTTP 400: bad latitude",
        ),
        (HTTPError("u", 503, "Unavailable", {}, io.BytesIO(b"")), "HTTP 503"),
        (URLError("Name or service not known"), "Name or service not known"),
        (TimeoutError("timed out"), "timed out"),
    ],
)
def test_get_json_wraps_transport_errors(monkeypatch, error, message):
    def fake_urlopen(request, timeout):
        raise error

    monkeypatch.setattr(openmeteo, "urlopen", fake_urlopen)

    with pytest.raises(WeatherAPIError, match=message):
        get_json("https://example.test/api", {})


def test_get_json_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(openmeteo, "urlopen", lambda request, timeout: FakeResponse(b"<html>"))

    with pytest.raises(WeatherAPIError, match="not valid JSON"):
        get_json("https://example.test/api", {})


def test_default_agent_uses_real_http_client_with_timeout(monkeypatch, context):
    # WeatherAgent() as discovery creates it: confirm it goes through get_json/urlopen.
    timeouts = []

    def fake_urlopen(request, timeout):
        timeouts.append(timeout)
        if request.full_url.startswith(GEOCODING_URL):
            return FakeResponse(json.dumps(GEOCODE_DALLAS).encode())
        return FakeResponse(json.dumps(forecast_payload()).encode())

    monkeypatch.setattr(openmeteo, "urlopen", fake_urlopen)
    agent = WeatherAgent(clock=lambda: NOW_UTC)

    assert agent.run({"city": "Dallas"}, context)["weather"]["condition"] == "rainy"
    assert timeouts == [openmeteo.DEFAULT_TIMEOUT_SECONDS] * 2
