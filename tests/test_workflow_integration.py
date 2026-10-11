"""Sprint 04 in-process integration: discovered plugins -> plan -> sequential execution.

Agents and workflows come from installed entry points. Weather HTTP is
replaced at the transport (urlopen) by the ``fake_weather_http`` fixture in
conftest.py, and the wardrobe is a temporary seeded SQLite database.
"""

import pytest

from agentctl_core import (
    AgentRegistry,
    CapabilityPlanner,
    MissingInputError,
    RuntimeContext,
    SequentialOrchestrator,
    WorkflowExecutionError,
    WorkflowRegistry,
    discover_agents,
    discover_workflows,
)
from agentctl_agents.shelf.db import ShelfDatabaseError
from agentctl_agents.weather import openmeteo

EXTERNAL_INPUTS = {"city", "activity", "style"}
INPUTS = {"city": "Dallas", "activity": "outdoor_walk", "style": "casual"}
EXPECTED_STEPS = ["weather.forecast", "clothes.advise", "shelf.match"]


@pytest.fixture
def registries():
    agents, workflows = AgentRegistry(), WorkflowRegistry()
    discover_agents(agents)
    discover_workflows(workflows)
    return agents, workflows


@pytest.fixture
def wardrobe(seeded_db, monkeypatch):
    monkeypatch.setenv("SHELF_DB_PATH", str(seeded_db))
    return seeded_db


def new_context(workflow_id="integration-1"):
    return RuntimeContext(session_id="integration", workflow_id=workflow_id, inputs=dict(INPUTS))


def assert_outfit_from_seed(context):
    assert set(context.results) == {"weather", "clothing_requirements", "outfit"}
    assert context.results["weather"]["condition"] == "rainy"
    assert context.results["clothing_requirements"]["outerwear"][0] == "rain_jacket"
    outfit = context.results["outfit"]
    # Seeded items: white t-shirt, olive chinos, yellow rain jacket, brown walking shoes.
    assert {category: item["id"] for category, item in outfit.items()} == {
        "top": 1, "bottom": 10, "outerwear": 13, "footwear": 17,
    }


def test_generated_plan_runs_discovered_agents(registries, fake_weather_http, wardrobe):
    agents, _ = registries

    plan = CapabilityPlanner(agents).plan_for_goal("outfit", INPUTS, EXTERNAL_INPUTS)
    assert (plan.steps, plan.source) == (EXPECTED_STEPS, "generated")

    context = SequentialOrchestrator(agents).execute(plan, new_context())

    assert_outfit_from_seed(context)
    assert fake_weather_http == ["geocoding-api.open-meteo.com", "api.open-meteo.com"]
    assert [e["type"] for e in context.events] == [
        "workflow_started",
        "agent_started", "agent_completed",
        "agent_started", "agent_completed",
        "agent_started", "agent_completed",
        "workflow_completed",
    ]
    assert [e["agent"] for e in context.events if e["type"] == "agent_completed"] == [
        "weather_provider", "clothes_adviser", "shelf_manager",
    ]


def test_named_workflow_runs_discovered_agents(registries, fake_weather_http, wardrobe):
    agents, workflows = registries
    definition = workflows.get_workflow("outfit_advisor")

    plan = CapabilityPlanner(agents).plan_from_workflow(definition, INPUTS, EXTERNAL_INPUTS)
    assert (plan.steps, plan.source) == (EXPECTED_STEPS, "named")

    context = SequentialOrchestrator(agents).execute(plan, new_context("integration-2"))

    assert_outfit_from_seed(context)
    assert context.events[0]["source"] == "named"


def test_formal_theatre_style_reaches_the_adviser(registries, fake_weather_http, wardrobe):
    agents, _ = registries
    inputs = {"city": "Dallas", "activity": "theatre", "style": "formal"}
    plan = CapabilityPlanner(agents).plan_for_goal("outfit", inputs, EXTERNAL_INPUTS)

    context = SequentialOrchestrator(agents).execute(
        plan, RuntimeContext(session_id="s", workflow_id="w", inputs=inputs)
    )

    # Seeded dress pants are unavailable, so the shelf falls back to chinos.
    assert context.results["clothing_requirements"]["bottom"] == ["dress_pants", "pants"]
    assert context.results["outfit"]["bottom"]["name"] == "Olive chinos"
    assert context.results["outfit"]["footwear"]["clothing_type"] == "dress_shoes"


def test_missing_city_is_a_planning_error(registries):
    agents, _ = registries

    with pytest.raises(MissingInputError) as excinfo:
        CapabilityPlanner(agents).plan_for_goal("outfit", {"activity": "theatre"}, EXTERNAL_INPUTS)

    assert (excinfo.value.input_name, excinfo.value.required_by) == ("city", "weather.forecast")


def test_missing_wardrobe_fails_at_shelf_step(registries, fake_weather_http, tmp_path, monkeypatch):
    agents, _ = registries
    monkeypatch.setenv("SHELF_DB_PATH", str(tmp_path / "not-created.db"))
    plan = CapabilityPlanner(agents).plan_for_goal("outfit", INPUTS, EXTERNAL_INPUTS)
    context = new_context()

    with pytest.raises(WorkflowExecutionError) as excinfo:
        SequentialOrchestrator(agents).execute(plan, context)

    error = excinfo.value
    assert (error.reason, error.capability, error.step_index) == ("agent_error", "shelf.match", 2)
    assert isinstance(error.__cause__, ShelfDatabaseError)
    assert set(context.results) == {"weather", "clothing_requirements"}
    assert [e["type"] for e in context.events][-2:] == ["agent_failed", "workflow_failed"]
    assert not (tmp_path / "not-created.db").exists()


def test_weather_timeout_fails_first_step(registries, wardrobe, monkeypatch):
    agents, _ = registries

    def timing_out(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(openmeteo, "urlopen", timing_out)
    plan = CapabilityPlanner(agents).plan_for_goal("outfit", INPUTS, EXTERNAL_INPUTS)
    context = new_context()

    with pytest.raises(WorkflowExecutionError) as excinfo:
        SequentialOrchestrator(agents).execute(plan, context)

    assert (excinfo.value.capability, excinfo.value.step_index) == ("weather.forecast", 0)
    assert isinstance(excinfo.value.__cause__, openmeteo.WeatherAPIError)
    assert context.results == {}
    assert [e["type"] for e in context.events].count("agent_started") == 1
