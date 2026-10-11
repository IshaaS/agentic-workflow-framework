# Architecture

This document describes how the framework works, as it is implemented in
`framework/src/agentctl_core/` and the plugin packages. For setup, see the
[README](../README.md). To add a plugin, see [EXTENDING.md](EXTENDING.md).

## Components

| Path | Distribution | Contents |
|---|---|---|
| `framework/` | `agentctl-core` | SDK (`sdk.py`, `context.py`), discovery and registries, planner, orchestrator, typed errors, intent catalog, validation and provider interface, Anthropic adapter (`providers/anthropic.py`), `agentctl` CLI |
| `agents/weather-agent/` | `agentctl-weather-agent` | `agentctl_agents.weather`: `weather.forecast` (`city` → `weather`) |
| `agents/clothes-agent/` | `agentctl-clothes-agent` | `agentctl_agents.clothes`: `clothes.advise` (`weather`, `activity`, optional `style` → `clothing_requirements`) |
| `agents/shelf-agent/` | `agentctl-shelf-agent` | `agentctl_agents.shelf`: `shelf.match` (`clothing_requirements` → `outfit`), plus the `agentctl-shelf-init` command |
| `workflows/outfit-workflow/` | `agentctl-outfit-workflow` | `agentctl_workflows.outfit`: the named workflow `outfit_advisor` |

`agentctl-core` has no required runtime dependencies. The Anthropic SDK is an
optional extra (`[llm]`). The weather agent uses only the standard library
(`urllib`), and the shelf agent uses `sqlite3`.

## Core SDK contracts

Defined in `agentctl_core/sdk.py` and `context.py`, and exported from `agentctl_core`.

| Type | Fields / methods | Role |
|---|---|---|
| `BaseAgent` (ABC) | `manifest` property; `run(inputs, context) -> dict` | What every agent implements. Agents never call each other. |
| `AgentManifest` | `name`, `version`, `description`, `capabilities` | Metadata the framework reads without running the agent |
| `Capability` | `name`, `requires`, `produces`, plus optional `optional_inputs`, `input_specs`, `goals` | One action, described by the data keys it consumes and produces |
| `InputSpec` | `name`, `description`, `value_type="string"`, `allowed_values` | Optional description of an input, used only for natural-language requests |
| `GoalSpec` | `output_key`, `description` | Optionally advertises a `produces` key as a goal users can ask for in natural language |
| `WorkflowDefinition` | `name`, `description`, `steps` (capability IDs) | A named, reusable workflow shipped by a plugin |
| `WorkflowPlan` | `steps`, `source` (`"named"` or `"generated"`) | The single plan format the orchestrator executes |
| `RuntimeContext` | `session_id`, `workflow_id`, `inputs`, `results`, `memory`, `events`, `logger` | State for one execution |

Planning uses only `Capability.name`, `requires` and `produces`. The other
`Capability` fields are optional metadata for `--request`. Plugins without them
still work with `--goal` and named workflows.

The demonstration capabilities are:

| Agent | Capability | requires | optional | produces |
|---|---|---|---|---|
| `weather_provider` | `weather.forecast` | `city` | | `weather` |
| `clothes_adviser` | `clothes.advise` | `weather`, `activity` | `style` | `clothing_requirements` |
| `shelf_manager` | `shelf.match` | `clothing_requirements` | | `outfit` (advertised with `GoalSpec`) |

## Plugins, discovery and registration

**Packaging:**
- Each agent and workflow is its own distribution, with its own
  `pyproject.toml`, and depends on `agentctl-core`.
- The agent packages share the PEP 420 namespace `agentctl_agents`, and
  workflows share `agentctl_workflows`. The shared directory has no
  `__init__.py`, so several distributions can install subpackages into it.
- The namespace only organises imports. Discovery comes from entry points.

| Entry-point group | Target |
|---|---|
| `agentctl.agents` | A `BaseAgent` subclass with a no-argument constructor |
| `agentctl.workflows` | A no-argument function returning a `WorkflowDefinition` |

