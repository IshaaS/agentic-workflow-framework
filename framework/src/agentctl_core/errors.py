"""Typed planning and execution errors.

Every error has a readable message plus attributes a caller can inspect.
``PlanningError`` means no agent has run; ``WorkflowExecutionError`` means
execution started and stopped at a specific step. ``step_index`` attributes
are 0-based; messages count steps from 1.
"""


class PlanningError(Exception):
    """A workflow plan could not be built or validated."""


class UnknownGoalError(PlanningError):
    def __init__(self, goal: str) -> None:
        self.goal = goal
        super().__init__(f"no installed capability produces goal {goal!r}")


class MissingInputError(PlanningError):
    """A declared external input that the caller must supply is absent."""

    def __init__(self, input_name: str, required_by: str) -> None:
        self.input_name = input_name
        self.required_by = required_by
        super().__init__(
            f"missing required input {input_name!r} (required by {required_by!r})"
        )


class MissingCapabilityError(PlanningError):
    """Something needed is not provided by any installed capability.

    Raised during goal planning with ``missing_output`` and ``required_by``,
    and for a named workflow step with ``capability``, ``workflow`` and
    ``step_index``. Fields that do not apply are None.
    """

    def __init__(
        self,
        *,
        missing_output: str | None = None,
        required_by: str | None = None,
        capability: str | None = None,
        workflow: str | None = None,
        step_index: int | None = None,
    ) -> None:
        self.missing_output = missing_output
        self.required_by = required_by
        self.capability = capability
        self.workflow = workflow
        self.step_index = step_index
        if capability is not None:
            message = (
                f"workflow {workflow!r} step {step_index + 1} references capability "
                f"{capability!r}, which is not installed"
            )
        else:
            message = (
                f"no installed capability produces {missing_output!r} "
                f"(required by {required_by!r}), and it is not a declared external input"
            )
        super().__init__(message)


class CircularDependencyError(PlanningError):
    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(f"circular dependency: {' -> '.join(cycle)}")


class AmbiguousProviderError(PlanningError):
    def __init__(self, output: str, providers: list[str]) -> None:
        self.output = output
        self.providers = providers
        super().__init__(
            f"output {output!r} is produced by more than one capability: {', '.join(providers)}"
        )


class InvalidWorkflowPlanError(PlanningError):
    """A plan's steps are unusable as declared (order, duplicates, conflicts)."""

    def __init__(
        self,
        message: str,
        *,
        workflow: str | None = None,
        step_index: int | None = None,
        capability: str | None = None,
        keys: list[str] | None = None,
    ) -> None:
        self.workflow = workflow
        self.step_index = step_index
        self.capability = capability
        self.keys = keys or []
        super().__init__(message)


class WorkflowExecutionError(Exception):
    """Execution stopped at a step. The original exception, if any, is ``__cause__``.

    ``reason`` is one of: ``unknown_capability``, ``duplicate_step``,
    ``missing_input``, ``agent_error``, ``invalid_output``, ``output_conflict``.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        workflow_id: str,
        step_index: int,
        capability: str,
        agent: str | None = None,
        keys: list[str] | None = None,
    ) -> None:
        self.reason = reason
        self.workflow_id = workflow_id
        self.step_index = step_index
        self.capability = capability
        self.agent = agent
        self.keys = keys or []
        super().__init__(message)
