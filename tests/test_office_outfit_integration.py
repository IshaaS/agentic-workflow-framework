"""Sprint 07 end-to-end: office, business_casual and activity aliases through the real stack.

Agents and workflows come from installed entry points; weather HTTP is faked
(rainy 22°C) and the wardrobe is a temporary seeded database. Request mode uses
a scripted intent provider, then the real catalog, validator, planner and
orchestrator. No framework code knows about clothing.
"""

import json
from pathlib import Path

import pytest

import agentctl_core
from agentctl_core import (
    AgentRegistry,
    CapabilityPlanner,
    ResolvedIntent,
    RuntimeContext,
    SequentialOrchestrator,
    WorkflowRegistry,
    build_intent_catalog,
    canonicalize_intent,
    cli,
    discover_agents,
    discover_workflows,
    validate_intent,
)

EXTERNAL_INPUTS = {"city", "activity", "style"}
OFFICE = {"city": "Chicago", "activity": "office", "style": "business_casual"}
OFFICE_REQUEST = "What should I wear to the office in Chicago? I prefer business casual."


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


def execute(agents, plan, inputs):
    context = RuntimeContext(session_id="s7", workflow_id="w7", inputs=dict(inputs))
    return SequentialOrchestrator(agents).execute(plan, context)


def assert_valid_outfit(requirements, outfit):
    """Each chosen item is one of the recommended types for its category."""
    assert list(requirements) == list(outfit) == ["top", "bottom", "outerwear", "footwear"]
    for category, item in outfit.items():
        if item is None:
            assert category == "outerwear" or not requirements[category], category
        else:
            assert item["clothing_type"] in requirements[category], (category, item)


def assert_business_casual(outfit):
    assert outfit["top"]["clothing_type"] in {"polo", "dress_shirt", "sweater"}
    assert outfit["bottom"]["clothing_type"] in {"pants", "dress_pants", "jeans"}
    assert outfit["footwear"]["clothing_type"] in {"dress_shoes", "boots", "walking_shoes"}


# Structured inputs ----------------------------------------------------------------------


def test_generated_office_plan(registries, fake_weather_http, wardrobe):
    agents, _ = registries
    plan = CapabilityPlanner(agents).plan_for_goal("outfit", OFFICE, EXTERNAL_INPUTS)

    context = execute(agents, plan, OFFICE)

    requirements, outfit = context.results["clothing_requirements"], context.results["outfit"]
    assert_valid_outfit(requirements, outfit)
    assert_business_casual(outfit)
    assert requirements["outerwear"][0] == "rain_jacket"  # the fake forecast is rainy; office has a commute
    assert [e["type"] for e in context.events][-1] == "workflow_completed"


@pytest.mark.parametrize(
    "alias, canonical", [("walk", "outdoor_walk"), ("outdoor walk", "outdoor_walk"), ("work", "office")]
)
def test_named_workflow_alias_matches_canonical(registries, fake_weather_http, wardrobe, alias, canonical):
    agents, workflows = registries
    definition = workflows.get_workflow("outfit_advisor")
    results = []
    for activity in (alias, canonical):
        inputs = {"city": "Chicago", "activity": activity}
        plan = CapabilityPlanner(agents).plan_from_workflow(definition, inputs, EXTERNAL_INPUTS)
        results.append(execute(agents, plan, inputs).results)

    assert results[0]["clothing_requirements"] == results[1]["clothing_requirements"]
    assert results[0]["outfit"] == results[1]["outfit"]
    assert_valid_outfit(results[0]["clothing_requirements"], results[0]["outfit"])


@pytest.mark.parametrize(
    "argv",
    [
        ["--goal", "outfit", "--input", "city=Chicago", "--input", "activity=office",
         "--input", "style=business_casual"],
        ["outfit_advisor", "--input", "city=Chicago", "--input", "activity=Office Meeting",
         "--input", "style=business casual"],
    ],
)
def test_cli_structured_office(capsys, fake_weather_http, wardrobe, argv):
    code = cli.main(["run", "workflow", *argv])
    out, err = capsys.readouterr()

    assert code == 0, err
    assert_business_casual(json.loads(out))
    assert "steps: weather.forecast, clothes.advise, shelf.match" in err


