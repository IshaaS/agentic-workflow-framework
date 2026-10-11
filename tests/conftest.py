import io
import json
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest

from agentctl_core import RuntimeContext


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that tries to open a network connection or resolve a host."""

    def blocked(*args, **kwargs):
        raise RuntimeError("network access is not allowed in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def context() -> RuntimeContext:
    return RuntimeContext(session_id="test-session", workflow_id="test-workflow", inputs={})


@pytest.fixture
def seeded_db(tmp_path):
    """A fresh wardrobe database with the demo seed items, unique per test."""
    from agentctl_agents.shelf.db import initialize_database

    path = tmp_path / "wardrobe.db"
    initialize_database(path, seed=True)
    return path


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def rainy_forecast():
    """Identical rainy 22°C rows for every UTC hour from yesterday to tomorrow."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hours = [now + timedelta(hours=offset) for offset in range(-24, 25)]
    return {
        "timezone": "GMT",
        "utc_offset_seconds": 0,
        "hourly": {
            "time": [h.strftime("%Y-%m-%dT%H:00") for h in hours],
            "temperature_2m": [22.0] * len(hours),
            "weather_code": [61] * len(hours),
            "precipitation_probability": [65] * len(hours),
            "wind_speed_10m": [15.0] * len(hours),
        },
    }


@pytest.fixture
def fake_weather_http(monkeypatch):
    """Replace the weather agent's Open-Meteo transport; returns the requested hosts."""
    from agentctl_agents.weather import openmeteo

    hosts = []

    def fake_urlopen(request, timeout):
        url = urlparse(request.full_url)
        hosts.append(url.hostname)
        if url.hostname == "geocoding-api.open-meteo.com":
            body = {"results": [{"name": "Dallas", "country": "US", "latitude": 32.8, "longitude": -96.8}]}
        elif url.hostname == "api.open-meteo.com":
            body = rainy_forecast()
        else:
            raise AssertionError(f"unexpected request to {url.hostname}")
        return FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(openmeteo, "urlopen", fake_urlopen)
    return hosts


class FakeIntentProvider:
    """Stands in for an LLM: returns a scripted intent (or raises) and records each call."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def resolve(self, request, catalog):
        self.calls.append((request, catalog))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def fake_intent():
    """Factory: ``fake_intent(answer)`` builds a FakeIntentProvider."""
    return FakeIntentProvider
