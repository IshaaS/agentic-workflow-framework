"""Sprint 04 orchestrator tests using test-local fake agents (no plugins, no I/O)."""

import logging

import pytest

from agentctl_core import (
    AgentManifest,
    AgentRegistry,
    BaseAgent,
    Capability,
    RuntimeContext,
    SequentialOrchestrator,
    WorkflowExecutionError,
    WorkflowPlan,
)


class FakeAgent(BaseAgent):
    """Runs ``behavior(inputs)`` and records every call in ``calls``."""

    def __init__(self, name, capability, behavior):
        self._manifest = AgentManifest(name, "0.0.1", f"fake {name}", [capability])
        self.behavior = behavior
        self.calls = []

    @property
    def manifest(self):
        return self._manifest

    def run(self, inputs, context):
        self.calls.append(dict(inputs))
        return self.behavior(inputs)


def make_agents(**overrides):
    """A three-step pipeline: city -> weather -> advice(+activity, optional style) -> outfit."""
    behaviors = {
        "forecast": lambda i: {"weather": {"temp": 21, "city": i["city"]}},
        "advise": lambda i: {"advice": f"{i['activity']}/{i.get('style', 'casual')}/{i['weather']['temp']}"},
        "match": lambda i: {"outfit": f"items for {i['advice']}"},
    }
    behaviors.update(overrides)
    return {
        "forecast": FakeAgent("forecaster", Capability("w.forecast", ["city"], ["weather"]), behaviors["forecast"]),
        "advise": FakeAgent("adviser", Capability("c.advise", ["weather", "activity"], ["advice"]), behaviors["advise"]),
        "match": FakeAgent("matcher", Capability("s.match", ["advice"], ["outfit"]), behaviors["match"]),
    }


def registry_of(agents):
    registry = AgentRegistry()
    for agent in agents.values():
        registry.register(agent)
    return registry


PLAN = WorkflowPlan(steps=["w.forecast", "c.advise", "s.match"], source="generated")
INPUTS = {"city": "Dallas", "activity": "walk", "style": "formal"}


def new_context(inputs=INPUTS):
    return RuntimeContext(session_id="sess-1", workflow_id="wf-1", inputs=dict(inputs))


def execute(agents, plan=PLAN, context=None):
    context = context or new_context()
    return SequentialOrchestrator(registry_of(agents)).execute(plan, context), context


def event_types(context):
    return [(e["type"], e.get("capability")) for e in context.events]


# Successful execution ------------------------------------------------------------


def test_executes_in_order_and_propagates_outputs():
    agents = make_agents()
    result, context = execute(agents)

    assert result is context
    assert context.results == {
        "weather": {"temp": 21, "city": "Dallas"},
        "advice": "walk/formal/21",
        "outfit": "items for walk/formal/21",
    }
    assert [len(a.calls) for a in agents.values()] == [1, 1, 1]


def test_agents_receive_original_inputs_including_optional_ones():
    agents = make_agents()
    execute(agents)

    assert agents["advise"].calls[0] == {**INPUTS, "weather": {"temp": 21, "city": "Dallas"}}
    assert agents["match"].calls[0]["style"] == "formal"


def test_original_inputs_are_not_modified():
    agents = make_agents(forecast=lambda i: (i.pop("city"), {"weather": {"temp": 1}})[1])
    _, context = execute(agents)

    assert context.inputs == INPUTS


def test_success_events():
    _, context = execute(make_agents())

    assert event_types(context) == [
        ("workflow_started", None),
        ("agent_started", "w.forecast"),
        ("agent_completed", "w.forecast"),
        ("agent_started", "c.advise"),
        ("agent_completed", "c.advise"),
        ("agent_started", "s.match"),
        ("agent_completed", "s.match"),
        ("workflow_completed", None),
    ]
    started, first_done = context.events[0], context.events[2]
    assert started["source"] == "generated"
    assert started["steps"] == PLAN.steps
    for event in context.events:
        assert event["workflow_id"] == "wf-1" and event["session_id"] == "sess-1"
        assert isinstance(event["timestamp"], str)
    assert first_done["agent"] == "forecaster"
    assert first_done["step_index"] == 0
    assert first_done["outputs"] == ["weather"]
    assert first_done["duration_ms"] >= 0


def test_logs_lifecycle_with_identifiers(caplog):
    with caplog.at_level(logging.INFO, logger="agentctl"):
        execute(make_agents())

    messages = [r.getMessage() for r in caplog.records]
    assert any("Workflow wf-1 started" in m and "sess-1" in m for m in messages)
    assert any("step 2/3 c.advise (agent adviser) completed" in m for m in messages)
    assert any("Workflow wf-1 completed" in m for m in messages)
    step_record = next(r for r in caplog.records if "step 1/3" in r.getMessage())
    assert (step_record.workflow_id, step_record.session_id) == ("wf-1", "sess-1")
    assert (step_record.capability, step_record.step_index) == ("w.forecast", 0)
    # Input values are not logged.
    assert not any("Dallas" in m for m in messages)


def test_does_not_configure_logging_handlers():
    root_handlers = list(logging.getLogger().handlers)
    execute(make_agents())

    assert logging.getLogger("agentctl").handlers == []
    assert logging.getLogger().handlers == root_handlers


