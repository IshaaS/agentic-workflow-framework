"""Build WorkflowPlans from a goal or a named workflow, using only registry metadata."""

from collections.abc import Iterable, Mapping
from typing import Any

from agentctl_core.errors import (
    AmbiguousProviderError,
    CircularDependencyError,
    InvalidWorkflowPlanError,
    MissingCapabilityError,
    MissingInputError,
    UnknownGoalError,
)
from agentctl_core.registry import AgentRegistry
from agentctl_core.sdk import Capability, WorkflowDefinition, WorkflowPlan


class CapabilityPlanner:
    """Plans capability steps from the ``requires``/``produces`` of registered agents.

    Rules shared by both planning methods:

    - A data key counts as available if it is a key of ``inputs``; values are
      not inspected. A supplied key is always used as-is, even when some
      capability could produce it.
    - ``external_inputs`` names keys the caller is expected to supply. A
      missing key in that set is reported as ``MissingInputError``; any other
      unresolvable key is reported as a missing capability or an invalid plan.
      Key names are never interpreted.
    - No two steps may produce the same key, and no step may produce a key
      already in ``inputs``.
    """

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def plan_for_goal(
        self,
        goal: str,
        inputs: Mapping[str, Any],
        external_inputs: Iterable[str] = (),
    ) -> WorkflowPlan:
        """Resolve producers for ``goal`` backwards, dependencies first.

        If ``goal`` is already in ``inputs`` the plan is empty. A key with more
        than one producer raises ``AmbiguousProviderError`` only when that key
        is actually needed.
        """
        capabilities = self._capabilities()
        producers: dict[str, list[str]] = {}
        for capability in capabilities.values():
            for output in capability.produces:
                producers.setdefault(output, []).append(capability.name)

        available = set(inputs)
        external = set(external_inputs)
        steps: list[str] = []
        path: list[str] = []

        def resolve(key: str, required_by: str | None) -> None:
            if key in available:
                return
            providers = producers.get(key, [])
            if len(providers) > 1:
                raise AmbiguousProviderError(key, sorted(providers))
            if not providers:
                if required_by is None:
                    raise UnknownGoalError(key)
                if key in external:
                    raise MissingInputError(key, required_by)
                raise MissingCapabilityError(missing_output=key, required_by=required_by)

            name = providers[0]
            if name in steps:
                return
            if name in path:
                raise CircularDependencyError(path[path.index(name):] + [name])
            path.append(name)
            for requirement in capabilities[name].requires:
                resolve(requirement, name)
            path.pop()
            steps.append(name)

        resolve(goal, None)
        _check_output_conflicts(steps, capabilities, available)
        return WorkflowPlan(steps=steps, source="generated")

    def plan_from_workflow(
        self,
        workflow: WorkflowDefinition,
        inputs: Mapping[str, Any],
        external_inputs: Iterable[str] = (),
    ) -> WorkflowPlan:
        """Validate a named workflow's steps in their declared order. Never reorders."""
        capabilities = self._capabilities()
        external = set(external_inputs)
        steps = list(workflow.steps)

        if not steps:
            raise InvalidWorkflowPlanError(
                f"workflow {workflow.name!r} has no steps", workflow=workflow.name
            )
        for index, name in enumerate(steps):
            if name not in capabilities:
                raise MissingCapabilityError(
                    capability=name, workflow=workflow.name, step_index=index
                )
            if name in steps[:index]:
                raise InvalidWorkflowPlanError(
                    f"workflow {workflow.name!r} step {index + 1} repeats capability {name!r}",
                    workflow=workflow.name,
                    step_index=index,
                    capability=name,
                )

        available = set(inputs)
        for index, name in enumerate(steps):
            for requirement in capabilities[name].requires:
                if requirement in available:
                    continue
                later = [
                    later_name
                    for later_name in steps[index + 1:]
                    if requirement in capabilities[later_name].produces
                ]
                if later:
                    raise InvalidWorkflowPlanError(
                        f"workflow {workflow.name!r} step {index + 1} {name!r} requires "
                        f"{requirement!r}, which is only produced by a later step "
                        f"({later[0]!r}); steps are out of order",
                        workflow=workflow.name,
                        step_index=index,
                        capability=name,
                        keys=[requirement],
                    )
                if requirement in external:
                    raise MissingInputError(requirement, name)
                raise InvalidWorkflowPlanError(
                    f"workflow {workflow.name!r} step {index + 1} {name!r} requires "
                    f"{requirement!r}, which no earlier step produces and is not a "
                    f"declared external input",
                    workflow=workflow.name,
                    step_index=index,
                    capability=name,
                    keys=[requirement],
                )
            available.update(capabilities[name].produces)

        _check_output_conflicts(steps, capabilities, set(inputs), workflow.name)
        return WorkflowPlan(steps=steps, source="named")

    def _capabilities(self) -> dict[str, Capability]:
        return {
            capability.name: capability
            for agent in self._registry.list_agents()
            for capability in agent.manifest.capabilities
        }


def _check_output_conflicts(
    steps: list[str],
    capabilities: dict[str, Capability],
    inputs: set[str],
    workflow: str | None = None,
) -> None:
    produced_by: dict[str, str] = {}
    for index, name in enumerate(steps):
        for output in capabilities[name].produces:
            if output in inputs:
                owner = "an input"
            elif output in produced_by:
                owner = f"step {produced_by[output]!r}"
            else:
                produced_by[output] = name
                continue
            raise InvalidWorkflowPlanError(
                f"step {index + 1} {name!r} would overwrite {output!r}, already provided by {owner}",
                workflow=workflow,
                step_index=index,
                capability=name,
                keys=[output],
            )
