"""Placeholder weather agent. Manifest only; behavior arrives in a later sprint."""

from typing import Any

from agentctl_core import AgentManifest, BaseAgent, Capability, RuntimeContext


class WeatherAgent(BaseAgent):
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
        raise NotImplementedError(
            "WeatherAgent is a placeholder; fetching a weather forecast is not implemented yet"
        )
