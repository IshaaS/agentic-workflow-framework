"""Sprint 05 CLI tests.

Most tests call ``cli.main(argv)`` in-process so they can share the fake
weather transport (``fake_weather_http``) and a temporary wardrobe. A few
run the installed ``agentctl`` executable as a subprocess.
"""

import json
import logging
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from agentctl_core import (
    AgentManifest,
    AgentRegistry,
    BaseAgent,
    Capability,
    PluginDiscoveryError,
    RuntimeContext,
    WorkflowPlan,
    cli,
)

INPUTS = ["--input", "city=Dallas", "--input", "activity=outdoor_walk", "--input", "style=casual"]

# Seeded items chosen for rainy 22°C, outdoor walk, casual style.
EXPECTED_OUTFIT_IDS = {"top": 1, "bottom": 10, "outerwear": 13, "footwear": 17}


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def wardrobe(seeded_db, monkeypatch):
    monkeypatch.setenv("SHELF_DB_PATH", str(seeded_db))
    return seeded_db


def outfit_ids(stdout):
    return {category: item["id"] for category, item in json.loads(stdout).items()}


# Help and listing --------------------------------------------------------------


def test_help_lists_commands(capsys):
    code, out, _ = run(capsys, "--help")

    assert code == 0
    assert "list" in out and "run" in out


def test_run_workflow_help(capsys):
    code, out, _ = run(capsys, "run", "workflow", "--help")

    assert code == 0
    assert "--goal" in out and "--input KEY=VALUE" in out


def test_list_agents_shows_manifests(capsys):
    code, out, err = run(capsys, "list", "agents")

    assert code == 0
    for text in (
        "weather_provider 0.1.0",
        "Provides a weather forecast for a city",
        "capability: weather.forecast",
        "requires: city",
        "produces: weather",
        "clothes_adviser 0.1.0",
        "requires: weather, activity",
        "produces: clothing_requirements",
        "shelf_manager 0.1.0",
        "capability: shelf.match",
        "produces: outfit",
    ):
        assert text in out
    assert "Discovered agent" in err and "Discovered agent" not in out


def test_list_workflows(capsys):
    code, out, _ = run(capsys, "list", "workflows")

    assert code == 0
    assert "outfit_advisor" in out
    assert "Recommend clothing using weather and a personal shelf" in out
    assert "steps: weather.forecast -> clothes.advise -> shelf.match" in out


# Running workflows ---------------------------------------------------------------


def test_goal_run_prints_outfit_json(capsys, fake_weather_http, wardrobe):
    code, out, err = run(capsys, "run", "workflow", "--goal", "outfit", *INPUTS)

    assert code == 0
    assert outfit_ids(out) == EXPECTED_OUTFIT_IDS
    assert json.loads(out)["outerwear"]["name"] == "Yellow rain jacket"
    assert fake_weather_http == ["geocoding-api.open-meteo.com", "api.open-meteo.com"]
    assert "source generated, steps: weather.forecast, clothes.advise, shelf.match" in err
    assert "completed" in err


def test_named_run_prints_last_step_output(capsys, fake_weather_http, wardrobe):
    code, out, err = run(capsys, "run", "workflow", "outfit_advisor", *INPUTS)

    assert code == 0
    assert outfit_ids(out) == EXPECTED_OUTFIT_IDS
    assert "source named" in err


def test_optional_style_reaches_agents(capsys, fake_weather_http, wardrobe):
    code, out, _ = run(
        capsys, "run", "workflow", "--goal", "outfit",
        "--input", "city=Dallas", "--input", "activity=theatre", "--input", "style=formal",
    )

    assert code == 0
    assert json.loads(out)["footwear"]["clothing_type"] == "dress_shoes"


def test_intermediate_goal(capsys, fake_weather_http):
    code, out, _ = run(capsys, "run", "workflow", "--goal", "weather", "--input", "city=Dallas")

    assert code == 0
    assert json.loads(out)["condition"] == "rainy"


def test_goal_already_supplied_prints_input(capsys, fake_weather_http):
    code, out, err = run(capsys, "run", "workflow", "--goal", "outfit", "--input", "outfit=as given")

    assert code == 0
    assert json.loads(out) == "as given"
    assert fake_weather_http == []
    assert "steps: none" in err


def test_logs_go_to_stderr_only(capsys, fake_weather_http, wardrobe):
    _, out, err = run(capsys, "run", "workflow", "--goal", "outfit", *INPUTS)

    json.loads(out)  # stdout is exactly one JSON document
    assert "INFO" not in out
    assert "INFO agentctl" in err


