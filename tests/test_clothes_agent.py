"""Sprint 03 clothes adviser tests."""

import itertools

import pytest

from agentctl_agents.clothes.agent import (
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


@pytest.mark.parametrize("activity", [None, "", "hiking", "Theatre"])
def test_unsupported_activity_rejected(context, activity):
    with pytest.raises(ValueError, match="'activity' must be one of"):
        ClothesAgent().run({"weather": MILD, "activity": activity}, context)


@pytest.mark.parametrize("style", ["", "sporty", "FORMAL", 1])
def test_unsupported_style_rejected(context, style):
    with pytest.raises(ValueError, match="'style' must be one of"):
        ClothesAgent().run({"weather": MILD, "activity": "casual", "style": style}, context)
