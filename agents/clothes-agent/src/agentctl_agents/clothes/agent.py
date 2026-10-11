"""Placeholder clothes agent. Manifest only; behavior arrives in a later sprint."""

from typing import Any

from agentctl_core import AgentManifest, BaseAgent, Capability, RuntimeContext


class ClothesAgent(BaseAgent):
    @property
    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="clothes_adviser",
            version="0.1.0",
            description="Recommends clothing types for the weather and activity",
            capabilities=[
                Capability(
                    name="clothes.advise",
                    requires=["weather", "activity"],
                    produces=["clothing_requirements"],
                )
            ],
        )

    def run(self, inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]:
        raise NotImplementedError(
            "ClothesAgent is a placeholder; clothing advice is not implemented yet"
        )
