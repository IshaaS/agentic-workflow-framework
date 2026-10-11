"""Clothes adviser tests (Sprint 03 rules; Sprint 07 office, business_casual and aliases)."""

import itertools
import re

import pytest

from agentctl_agents.clothes.agent import (
    ACCEPTED_ACTIVITIES,
    ACTIVITIES,
    CLOTHING_TYPES,
    STYLES,
    ClothesAgent,
    advise,
)


def weather(temperature_c=15.0, condition="clear", precipitation_probability=0, wind_speed_kmh=5.0):
    return {
        "temperature_c": temperature_c,
        "condition": condition,
        "precipitation_probability": precipitation_probability,
        "wind_speed_kmh": wind_speed_kmh,
    }


COLD = weather(temperature_c=3.0, condition="cloudy")
MILD = weather(temperature_c=15.0)
WARM = weather(temperature_c=27.0)
RAINY_WARM = weather(temperature_c=22.0, condition="rainy", precipitation_probability=65, wind_speed_kmh=15.0)


def test_run_returns_clothing_requirements(context):
    result = ClothesAgent().run(
        {"weather": RAINY_WARM, "activity": "outdoor_walk", "style": "casual"}, context
    )

    assert result == {
        "clothing_requirements": {
            "top": ["t_shirt", "polo"],
            "bottom": ["pants", "jeans"],
            "outerwear": ["rain_jacket", "light_jacket"],
            "footwear": ["walking_shoes", "sneakers"],
        }
    }


# Scenarios ------------------------------------------------------------------


def test_cold_outdoor_walk():
    assert advise(COLD, "outdoor_walk") == {
        "top": ["sweater", "long_sleeve_shirt"],
        "bottom": ["jeans", "pants"],
        "outerwear": ["winter_coat", "light_jacket"],
        "footwear": ["walking_shoes", "sneakers"],
    }


def test_cold_rainy_outdoor_walk_adds_rain_protection_and_boots():
    result = advise(weather(5.0, "rainy", 80), "outdoor_walk")

    assert result["outerwear"] == ["winter_coat", "rain_jacket"]
    assert result["footwear"] == ["boots", "walking_shoes"]
    assert result["bottom"] == ["pants", "jeans"]


def test_mild_outdoor_walk():
    assert advise(MILD, "outdoor_walk") == {
        "top": ["long_sleeve_shirt", "t_shirt"],
        "bottom": ["jeans", "pants"],
        "outerwear": ["light_jacket"],
        "footwear": ["walking_shoes", "sneakers"],
    }


def test_warm_outdoor_walk_needs_no_outerwear():
    assert advise(WARM, "outdoor_walk") == {
        "top": ["t_shirt", "polo"],
        "bottom": ["shorts", "jeans"],
        "outerwear": [],
        "footwear": ["walking_shoes", "sneakers"],
    }


def test_rain_probability_alone_counts_as_wet():
    result = advise(weather(25.0, "cloudy", precipitation_probability=50), "outdoor_walk")

    assert result["outerwear"] == ["rain_jacket", "light_jacket"]
    assert result["bottom"] == ["pants", "jeans"]


def test_stormy_counts_as_wet():
    assert advise(weather(25.0, "stormy", 10), "casual")["outerwear"] == ["rain_jacket", "light_jacket"]


def test_wind_adds_a_layer_when_warm():
    assert advise(weather(25.0, wind_speed_kmh=30.0), "outdoor_walk")["outerwear"] == ["light_jacket"]
    assert advise(weather(25.0, wind_speed_kmh=29.9), "outdoor_walk")["outerwear"] == []


def test_snow_means_coat_and_boots():
    result = advise(weather(12.0, "snowy", 40), "casual")

    assert result["outerwear"] == ["winter_coat", "light_jacket"]
    assert result["footwear"] == ["boots", "walking_shoes"]


def test_theatre_is_dressier_than_outdoor_walk():
    walk = advise(WARM, "outdoor_walk")
    theatre = advise(WARM, "theatre")

    assert theatre == {
        "top": ["polo", "long_sleeve_shirt"],
        "bottom": ["pants", "jeans"],
        "outerwear": [],
        "footwear": ["dress_shoes", "sneakers"],
    }
    assert theatre != walk


def test_formal_theatre():
    assert advise(MILD, "theatre", "formal") == {
        "top": ["dress_shirt", "long_sleeve_shirt"],
        "bottom": ["dress_pants", "pants"],
        "outerwear": ["blazer", "light_jacket"],
        "footwear": ["dress_shoes"],
    }


def test_theatre_ignores_rain_for_outerwear():
    # Theatre is indoors, so rain alone doesn't call for a rain jacket.
    assert advise(RAINY_WARM, "theatre")["outerwear"] == []
    assert advise(RAINY_WARM, "theatre", "formal")["outerwear"] == ["blazer"]


def test_cold_theatre_still_gets_a_coat():
    assert advise(COLD, "theatre", "formal")["outerwear"] == ["winter_coat", "blazer"]


