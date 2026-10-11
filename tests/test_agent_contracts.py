"""Cross-agent data contracts: each agent's output is valid input for the next.

These tests call agents directly; they do not orchestrate a workflow.
"""

import itertools
from datetime import datetime, timezone

import pytest

from agentctl_agents.clothes import agent as clothes
from agentctl_agents.shelf.agent import ShelfAgent
from agentctl_agents.shelf.db import CATEGORIES, SEED_ITEMS
from agentctl_agents.weather import openmeteo
from agentctl_agents.weather.agent import WeatherAgent


def test_weather_conditions_match_adviser_conditions():
    assert set(openmeteo.CONDITIONS) == set(clothes.CONDITIONS)


def test_adviser_categories_match_shelf_categories():
    assert tuple(clothes.CLOTHING_TYPES) == CATEGORIES


def test_every_recommendable_type_exists_in_seed_wardrobe():
    seeded = {(item[2], item[3]) for item in SEED_ITEMS}
    for category, types in clothes.CLOTHING_TYPES.items():
        for clothing_type in types:
            assert (category, clothing_type) in seeded


@pytest.mark.parametrize(
    "activity, style", list(itertools.product(clothes.ACTIVITIES, clothes.STYLES))
)
def test_seed_wardrobe_dresses_every_advised_outfit(context, seeded_db, activity, style):
    shelf = ShelfAgent(seeded_db)
    for temperature, condition, rain, wind in itertools.product(
        (-5.0, 15.0, 30.0), clothes.CONDITIONS, (0, 80), (5.0, 40.0)
    ):
        weather = {
            "temperature_c": temperature,
            "condition": condition,
            "precipitation_probability": rain,
            "wind_speed_kmh": wind,
        }
        requirements = clothes.advise(weather, activity, style)
        outfit = shelf.run({"clothing_requirements": requirements}, context)["outfit"]

        for category in CATEGORIES:
            if requirements[category]:
                assert outfit[category] is not None, (category, weather, activity, style)


def test_outputs_feed_the_next_agent(context, seeded_db):
    geocode = {"results": [{"name": "Dallas", "country": "US", "latitude": 32.8, "longitude": -96.8}]}
    forecast = {
        "timezone": "America/Chicago",
        "utc_offset_seconds": -18000,
        "hourly": {
            "time": ["2026-10-11T14:00"],
            "temperature_2m": [22.0],
            "weather_code": [61],
            "precipitation_probability": [65],
            "wind_speed_10m": [15.0],
        },
    }
    responses = {openmeteo.GEOCODING_URL: geocode, openmeteo.FORECAST_URL: forecast}
    weather_agent = WeatherAgent(
        fetch_json=lambda url, params: responses[url],
        clock=lambda: datetime(2026, 10, 11, 19, 30, tzinfo=timezone.utc),
    )

    weather = weather_agent.run({"city": "Dallas"}, context)
    advice = clothes.ClothesAgent().run({**weather, "activity": "outdoor_walk"}, context)
    outfit = ShelfAgent(seeded_db).run(advice, context)

    assert set(weather) == {"weather"}
    assert set(advice) == {"clothing_requirements"}
    assert set(outfit) == {"outfit"}
    assert [outfit["outfit"][c]["clothing_type"] for c in CATEGORIES] == [
        "t_shirt",
        "pants",
        "rain_jacket",
        "walking_shoes",
    ]
