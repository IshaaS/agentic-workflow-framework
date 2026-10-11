"""Placeholder shelf agent. Manifest only; behavior arrives in a later sprint."""

from typing import Any

from agentctl_core import AgentManifest, BaseAgent, Capability, RuntimeContext


class ShelfAgent(BaseAgent):
    @property
    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="shelf_manager",
            version="0.1.0",
            description="Matches clothing requirements to items on the personal shelf",
            capabilities=[
                Capability(
                    name="shelf.match",
                    requires=["clothing_requirements"],
                    produces=["outfit"],
                )
            ],
        )

    def run(self, inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]:
        raise NotImplementedError(
            "ShelfAgent is a placeholder; shelf matching is not implemented yet"
        )