def test_formal_style_changes_outdoor_advice():
    casual = advise(WARM, "outdoor_walk", "casual")
    formal = advise(WARM, "outdoor_walk", "formal")

    assert formal["top"] == ["polo", "long_sleeve_shirt"]
    assert formal["bottom"] == ["pants", "jeans"]
    assert formal != casual


@pytest.mark.parametrize("temperature, top", [(9.9, "sweater"), (10.0, "long_sleeve_shirt"), (20.0, "long_sleeve_shirt"), (20.1, "t_shirt")])
def test_temperature_thresholds(temperature, top):
    assert advise(weather(temperature), "outdoor_walk")["top"][0] == top


def test_unknown_condition_is_accepted_and_uses_rain_probability():
    assert advise(weather(25.0, "unknown", 0), "outdoor_walk")["outerwear"] == []
    assert advise(weather(25.0, "unknown", 70), "outdoor_walk")["outerwear"][0] == "rain_jacket"


# Style default ----------------------------------------------------------------


def test_style_defaults_to_casual(context):
    agent = ClothesAgent()
    omitted = agent.run({"weather": MILD, "activity": "theatre"}, context)
    none = agent.run({"weather": MILD, "activity": "theatre", "style": None}, context)
    explicit = agent.run({"weather": MILD, "activity": "theatre", "style": "casual"}, context)

    assert omitted == none == explicit


# Output shape across every input combination ---------------------------------

WEATHER_GRID = [
    weather(t, c, p, w)
    for t, c, p, w in itertools.product(
        (-5.0, 10.0, 15.0, 20.0, 30.0),
        ("clear", "cloudy", "rainy", "snowy", "stormy", "unknown"),
        (0, 50, 100),
        (0.0, 30.0),
    )
]


@pytest.mark.parametrize("activity, style", list(itertools.product(ACTIVITIES, STYLES)))
def test_output_shape_and_vocabulary(activity, style):
    for w in WEATHER_GRID:
        result = advise(w, activity, style)

        assert list(result) == ["top", "bottom", "outerwear", "footwear"]
        for category, types in result.items():
            assert isinstance(types, list)
            assert len(types) == len(set(types)), (category, types)
            assert set(types) <= set(CLOTHING_TYPES[category]), (category, types)
            if category != "outerwear":
                assert types, (category, w, activity, style)


# Validation -------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_weather, message",
    [
        (None, "'weather' must be a dict"),
        ("sunny", "'weather' must be a dict"),
        ({**MILD, "temperature_c": None}, "temperature_c"),
        ({**MILD, "temperature_c": "15"}, "temperature_c"),
        ({**MILD, "temperature_c": True}, "temperature_c"),
        ({k: v for k, v in MILD.items() if k != "wind_speed_kmh"}, "wind_speed_kmh"),
        ({**MILD, "precipitation_probability": 101}, "between 0 and 100"),
        ({**MILD, "wind_speed_kmh": -1}, "must not be negative"),
        ({**MILD, "condition": "drizzly"}, "condition"),
        ({k: v for k, v in MILD.items() if k != "condition"}, "condition"),
    ],
)
def test_malformed_weather_rejected(context, bad_weather, message):
    with pytest.raises(ValueError, match=message):
        ClothesAgent().run({"weather": bad_weather, "activity": "casual"}, context)


# Case and spacing are normalized (see test_case_and_spacing_are_normalized), so
# "Theatre" and "FORMAL" are now accepted; near misses are still rejected.
@pytest.mark.parametrize(
    "activity", [None, "", "   ", 1, "hiking", "walks", "outdoor", "office party", "the office", "theatre_show"]
)
def test_unsupported_activity_rejected(context, activity):
    message = f"'activity' must be one of outdoor_walk, theatre, casual, office; got {activity!r}"
    with pytest.raises(ValueError, match=re.escape(message)):
        ClothesAgent().run({"weather": MILD, "activity": activity}, context)


@pytest.mark.parametrize("style", ["", "sporty", "smart casual", "business", "casual_formal", 1])
def test_unsupported_style_rejected(context, style):
    message = f"'style' must be one of casual, formal, business_casual; got {style!r}"
    with pytest.raises(ValueError, match=re.escape(message)):
        ClothesAgent().run({"weather": MILD, "activity": "casual", "style": style}, context)


# Office and business casual ----------------------------------------------------------


def test_office_business_casual_mild():
    assert advise(MILD, "office", "business_casual") == {
        "top": ["dress_shirt", "polo"],
        "bottom": ["pants", "jeans"],
        "outerwear": ["light_jacket"],
        "footwear": ["dress_shoes", "walking_shoes"],
    }


def test_office_business_casual_cold_adds_warm_layers():
    result = advise(COLD, "office", "business_casual")

    assert result["top"][0] == "sweater"
    assert result["outerwear"][0] == "winter_coat"
    assert result["bottom"][0] == "pants"