def test_empty_plan_completes_without_steps():
    _, context = execute(make_agents(), WorkflowPlan([], "generated"))

    assert context.results == {}
    assert event_types(context) == [("workflow_started", None), ("workflow_completed", None)]


# Failures ------------------------------------------------------------------------


def assert_failed_at(context, capability, completed):
    types = event_types(context)
    assert types[-2] == ("agent_failed", capability)
    assert types[-1] == ("workflow_failed", capability)
    assert [c for t, c in types if t == "agent_completed"] == completed


def test_agent_exception_stops_workflow_and_keeps_earlier_results(caplog):
    cause = TimeoutError("shelf database locked")
    agents = make_agents(match=lambda i: (_ for _ in ()).throw(cause))

    with caplog.at_level(logging.ERROR, logger="agentctl"):
        with pytest.raises(WorkflowExecutionError) as excinfo:
            execute(agents, context=(context := new_context()))

    error = excinfo.value
    assert (error.reason, error.capability, error.step_index, error.agent) == (
        "agent_error", "s.match", 2, "matcher"
    )
    assert error.workflow_id == "wf-1"
    assert error.__cause__ is cause
    assert "step 3 of 3 's.match'" in str(error) and "TimeoutError" in str(error)
    assert set(context.results) == {"weather", "advice"}
    assert_failed_at(context, "s.match", ["w.forecast", "c.advise"])
    assert context.events[-2]["reason"] == "agent_error"
    assert any(r.exc_info and r.exc_info[1] is cause for r in caplog.records)


def test_failure_skips_later_steps():
    agents = make_agents(forecast=lambda i: 1 / 0)

    with pytest.raises(WorkflowExecutionError) as excinfo:
        execute(agents, context=(context := new_context()))

    assert isinstance(excinfo.value.__cause__, ZeroDivisionError)
    assert agents["advise"].calls == [] and agents["match"].calls == []
    assert context.results == {}
    assert_failed_at(context, "w.forecast", [])


def test_missing_runtime_input_fails_before_agent_runs():
    agents = make_agents()

    with pytest.raises(WorkflowExecutionError) as excinfo:
        execute(agents, context=(context := new_context({"city": "Dallas"})))

    error = excinfo.value
    assert (error.reason, error.capability, error.keys) == ("missing_input", "c.advise", ["activity"])
    assert agents["advise"].calls == []
    assert_failed_at(context, "c.advise", ["w.forecast"])


@pytest.mark.parametrize(
    "returned, keys, message",
    [
        (["not", "a", "dict"], [], "returned list, expected dict"),
        ({}, ["weather"], "did not return declared output(s) weather"),
        ({"weather": 1, "debug": 2}, ["debug"], "undeclared output(s) debug"),
    ],
)
def test_invalid_output_is_not_committed(returned, keys, message):
    agents = make_agents(forecast=lambda i: returned)

    with pytest.raises(WorkflowExecutionError, match=message.replace("(", r"\(").replace(")", r"\)")) as excinfo:
        execute(agents, context=(context := new_context()))

    assert (excinfo.value.reason, excinfo.value.keys) == ("invalid_output", keys)
    assert context.results == {}
    assert agents["advise"].calls == []


def test_output_may_not_overwrite_original_input():
    agents = make_agents()
    context = new_context({**INPUTS, "weather": "user supplied"})

    with pytest.raises(WorkflowExecutionError) as excinfo:
        execute(agents, context=context)

    assert (excinfo.value.reason, excinfo.value.keys) == ("output_conflict", ["weather"])
    assert context.inputs["weather"] == "user supplied"
    assert context.results == {}


def test_output_may_not_overwrite_earlier_output():
    agents = make_agents()
    agents["echo"] = FakeAgent("echoer", Capability("x.echo", ["city"], ["weather"]), lambda i: {"weather": "again"})
    plan = WorkflowPlan(["w.forecast", "x.echo"], "named")

    with pytest.raises(WorkflowExecutionError) as excinfo:
        execute(agents, plan, context := new_context())

    assert (excinfo.value.reason, excinfo.value.capability) == ("output_conflict", "x.echo")
    assert context.results == {"weather": {"temp": 21, "city": "Dallas"}}


def test_unknown_capability_fails_before_any_agent_runs():
    agents = make_agents()

    with pytest.raises(WorkflowExecutionError) as excinfo:
        execute(agents, WorkflowPlan(["w.forecast", "x.missing"], "named"), context := new_context())

    assert (excinfo.value.reason, excinfo.value.step_index) == ("unknown_capability", 1)
    assert agents["forecast"].calls == []
    assert event_types(context) == [("workflow_started", None), ("workflow_failed", "x.missing")]


def test_duplicate_step_rejected_before_any_agent_runs():
    agents = make_agents()

    with pytest.raises(WorkflowExecutionError) as excinfo:
        execute(agents, WorkflowPlan(["w.forecast", "w.forecast"], "named"))

    assert (excinfo.value.reason, excinfo.value.step_index) == ("duplicate_step", 1)
    assert agents["forecast"].calls == []
