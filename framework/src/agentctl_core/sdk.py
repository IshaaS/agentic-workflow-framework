"""Public contracts for agent and workflow packages."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agentctl_core.context import RuntimeContext


@dataclass
class Capability:
    """An action an agent offers, described by the data keys it consumes and produces."""

    name: str
    requires: list[str]
    produces: list[str]


@dataclass
class AgentManifest:
    """Metadata describing an agent, inspectable without running it."""

    name: str
    version: str
    description: str
    capabilities: list[Capability]


class BaseAgent(ABC):
    """Base class every agent implements.

    Agents receive resolved inputs and return a dict keyed by the data keys
    their capability declares in ``produces``. Agents must not call other
    agents; coordination belongs to the orchestrator.
    """

    @property
    @abstractmethod
    def manifest(self) -> AgentManifest:
        ...

    @abstractmethod
    def run(self, inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]:
        ...


@dataclass
class WorkflowDefinition:
    """A named, reusable workflow: an ordered list of capability identifiers."""

    name: str
    description: str
    steps: list[str]


@dataclass
class WorkflowPlan:
    """An ordered list of capability identifiers ready for execution.

    ``source`` is ``"named"`` for plans built from a WorkflowDefinition and
    ``"generated"`` for plans produced by the planner.
    """

    steps: list[str]
    source: str
