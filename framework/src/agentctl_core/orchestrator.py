"""Run a WorkflowPlan one step at a time, passing outputs forward through a RuntimeContext."""

import time
from datetime import datetime, timezone
from typing import Any, NoReturn

from agentctl_core.context import RuntimeContext
from agentctl_core.errors import WorkflowExecutionError
from agentctl_core.registry import AgentRegistry
from agentctl_core.sdk import BaseAgent, Capability, WorkflowPlan


class SequentialOrchestrator:
    """Executes plans against the agents in a registry.

    Each step receives ``{**context.inputs, **outputs so far}`` and must return
    a dict with exactly the keys its capability declares in ``produces``.
    Those keys are stored in ``context.results`` by output name. The first
    failure stops the workflow; outputs from earlier steps stay in
    ``context.results``.

    Lifecycle events are appended to ``context.events`` and logged through
    ``context.logger``; no logging handlers are configured here.
    """

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def execute(self, plan: WorkflowPlan, context: RuntimeContext) -> RuntimeContext:
        run = _Run(context, plan)
        run.workflow_started()

        steps = self._resolve_steps(plan, run)
        working: dict[str, Any] = {**context.inputs, **context.results}
        for index, (agent, capability) in enumerate(steps):
            outputs = self._run_step(index, agent, capability, working, run)
            for key in capability.produces:
                context.results[key] = outputs[key]
                working[key] = outputs[key]

        run.workflow_completed()
        return context

    def _resolve_steps(self, plan: WorkflowPlan, run: "_Run") -> list[tuple[BaseAgent, Capability]]:
        steps = []
        for index, name in enumerate(plan.steps):
            if name in plan.steps[:index]:
                run.fail(f"plan repeats capability {name!r}", "duplicate_step", index, name)
            agent = self._registry.find_by_capability(name)
            if agent is None:
                run.fail(f"no registered agent provides {name!r}", "unknown_capability", index, name)
            capability = next(c for c in agent.manifest.capabilities if c.name == name)
            steps.append((agent, capability))
        return steps

    def _run_step(
        self,
        index: int,
        agent: BaseAgent,
        capability: Capability,
        working: dict[str, Any],
        run: "_Run",
    ) -> dict[str, Any]:
        agent_name = agent.manifest.name
        step = run.step_started(index, capability.name, agent_name)

        missing = [key for key in capability.requires if key not in working]
        if missing:
            step.fail(f"missing required input(s) {', '.join(missing)}", "missing_input", missing)

        try:
            outputs = agent.run(dict(working), run.context)
        except Exception as exc:
            step.fail(f"agent raised {type(exc).__name__}: {exc}", "agent_error", cause=exc)

        if not isinstance(outputs, dict):
            step.fail(f"agent returned {type(outputs).__name__}, expected dict", "invalid_output")
        missing = [key for key in capability.produces if key not in outputs]
        if missing:
            step.fail(f"agent did not return declared output(s) {', '.join(missing)}", "invalid_output", missing)
        unexpected = sorted(set(outputs) - set(capability.produces), key=str)
        if unexpected:
            step.fail(
                f"agent returned undeclared output(s) {', '.join(map(str, unexpected))}",
                "invalid_output",
                [str(key) for key in unexpected],
            )
        conflicts = [key for key in capability.produces if key in working]
        if conflicts:
            step.fail(
                f"output(s) {', '.join(conflicts)} would overwrite an existing input or output",
                "output_conflict",
                conflicts,
            )

        step.completed(list(capability.produces))
        return outputs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