# Planning failures (exit 3) --------------------------------------------------------


def test_missing_input(capsys, fake_weather_http):
    code, out, err = run(capsys, "run", "workflow", "--goal", "outfit", "--input", "activity=theatre")

    assert code == cli.EXIT_PLANNING
    assert out == ""
    assert "missing required input 'city' (required by 'weather.forecast')" in err
    assert "--input city=VALUE" in err
    assert fake_weather_http == []


def test_missing_input_for_named_workflow(capsys, fake_weather_http):
    code, _, err = run(capsys, "run", "workflow", "outfit_advisor", "--input", "city=Dallas")

    assert code == cli.EXIT_PLANNING
    assert "missing required input 'activity'" in err
    assert fake_weather_http == []


def test_unknown_goal(capsys):
    code, out, err = run(capsys, "run", "workflow", "--goal", "party_plan", "--input", "city=Dallas")

    assert code == cli.EXIT_PLANNING
    assert out == ""
    assert "no installed capability produces goal 'party_plan'" in err


def test_unknown_workflow(capsys):
    code, _, err = run(capsys, "run", "workflow", "no_such_flow", *INPUTS)

    assert code == cli.EXIT_PLANNING
    assert "unknown workflow 'no_such_flow' (installed workflows: outfit_advisor)" in err


def test_input_that_a_step_would_overwrite_is_rejected(capsys, fake_weather_http):
    code, _, err = run(capsys, "run", "workflow", "outfit_advisor", *INPUTS, "--input", "weather=sunny")

    assert code == cli.EXIT_PLANNING
    assert "would overwrite 'weather'" in err
    assert fake_weather_http == []


# Usage errors (exit 2) -----------------------------------------------------------------


@pytest.mark.parametrize(
    "argv, message",
    [
        (["run", "workflow", "outfit_advisor", "--goal", "outfit"], "exactly one of a workflow NAME or --goal"),
        (["run", "workflow", *INPUTS], "exactly one of a workflow NAME or --goal"),
        (["run", "workflow", "--goal", "outfit", "--input", "city"], "must have the form KEY=VALUE"),
        (["run", "workflow", "--goal", "outfit", "--input", "=Dallas"], "has an empty key"),
        (["run", "workflow", "--goal", "outfit", "--input", "city=A", "--input", "city=B"], "given more than once"),
        (["list"], "required"),
        (["list", "plugins"], "invalid choice"),
        ([], "required"),
    ],
)
def test_usage_errors(capsys, argv, message):
    code, out, err = run(capsys, *argv)

    assert code == cli.EXIT_USAGE
    assert out == ""
    assert message in err


def test_parse_inputs_splits_at_first_equals():
    assert cli.parse_inputs(["query=a=b", "empty=", " key =v"]) == {"query": "a=b", "empty": "", "key": "v"}


# Execution failures (exit 4) -----------------------------------------------------------