```toml
# agents/clothes-agent/pyproject.toml
[project.entry-points."agentctl.agents"]
clothes = "agentctl_agents.clothes.agent:ClothesAgent"
```

**How discovery works** (`discovery.py`):
- `discover_agents()` and `discover_workflows()` read the groups with
  `importlib.metadata.entry_points` and load the entries in `(name, value)`
  order.
- Agents are instantiated; workflow factories are called.
- A plugin that fails to import, has the wrong type, or collides with an
  existing one raises `PluginDiscoveryError`, which names the entry point.
- Loading an entry point runs the plugin's code.

**Registries** (`registry.py`):
- `AgentRegistry` indexes agents by manifest name and by capability name. Both
  must be unique.
- `WorkflowRegistry` stores definitions by name, as metadata only. Their steps
  are checked at planning time.

The core never imports a plugin. Tests check this: they search the core
source for plugin package names and clothing vocabulary.

## Planning

`CapabilityPlanner` (`planner.py`) builds a `WorkflowPlan` from registry
metadata only. A data key counts as available when it is a key of `inputs`;
the values themselves are never inspected.

### Generated plans (`plan_for_goal`)

The goal is an output key, such as `outfit`. The planner resolves it
backwards, depth-first:

1. **Already supplied:** if the key is in `inputs`, it is not produced. A goal
   that is already supplied gives an empty plan.
2. **Find the producer:** otherwise the planner finds the capability that
   produces the key. Two or more producers raise `AmbiguousProviderError`, but
   only if that key is actually needed.
3. **Dependencies first:** each of that capability's `requires` is resolved
   recursively, then the capability is appended. A capability needed by
   several others appears once.
4. **Cycles:** these raise `CircularDependencyError`.
5. **No producer:** the error depends on the key.
   - The goal itself: `UnknownGoalError`.
   - A key the caller is expected to supply (`external_inputs`):
     `MissingInputError`.
   - Anything else: `MissingCapabilityError`.
6. **Output conflicts:** the finished plan is rejected
   (`InvalidWorkflowPlanError`) if a step would produce a key that is already
   an input, or that another step also produces.

Plugins don't label which keys come from users, so the CLI works out
`external_inputs`. It takes every key some capability requires but no
installed capability produces, plus every key the user passed. A run without
`city` is therefore reported as a missing input, while an uninstalled clothes
agent is reported as a missing capability.

### Named workflows (`plan_from_workflow`)

The workflow's steps are capability IDs. The planner checks that:
- every step is installed;
- no step repeats;
- each step's `requires` come from `inputs` or an earlier step (it reports
  "out of order" when only a later step produces the key);
- no outputs conflict.

It never reorders steps. A valid named workflow and a generated plan for the
same goal give the same kind of `WorkflowPlan`; only `source` differs.

## Sequential orchestration

`SequentialOrchestrator.execute(plan, context)` (`orchestrator.py`) runs the
steps in order:

1. **Resolve:** each capability ID is mapped to its registered agent.
2. **Inputs:** each agent gets a copy of the working data, which is
   `context.inputs` plus every output produced so far. All declared `requires`
   must be present.
3. **Outputs:** the agent must return a dict with exactly the keys in
   `produces`. Missing or undeclared keys are an `invalid_output` failure. A
   key that would overwrite an input or an earlier output is an
   `output_conflict`.
4. **Results:** outputs are stored in `context.results`, keyed by output name
   (for example `results["weather"]`), and added to the working data for later
   steps.
5. **Fail fast:** the first failure stops the run with a
   `WorkflowExecutionError`. The error has a `reason`, `capability`,
   `step_index` and the agent's original exception as `__cause__`. Results
   from earlier steps are kept, and no partial result is printed.

**What the CLI prints:**
- For `--goal`, the value of the goal key.
- For a named workflow, the last step's output: the value itself if the step
  produces one key, otherwise a mapping of its keys.

## Runtime context, events and logging

