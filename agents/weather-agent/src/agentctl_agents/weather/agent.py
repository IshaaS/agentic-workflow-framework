"""Weather agent: current-hour forecast for a city from Open-Meteo."""

from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable

from agentctl_core import AgentManifest, BaseAgent, Capability, RuntimeContext

from agentctl_agents.weather.openmeteo import (
    DEFAULT_TIMEOUT_SECONDS,
    FetchJson,
    current_hour_weather,
    fetch_forecast,
    geocode,
    get_json,
)


class WeatherAgent(BaseAgent):
    """Returns ``{"weather": {temperature_c, condition, precipitation_probability, wind_speed_kmh}}``.

    ``fetch_json`` and ``clock`` exist so tests can replace the network and the
    current time; by default the agent calls Open-Meteo and uses the real UTC time.
    """

    def __init__(
        self,
        fetch_json: FetchJson | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._fetch_json = fetch_json or partial(get_json, timeout=timeout)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="weather_provider",
            version="0.1.0",
            description="Provides a weather forecast for a city",
            capabilities=[
                Capability(
                    name="weather.forecast",
                    requires=["city"],
                    produces=["weather"],
                )
            ],
        )

    def run(self, inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]:
        city = inputs.get("city")
        if not isinstance(city, str) or not city.strip():
            raise ValueError(f"'city' must be a non-empty string, got {city!r}")

        location = geocode(city.strip(), self._fetch_json)
        forecast = fetch_forecast(location, self._fetch_json)
        weather = current_hour_weather(forecast, self._clock())

        context.logger.info(
            "Weather for %s, %s (%s): %s, %.1f°C",
            location.name,
            location.country,
            forecast.get("timezone", "unknown timezone"),
            weather["condition"],
            weather["temperature_c"],
        )
        return {"weather": weather}
