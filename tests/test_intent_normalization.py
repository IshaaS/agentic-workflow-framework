"""Mapping natural-language phrasing onto declared allowed values.

Two layers, both generic:
- the provider prompt asks the model to return the allowed value that means
  what the request says, and the user's own word when none does;
- ``canonicalize_intent`` turns provider values that differ from an allowed
  value only in formatting ("Outdoor walk") into that value.
The validator itself stays exact, and explicit ``--input`` values are never changed.
"""

import json
import logging
from types import SimpleNamespace

import pytest

from agentctl_core import (
    AgentManifest,
    AgentRegistry,
    BaseAgent,
    Capability,
    GoalSpec,
    InputSpec,
    IntentValidationError,
    ResolvedIntent,
    build_intent_catalog,
    canonicalize_intent,
    cli,
    discover_agents,
    validate_intent,
)
from agentctl_core.providers.anthropic import SYSTEM_PROMPT, AnthropicIntentProvider


class MetaAgent(BaseAgent):
    def __init__(self, name, capability):
        self._manifest = AgentManifest(name, "1.0", name, [capability])

    @property
    def manifest(self):
        return self._manifest

    def run(self, inputs, context):
        raise AssertionError("never run")


@pytest.fixture(scope="module")
def delivery_catalog():
    """A non-clothing goal with a multi-word allowed value and a free-text parameter."""
    registry = AgentRegistry()
    registry.register(MetaAgent("courier", Capability(
        "parcel.quote", ["destination", "speed"], ["quote"],
        input_specs=[
            InputSpec("destination", "Destination town"),
            InputSpec("speed", "Delivery speed", allowed_values=["next_day", "same_day", "standard"]),
        ],
        goals=[GoalSpec("quote", "Quote a parcel delivery")],
    )))
    return build_intent_catalog(registry)


@pytest.fixture(scope="module")
def outfit_catalog():
    registry = AgentRegistry()
    discover_agents(registry)
    return build_intent_catalog(registry)


# canonicalize_intent: formatting only --------------------------------------------------


@pytest.mark.parametrize("value", ["next day", "Next Day", "next-day", "  NEXT   day ", "Next_Day", "next - day"])
def test_formatting_variants_become_the_allowed_value(delivery_catalog, value):
    intent = ResolvedIntent("quote", {"destination": "Leeds", "speed": value})

    canonical, changed = canonicalize_intent(intent, delivery_catalog)

    assert canonical.parameters == {"destination": "Leeds", "speed": "next_day"}
    assert changed == ["speed"]
    assert validate_intent(canonical, delivery_catalog).inputs["speed"] == "next_day"


@pytest.mark.parametrize("value", ["overnight", "tomorrow", "next", "express", "next day air"])
def test_meaning_is_not_inferred(delivery_catalog, value):
    intent = ResolvedIntent("quote", {"destination": "Leeds", "speed": value})

    canonical, changed = canonicalize_intent(intent, delivery_catalog)

    assert canonical.parameters["speed"] == value and changed == []
    with pytest.raises(IntentValidationError, match="must be one of: next_day, same_day, standard"):
        validate_intent(canonical, delivery_catalog)


def test_free_text_parameters_are_untouched(delivery_catalog):
    intent = ResolvedIntent("quote", {"destination": "  new-york ", "speed": "standard"})

    canonical, changed = canonicalize_intent(intent, delivery_catalog)

    assert canonical.parameters["destination"] == "  new-york " and changed == []


def test_values_already_allowed_are_not_reported(delivery_catalog):
    intent = ResolvedIntent("quote", {"destination": "Leeds", "speed": "same_day"})

    assert canonicalize_intent(intent, delivery_catalog) == (intent, [])