**Runtime context:**
- A new `RuntimeContext` is created for each CLI run, with a random
  `session_id` and `workflow_id` (UUID hex).
- There is no `--session-id` option. Session IDs label one execution in logs
  and events; they are not user identities.
- `memory` is a per-run dict available to agents. None of the bundled agents
  use it, and nothing is persisted between runs.

**Events:** `events` is an in-memory list of dicts. Every event has `type`,
`workflow_id`, `session_id` and a UTC `timestamp`.

| Event | Extra fields |
|---|---|
| `workflow_started` | `source`, `steps` |
| `agent_started` | `step_index`, `capability`, `agent` |
| `agent_completed` | step fields, `outputs`, `duration_ms` |
| `agent_failed` | step fields, `reason`, `error`, `duration_ms` |
| `workflow_completed` | `duration_ms` |
| `workflow_failed` | `step_index`, `capability`, `reason`, `error`, `duration_ms` |

**Logging:**
- The framework uses standard `logging` under the `agentctl` logger. Agents
  log through `context.logger`.
- Lifecycle messages include the workflow ID, session ID, step number,
  capability, agent and duration, and pass them as `extra` fields too.
- Importing the library configures no handlers. The CLI attaches an INFO-level
  stderr handler only while a command runs.
- stdout carries only the JSON result.
- Request text and parameter values from `--request` are never logged; only
  the goal and parameter names are. The weather agent logs the resolved city
  name.

## Errors and exit codes

Planning errors subclass `PlanningError` and mean no agent has run. Execution
errors are `WorkflowExecutionError`. Intent errors are `IntentCatalogError`,
`IntentValidationError` (also a `PlanningError`), `IntentProviderError` and
`IntentProviderConfigError`.

| Exit | Meaning |
|---:|---|
| 0 | Success |
| 2 | Invalid command line or `--input` |
| 3 | Planning failed (missing input, unknown goal or workflow, invalid plan, rejected `--request` intent); nothing ran |
| 4 | A step failed (e.g. weather API error, missing wardrobe, an agent rejecting an input value), or the intent provider failed at run time |
| 5 | A plugin could not be loaded, plugin goal metadata is invalid, or `--request` is not configured (no `ANTHROPIC_API_KEY`, no SDK, rejected key) |

## Natural-language requests

`agentctl run workflow --request "TEXT"` adds one step before normal planning.

```text
installed manifests ─► intent catalog ─► provider (Anthropic) ─► canonicalize ─► validate ─► planner ─► orchestrator
                       (goals, params)    goal + parameters      formatting only   exact checks  (same as --goal)
```

1. **Catalog** (`intent_catalog.py`):
   - Only outputs advertised with a `GoalSpec` become goals.
   - For each goal, the planner finds its capability chain. The goal's
     parameters are the chain's external `requires` (required) and
     `optional_inputs` (optional).
   - Each parameter must have an `InputSpec`, and specs for the same key must
     agree across the chain. Invalid metadata raises `IntentCatalogError`
     (exit 5).
   - For the demo, the only goal is `outfit`. Its parameters are `city` and
     `activity` (required) and `style` (optional).
2. **Provider** (`intent.py`, `providers/anthropic.py`):
   - `IntentProvider` is a one-method protocol:
     `resolve(request, catalog) -> ResolvedIntent(goal, parameters)`.
   - The Anthropic adapter sends a domain-neutral system prompt, plus the
     catalog and the request as data, to the Messages API.
   - It uses structured outputs: a JSON schema with a `goal` string and a
     `parameters` object in which every catalog key is required, in catalog
     order. `""` means "not stated" and is dropped.
   - Other settings: effort `low`, a 30-second timeout and one SDK retry. The
     default model is `claude-opus-5-5`, which `ANTHROPIC_MODEL` can override.
   - For the model IDs listed in `FALLBACK_MODELS`, the call goes through the
     beta endpoint with Anthropic's server-side refusal fallback
     (`fallbacks="default"`).
   - The SDK is imported only when `--request` is used.
