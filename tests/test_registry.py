"""Sprint 02 unit tests for AgentRegistry and WorkflowRegistry."""

import pytest

from agentctl_core import (
    AgentManifest,
    AgentRegistry,
    BaseAgent,
    Capability,
    WorkflowDefinition,
    WorkflowRegistry,
)


class FakeAgent(BaseAgent):
    """Test-local agent whose manifest is supplied at construction."""

    def __init__(self, name: str, *capability_names: str):
        self._manifest = AgentManifest(
            name=name,
            version="0.0.1",
            description=f"fake agent {name}",
            capabilities=[Capability(c, requires=[], produces=[]) for c in capability_names],
        )

    @property
    def manifest(self) -> AgentManifest:
        return self._manifest

    def run(self, inputs, context):
        return {}


@pytest.fixture
def agents() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture
def workflows() -> WorkflowRegistry:
    return WorkflowRegistry()


# AgentRegistry -------------------------------------------------------------


def test_register_and_get_agent(agents):
    agent = FakeAgent("alpha", "a.one")
    agents.register(agent)

    assert agents.get_agent("alpha") is agent


def test_get_unknown_agent_returns_none(agents):
    assert agents.get_agent("missing") is None


def test_list_agents_sorted_by_name(agents):
    for name in ("charlie", "alpha", "bravo"):
        agents.register(FakeAgent(name, f"{name}.cap"))

    assert [a.manifest.name for a in agents.list_agents()] == ["alpha", "bravo", "charlie"]


def test_list_agents_empty(agents):
    assert agents.list_agents() == []


def test_find_by_capability(agents):
    multi = FakeAgent("multi", "m.first", "m.second")
    agents.register(multi)

    assert agents.find_by_capability("m.first") is multi
    assert agents.find_by_capability("m.second") is multi
    assert agents.find_by_capability("m.unknown") is None


def test_duplicate_agent_name_rejected(agents):
    agents.register(FakeAgent("alpha", "a.one"))

    with pytest.raises(ValueError, match="'alpha' is already registered"):
        agents.register(FakeAgent("alpha", "a.two"))


def test_duplicate_capability_provider_rejected(agents):
    first = FakeAgent("alpha", "shared.cap")
    agents.register(first)

    with pytest.raises(ValueError, match="'shared.cap'.*already provided by agent 'alpha'"):
        agents.register(FakeAgent("bravo", "shared.cap"))

    assert agents.get_agent("bravo") is None
    assert agents.find_by_capability("shared.cap") is first


def test_duplicate_capability_within_agent_rejected(agents):
    with pytest.raises(ValueError, match="more than once"):
        agents.register(FakeAgent("alpha", "a.dup", "a.dup"))

    assert agents.list_agents() == []


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_agent_name_rejected(agents, name):
    with pytest.raises(ValueError, match="blank manifest name"):
        agents.register(FakeAgent(name, "a.one"))


@pytest.mark.parametrize("name", ["", "  "])
def test_blank_capability_name_rejected(agents, name):
    with pytest.raises(ValueError, match="blank capability name"):
        agents.register(FakeAgent("alpha", name))


def test_rejected_agent_leaves_registry_unchanged(agents):
    # The first capability is fine; the second collides. Nothing should be kept.
    agents.register(FakeAgent("alpha", "a.taken"))

    with pytest.raises(ValueError):
        agents.register(FakeAgent("bravo", "b.fresh", "a.taken"))

    assert agents.find_by_capability("b.fresh") is None
    assert [a.manifest.name for a in agents.list_agents()] == ["alpha"]


def test_non_agent_rejected(agents):
    with pytest.raises(TypeError, match="BaseAgent"):
        agents.register(object())


def test_non_manifest_rejected(agents):
    class BadManifest(FakeAgent):
        @property
        def manifest(self):
            return {"name": "bad"}

    with pytest.raises(TypeError, match="AgentManifest"):
        agents.register(BadManifest("bad"))


def test_registries_do_not_share_state():
    first, second = AgentRegistry(), AgentRegistry()
    first.register(FakeAgent("alpha", "a.one"))

    assert second.list_agents() == []
    second.register(FakeAgent("alpha", "a.one"))


# WorkflowRegistry ----------------------------------------------------------


def make_workflow(name: str) -> WorkflowDefinition:
    return WorkflowDefinition(name=name, description=f"{name} flow", steps=["x.y"])


def test_register_and_get_workflow(workflows):
    workflow = make_workflow("demo")
    workflows.register(workflow)

    assert workflows.get_workflow("demo") is workflow


def test_get_unknown_workflow_returns_none(workflows):
    assert workflows.get_workflow("missing") is None


def test_list_workflows_sorted_by_name(workflows):
    for name in ("zeta", "alpha", "mid"):
        workflows.register(make_workflow(name))

    assert [w.name for w in workflows.list_workflows()] == ["alpha", "mid", "zeta"]


def test_duplicate_workflow_name_rejected(workflows):
    workflows.register(make_workflow("demo"))

    with pytest.raises(ValueError, match="'demo' is already registered"):
        workflows.register(make_workflow("demo"))


@pytest.mark.parametrize("name", ["", " "])
def test_blank_workflow_name_rejected(workflows, name):
    with pytest.raises(ValueError, match="blank name"):
        workflows.register(make_workflow(name))


def test_non_workflow_rejected(workflows):
    with pytest.raises(TypeError, match="WorkflowDefinition"):
        workflows.register({"name": "demo"})


def test_workflow_steps_are_not_validated_against_agents(workflows):
    # Workflows are metadata only in Sprint 2; unknown capabilities are accepted.
    workflow = WorkflowDefinition("orphan", "references nothing", ["no.such.capability"])
    workflows.register(workflow)

    assert workflows.get_workflow("orphan") is workflow