def test_ambiguous_formatting_match_is_left_for_validation():
    registry = AgentRegistry()
    registry.register(MetaAgent("x", Capability(
        "x.make", ["mode"], ["thing"],
        input_specs=[InputSpec("mode", "Mode", allowed_values=["fast_lane", "fast-lane"])],
        goals=[GoalSpec("thing", "Make a thing")],
    )))
    catalog = build_intent_catalog(registry)

    canonical, changed = canonicalize_intent(ResolvedIntent("thing", {"mode": "Fast Lane"}), catalog)

    assert canonical.parameters["mode"] == "Fast Lane" and changed == []


@pytest.mark.parametrize(
    "intent",
    [
        ResolvedIntent("unknown_goal", {"speed": "next day"}),
        ResolvedIntent("quote", {"speed": 3}),
        ResolvedIntent("quote", {"colour": "next day"}),
        ResolvedIntent("quote", ["speed"]),
        ResolvedIntent(None, {}),
        {"goal": "quote", "parameters": {"speed": "next day"}},
    ],
)
def test_other_shapes_pass_through_unchanged(delivery_catalog, intent):
    assert canonicalize_intent(intent, delivery_catalog) == (intent, [])


def test_original_intent_is_not_mutated(delivery_catalog):
    parameters = {"destination": "Leeds", "speed": "Next Day"}
    canonicalize_intent(ResolvedIntent("quote", parameters), delivery_catalog)

    assert parameters["speed"] == "Next Day"


def test_validator_itself_is_still_exact(delivery_catalog):
    with pytest.raises(IntentValidationError, match="got 'next day'"):
        validate_intent(ResolvedIntent("quote", {"destination": "Leeds", "speed": "next day"}), delivery_catalog)


# Installed outfit plugins -------------------------------------------------------------------


@pytest.mark.parametrize("value", ["outdoor walk", "Outdoor Walk", "outdoor-walk", "OUTDOOR_WALK"])
def test_outdoor_walk_phrasings(outfit_catalog, value):
    intent = ResolvedIntent("outfit", {"city": "Chicago", "activity": value})

    canonical, _ = canonicalize_intent(intent, outfit_catalog)

    assert validate_intent(canonical, outfit_catalog).inputs == {"city": "Chicago", "activity": "outdoor_walk"}


@pytest.mark.parametrize(
    "parameter, value, allowed",
    [
        ("activity", "Office", "office"),
        ("activity", "Office Meeting", "office_meeting"),
        ("activity", "WALK", "walk"),
        ("style", "business casual", "business_casual"),
        ("style", "Business-Casual", "business_casual"),
    ],
)
def test_sprint_7_values_map_unambiguously(outfit_catalog, parameter, value, allowed):
    # Advertised values are distinct after formatting, so a variant maps to exactly one.
    parameters = {"city": "Chicago", "activity": "theatre", parameter: value}

    canonical, changed = canonicalize_intent(ResolvedIntent("outfit", parameters), outfit_catalog)

    assert canonical.parameters[parameter] == allowed and changed == [parameter]
    assert validate_intent(canonical, outfit_catalog).inputs[parameter] == allowed


@pytest.mark.parametrize(
    "parameter, value, allowed",
    [
        ("activity", "office work", "outdoor_walk, theatre, casual, office, walk, walking, work, office_meeting"),
        ("activity", "walks", "outdoor_walk, theatre, casual, office, walk, walking, work, office_meeting"),
        ("activity", "hiking", "outdoor_walk, theatre, casual, office, walk, walking, work, office_meeting"),
        ("style", "smart casual", "casual, formal, business_casual"),
        ("style", "sporty", "casual, formal, business_casual"),
    ],
)
def test_unsupported_values_are_never_mapped(outfit_catalog, parameter, value, allowed):
    parameters = {"city": "Chicago", "activity": "theatre", parameter: value}

    canonical, changed = canonicalize_intent(ResolvedIntent("outfit", parameters), outfit_catalog)

    assert canonical.parameters[parameter] == value and changed == []
    with pytest.raises(IntentValidationError, match=f"parameter '{parameter}' must be one of: {allowed}; got '{value}'"):
        validate_intent(canonical, outfit_catalog)


# Prompt -----------------------------------------------------------------------------


