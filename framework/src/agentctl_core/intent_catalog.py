"""Build the natural-language goal catalog from installed capability metadata.

Only outputs advertised with ``GoalSpec`` become goals. For each goal, the
existing planner works out the chain of capabilities that produces it, and
the goal's parameters are the inputs of that chain:

- required: keys some step ``requires`` that no step in the chain produces;
- optional: keys listed in a step's ``optional_inputs``.

Inputs of capabilities outside the chain are never included.
"""

from dataclasses import dataclass
from typing import Any

from agentctl_core.errors import IntentCatalogError, PlanningError
from agentctl_core.planner import CapabilityPlanner
from agentctl_core.registry import AgentRegistry
from agentctl_core.sdk import Capability, InputSpec

SUPPORTED_VALUE_TYPES = ("string",)


@dataclass
class ParameterSpec:
    name: str
    description: str
    required: bool
    value_type: str = "string"
    allowed_values: list[str] | None = None


@dataclass
class GoalEntry:
    name: str
    description: str
    steps: list[str]
    parameters: dict[str, ParameterSpec]

    @property
    def required(self) -> list[str]:
        return [name for name, spec in self.parameters.items() if spec.required]


@dataclass
class IntentCatalog:
    goals: dict[str, GoalEntry]

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready description of the goals, e.g. for a provider prompt."""
        return {
            "goals": [
                {
                    "name": goal.name,
                    "description": goal.description,
                    "parameters": {
                        spec.name: {
                            "type": spec.value_type,
                            "description": spec.description,
                            "required": spec.required,
                            **({"allowed_values": spec.allowed_values} if spec.allowed_values else {}),
                        }
                        for spec in goal.parameters.values()
                    },
                }
                for goal in self.goals.values()
            ]
        }


def build_intent_catalog(registry: AgentRegistry) -> IntentCatalog:
    capabilities = {
        capability.name: capability
        for agent in registry.list_agents()
        for capability in agent.manifest.capabilities
    }
    advertised: dict[str, tuple[str, str]] = {}  # goal -> (capability, description)
    for capability in capabilities.values():
        _check_metadata(capability)
        for goal in capability.goals:
            if goal.output_key in advertised:
                raise IntentCatalogError(
                    f"goal {goal.output_key!r} is advertised by both "
                    f"{advertised[goal.output_key][0]!r} and {capability.name!r}",
                    capability=capability.name,
                    goal=goal.output_key,
                )
            advertised[goal.output_key] = (capability.name, goal.description)

    # Keys some capability requires but none produces must come from the user.
    # They are given placeholder values only so the planner can find each
    # goal's chain; these values are never used for execution.
    produced = {key for c in capabilities.values() for key in c.produces}
    external = {key for c in capabilities.values() for key in c.requires} - produced
    placeholders = dict.fromkeys(external)
    planner = CapabilityPlanner(registry)

    goals = {}
    for goal, (owner, description) in sorted(advertised.items()):
        try:
            plan = planner.plan_for_goal(goal, placeholders, external)
        except PlanningError as exc:
            raise IntentCatalogError(
                f"cannot derive inputs for goal {goal!r}: {exc}", capability=owner, goal=goal
            ) from exc
        if owner not in plan.steps:
            raise IntentCatalogError(
                f"goal {goal!r} is advertised by {owner!r} but planned through {plan.steps}",
                capability=owner,
                goal=goal,
            )
        chain = [capabilities[name] for name in plan.steps]
        goals[goal] = GoalEntry(goal, description, plan.steps, _parameters(goal, chain))
    return IntentCatalog(goals)


def _parameters(goal: str, chain: list[Capability]) -> dict[str, ParameterSpec]:
    produced = {key for capability in chain for key in capability.produces}
    required = [key for c in chain for key in c.requires if key not in produced]
    optional = [key for c in chain for key in c.optional_inputs if key not in produced]

    parameters: dict[str, ParameterSpec] = {}
    for name in dict.fromkeys(required + optional):
        specs = [(c.name, s) for c in chain for s in c.input_specs if s.name == name]
        if not specs:
            raise IntentCatalogError(
                f"goal {goal!r} needs input {name!r}, but no capability in its chain "
                f"describes it with an InputSpec",
                goal=goal,
            )
        first_owner, first = specs[0]
        for owner, spec in specs[1:]:
            if (spec.value_type, spec.allowed_values) != (first.value_type, first.allowed_values):
                raise IntentCatalogError(
                    f"input {name!r} for goal {goal!r} is described differently by "
                    f"{first_owner!r} and {owner!r}",
                    capability=owner,
                    goal=goal,
                )
        parameters[name] = ParameterSpec(
            name=name,
            description=first.description,
            required=name in required,
            value_type=first.value_type,
            allowed_values=list(first.allowed_values) if first.allowed_values else None,
        )
    return parameters


def _check_metadata(capability: Capability) -> None:
    def fail(message: str) -> None:
        raise IntentCatalogError(f"capability {capability.name!r}: {message}", capability=capability.name)

    optional = capability.optional_inputs
    if len(set(optional)) != len(optional):
        fail("optional_inputs contains duplicates")
    overlap = sorted(set(optional) & set(capability.requires))
    if overlap:
        fail(f"{', '.join(overlap)} cannot be both required and optional")

    declared = set(capability.requires) | set(optional)
    seen: set[str] = set()
    for spec in capability.input_specs:
        if not isinstance(spec, InputSpec):
            fail(f"input_specs entry {spec!r} is not an InputSpec")
        if spec.name not in declared:
            fail(f"InputSpec {spec.name!r} is neither in requires nor in optional_inputs")
        if spec.name in seen:
            fail(f"InputSpec {spec.name!r} is declared more than once")
        seen.add(spec.name)
        if not isinstance(spec.description, str) or not spec.description.strip():
            fail(f"InputSpec {spec.name!r} needs a description")
        if spec.value_type not in SUPPORTED_VALUE_TYPES:
            fail(f"InputSpec {spec.name!r} has unsupported value_type {spec.value_type!r}")
        values = spec.allowed_values
        if values is not None and (
            not isinstance(values, list)
            or not values
            or not all(isinstance(v, str) and v for v in values)
            or len(set(values)) != len(values)
        ):
            fail(f"InputSpec {spec.name!r} allowed_values must be a non-empty list of distinct strings")

    for goal in capability.goals:
        if goal.output_key not in capability.produces:
            fail(f"goal {goal.output_key!r} is not one of its produces keys")
        if not isinstance(goal.description, str) or not goal.description.strip():
            fail(f"goal {goal.output_key!r} needs a description")
