# Extending the framework

This guide adds a new agent as an independent distribution, with no change to
`agentctl-core`. The example estimates how long a text takes to read, which
shows that nothing in the framework is specific to clothing. The code below was
installed and run against the current framework, including the CLI commands
and tests at the end.

Background on the concepts used here: [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Package layout

```text
reading-agent/
├── pyproject.toml
├── src/
│   └── agentctl_agents/          # shared PEP 420 namespace: no __init__.py here
│       └── reading/
│           ├── __init__.py
│           └── agent.py
└── tests/
    └── test_reading_agent.py
```

`agentctl_agents` is shared by every agent distribution, so it must not have
an `__init__.py`. Your own subpackage (`reading/`) can have one. You can also
use your own top-level package; the namespace is a convention, not a
requirement.

## 2. Implement the agent

```python
# src/agentctl_agents/reading/agent.py
from typing import Any

from agentctl_core import (
    AgentManifest,
    BaseAgent,
    Capability,
    GoalSpec,
    InputSpec,
    RuntimeContext,
    WorkflowDefinition,
)

WORDS_PER_MINUTE = {"slow": 150, "average": 230, "fast": 350}


class ReadingTimeAgent(BaseAgent):
    @property
    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="reading_time_estimator",
            version="0.1.0",
            description="Estimates how long a text takes to read",
            capabilities=[
                Capability(
                    name="text.reading_time",
                    requires=["text"],
                    produces=["reading_time"],
                    # Optional metadata, used only by --request:
                    optional_inputs=["reading_speed"],
                    input_specs=[
                        InputSpec("text", "The text to be read"),
                        InputSpec("reading_speed", "How fast the reader reads; average if not stated",
                                  allowed_values=list(WORDS_PER_MINUTE)),
                    ],
                    goals=[GoalSpec("reading_time", "Estimate how long a text takes to read")],
                )
            ],
        )

    def run(self, inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]:
        speed = inputs.get("reading_speed") or "average"
        if speed not in WORDS_PER_MINUTE:
            raise ValueError(f"'reading_speed' must be one of {', '.join(WORDS_PER_MINUTE)}; got {speed!r}")
        words = len(inputs["text"].split())
        minutes = round(words / WORDS_PER_MINUTE[speed], 1)
        context.logger.info("Estimated reading time for %d words", words)
        return {"reading_time": {"words": words, "minutes": minutes, "reading_speed": speed}}


def reading_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        name="reading_estimate",
        description="Estimate reading time for a text",
        steps=["text.reading_time"],
    )
```

### Rules the framework enforces

- **Construction:** the agent class must be constructible with no arguments,
  because discovery instantiates it.
- **Names:** `manifest.name` and every capability name must be unique among
  installed agents.
- **Inputs:** `run` receives every user input plus every output produced
  earlier in the run, not only the keys in `requires`. Read the keys you need.
- **Outputs:** `run` must return a dict with exactly the keys in `produces`,
  and must not overwrite an existing input or output.
- **Isolation:** don't call other agents. The planner connects capabilities
  through matching key names, so if your agent needs `weather`, declare
  `requires=["weather"]` and the weather agent's output will be passed in.
- **Producers:** each output key should have one producer. If two installed
  capabilities produce a key that a plan needs, planning fails with
  `AmbiguousProviderError`.
- **Validation:** validate your own input values and raise a clear exception.
  Structured runs (`--goal`, named workflows) pass `--input` strings to
  agents unchanged.

### `requires` and `produces`

These two lists are all the planner uses. Asking for `--goal reading_time`
finds `text.reading_time` as the producer of `reading_time`. Its requirement
`text` is supplied by the user, so the plan is one step. If `text` were
produced by another installed capability, for example a document extractor,
the planner would put that step first automatically.

### Optional natural-language metadata

`optional_inputs`, `input_specs` and `goals` matter only for `--request`:
- **`GoalSpec`:** advertises an output as a goal the model may choose.
- **`InputSpec`:** describes an input. `allowed_values`, if given, is enforced
  exactly by the validator.
- **Every parameter needs an `InputSpec`:** if you advertise a goal, every
  input in that goal's capability chain needs one. If two capabilities in the
  chain describe the same key, the descriptions must agree.

Invalid metadata makes `--request` fail with exit code 5 for every goal, so
test it (see below). Agents without this metadata still work with `--goal` and
named workflows.

## 3. Register entry points

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "agentctl-reading-agent"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["agentctl-core>=0.1.0"]

[project.entry-points."agentctl.agents"]
reading = "agentctl_agents.reading.agent:ReadingTimeAgent"

[project.entry-points."agentctl.workflows"]
reading = "agentctl_agents.reading.agent:reading_workflow"

# agentctl_agents/ is shared with other distributions, so it has no __init__.py.
[tool.setuptools.packages.find]
where = ["src"]
namespaces = true
```

For brevity, this distribution registers both an agent and a named workflow.
The repository keeps them in separate distributions instead: a workflow plugin
under `agentctl_workflows.*` with only an `agentctl.workflows` entry point (see
`workflows/outfit-workflow/`). A workflow entry point must be a no-argument
function returning a `WorkflowDefinition`. Its `steps` are capability IDs,
checked against installed agents when the workflow runs.

## 4. Install and discover

Install `agentctl-core` (from `./framework`) first. This project is not
published on PyPI, so if the core is missing, pip will look for
`agentctl-core` on PyPI and either fail or install an unrelated package.

```bash
python -m pip install -e ./reading-agent

agentctl list agents        # shows reading_time_estimator and text.reading_time
agentctl list workflows     # shows reading_estimate: text.reading_time
agentctl run workflow --goal reading_time --input "text=The quick brown fox jumps over the lazy dog" --input reading_speed=slow
agentctl run workflow reading_estimate --input "text=hello world"
```

The first run prints:

```json
{
  "words": 9,
  "minutes": 0.1,
  "reading_speed": "slow"
}
```

With an Anthropic key configured, `reading_time` also appears as a
natural-language goal next to `outfit`. Its required parameter is `text`, and
its optional parameter is `reading_speed` with the allowed values `slow`,
`average` and `fast`.

## 5. Test the plugin

Test the agent directly, and test it through real discovery, planning and
orchestration:

```python
# tests/test_reading_agent.py
from agentctl_core import (
    AgentRegistry,
    CapabilityPlanner,
    RuntimeContext,
    SequentialOrchestrator,
    discover_agents,
)
from agentctl_agents.reading.agent import ReadingTimeAgent


def test_run_returns_declared_output():
    context = RuntimeContext("s", "w", {})
    result = ReadingTimeAgent().run({"text": "one two three"}, context)

    assert result == {"reading_time": {"words": 3, "minutes": 0.0, "reading_speed": "average"}}


def test_discovered_plan_runs():
    registry = AgentRegistry()
    discover_agents(registry)  # finds the installed entry point, not a hand-built registry
    inputs = {"text": "word " * 460, "reading_speed": "average"}

    plan = CapabilityPlanner(registry).plan_for_goal("reading_time", inputs, {"text"})
    context = SequentialOrchestrator(registry).execute(plan, RuntimeContext("s", "w", inputs))

    assert plan.steps == ["text.reading_time"]
    assert context.results["reading_time"]["minutes"] == 2.0
```

**More checks worth adding:**
- `build_intent_catalog(registry)` succeeds when you advertise goals.
- Your agent fails clearly on bad input values.
- Any network or database access is faked. The repository's
  [tests/conftest.py](../tests/conftest.py) shows a network-blocking fixture,
  an HTTP transport fake and a temporary SQLite database.

**Test environments:** installing your plugin next to the bundled ones does
not break the repository's own suite. Its discovery-based tests require the
bundled plugins to be present but allow others. Tests that need an exact
registry or catalog build their own. The suite was run with this example
plugin installed (see [TESTING.md](TESTING.md#recorded-results)).