def test_prompt_asks_for_semantic_mapping_without_substitution():
    assert '"parameters" must contain every key in the response schema' in SYSTEM_PROMPT
    assert "that the request mentions, even in different words, give its value" in SYSTEM_PROMPT
    assert "Use an empty string for every other key" in SYSTEM_PROMPT
    assert "return that allowed value exactly as written in the catalog" in SYSTEM_PROMPT
    assert "Never substitute a different, merely related, or more general allowed value" in SYSTEM_PROMPT
    assert "return the user's own word" in SYSTEM_PROMPT


def test_prompt_example_is_domain_neutral():
    lowered = SYSTEM_PROMPT.lower()
    for word in ("outfit", "city", "activity", "style", "weather", "walk", "office", "casual", "theatre"):
        assert word not in lowered


# CLI request mode -------------------------------------------------------------------------


@pytest.fixture
def wardrobe(seeded_db, monkeypatch):
    monkeypatch.setenv("SHELF_DB_PATH", str(seeded_db))


REQUEST = "What should I wear for an outdoor walk in Chicago?"


def test_cli_accepts_formatting_variant_from_provider(capsys, fake_intent, fake_weather_http, wardrobe, caplog):
    provider = fake_intent(ResolvedIntent("outfit", {"city": "Chicago", "activity": "Outdoor walk"}))

    with caplog.at_level(logging.INFO, logger="agentctl"):
        code = cli.main(["run", "workflow", "--request", REQUEST], intent_provider=provider)
    out, _ = capsys.readouterr()

    assert code == 0
    assert json.loads(out)["outerwear"]["clothing_type"] == "rain_jacket"  # rainy fake forecast, outdoor walk
    assert "Matched parameter(s) activity to allowed values" in caplog.text
    assert "Intent validated: goal outfit with parameters activity, city" in caplog.text


def test_cli_explicit_input_is_not_canonicalized(capsys, fake_intent, fake_weather_http):
    provider = fake_intent(ResolvedIntent("outfit", {"city": "Chicago"}))

    code = cli.main(
        ["run", "workflow", "--request", REQUEST, "--input", "activity=outdoor walk"], intent_provider=provider
    )
    _, err = capsys.readouterr()

    assert code == cli.EXIT_PLANNING
    assert "got 'outdoor walk' (from --input)" in err
    assert fake_weather_http == []


def test_cli_still_rejects_unsupported_activity(capsys, fake_intent, fake_weather_http):
    provider = fake_intent(ResolvedIntent("outfit", {"city": "Chicago", "activity": "Hiking"}))

    code = cli.main(["run", "workflow", "--request", "What should I wear for hiking in Chicago?"],
                    intent_provider=provider)
    _, err = capsys.readouterr()

    assert code == cli.EXIT_PLANNING
    assert "parameter 'activity' must be one of: outdoor_walk, theatre, casual, office, walk, walking, work, office_meeting; got 'Hiking'" in err
    assert fake_weather_http == []


# Through the Anthropic adapter with a scripted SDK client --------------------------------------