def test_office_commute_gets_rain_protection():
    # Unlike theatre, the office rule assumes a commute, so rain matters.
    assert advise(RAINY_WARM, "office", "business_casual")["outerwear"] == ["rain_jacket", "light_jacket"]
    assert advise(RAINY_WARM, "theatre", "casual")["outerwear"] == []

    cold_rain = advise(weather(5.0, "rainy", 80), "office", "business_casual")
    assert cold_rain["outerwear"] == ["winter_coat", "rain_jacket"]
    assert cold_rain["footwear"] == ["boots", "dress_shoes"]


def test_office_warm_dry_needs_no_outerwear():
    result = advise(WARM, "office", "business_casual")

    assert result["top"] == ["polo", "dress_shirt"]
    assert result["outerwear"] == []


@pytest.mark.parametrize("style", STYLES)
def test_office_is_never_dressed_down(style):
    for w in WEATHER_GRID:
        result = advise(w, "office", style)

        assert "t_shirt" not in result["top"], (w, style)
        assert "shorts" not in result["bottom"], (w, style)
        assert "sneakers" not in result["footwear"], (w, style)


def test_formal_office():
    assert advise(MILD, "office", "formal") == {
        "top": ["dress_shirt", "long_sleeve_shirt"],
        "bottom": ["dress_pants", "pants"],
        "outerwear": ["blazer", "light_jacket"],
        "footwear": ["dress_shoes"],
    }


def test_office_is_at_least_business_casual():
    # An office is smart dress by default, so casual style means business casual there.
    assert advise(MILD, "office") == advise(MILD, "office", "casual") == advise(MILD, "office", "business_casual")


def test_activity_changes_business_casual_advice():
    office = advise(RAINY_WARM, "office", "business_casual")
    theatre = advise(RAINY_WARM, "theatre", "business_casual")
    walk = advise(RAINY_WARM, "outdoor_walk", "business_casual")

    assert len({str(office), str(theatre), str(walk)}) == 3


def test_business_casual_is_smarter_than_casual_for_a_walk():
    casual = advise(WARM, "outdoor_walk", "casual")
    business = advise(WARM, "outdoor_walk", "business_casual")

    assert business["top"] == ["polo", "long_sleeve_shirt"]
    assert business["bottom"] == ["pants", "jeans"]
    assert business["footwear"] == casual["footwear"] == ["walking_shoes", "sneakers"]


def test_business_casual_theatre_matches_existing_smart_theatre():
    for w in (COLD, MILD, WARM, RAINY_WARM):
        assert advise(w, "theatre", "business_casual") == advise(w, "theatre", "casual")


# Aliases and normalization ----------------------------------------------------------


@pytest.mark.parametrize(
    "alias, canonical",
    [
        ("walk", "outdoor_walk"),
        ("walking", "outdoor_walk"),
        ("outdoor walk", "outdoor_walk"),
        ("work", "office"),
        ("office meeting", "office"),
        ("office_meeting", "office"),
    ],
)
def test_activity_alias_gives_same_advice(context, alias, canonical):
    for w in (COLD, MILD, WARM, RAINY_WARM, weather(-2.0, "snowy", 90, 35.0)):
        for style in (None, *STYLES):
            assert advise(w, alias, style) == advise(w, canonical, style), (alias, w, style)

    agent = ClothesAgent()
    assert agent.run({"weather": MILD, "activity": alias}, context) == agent.run(
        {"weather": MILD, "activity": canonical}, context
    )


@pytest.mark.parametrize(
    "activity, style, canonical",
    [
        ("Office", None, ("office", "casual")),
        ("  office  ", "Business Casual", ("office", "business_casual")),
        ("Office Meeting", "business  casual", ("office", "business_casual")),
        ("OUTDOOR_WALK", "FORMAL", ("outdoor_walk", "formal")),
        ("Outdoor-Walk", " casual ", ("outdoor_walk", "casual")),
        ("WALK", "business-casual", ("outdoor_walk", "business_casual")),
        ("Theatre", "Formal", ("theatre", "formal")),
    ],
)
def test_case_and_spacing_are_normalized(activity, style, canonical):
    assert advise(MILD, activity, style) == advise(MILD, *canonical)


# Manifest ---------------------------------------------------------------------------------


def test_manifest_inputs_and_advertised_values():
    (capability,) = ClothesAgent().manifest.capabilities
    specs = {spec.name: spec for spec in capability.input_specs}

    assert capability.requires == ["weather", "activity"]
    assert capability.optional_inputs == ["style"]
    assert specs["activity"].allowed_values == [
        "outdoor_walk", "theatre", "casual", "office", "walk", "walking", "work", "office_meeting",
    ]
    assert specs["activity"].allowed_values == list(ACCEPTED_ACTIVITIES)
    assert specs["style"].allowed_values == ["casual", "formal", "business_casual"] == list(STYLES)


def test_every_advertised_value_is_accepted():
    (capability,) = ClothesAgent().manifest.capabilities
    specs = {spec.name: spec for spec in capability.input_specs}

    for activity in specs["activity"].allowed_values:
        for style in specs["style"].allowed_values:
            advise(MILD, activity, style)
