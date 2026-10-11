"""Public contracts for agent and workflow packages."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from agentctl_core.context import RuntimeContext


@dataclass
class InputSpec:
    """Describes one input key of a capability for natural-language requests.

    Whether the input is required comes from the capability: keys in
    ``requires`` are required, keys in ``optional_inputs`` are optional.
    ``value_type`` is currently always ``"string"``.
    """

    name: str
    description: str
    value_type: str = "string"
    allowed_values: list[str] | None = None


@dataclass
class GoalSpec:
    """Advertises one of a capability's ``produces`` keys as a user-facing goal."""

    output_key: str
    description: str


@dataclass
class Capability:
    """An action an agent offers, described by the data keys it consumes and produces.

    Planning uses only ``name``, ``requires`` and ``produces``. The remaining
    fields are optional metadata for natural-language requests:
    ``optional_inputs`` lists keys the agent accepts but does not need,
    ``input_specs`` describes inputs, and ``goals`` advertises outputs a user
    can ask for.
    """

    name: str
    requires: list[str]
    produces: list[str]
    optional_inputs: list[str] = field(default_factory=list)
    input_specs: list[InputSpec] = field(default_factory=list)
    goals: list[GoalSpec] = field(default_factory=list)


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