class _Run:
    """Event recording and logging for one execute() call.

    ``step_index`` fields are 0-based; log and error text counts steps from 1.
    """

    def __init__(self, context: RuntimeContext, plan: WorkflowPlan) -> None:
        self.context = context
        self.plan = plan
        self.ids = {"workflow_id": context.workflow_id, "session_id": context.session_id}
        self.start = time.perf_counter()

    def emit(self, event_type: str, **fields: Any) -> None:
        self.context.events.append({"type": event_type, **self.ids, "timestamp": _now(), **fields})

    def workflow_started(self) -> None:
        self.emit("workflow_started", source=self.plan.source, steps=list(self.plan.steps))
        self.context.logger.info(
            "Workflow %s started (session %s, source %s, steps: %s)",
            self.context.workflow_id,
            self.context.session_id,
            self.plan.source,
            ", ".join(self.plan.steps) or "none",
            extra={**self.ids, "source": self.plan.source},
        )

    def workflow_completed(self) -> None:
        duration = _elapsed_ms(self.start)
        self.emit("workflow_completed", duration_ms=duration)
        self.context.logger.info(
            "Workflow %s completed in %.1f ms (session %s)",
            self.context.workflow_id,
            duration,
            self.context.session_id,
            extra={**self.ids, "duration_ms": duration},
        )

    def step_started(self, index: int, capability: str, agent: str) -> "_Step":
        return _Step(self, index, capability, agent)

    def fail(
        self,
        detail: str,
        reason: str,
        index: int,
        capability: str,
        agent: str | None = None,
        keys: list[str] | None = None,
        cause: BaseException | None = None,
    ) -> NoReturn:
        duration = _elapsed_ms(self.start)
        message = (
            f"workflow {self.context.workflow_id!r} failed at step "
            f"{index + 1} of {len(self.plan.steps)} {capability!r}: {detail}"
        )
        self.emit(
            "workflow_failed",
            step_index=index,
            capability=capability,
            reason=reason,
            error=detail,
            duration_ms=duration,
        )
        self.context.logger.error(
            "Workflow %s failed at step %d/%d (%s) after %.1f ms: %s (session %s)",
            self.context.workflow_id,
            index + 1,
            len(self.plan.steps),
            capability,
            duration,
            detail,
            self.context.session_id,
            extra={**self.ids, "step_index": index, "capability": capability, "duration_ms": duration},
        )
        raise WorkflowExecutionError(
            message,
            reason=reason,
            workflow_id=self.context.workflow_id,
            step_index=index,
            capability=capability,
            agent=agent,
            keys=keys,
        ) from cause


class _Step:
    def __init__(self, run: _Run, index: int, capability: str, agent: str) -> None:
        self.run = run
        self.fields = {"step_index": index, "capability": capability, "agent": agent}
        self.label = f"step {index + 1}/{len(run.plan.steps)} {capability} (agent {agent})"
        self.start = time.perf_counter()
        run.emit("agent_started", **self.fields)
        run.context.logger.info(
            "Workflow %s %s started",
            run.context.workflow_id,
            self.label,
            extra={**run.ids, **self.fields},
        )

    def completed(self, outputs: list[str]) -> None:
        duration = _elapsed_ms(self.start)
        self.run.emit("agent_completed", **self.fields, outputs=outputs, duration_ms=duration)
        self.run.context.logger.info(
            "Workflow %s %s completed in %.1f ms",
            self.run.context.workflow_id,
            self.label,
            duration,
            extra={**self.run.ids, **self.fields, "duration_ms": duration},
        )

    def fail(
        self,
        detail: str,
        reason: str,
        keys: list[str] | None = None,
        cause: BaseException | None = None,
    ) -> NoReturn:
        duration = _elapsed_ms(self.start)
        self.run.emit(
            "agent_failed", **self.fields, reason=reason, error=detail, duration_ms=duration
        )
        self.run.context.logger.error(
            "Workflow %s %s failed after %.1f ms: %s",
            self.run.context.workflow_id,
            self.label,
            duration,
            detail,
            exc_info=cause,
            extra={**self.run.ids, **self.fields, "duration_ms": duration},
        )
        self.run.fail(
            detail,
            reason,
            self.fields["step_index"],
            self.fields["capability"],
            self.fields["agent"],
            keys,
            cause,
        )