def test_weather_failure(capsys, wardrobe, monkeypatch):
    from agentctl_agents.weather import openmeteo

    def timing_out(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(openmeteo, "urlopen", timing_out)
    code, out, err = run(capsys, "run", "workflow", "--goal", "outfit", *INPUTS)

    assert code == cli.EXIT_EXECUTION
    assert out == ""
    assert "failed at step 1 of 3 'weather.forecast'" in err
    assert "timed out" in err


def test_missing_wardrobe(capsys, fake_weather_http, tmp_path, monkeypatch):
    monkeypatch.setenv("SHELF_DB_PATH", str(tmp_path / "missing.db"))
    code, out, err = run(capsys, "run", "workflow", "outfit_advisor", *INPUTS)

    assert code == cli.EXIT_EXECUTION
    assert out == ""
    assert "failed at step 3 of 3 'shelf.match'" in err
    assert "agentctl-shelf-init" in err
    assert not (tmp_path / "missing.db").exists()


def test_unconfigured_wardrobe(capsys, fake_weather_http, monkeypatch):
    monkeypatch.delenv("SHELF_DB_PATH", raising=False)
    code, out, err = run(capsys, "run", "workflow", "--goal", "outfit", *INPUTS)

    assert code == cli.EXIT_EXECUTION
    assert out == ""
    assert "SHELF_DB_PATH" in err


# Plugin discovery failures (exit 5) ---------------------------------------------------


@pytest.mark.parametrize("argv", [["list", "agents"], ["run", "workflow", "--goal", "outfit", *INPUTS]])
def test_discovery_failure(capsys, monkeypatch, argv):
    def broken(registry):
        raise PluginDiscoveryError("failed to load agent from entry point 'bad'")

    monkeypatch.setattr(cli, "discover_agents", broken)
    code, out, err = run(capsys, *argv)

    assert code == cli.EXIT_PLUGIN
    assert out == ""
    assert "entry point 'bad'" in err


# Generic behaviour (synthetic agents, no plugins) -----------------------------------


class SyntheticAgent(BaseAgent):
    def __init__(self, name, capability):
        self._manifest = AgentManifest(name, "1.0", "synthetic", [capability])

    @property
    def manifest(self):
        return self._manifest

    def run(self, inputs, context):
        return {}


def synthetic_registry(*capabilities):
    registry = AgentRegistry()
    for index, capability in enumerate(capabilities):
        registry.register(SyntheticAgent(f"agent{index}", capability))
    return registry


def test_external_inputs_are_unproduced_requirements_plus_user_keys():
    registry = synthetic_registry(
        Capability("a.make", ["seed", "shared"], ["mid"]),
        Capability("b.make", ["mid", "extra"], ["final"]),
    )

    assert cli.external_inputs(registry, {"note": "x"}) == {"seed", "shared", "extra", "note"}


def test_named_result_with_one_output_is_the_value():
    registry = synthetic_registry(Capability("a.make", [], ["answer"]))
    context = RuntimeContext("s", "w", {}, results={"answer": 42})

    assert cli.select_result(WorkflowPlan(["a.make"], "named"), context, registry, None) == 42


def test_named_result_with_several_outputs_is_a_mapping():
    registry = synthetic_registry(
        Capability("a.make", [], ["first"]),
        Capability("b.make", ["first"], ["left", "right"]),
    )
    context = RuntimeContext("s", "w", {}, results={"first": 1, "left": 2, "right": 3})

    result = cli.select_result(WorkflowPlan(["a.make", "b.make"], "named"), context, registry, None)

    assert result == {"left": 2, "right": 3}


def test_non_json_result_is_an_execution_error(capsys, monkeypatch):
    monkeypatch.setattr(cli, "select_result", lambda *args: {1, 2})
    code, out, err = run(capsys, "run", "workflow", "--goal", "outfit", "--input", "outfit=x")

    assert code == cli.EXIT_EXECUTION
    assert out == ""
    assert "not JSON-serializable" in err


def test_cli_source_has_no_application_names():
    source = Path(cli.__file__).read_text()
    for name in ("agentctl_agents", "agentctl_workflows", "outfit", "city", "activity", "weather", "shelf"):
        assert name not in source


def test_cli_removes_its_log_handler_after_each_call(capsys):
    before = list(logging.getLogger("agentctl").handlers)
    run(capsys, "list", "workflows")

    assert logging.getLogger("agentctl").handlers == before


def test_network_is_blocked_in_tests():
    with pytest.raises(RuntimeError, match="network access is not allowed"):
        socket.create_connection(("example.com", 80), timeout=1)


# Installed executable ------------------------------------------------------------------


def agentctl(*argv):
    executable = Path(sys.executable).parent / "agentctl"
    assert executable.exists(), f"agentctl not installed next to {sys.executable}; pip install -e ./framework"
    return subprocess.run([str(executable), *argv], capture_output=True, text=True, timeout=60)


def test_installed_agentctl_lists_agents():
    result = agentctl("list", "agents")

    assert result.returncode == 0
    assert "weather_provider" in result.stdout and "shelf_manager" in result.stdout
    assert "Discovered agent" in result.stderr and "Discovered agent" not in result.stdout


def test_exit_codes_match_documentation():
    assert (cli.EXIT_OK, cli.EXIT_USAGE, cli.EXIT_PLANNING, cli.EXIT_EXECUTION, cli.EXIT_PLUGIN) == (0, 2, 3, 4, 5)


def test_installed_agentctl_planning_error_exit_code():
    result = agentctl("run", "workflow", "--goal", "no_such_output")

    assert result.returncode == 3
    assert result.stdout == ""
    assert "agentctl: error: no installed capability produces goal 'no_such_output'" in result.stderr


def test_installed_agentctl_usage_error_exit_code():
    result = agentctl("run", "workflow")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage: agentctl run workflow" in result.stderr


def test_importing_core_configures_no_handlers():
    code = (
        "import logging, agentctl_core, agentctl_core.cli; "
        "print(logging.getLogger('agentctl').handlers, logging.getLogger().handlers)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)

    assert result.stdout.strip() == "[] []"