3. **Canonicalize** (`canonicalize_intent`): a provider value that differs from
   exactly one allowed value only in case, spaces, hyphens or underscores is
   replaced by that value (`Outdoor walk` → `outdoor_walk`). No meaning is
   inferred.
4. **Validate** (`intent_validation.py`), with exact checks:
   - the goal is in the catalog;
   - every parameter is declared for it;
   - values are non-empty strings;
   - values match `allowed_values` when declared;
   - required parameters are present.

   Values given with `--input` take precedence and pass the same checks, but
   they are never canonicalized.
5. **Plan and run:** the validated goal and inputs go through the same planner
   and orchestrator as `--goal`.

The model never sees capability or agent names. It cannot add steps, choose
agents or run anything. Its whole contribution is one goal string and a dict
of string parameters, and both are validated before execution.

The clothes adviser advertises its accepted values, including aliases such as
`walk` and `office_meeting`, through `InputSpec.allowed_values`. That makes
them valid in request mode without any clothing-specific code in the core.

## Example runtime flow

`agentctl run workflow --goal outfit --input city=Chicago --input activity=office --input style=business_casual`

1. **Discovery:** the CLI discovers three agents from the `agentctl.agents`
   group.
2. **Planning:** `external_inputs` is `{city, activity, style}`. The planner
   needs `outfit`, which `shelf.match` produces.
   - `shelf.match` needs `clothing_requirements`, produced by `clothes.advise`.
   - `clothes.advise` needs `weather` (from `weather.forecast`) and `activity`
     (an input).
   - `weather.forecast` needs `city` (an input).
   - Plan: `weather.forecast → clothes.advise → shelf.match`, source
     `generated`.
3. **`weather.forecast`:** geocodes Chicago and reads the current local hour
   from Open-Meteo. It returns
   `{"weather": {"temperature_c": 20.3, "condition": "clear", "precipitation_probability": 0, "wind_speed_kmh": 9.4}}`
   (illustrative values).
4. **`clothes.advise`:** receives `city`, `activity`, `style` and `weather`.
   20.3°C counts as warm and it is dry, so it returns
   `{"top": ["polo", "dress_shirt"], "bottom": ["pants", "jeans"], "outerwear": [], "footwear": ["dress_shoes", "walking_shoes"]}`.
5. **`shelf.match`:** for each category, picks the lowest-id available item of
   the first preferred type in `SHELF_DB_PATH`. It returns the Navy polo, the
   Olive chinos, no outerwear and the Black dress shoes.
6. **Result:** the CLI prints `results["outfit"]` as JSON. `context.events`
   holds eight lifecycle events.

With `--request`, steps 2–6 are identical once the validated intent supplies
`goal=outfit` and the three inputs.

## Demonstration agents

- **Weather provider:**
  - Uses the Open-Meteo geocoding API (first match) and the hourly forecast
    with `timezone=auto`.
  - Returns the row for the city's current local hour.
  - Weather codes are mapped to `clear`, `cloudy`, `rainy`, `snowy`, `stormy`
    or `unknown`.
  - Requests have a 10-second timeout and are not retried. Failures raise
    `WeatherAPIError`; it never invents weather.
- **Clothes adviser:** deterministic rules that map the weather, activity and
  style to a ranked list of clothing types for each category. The vocabulary
  and rules are summarised in [LIMITATIONS.md](LIMITATIONS.md#clothing-rules-and-vocabulary).
- **Shelf manager:**
  - Opens an existing SQLite database read-only. The path is
    `ShelfAgent(db_path=...)` or `SHELF_DB_PATH`, and there is no default.
  - The schema is one table, `clothing_items(id, name, category,
    clothing_type, color, available)`.
  - `agentctl-shelf-init --db PATH [--seed]` creates it. `--seed` adds 19
    sample items with fixed IDs, two of them marked unavailable, using
    `INSERT OR IGNORE`.
  - A category with no matching available item is returned as `null`.
