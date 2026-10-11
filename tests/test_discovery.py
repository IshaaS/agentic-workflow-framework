"""Sprint 02 tests for entry-point discovery against the installed plugin distributions."""

import importlib
import importlib.metadata
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from agentctl_core import (
    AGENT_ENTRY_POINT_GROUP,
    WORKFLOW_ENTRY_POINT_GROUP,
    AgentManifest,
    AgentRegistry,
    BaseAgent,
    Capability,
    PluginDiscoveryError,
    RuntimeContext,
    WorkflowDefinition,
    WorkflowRegistry,
    discover_agents,
    discover_workflows,
)
from agentctl_core.discovery import load_agent, load_workflow

REQUIRED_DISTRIBUTIONS = {
    "agentctl-weather-agent": "./agents/weather-agent",
    "agentctl-clothes-agent": "./agents/clothes-agent",
    "agentctl-shelf-agent": "./agents/shelf-agent",
    "agentctl-outfit-workflow": "./workflows/outfit-workflow",
}

EXPECTED_AGENTS = {
    "weather_provider": Capability("weather.forecast", ["city"], ["weather"]),
    "clothes_adviser": Capability(
        "clothes.advise", ["weather", "activity"], ["clothing_requirements"]
    ),
    "shelf_manager": Capability("shelf.match", ["clothing_requirements"], ["outfit"]),
}


@pytest.fixture(scope="module", autouse=True)
def require_installed_plugins():
    missing = []
    for dist, path in REQUIRED_DISTRIBUTIONS.items():
        try:
            importlib.metadata.distribution(dist)
        except importlib.metadata.PackageNotFoundError:
            missing.append((dist, path))
    if missing:
        commands = "\n".join(f"  python -m pip install -e {path}" for _, path in missing)
        names = ", ".join(dist for dist, _ in missing)
        pytest.fail(
            f"Plugin distributions not installed: {names}.\n"
            f"Install them from the repository root:\n{commands}",
            pytrace=False,
        )


@pytest.fixture
def agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    discover_agents(registry)
    return registry


@pytest.fixture
def workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    discover_workflows(registry)
    return registry


# Real installed entry points ----------------------------------------------


def test_entry_points_declared_by_plugin_distributions():
    agent_eps = {
        ep.name: ep.dist.name
        for ep in importlib.metadata.entry_points(group=AGENT_ENTRY_POINT_GROUP)
    }
    workflow_eps = {
        ep.name: ep.dist.name
        for ep in importlib.metadata.entry_points(group=WORKFLOW_ENTRY_POINT_GROUP)
    }

    assert agent_eps.get("weather") == "agentctl-weather-agent"
    assert agent_eps.get("clothes") == "agentctl-clothes-agent"
    assert agent_eps.get("shelf") == "agentctl-shelf-agent"
    assert workflow_eps.get("outfit") == "agentctl-outfit-workflow"


def test_discovers_three_agents(agent_registry):
    names = {agent.manifest.name for agent in agent_registry.list_agents()}

    # Other plugins may be installed in the environment; require ours, not exclusivity.
    assert set(EXPECTED_AGENTS) <= names


@pytest.mark.parametrize("agent_name", sorted(EXPECTED_AGENTS))
def test_discovered_manifest_contracts(agent_registry, agent_name):
    agent = agent_registry.get_agent(agent_name)

    assert isinstance(agent, BaseAgent)
    assert isinstance(agent.manifest, AgentManifest)
    assert agent.manifest.version == "0.1.0"
    assert agent.manifest.description
    assert agent.manifest.capabilities == [EXPECTED_AGENTS[agent_name]]


@pytest.mark.parametrize(
    "capability, agent_name",
    [(cap.name, name) for name, cap in EXPECTED_AGENTS.items()],
)
def test_capability_lookup_after_discovery(agent_registry, capability, agent_name):
    assert agent_registry.find_by_capability(capability).manifest.name == agent_name


def test_discovers_outfit_workflow(workflow_registry):
    workflow = workflow_registry.get_workflow("outfit_advisor")

    assert workflow == WorkflowDefinition(
        name="outfit_advisor",
        description="Recommend clothing using weather and a personal shelf",
        steps=["weather.forecast", "clothes.advise", "shelf.match"],
    )