def test_cli_structured_unknown_activity_fails_clearly(capsys, fake_weather_http, wardrobe):
    code = cli.main(["run", "workflow", "--goal", "outfit", "--input", "city=Chicago", "--input", "activity=hiking"])
    out, err = capsys.readouterr()

    assert code != 0 and out == ""
    assert "'activity' must be one of outdoor_walk, theatre, casual, office; got 'hiking'" in err


# Natural-language request mode (scripted provider) --------------------------------------


def test_catalog_advertises_new_values(registries):
    agents, _ = registries
    goal = build_intent_catalog(agents).goals["outfit"]

    assert goal.required == ["city", "activity"]
    assert {"office", "walk", "walking", "work", "office_meeting"} <= set(goal.parameters["activity"].allowed_values)
    assert "business_casual" in goal.parameters["style"].allowed_values


def test_office_request_through_catalog_validator_planner_and_orchestrator(
    registries, fake_intent, fake_weather_http, wardrobe
):
    agents, _ = registries
    provider = fake_intent(ResolvedIntent("outfit", dict(OFFICE)))

    catalog = build_intent_catalog(agents)
    intent, changed = canonicalize_intent(provider.resolve(OFFICE_REQUEST, catalog), catalog)
    validated = validate_intent(intent, catalog)
    plan = CapabilityPlanner(agents).plan_for_goal(validated.goal, validated.inputs, set(catalog.goals["outfit"].parameters))
    context = execute(agents, plan, validated.inputs)

    assert changed == [] and validated.inputs == OFFICE
    assert (plan.steps, plan.source) == (["weather.forecast", "clothes.advise", "shelf.match"], "generated")
    assert_valid_outfit(context.results["clothing_requirements"], context.results["outfit"])
    assert_business_casual(context.results["outfit"])


def test_office_request_through_the_cli(capsys, fake_intent, fake_weather_http, wardrobe):
    provider = fake_intent(ResolvedIntent("outfit", dict(OFFICE)))

    code = cli.main(["run", "workflow", "--request", OFFICE_REQUEST], intent_provider=provider)
    out, err = capsys.readouterr()

    assert code == 0, err
    assert_business_casual(json.loads(out))
    assert fake_weather_http == ["geocoding-api.open-meteo.com", "api.open-meteo.com"]
    ((request, catalog),) = provider.calls
    assert request == OFFICE_REQUEST
    assert "office" in catalog.goals["outfit"].parameters["activity"].allowed_values


@pytest.mark.parametrize("activity", ["office_meeting", "Office Meeting", "work"])
def test_request_mode_aliases_give_the_office_outfit(capsys, fake_intent, fake_weather_http, wardrobe, activity):
    outfits = []
    for value in ("office", activity):
        provider = fake_intent(ResolvedIntent("outfit", {"city": "Chicago", "activity": value, "style": "Business Casual"}))
        code = cli.main(["run", "workflow", "--request", OFFICE_REQUEST], intent_provider=provider)
        out, err = capsys.readouterr()
        assert code == 0, err
        outfits.append(json.loads(out))

    assert outfits[0] == outfits[1]


@pytest.mark.parametrize(
    "parameters, message",
    [
        ({"city": "Chicago", "activity": "hiking"}, "parameter 'activity' must be one of: outdoor_walk, theatre, "
                                                    "casual, office, walk, walking, work, office_meeting; got 'hiking'"),
        ({"city": "Chicago", "activity": "office", "style": "smart casual"},
         "parameter 'style' must be one of: casual, formal, business_casual; got 'smart casual'"),
    ],
)
def test_request_mode_rejects_unknown_values_before_running(capsys, fake_intent, fake_weather_http, parameters, message):
    code = cli.main(["run", "workflow", "--request", OFFICE_REQUEST], intent_provider=fake_intent(ResolvedIntent("outfit", parameters)))
    out, err = capsys.readouterr()

    assert code == cli.EXIT_PLANNING and out == ""
    assert message in err
    assert fake_weather_http == []


def test_framework_has_no_sprint_7_vocabulary():
    # The new values and aliases live only in the clothes agent's manifest.
    core = Path(agentctl_core.__file__).parent
    for source in core.rglob("*.py"):
        text = source.read_text().lower()
        for word in ("office", "business", "walking"):
            assert word not in text, (source.name, word)
