"""Clothes adviser: deterministic rules turning weather and activity into clothing types.

Inputs
    weather   {"temperature_c", "condition", "precipitation_probability", "wind_speed_kmh"}
    activity  one of ACTIVITIES
    style     optional, one of STYLES, default "casual"

Weather is reduced to a temperature band plus three flags:
    cold   temperature_c < 10
    mild   10 <= temperature_c <= 20
    warm   temperature_c > 20
    wet    condition is rainy/stormy, or precipitation_probability >= 50
    snowy  condition is snowy
    windy  wind_speed_kmh >= 30

Activity and style set a dress level:
    relaxed  outdoor_walk or casual activity, casual style
    smart    theatre with casual style, or outdoor_walk/casual with formal style
    formal   theatre with formal style

Each category returns clothing types, best fit first. The rules for each
category are in the functions below, checked top to bottom.
"""

from typing import Any

from agentctl_core import AgentManifest, BaseAgent, Capability, RuntimeContext

ACTIVITIES = ("outdoor_walk", "theatre", "casual")
STYLES = ("casual", "formal")
DEFAULT_STYLE = "casual"

# Must match the weather agent's condition vocabulary.
CONDITIONS = ("clear", "cloudy", "rainy", "snowy", "stormy", "unknown")

COLD_BELOW_C = 10.0
WARM_ABOVE_C = 20.0
WET_PRECIPITATION_PERCENT = 50
WINDY_KMH = 30.0

# Activities where rain protection matters. Theatre is indoors.
OUTDOOR_ACTIVITIES = ("outdoor_walk", "casual")

# Every clothing type the adviser can recommend; the shelf database uses the same values.
CLOTHING_TYPES = {
    "top": ("t_shirt", "polo", "long_sleeve_shirt", "sweater", "dress_shirt"),
    "bottom": ("shorts", "jeans", "pants", "dress_pants"),
    "outerwear": ("light_jacket", "rain_jacket", "winter_coat", "blazer"),
    "footwear": ("sneakers", "walking_shoes", "boots", "dress_shoes"),
}


class ClothesAgent(BaseAgent):
    @property
    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="clothes_adviser",
            version="0.1.0",
            description="Recommends clothing types for the weather and activity",
            capabilities=[
                Capability(
                    name="clothes.advise",
                    requires=["weather", "activity"],
                    produces=["clothing_requirements"],
                )
            ],
        )

    def run(self, inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]:
        requirements = advise(inputs.get("weather"), inputs.get("activity"), inputs.get("style"))
        context.logger.info("Clothing advice: %s", requirements)
        return {"clothing_requirements": requirements}


def advise(weather: Any, activity: Any, style: Any = None) -> dict[str, list[str]]:
    _validate_weather(weather)
    if activity not in ACTIVITIES:
        raise ValueError(f"'activity' must be one of {', '.join(ACTIVITIES)}; got {activity!r}")
    style = DEFAULT_STYLE if style is None else style
    if style not in STYLES:
        raise ValueError(f"'style' must be one of {', '.join(STYLES)}; got {style!r}")

    temperature = weather["temperature_c"]
    band = "cold" if temperature < COLD_BELOW_C else "warm" if temperature > WARM_ABOVE_C else "mild"
    wet = (
        weather["condition"] in ("rainy", "stormy")
        or weather["precipitation_probability"] >= WET_PRECIPITATION_PERCENT
    )
    snowy = weather["condition"] == "snowy"
    windy = weather["wind_speed_kmh"] >= WINDY_KMH
    level = _dress_level(activity, style)

    return {
        "top": _top(band, level),
        "bottom": _bottom(band, level, wet),
        "outerwear": _outerwear(band, level, activity, wet, snowy, windy),
        "footwear": _footwear(band, level, activity, wet, snowy),
    }


def _dress_level(activity: str, style: str) -> str:
    if activity == "theatre":
        return "formal" if style == "formal" else "smart"
    return "smart" if style == "formal" else "relaxed"


def _top(band: str, level: str) -> list[str]:
    if level == "formal":
        return ["dress_shirt", "long_sleeve_shirt"]
    if band == "cold":
        return ["sweater", "long_sleeve_shirt"]
    if level == "smart":
        return ["polo", "long_sleeve_shirt"] if band == "warm" else ["long_sleeve_shirt", "polo"]
    if band == "mild":
        return ["long_sleeve_shirt", "t_shirt"]
    return ["t_shirt", "polo"]


def _bottom(band: str, level: str, wet: bool) -> list[str]:
    if level == "formal":
        return ["dress_pants", "pants"]
    if level == "smart" or wet:
        return ["pants", "jeans"]
    if band == "warm":
        return ["shorts", "jeans"]
    return ["jeans", "pants"]


def _outerwear(
    band: str, level: str, activity: str, wet: bool, snowy: bool, windy: bool
) -> list[str]:
    rain_matters = wet and activity in OUTDOOR_ACTIVITIES
    if band == "cold" or snowy:
        fallback = "rain_jacket" if rain_matters else "blazer" if level == "formal" else "light_jacket"
        return ["winter_coat", fallback]
    if rain_matters:
        return ["rain_jacket", "light_jacket"]
    if band == "mild" or windy:
        return ["blazer", "light_jacket"] if level == "formal" else ["light_jacket"]
    return ["blazer"] if level == "formal" else []


def _footwear(band: str, level: str, activity: str, wet: bool, snowy: bool) -> list[str]:
    if activity == "theatre":
        if snowy:
            return ["boots", "dress_shoes"]
        return ["dress_shoes"] if level == "formal" else ["dress_shoes", "sneakers"]
    if snowy or (band == "cold" and wet):
        return ["boots", "walking_shoes"]
    if activity == "outdoor_walk":
        return ["walking_shoes", "sneakers"]
    return ["sneakers", "walking_shoes"]


def _validate_weather(weather: Any) -> None:
    if not isinstance(weather, dict):
        raise ValueError(f"'weather' must be a dict, got {type(weather).__name__}")
    for key in ("temperature_c", "precipitation_probability", "wind_speed_kmh"):
        value = weather.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"weather[{key!r}] must be a number, got {value!r}")
    if not 0 <= weather["precipitation_probability"] <= 100:
        raise ValueError("weather['precipitation_probability'] must be between 0 and 100")
    if weather["wind_speed_kmh"] < 0:
        raise ValueError("weather['wind_speed_kmh'] must not be negative")
    if weather.get("condition") not in CONDITIONS:
        raise ValueError(
            f"weather['condition'] must be one of {', '.join(CONDITIONS)}; "
            f"got {weather.get('condition')!r}"
        )