def test_named_workflow_steps_resolve_to_discovered_agents(
    agent_registry, workflow_registry
):
    workflow = workflow_registry.get_workflow("outfit_advisor")

    assert [agent_registry.find_by_capability(s).manifest.name for s in workflow.steps] == [
        "weather_provider",
        "clothes_adviser",
        "shelf_manager",
    ]


def test_core_does_not_reference_plugin_packages():
    import agentctl_core

    for source in Path(agentctl_core.__file__).parent.glob("*.py"):
        text = source.read_text()
        assert "agentctl_agents" not in text, source.name
        assert "agentctl_workflows" not in text, source.name


def test_discovery_is_repeatable_with_fresh_registries():
    first, second = AgentRegistry(), AgentRegistry()
    discover_agents(first)
    discover_agents(second)

    assert [a.manifest.name for a in first.list_agents()] == [
        a.manifest.name for a in second.list_agents()
    ]


def test_discovering_twice_into_one_registry_names_the_entry_point():
    registry = AgentRegistry()
    discover_agents(registry)

    with pytest.raises(PluginDiscoveryError, match="entry point .* already registered"):
        discover_agents(registry)


@pytest.mark.parametrize("agent_name", sorted(EXPECTED_AGENTS))
def test_placeholder_agents_refuse_to_run(agent_registry, agent_name):
    agent = agent_registry.get_agent(agent_name)
    context = RuntimeContext(session_id="s", workflow_id="w", inputs={})

    with pytest.raises(NotImplementedError, match="placeholder"):
        agent.run({}, context)


# Namespace packaging --------------------------------------------------------


@pytest.mark.parametrize(
    "namespace, leaves",
    [
        ("agentctl_agents", ["weather", "clothes", "shelf"]),
        ("agentctl_workflows", ["outfit"]),
    ],
)
def test_namespace_packages(namespace, leaves):
    package = importlib.import_module(namespace)

    # A PEP 420 namespace package has no __init__.py, so no __file__.
    assert getattr(package, "__file__", None) is None
    for entry in package.__path__:
        assert not (Path(entry) / "__init__.py").exists()

    for leaf in leaves:
        module = importlib.import_module(f"{namespace}.{leaf}")
        assert module.__file__.endswith("__init__.py")


def test_agent_namespace_is_shared_by_three_distributions():
    providers = importlib.metadata.packages_distributions().get("agentctl_agents", [])

    assert {
        "agentctl-weather-agent",
        "agentctl-clothes-agent",
        "agentctl-shelf-agent",
    } <= set(providers)


# Loader error handling (synthetic entry points; nothing is installed) ------


@pytest.mark.parametrize(
    "value, message",
    [
        ("agentctl_no_such_module:Agent", "No module named"),
        ("agentctl_core.sdk:NoSuchAgent", "NoSuchAgent"),
        ("agentctl_core.sdk:WorkflowPlan", "not a BaseAgent subclass"),
        ("agentctl_core.sdk:BaseAgent", "abstract"),
    ],
)
def test_load_agent_errors_name_the_entry_point(value, message):
    entry_point = EntryPoint(name="broken", value=value, group=AGENT_ENTRY_POINT_GROUP)

    with pytest.raises(PluginDiscoveryError) as excinfo:
        load_agent(entry_point)

    text = str(excinfo.value)
    assert "'broken'" in text and value in text
    assert message in text
    assert excinfo.value.__cause__ is not None


@pytest.mark.parametrize(
    "value, message",
    [
        ("agentctl_no_such_module:get_workflow", "No module named"),
        ("agentctl_core.discovery:AGENT_ENTRY_POINT_GROUP", "not callable"),
        ("builtins:dict", "expected WorkflowDefinition"),
        ("agentctl_core.sdk:WorkflowDefinition", "missing"),
    ],
)
def test_load_workflow_errors_name_the_entry_point(value, message):
    entry_point = EntryPoint(name="broken", value=value, group=WORKFLOW_ENTRY_POINT_GROUP)

    with pytest.raises(PluginDiscoveryError) as excinfo:
        load_workflow(entry_point)

    text = str(excinfo.value)
    assert "'broken'" in text and value in text
    assert message in text