class ScriptedClaude:
    def __init__(self, answer):
        response = SimpleNamespace(
            stop_reason="end_turn", model="claude-opus-5-5", _request_id="req_offline",
            content=[SimpleNamespace(type="text", text=json.dumps(answer))],
        )
        create = lambda **kwargs: response  # noqa: E731
        self.messages = SimpleNamespace(create=create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


def adapter(answer):
    return AnthropicIntentProvider(api_key="sk-ant-offline-test", client=ScriptedClaude(answer))


def test_reported_live_failure_reproduced_offline(capsys, fake_weather_http):
    """The first live run returned no activity at all, so validation reported it missing."""
    pytest.importorskip("anthropic")
    code = cli.main(["run", "workflow", "--request", REQUEST],
                    intent_provider=adapter({"goal": "outfit", "parameters": {"city": "Chicago"}}))
    _, err = capsys.readouterr()

    assert code == cli.EXIT_PLANNING
    assert "missing required input 'activity' for goal 'outfit'" in err
    assert fake_weather_http == []


@pytest.mark.parametrize("activity", ["outdoor_walk", "outdoor walk"])
def test_outdoor_walk_request_succeeds_through_adapter(capsys, fake_weather_http, wardrobe, activity):
    pytest.importorskip("anthropic")
    code = cli.main(["run", "workflow", "--request", REQUEST],
                    intent_provider=adapter({"goal": "outfit", "parameters": {"city": "Chicago", "activity": activity}}))
    out, err = capsys.readouterr()

    assert code == 0
    assert set(json.loads(out)) == {"top", "bottom", "outerwear", "footwear"}
    assert "steps: weather.forecast, clothes.advise, shelf.match" in err


# Response schema and empty values (second live run) -----------------------------------------
#
# Second live run of "What should I wear for an outdoor walk in Chicago?" returned
# parameters city=<7 chars> and style="" with no activity. The schema then listed
# activity, city, style (sorted, all optional); structured outputs write keys in schema
# order, so after starting with city the model could no longer add activity.


def test_outfit_schema_requires_every_key_in_catalog_order(outfit_catalog):
    from agentctl_core.providers.anthropic import response_schema

    parameters = response_schema(outfit_catalog)["properties"]["parameters"]

    assert list(parameters["properties"]) == ["city", "activity", "style"]
    assert parameters["required"] == ["city", "activity", "style"]


@pytest.mark.parametrize(
    "returned, kept",
    [
        ({"city": "Chicago", "activity": "outdoor_walk", "style": ""}, {"city": "Chicago", "activity": "outdoor_walk"}),
        ({"city": "Chicago", "activity": "outdoor_walk", "style": "   "}, {"city": "Chicago", "activity": "outdoor_walk"}),
        ({"city": "", "activity": "", "style": ""}, {}),
        ({"city": "Chicago", "activity": 3}, {"city": "Chicago", "activity": 3}),  # non-strings left for validation
    ],
)
def test_adapter_drops_empty_values(outfit_catalog, returned, kept, caplog):
    pytest.importorskip("anthropic")
    with caplog.at_level(logging.INFO, logger="agentctl.intent"):
        intent = adapter({"goal": "outfit", "parameters": returned}).resolve("request", outfit_catalog)

    assert intent.parameters == kept
    if len(kept) < len(returned):
        assert "unset" in caplog.text and "Chicago" not in caplog.text


def test_second_live_answer_replayed(capsys, fake_weather_http):
    """The exact shape of the second live answer now reports the real problem: activity is missing."""
    pytest.importorskip("anthropic")
    code = cli.main(["run", "workflow", "--request", REQUEST],
                    intent_provider=adapter({"goal": "outfit", "parameters": {"city": "Chicago", "style": ""}}))
    _, err = capsys.readouterr()

    assert code == cli.EXIT_PLANNING
    assert "missing required input 'activity' for goal 'outfit'" in err
    assert "must not be empty" not in err
    assert fake_weather_http == []


def test_answer_shape_expected_from_new_schema_succeeds(capsys, fake_weather_http, wardrobe):
    pytest.importorskip("anthropic")
    answer = {"goal": "outfit", "parameters": {"city": "Chicago", "activity": "outdoor_walk", "style": ""}}

    code = cli.main(["run", "workflow", "--request", REQUEST], intent_provider=adapter(answer))
    out, err = capsys.readouterr()

    assert code == 0
    assert set(json.loads(out)) == {"top", "bottom", "outerwear", "footwear"}
    assert "Intent validated: goal outfit with parameters activity, city" in err


def test_explicit_empty_input_is_still_rejected(capsys, fake_intent, fake_weather_http):
    provider = fake_intent(ResolvedIntent("outfit", {"city": "Chicago", "activity": "outdoor_walk"}))

    code = cli.main(["run", "workflow", "--request", REQUEST, "--input", "style="], intent_provider=provider)
    _, err = capsys.readouterr()

    assert code == cli.EXIT_PLANNING
    assert "parameter 'style' must not be empty (from --input)" in err
