"""Sprint 06 CLI tests for ``agentctl run workflow --request``.

A fake intent provider is passed to ``cli.main``; everything after it (real
plugin discovery, catalog, validation, planner, orchestrator) is the real code.
Weather HTTP is faked and the wardrobe is a temporary seeded database.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from agentctl_core import IntentProviderConfigError, IntentProviderError, ResolvedIntent, cli

REQUEST = "Suggest an outfit for a casual theatre visit in Dallas"
SUPPORTED = ResolvedIntent("outfit", {"city": "Dallas", "activity": "theatre", "style": "casual"})


@pytest.fixture
def wardrobe(seeded_db, monkeypatch):
    monkeypatch.setenv("SHELF_DB_PATH", str(seeded_db))
    return seeded_db


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def run(capsys, argv, provider=None):
    code = cli.main(argv, intent_provider=provider)
    out, err = capsys.readouterr()
    return code, out, err


def request_argv(*extra, request=REQUEST):
    return ["run", "workflow", "--request", request, *extra]


# Parsing ---------------------------------------------------------------------------------


def test_help_mentions_request(capsys):
    code, out, _ = run(capsys, ["run", "workflow", "--help"])

    assert code == 0
    assert "--request TEXT" in out and "ANTHROPIC_API_KEY" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "workflow", "outfit_advisor", "--request", REQUEST],
        ["run", "workflow", "--goal", "outfit", "--request", REQUEST],
        ["run", "workflow", "outfit_advisor", "--goal", "outfit", "--request", REQUEST],
        ["run", "workflow", "--input", "city=Dallas"],
    ],
)
def test_exactly_one_mode(capsys, fake_intent, argv):
    provider = fake_intent(SUPPORTED)
    code, out, err = run(capsys, argv, provider)

    assert code == cli.EXIT_USAGE
    assert out == ""
    assert "exactly one of a workflow NAME or --goal or --request" in err
    assert provider.calls == []


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_request(capsys, fake_intent, text):
    provider = fake_intent(SUPPORTED)
    code, _, err = run(capsys, request_argv(request=text), provider)

    assert code == cli.EXIT_USAGE
    assert "--request must not be empty" in err
    assert provider.calls == []


def test_duplicate_inputs_still_rejected(capsys, fake_intent):
    code, _, err = run(capsys, request_argv("--input", "city=A", "--input", "city=B"), fake_intent(SUPPORTED))

    assert code == cli.EXIT_USAGE
    assert "given more than once" in err


# Missing configuration (exit 5) ---------------------------------------------------------------


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_api_key(capsys, monkeypatch, fake_weather_http, wardrobe, key):
    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)

    code, out, err = run(capsys, request_argv())

    assert code == cli.EXIT_PLUGIN == 5
    assert out == ""
    assert "agentctl: error: natural-language requests are unavailable: ANTHROPIC_API_KEY is not configured." in err
    assert "agentctl run workflow --goal OUTPUT_KEY --input KEY=VALUE" in err
    assert "agentctl run workflow WORKFLOW_NAME --input KEY=VALUE" in err
    assert fake_weather_http == []  # no agent ran


def test_missing_sdk_with_key(capsys, monkeypatch, fake_weather_http):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setitem(sys.modules, "anthropic", None)

    code, out, err = run(capsys, request_argv())

    assert code == cli.EXIT_PLUGIN
    assert out == ""
    assert "pip install -e './framework[llm]'" in err
    assert fake_weather_http == []


def test_provider_configuration_error(capsys, fake_intent, fake_weather_http):
    provider = fake_intent(IntentProviderConfigError("Anthropic rejected the API key (authentication failed)"))
    code, out, err = run(capsys, request_argv(), provider)

    assert code == cli.EXIT_PLUGIN
    assert out == ""
    assert "authentication failed" in err
    assert fake_weather_http == []


@pytest.mark.parametrize("argv", [
    ["list", "agents"],
    ["list", "workflows"],
    ["run", "workflow", "outfit_advisor", "--input", "city=Dallas", "--input", "activity=theatre"],
    ["run", "workflow", "--goal", "outfit", "--input", "city=Dallas", "--input", "activity=theatre"],
])
def test_structured_commands_need_no_key(capsys, no_key, fake_weather_http, wardrobe, argv):
    code, out, _ = run(capsys, argv)

    assert code == 0
    assert out


# Successful requests ------------------------------------------------------------------------


def test_request_runs_planner_and_orchestrator(capsys, fake_intent, fake_weather_http, wardrobe):
    provider = fake_intent(SUPPORTED)
    code, out, err = run(capsys, request_argv(), provider)

    assert code == 0
    outfit = json.loads(out)  # exactly one JSON document on stdout
    assert set(outfit) == {"top", "bottom", "outerwear", "footwear"}
    assert outfit["footwear"]["clothing_type"] == "dress_shoes"
    assert fake_weather_http == ["geocoding-api.open-meteo.com", "api.open-meteo.com"]

    (request, catalog), = provider.calls
    assert request == REQUEST
    assert list(catalog.goals) == ["outfit"]
    assert "Request mode" in err
    assert "Intent validated: goal outfit with parameters activity, city, style" in err
    assert "source generated, steps: weather.forecast, clothes.advise, shelf.match" in err


def test_explicit_input_overrides_extracted_value(capsys, fake_intent, fake_weather_http, wardrobe):
    provider = fake_intent(ResolvedIntent("outfit", {"city": "Dallas", "activity": "theatre", "style": "casual"}))
    code, out, _ = run(capsys, request_argv("--input", "style=formal"), provider)

    assert code == 0
    assert json.loads(out)["top"]["clothing_type"] == "dress_shirt"  # formal theatre


def test_explicit_input_supplies_missing_value(capsys, fake_intent, fake_weather_http, wardrobe):
    provider = fake_intent(ResolvedIntent("outfit", {"activity": "outdoor_walk"}))
    code, out, _ = run(capsys, request_argv("--input", "city=Dallas", request="Outfit for a walk"), provider)

    assert code == 0
    assert json.loads(out)["outerwear"]["clothing_type"] == "rain_jacket"


def test_request_text_is_not_logged(capsys, fake_intent, fake_weather_http, wardrobe):
    _, out, err = run(capsys, request_argv(request="Outfit for theatre in Dallas, my secret plan"),
                      fake_intent(SUPPORTED))

    assert "secret plan" not in err and "secret plan" not in out
    assert "INFO" not in out


# Rejected intents (exit 3) ------------------------------------------------------------------


@pytest.mark.parametrize(
    "intent, message",
    [
        (ResolvedIntent("outfit", {"activity": "theatre"}),
         "missing required input 'city' for goal 'outfit'; supply --input city=VALUE"),
        (ResolvedIntent("outfit", {"city": "Dallas", "activity": "hiking"}),
         "parameter 'activity' must be one of: outdoor_walk, theatre, casual, office, walk, walking, work, office_meeting; got 'hiking'"),
        (ResolvedIntent("outfit", {"city": "Dallas", "activity": "theatre", "style": "sporty"}),
         "parameter 'style' must be one of: casual, formal, business_casual"),
        (ResolvedIntent("flight_booking", {"city": "Dallas"}),
         "unsupported natural-language goal 'flight_booking' (available: outfit)"),
        (ResolvedIntent("outfit", {"city": "Dallas", "activity": "theatre", "fashion_score": "9"}),
         "unknown parameter 'fashion_score' for selected goal 'outfit'"),
        (ResolvedIntent("clothing_requirements", {"city": "Dallas", "activity": "theatre"}),
         "unsupported natural-language goal 'clothing_requirements'"),
        (ResolvedIntent("outfit", {"city": 42, "activity": "theatre"}),
         "parameter 'city' must be a string"),
    ],
)
def test_rejected_intent_runs_nothing(capsys, fake_intent, fake_weather_http, wardrobe, intent, message):
    code, out, err = run(capsys, request_argv(), fake_intent(intent))

    assert code == cli.EXIT_PLANNING
    assert out == ""
    assert message in err
    assert fake_weather_http == []


def test_invalid_explicit_input_rejected(capsys, fake_intent, fake_weather_http):
    code, _, err = run(capsys, request_argv("--input", "style=sporty"), fake_intent(SUPPORTED))

    assert code == cli.EXIT_PLANNING
    assert "parameter 'style' must be one of: casual, formal, business_casual; got 'sporty' (from --input)" in err
    assert fake_weather_http == []


def test_explicit_input_for_produced_key_rejected(capsys, fake_intent, fake_weather_http):
    code, _, err = run(capsys, request_argv("--input", "weather=sunny"), fake_intent(SUPPORTED))

    assert code == cli.EXIT_PLANNING
    assert "unknown parameter 'weather'" in err


# Failures after validation --------------------------------------------------------------------


def test_provider_runtime_failure(capsys, fake_intent, fake_weather_http):
    code, out, err = run(capsys, request_argv(), fake_intent(IntentProviderError("Anthropic rate limit reached")))

    assert code == cli.EXIT_EXECUTION
    assert out == ""
    assert "intent provider failed: Anthropic rate limit reached" in err
    assert fake_weather_http == []


def test_agent_failure_after_valid_intent(capsys, fake_intent, fake_weather_http, tmp_path, monkeypatch):
    monkeypatch.setenv("SHELF_DB_PATH", str(tmp_path / "missing.db"))
    code, out, err = run(capsys, request_argv(), fake_intent(SUPPORTED))

    assert code == cli.EXIT_EXECUTION
    assert out == ""
    assert "failed at step 3 of 3 'shelf.match'" in err


def test_no_advertised_goals(capsys, fake_intent, monkeypatch):
    from agentctl_core import AgentRegistry

    monkeypatch.setattr(cli, "_discover_agents", AgentRegistry)
    provider = fake_intent(SUPPORTED)
    code, _, err = run(capsys, request_argv(), provider)

    assert code == cli.EXIT_PLANNING
    assert "no installed agent advertises a natural-language goal" in err
    assert provider.calls == []


def test_handlers_removed_after_request(capsys, fake_intent, fake_weather_http, wardrobe):
    before = list(logging.getLogger("agentctl").handlers)
    run(capsys, request_argv(), fake_intent(SUPPORTED))

    assert logging.getLogger("agentctl").handlers == before


# Installed executable ---------------------------------------------------------------------------


def test_installed_agentctl_without_key_exits_5():
    executable = Path(sys.executable).parent / "agentctl"
    env = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
    result = subprocess.run(
        [str(executable), "run", "workflow", "--request", REQUEST],
        capture_output=True, text=True, timeout=60, env=env,
    )

    assert result.returncode == 5
    assert result.stdout == ""
    assert "ANTHROPIC_API_KEY is not configured" in result.stderr


def test_structured_commands_work_without_the_sdk():
    code = (
        "import sys; sys.modules['anthropic'] = None; "
        "from agentctl_core import cli; "
        "sys.exit(cli.main(['run', 'workflow', '--goal', 'outfit', '--input', 'outfit=given']))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)

    assert result.returncode == 0
    assert json.loads(result.stdout) == "given"
