"""Sprint 01 unit tests for the agentctl_core SDK contracts."""

import dataclasses
import importlib.metadata
import logging

import pytest

import agentctl_core
from agentctl_core.context import RuntimeContext
from agentctl_core.sdk import (
    AgentManifest,
    BaseAgent,
    Capability,
    WorkflowDefinition,
    WorkflowPlan,
)


class DummyAgent(BaseAgent):
    """Test-local agent; not a real plugin."""

    @property
    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="dummy",
            version="0.1.0",
            description="A tiny SDK contract test",
            capabilities=[
                Capability(name="demo.echo", requires=["text"], produces=["echo"])
            ],
        )

    def run(self, inputs, context):
        context.events.append({"type": "agent_ran", "agent": self.manifest.name})
        context.memory["last_text"] = inputs["text"]
        return {"echo": inputs["text"]}


def make_context(**overrides) -> RuntimeContext:
    values = {"session_id": "session-1", "workflow_id": "wf-1", "inputs": {}}
    values.update(overrides)
    return RuntimeContext(**values)


# 1. Installation ----------------------------------------------------------


def test_distribution_is_installed():
    assert importlib.metadata.version("agentctl-core") == agentctl_core.__version__


def test_distribution_has_no_runtime_dependencies():
    requirements = importlib.metadata.requires("agentctl-core") or []
    runtime = [r for r in requirements if "extra ==" not in r]
    assert runtime == []


# 2. BaseAgent abstraction -------------------------------------------------


def test_base_agent_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseAgent()


def test_subclass_missing_run_cannot_be_instantiated():
    class NoRun(BaseAgent):
        @property
        def manifest(self):
            return AgentManifest("x", "0", "", [])

    with pytest.raises(TypeError):
        NoRun()


def test_subclass_missing_manifest_cannot_be_instantiated():
    class NoManifest(BaseAgent):
        def run(self, inputs, context):
            return {}

    with pytest.raises(TypeError):
        NoManifest()


def test_dummy_agent_can_be_instantiated():
    agent = DummyAgent()
    assert isinstance(agent, BaseAgent)


# 3. run(inputs, context) --------------------------------------------------


def test_dummy_agent_run_returns_expected_dict():
    agent = DummyAgent()
    context = make_context(inputs={"text": "hello"})

    result = agent.run({"text": "hello"}, context)

    assert result == {"echo": "hello"}
    assert context.memory == {"last_text": "hello"}
    assert context.events == [{"type": "agent_ran", "agent": "dummy"}]


# 4. Manifest and capabilities ---------------------------------------------


def test_manifest_stores_metadata_and_capabilities():
    manifest = DummyAgent().manifest

    assert manifest.name == "dummy"
    assert manifest.version == "0.1.0"
    assert manifest.description == "A tiny SDK contract test"
    assert len(manifest.capabilities) == 1

    capability = manifest.capabilities[0]
    assert capability.name == "demo.echo"
    assert capability.requires == ["text"]
    assert capability.produces == ["echo"]


def test_manifest_supports_multiple_capabilities():
    manifest = AgentManifest(
        name="multi",
        version="1.0.0",
        description="Declares two capabilities",
        capabilities=[
            Capability(name="a.one", requires=["x"], produces=["y"]),
            Capability(name="a.two", requires=["y"], produces=["z"]),
        ],
    )

    assert [c.name for c in manifest.capabilities] == ["a.one", "a.two"]


def test_manifest_is_inspectable_with_dataclass_tools():
    assert dataclasses.asdict(DummyAgent().manifest) == {
        "name": "dummy",
        "version": "0.1.0",
        "description": "A tiny SDK contract test",
        "capabilities": [
            {
                "name": "demo.echo",
                "requires": ["text"],
                "produces": ["echo"],
                # Optional natural-language metadata added in Sprint 6; empty by default.
                "optional_inputs": [],
                "input_specs": [],
                "goals": [],
            }
        ],
    }


# 5. RuntimeContext mutable defaults ---------------------------------------


def test_contexts_do_not_share_mutable_defaults():
    first = make_context(workflow_id="wf-1")
    second = make_context(workflow_id="wf-2")

    first.results["step"] = {"k": "v"}
    first.memory["note"] = 1
    first.events.append({"type": "workflow_started"})

    assert second.results == {}
    assert second.memory == {}
    assert second.events == []
    assert first.results is not second.results
    assert first.memory is not second.memory
    assert first.events is not second.events


def test_context_stores_identifiers_and_inputs():
    context = make_context(inputs={"text": "hi"})

    assert context.session_id == "session-1"
    assert context.workflow_id == "wf-1"
    assert context.inputs == {"text": "hi"}


# 6. Logger ----------------------------------------------------------------


def test_context_exposes_usable_logger(caplog):
    context = make_context()

    assert isinstance(context.logger, logging.Logger)
    assert context.logger.name == "agentctl"

    with caplog.at_level(logging.INFO, logger="agentctl"):
        context.logger.info("hello from agent")

    assert "hello from agent" in caplog.text


def test_sdk_does_not_configure_logging_handlers():
    make_context()

    assert logging.getLogger("agentctl").handlers == []
    # pytest installs its own capture handlers on the root logger, so check
    # that none of them came from the SDK rather than asserting it is empty.
    assert not any(
        type(h).__module__.startswith("agentctl_core")
        for h in logging.getLogger().handlers
    )


def test_context_accepts_custom_logger():
    custom = logging.getLogger("agentctl.test")
    context = make_context(logger=custom)

    assert context.logger is custom


# 7. Workflow types --------------------------------------------------------


def test_workflow_definition_holds_capability_ids():
    definition = WorkflowDefinition(
        name="demo_flow",
        description="Echo then shout",
        steps=["demo.echo", "demo.shout"],
    )

    assert definition.name == "demo_flow"
    assert definition.description == "Echo then shout"
    assert definition.steps == ["demo.echo", "demo.shout"]
    assert all(isinstance(step, str) for step in definition.steps)


def test_workflow_plan_holds_capability_ids_and_source():
    named = WorkflowPlan(steps=["demo.echo"], source="named")
    generated = WorkflowPlan(steps=["demo.echo", "demo.shout"], source="generated")

    assert named.steps == ["demo.echo"]
    assert named.source == "named"
    assert generated.source == "generated"
    for plan in (named, generated):
        assert all(isinstance(step, str) for step in plan.steps)
        assert not any(isinstance(step, BaseAgent) for step in plan.steps)


def test_workflow_types_are_dataclasses():
    assert dataclasses.asdict(WorkflowPlan(steps=["a.b"], source="named")) == {
        "steps": ["a.b"],
        "source": "named",
    }


# 8. Public imports --------------------------------------------------------


def test_public_types_are_reexported_from_package():
    from agentctl_core import (
        AgentManifest as A,
        BaseAgent as B,
        Capability as C,
        RuntimeContext as R,
        WorkflowDefinition as D,
        WorkflowPlan as P,
    )

    assert (A, B, C, R, D, P) == (
        AgentManifest,
        BaseAgent,
        Capability,
        RuntimeContext,
        WorkflowDefinition,
        WorkflowPlan,
    )
    assert set(agentctl_core.__all__) >= {
        "AgentManifest",
        "BaseAgent",
        "Capability",
        "RuntimeContext",
        "WorkflowDefinition",
        "WorkflowPlan",
    }

