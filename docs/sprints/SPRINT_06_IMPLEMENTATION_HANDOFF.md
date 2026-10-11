# Sprint 06 Implementation Handoff: Generic Natural-Language Intent

**Scope:** Sprint 6 only (`SPRINT_06_GENERIC_NATURAL_LANGUAGE_INTENT.md`). Sprint 7 clothing work has not been started.
**Status:** Implemented. Offline tests and CI are green. **A live Anthropic call has not been tested**: no credentials were available.

## 1. Branch, commits, PR and CI

| Item | Value |
|---|---|
| Branch | `feat/natural-language-intent`, branched from `main` at `cd13296` (after PR #4 was merged) |
| Implementation commit | `93b65d02bf02264817bb21c1c8bf4fb3b0ddcd0b`: "Add Sprint 6 generic natural-language intent resolution" |
| Handoff commit | The commit that adds this file, on the same branch |
| PR | [#5](https://github.com/IshaaS/agentic-workflow-framework/pull/5): open, **not merged** |
| CI on `93b65d0` | [run 38154832085](https://github.com/IshaaS/agentic-workflow-framework/actions/runs/38154832085): **success** on Python 3.10, 3.11 and 3.12. Each job: `anthropic 1.13.0` installed, 88 integration/CLI/intent tests passed, **421 passed with 0 skipped** in the full suite |

## 2. Files changed

### Core (`framework/`)

| File | Change |
|---|---|
| `src/agentctl_core/sdk.py` | Adds the `InputSpec` and `GoalSpec` dataclasses, and three **defaulted** fields appended to `Capability` (see below). |
| `src/agentctl_core/errors.py` | Adds `IntentCatalogError`, `IntentValidationError` (a subclass of `PlanningError`), `IntentProviderError`, and `IntentProviderConfigError` (a subclass of `IntentProviderError`). |
| `src/agentctl_core/intent.py` | **New.** `ResolvedIntent(goal, parameters)` and the `IntentProvider` protocol (`resolve(request, catalog) -> ResolvedIntent`). |
| `src/agentctl_core/intent_catalog.py` | **New.** `build_intent_catalog(registry) -> IntentCatalog`, plus `GoalEntry` and `ParameterSpec`, and checks on plugin metadata. |
| `src/agentctl_core/intent_validation.py` | **New.** `validate_intent(intent, catalog, explicit_inputs) -> ValidatedIntent(goal, inputs)`. |
| `src/agentctl_core/providers/__init__.py`, `providers/anthropic.py` | **New.** `AnthropicIntentProvider`, the optional adapter. |
| `src/agentctl_core/cli.py` | Adds the `--request TEXT` option, `run_request()`, and an optional `agents` argument on `run_workflow()` so request mode reuses the `--goal` path. `main(argv, intent_provider=None)` gains a keyword argument that lets tests inject a provider. Updated docstring for the exit codes. |
| `src/agentctl_core/__init__.py` | Re-exports the new public types (35 names in `__all__`). |
| `pyproject.toml` | Adds the optional extra `llm = ["anthropic>=1,<2"]`. **No new runtime dependency.** |

**Unchanged** (`git diff main` is empty): `planner.py`, `orchestrator.py`, `registry.py`, `discovery.py`, `context.py`.

### Plugins (metadata only)

The `run()` methods, the clothing rules and the SQLite logic are unchanged.

| Plugin | Metadata added |
|---|---|
| `agents/weather-agent/.../agent.py` | `InputSpec("city", ...)` on `weather.forecast`. |
| `agents/clothes-agent/.../agent.py` | `optional_inputs=["style"]`, plus an `InputSpec` for `activity` (`allowed_values=list(ACTIVITIES)`) and one for `style` (`allowed_values=list(STYLES)`). Both lists come from the existing rule constants, so they can't drift. |
| `agents/shelf-agent/.../agent.py` | `GoalSpec("outfit", ...)` on `shelf.match`. |

### Tests, CI and docs

| File | Change |
|---|---|
| `tests/test_intent_catalog.py`, `test_intent_validation.py`, `test_anthropic_intent.py`, `test_cli_request.py`, `test_intent_integration.py` | **New.** 127 tests. |
| `tests/conftest.py` | Adds `FakeIntentProvider` and the `fake_intent` fixture. The network-blocking fixture is unchanged and still autouse. |
| `tests/test_sdk.py`, `tests/test_discovery.py` | **Two assertions updated**, because adding fields changes `dataclasses.asdict(...)` and whole-object `Capability` equality. The test that inspects a manifest with `asdict` now expects the three new empty fields. The discovery test now compares `(name, requires, produces)`. No behaviour assertion was weakened. |
| `.github/workflows/ci.yml` | Installs `'./framework[dev,llm]'`, checks that `anthropic` imports (no key is used), and runs `test_cli_request.py` and `test_intent_integration.py` in the named integration step. Triggers and matrix are unchanged. |
| `README.md` | Adds a "Natural-language requests" section; updates the run modes, the "How plans are chosen" wording, the exit-code table, test counts and limitations. The AI disclosure is unchanged (see section 9). |

### Public SDK additions

```python
@dataclass
class InputSpec:
    name: str
    description: str
    value_type: str = "string"            # only "string" is supported in Sprint 6
    allowed_values: list[str] | None = None

@dataclass
class GoalSpec:
    output_key: str                       # must be one of the capability's produces keys
    description: str

@dataclass
class Capability:
    name: str
    requires: list[str]
    produces: list[str]
    optional_inputs: list[str] = field(default_factory=list)   # new
    input_specs: list[InputSpec] = field(default_factory=list) # new
    goals: list[GoalSpec] = field(default_factory=list)        # new
```

Construction with positional or keyword arguments works exactly as before. The planner still reads only `name`, `requires` and `produces`.

### CLI syntax

```text
agentctl run workflow NAME            [--input KEY=VALUE ...]   # unchanged
agentctl run workflow --goal KEY      [--input KEY=VALUE ...]   # unchanged
agentctl run workflow --request TEXT  [--input KEY=VALUE ...]   # new
```

**Rules:**
- **One mode only:** exactly one of `NAME`, `--goal` or `--request` is allowed; otherwise exit 2 with the message `give exactly one of a workflow NAME or --goal or --request`.
- **Empty request:** a blank or whitespace-only `--request` exits 2.
- **Duplicate inputs:** repeating an `--input` key is still rejected (exit 2).
- **No new commands:** there is no `agentctl plan` and no `agentctl chat`.

## 3. How goals and parameters are found

`build_intent_catalog(registry)` reads only registry metadata. It never imports an application package.

1. **Metadata checks for each capability.** Each of these raises `IntentCatalogError`:
   - an `optional_inputs` entry is duplicated, or also appears in `requires`;
   - an `InputSpec` names a key that is in neither `requires` nor `optional_inputs`, is declared twice, has a blank description, uses a `value_type` other than `string`, or has malformed `allowed_values` (empty, non-strings, or duplicates);
   - a `GoalSpec.output_key` is not in `produces`, or its description is blank;
   - the same goal is advertised by two capabilities.
2. **Goals.** Only outputs advertised with a `GoalSpec` become goals. Other producible outputs, such as `clothing_requirements`, are still reachable with `--goal` but are not offered to the model.
3. **Each goal's chain.** The **unchanged** `CapabilityPlanner.plan_for_goal()` is called with *placeholder* inputs (value `None`) for every key that some capability requires but none produces. These placeholders are used only to derive the chain; they never reach execution. Planner errors such as ambiguous providers or cycles become `IntentCatalogError`, and the planning algorithm is not duplicated.
4. **Whether each parameter is required:**
   - **Required:** a key in the `requires` of a chain step that no chain step produces.
   - **Optional:** a key in the `optional_inputs` of a chain step.
   - Inputs of capabilities **outside** the chain are never included; a test covers this with an unrelated `text.translate` agent.
5. **Descriptions.**
   - Every parameter of an advertised goal must have an `InputSpec` somewhere in the chain. Otherwise the catalog fails rather than guessing; this also covers a missing provider.
   - If two chain steps describe the same input with different types or allowed values, the catalog fails.

Catalog derived from the real installed plugins (from `IntentCatalog.to_dict()`):

```text
outfit: "Choose an outfit from the user's own wardrobe for the current weather in a city and a planned activity"
  steps: weather.forecast -> clothes.advise -> shelf.match
  city      required  string
  activity  required  string  allowed: outdoor_walk, theatre, casual
  style     optional  string  allowed: casual, formal
```

### Validation (`validate_intent`)

Checks run in this order and are domain-neutral. Any failure raises `IntentValidationError` (exit 3), and no agent runs.

1. **Shape:**
   - the intent is a `ResolvedIntent`, or a mapping with only `goal` and `parameters`;
   - `goal` is a non-empty string;
   - `parameters` is a mapping with string keys.
2. **Known goal:** the goal must be in the *advertised* catalog. For example: `unsupported natural-language goal 'flight_booking' (available: outfit)`.
3. **Merging `--input`:** explicit `--input` values are merged **over** the extracted parameters, so the user's value wins. Each error message names its source: `(from request)` or `(from --input)`.
4. **Known parameters:** every key must be declared for the goal's chain. Unknown keys are rejected, never silently dropped. Example: `unknown parameter 'fashion_score' for selected goal 'outfit'`.
5. **Type:** values must be `str`. Numbers, booleans, `None`, lists and dicts are rejected, not converted.
6. **Non-empty:** values must be non-empty after trimming. Values are passed on unmodified.
7. **Allowed values:** these must match exactly, with no case-folding, trimming or semantic remapping. Example: `parameter 'activity' must be one of: outdoor_walk, theatre, casual; got 'office'`.
8. **Required inputs:** all are listed if missing. Example: `missing required input 'city' for goal 'outfit'; supply --input city=VALUE`.
9. **Plan check:** the CLI then calls the unchanged `plan_for_goal(goal, inputs, external_inputs(...))`, so ambiguity, cycles, missing capabilities and output conflicts are still reported by the planner (exit 3).

## 4. Anthropic adapter

**SDK:**
- `anthropic` **1.13.0** (the newest on PyPI at implementation time), required via `anthropic>=1,<2` in the `[llm]` extra only.
- I inspected the installed SDK before writing the adapter. It provides `output_config`, `beta.messages.create(fallbacks=..., betas=...)`, and the typed error classes used below.

**Lazy loading:**
- `providers/anthropic.py` doesn't import `anthropic` at module level.
- `from_environment()` checks the key, then uses `importlib.util.find_spec("anthropic")`, which doesn't import anything.
- The SDK is imported only inside `resolve()`.
- A subprocess test confirms that importing `agentctl_core`, `agentctl_core.cli` and the provider module leaves `anthropic` out of `sys.modules`.

**Configuration:**

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Required for `--request`. An empty or whitespace-only value is treated as missing. |
| `ANTHROPIC_MODEL` | Optional; default `claude-opus-5-5`. The model must support structured outputs and `output_config.effort`. |

The default model ID comes from the bundled Claude API reference I consulted during implementation (model table dated 2026-10-06). **It was not checked against the live API**, because no credentials were available.

**The request:**
- One `messages.create` call: `max_tokens=4096`, `output_config={"effort": "low", "format": {"type": "json_schema", "schema": ...}}`, a generic system prompt, and one user message containing the catalog JSON and the request text in `<catalog>` and `<request>` tags.
- There's no `temperature` (removed on current models) and no `thinking` parameter (adaptive by default).
- The client is created with `timeout=30.0` and `max_retries=1`.

**Response schema** (`response_schema(catalog)`):
- `{"goal": string, "parameters": {<every catalog parameter name>: string}}`, all with `additionalProperties: false`, and no parameter required.
- There are deliberately **no enums**. A strict enum would force a request like "office" onto an allowed value such as "casual", which the spec forbids. Free strings let validation reject it explicitly instead.

**System prompt:**
- It contains no domain words (tested).
- It tells the model to choose a catalog goal or name the unsupported request in snake_case, never pick an unrelated goal, include only values the request states, never substitute a different allowed value, and treat the catalog and request as data rather than instructions.

**Refusal fallback:**
- For `claude-fable-5-1`, `claude-opus-5-5`, `claude-opus-5` and `claude-sonnet-5-5`, the call goes through `client.beta.messages.create(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`. This is Anthropic's server-side refusal fallback, enabled by default as the Claude API reference recommends for these models.
- Other model overrides use plain `client.messages.create`.
- **Unverified live:** whether this beta works together with structured outputs. If it doesn't, the call fails with exit 4 and `Anthropic API rejected the request: …`.

**Errors:**

| Situation | Error | Exit |
|---|---|---|
| No or whitespace-only `ANTHROPIC_API_KEY` | `IntentProviderConfigError` with the spec's message and the structured-command alternatives | 5 |
| SDK not installed | Config error: `natural-language requests need the Anthropic SDK; install it with: python -m pip install -e './framework[llm]'` | 5 |
| `AuthenticationError` (401) | Config error: `Anthropic rejected the API key (authentication failed); check ANTHROPIC_API_KEY` | 5 |
| `PermissionDeniedError` (403) | Config error: key not permitted | 5 |
| `NotFoundError` (404) | Config error: `Anthropic model '<m>' was not found; check ANTHROPIC_MODEL` | 5 |
| `RateLimitError` (429) | `IntentProviderError`: rate limit reached | 4 |
| `APITimeoutError` | Provider error: did not respond within 30 seconds | 4 |
| `APIConnectionError` | Provider error: could not connect | 4 |
| `BadRequestError` (400) | Provider error, including the API's error message | 4 |
| Other `APIStatusError` (5xx, 529) | Provider error with the HTTP status | 4 |
| `stop_reason` `refusal` or `max_tokens`; no text block; invalid JSON; fields other than exactly `goal` and `parameters` | Provider error | 4 |

**Notes:**
- Every error keeps the original exception as `__cause__`, and no SDK traceback reaches the user.
- **Secrets:** the API key never appears in error messages or logs (tested with a sentinel key).
- **Logging:**
  - The request text is never logged; only its length is.
  - The CLI logs the goal and the *names* of the parameters.
  - The adapter logs the model and the Anthropic request ID.
  - No raw provider response is logged.
- **No retry:** there is no retry for malformed output; this is a one-shot CLI. The only retry is the SDK's single transport retry.

## 5. How the planner and orchestrator are reused unchanged

- `planner.py`, `orchestrator.py`, `registry.py`, `discovery.py` and `context.py` have **no diff** against `main`.
- `run_request()` ends with `run_workflow(None, validated.goal, validated.inputs, agents)`. That is the **same function** `--goal` uses: `CapabilityPlanner.plan_for_goal` with the same `external_inputs()` rule, then a fresh `RuntimeContext` with new IDs, `SequentialOrchestrator.execute`, the same `select_result`, and the same JSON printing.
- The model's output is only a `goal` string and a `parameters` dict. It has no way to supply steps, agent names or execution order.
- Tests prove this: the integration tests check the orchestrator's `source generated, steps: weather.forecast, clothes.advise, shelf.match` log line, and the cross-domain test plans `document.extract → document.summarize` with the real planner.

## 6. Command examples

Sanitized: timestamps were removed and 32-hex workflow and session IDs replaced with `<id>`.

**No key, from the installed `agentctl`, run manually:**

```console
$ agentctl run workflow --request "Suggest an outfit for a casual theatre visit in Dallas"
INFO agentctl.cli: Request mode: resolving a natural-language request (54 characters)
agentctl: error: natural-language requests are unavailable: ANTHROPIC_API_KEY is not configured.
Structured commands still work without an Anthropic key:
  agentctl run workflow --goal OUTPUT_KEY --input KEY=VALUE
  agentctl run workflow WORKFLOW_NAME --input KEY=VALUE
Set ANTHROPIC_API_KEY to enable --request.
$ echo $?
5
```

**Structured command with no key**, run manually against the live Open-Meteo API and a seeded scratch wardrobe:

```console
$ agentctl run workflow --goal outfit --input city=Dallas --input activity=theatre
→ exit 0; top "Navy polo", bottom "Olive chinos", outerwear null, footwear "Black dress shoes"
  (stderr: Weather for Dallas, United States (America/Chicago): clear, 27.8°C)
```

**Request mode with a scripted intent provider in place of Claude.** The provider returned `{"goal": "outfit", "parameters": {"city": "Dallas", "activity": "theatre", "style": "casual"}}`, and everything after it ran for real, including the live weather API:

```text
INFO agentctl.cli: Request mode: resolving a natural-language request (54 characters)
INFO agentctl.cli: Natural-language goals available: outfit
INFO agentctl.cli: Intent validated: goal outfit with parameters activity, city, style
INFO agentctl: Workflow <id> started (session <id>, source generated, steps: weather.forecast, clothes.advise, shelf.match)
INFO agentctl: Weather for Dallas, United States (America/Chicago): clear, 27.8°C
INFO agentctl: Selected items: {'top': 2, 'bottom': 10, 'footwear': 19}
INFO agentctl: Workflow <id> completed in 1425.4 ms (session <id>)
```

```json
{
  "top": {"id": 2, "name": "Navy polo", "clothing_type": "polo", "color": "navy"},
  "bottom": {"id": 10, "name": "Olive chinos", "clothing_type": "pants", "color": "olive"},
  "outerwear": null,
  "footwear": {"id": 19, "name": "Black dress shoes", "clothing_type": "dress_shoes", "color": "black"}
}
```

**Unsupported `office` activity** (scripted intent `activity=office`). This exits 3 with no workflow started:

```text
agentctl: error: parameter 'activity' must be one of: outdoor_walk, theatre, casual; got 'office' (from request)
```

**Explicit `--input` overriding the extracted values.** The scripted intent had `activity=theatre, style=casual` and no city; the command added `--input city=Dallas --input style=formal`. This exits 0, and `style=formal` was used: dress shirt (5), chinos (10), blazer (15) and dress shoes (19).

## 7. Tests

| File | Tests | Covers |
|---|---:|---|
| Sprint 1–5 files | 294 | All still pass (two assertions adapted; see section 2) |
| `test_intent_catalog.py` | 20 | Goals found dynamically; unadvertised outputs hidden; parameters from the chain only; unrelated agents add nothing; optional stays optional; installed-plugin catalog (no `office`); 10 invalid-metadata cases; conflicting specs; ambiguous provider; cycle; plugins without metadata still plan |
| `test_intent_validation.py` | 36 | Valid intents; 8 malformed shapes; unknown goal; unadvertised output; unknown and cross-goal keys; 6 wrong types (no coercion); empty strings; exact allowed values; missing required (single and multiple); unrelated inputs never required; `--input` precedence, filling gaps, fixing, and being validated itself; no mutation |
| `test_anthropic_intent.py` | 30 | Missing or whitespace key; environment and model config; missing SDK; no SDK import from core; request parameters (model, effort, schema, system prompt, user message, fallback path vs plain path); lazy client with timeout and retries; schema without enums; generic prompt; 7 malformed answers; 9 SDK errors translated with cause kept and no secret in messages or logs; no request text logged |
| `test_cli_request.py` | 36 | Help; one-mode rule; blank request; duplicate inputs; missing key (exit 5, 3 variants, no agent ran); missing SDK; provider config error; structured commands without a key; successful request through the real planner and orchestrator; override and gap-filling `--input`; request text not logged; 7 rejected intents (exit 3, no agent ran); invalid or unknown explicit input; provider failure (exit 4); agent failure (exit 4); no advertised goals; log handlers removed; installed `agentctl` without a key exits 5; structured commands with the SDK blocked |
| `test_intent_integration.py` | 5 | **Cross-domain proof** (below); the same through `cli.main`; an invalid document intent runs no agents; **outfit request through the real Anthropic adapter with a mocked SDK client**, real plugins, fake weather and a seeded SQLite database; `office` rejected with no agent run |
| **Total** | **421** | **421 passed** |

**Where the suite was run:**

| Environment | Result |
|---|---|
| Local, Python 3.11.5 with `anthropic` 1.13.0 | 421 passed |
| Clean Python 3.12 environment **without** the SDK (regular install of all five distributions, tests run from outside the repo) | 397 passed, 24 skipped, all skips being SDK-dependent adapter tests. In that environment `--request` with a key exits 5 with the install hint, and structured commands work. |
| CI: Python 3.10, 3.11 and 3.12 with the `[llm]` extra | 421 passed, 0 skipped each ([run 38154832085](https://github.com/IshaaS/agentic-workflow-framework/actions/runs/38154832085)) |

**Cross-domain proof** (`test_document_goal_end_to_end_with_generic_core`):
- **Setup:** fake `document.extract` (`document_path` → `extracted_text`) and `document.summarize` (`extracted_text` → `summary`, advertised with a `GoalSpec`). A fake provider returns `{"goal": "summary", "parameters": {"document_path": "report.pdf"}}`.
- **Checks:**
  - the catalog has exactly the `summary` goal, with `document_path` required;
  - validation passes;
  - the real planner gives `document.extract → document.summarize` (source `generated`);
  - the real orchestrator returns `"summary of [text of report.pdf]"`, with each agent run once.
- No clothing code is involved, and the same path also passes through `cli.main`.

**Offline mocking:**
- The network-blocking autouse fixture stays enabled, so all sockets and DNS fail in tests.
- Weather goes through the existing `fake_weather_http` transport fake.
- The language model is either `FakeIntentProvider` or a fake SDK client handed to `AnthropicIntentProvider` (`client=`).
- SDK error tests use real `anthropic` exception classes built with `httpx2` request and response objects.
- No API key or paid call is used anywhere.

**Mutation checks.** I deliberately broke the code five ways; each was caught, and the restored code passes 421:

| Deliberate break | Failing tests |
|---|---:|
| Skip the allowed-values check | 8 |
| Let the model's value win over `--input` | 4 |
| Silently drop unknown parameters | 5 |
| Make the catalog include every agent's inputs | 12 |
| Mark optional inputs as required | 10 |

**Manual checks:**

| Check | Result |
|---|---|
| `--request` without a key (exit 5) | **Tested** |
| Structured `--goal` run without a key, live Open-Meteo | **Tested** |
| Real Anthropic call with a key | **Not tested**: no `ANTHROPIC_API_KEY`, no auth token, and no `ant` CLI were available on this machine |

**Live checks still needed before relying on `--request`:**
1. The default model ID responds.
2. Structured outputs work together with the server-side fallback beta.
3. The model omits unstated values and reports "office" as `office` rather than mapping it to an allowed value.

## 8. Limitations, deviations and items deferred to Sprint 7

**Deviations and choices:**
- **Validation happens in the catalog, not the dataclass.** Malformed metadata is rejected when the catalog is built (exit 5 in request mode), not when a `Capability` is constructed. So a plugin with broken natural-language metadata still works for `--goal` and named workflows.
- **No advertised goals gives exit 3**, with a message pointing to `--goal` and `NAME`.
- **Unknown or produced keys passed with `--input` are rejected in request mode** (e.g. `--input weather=sunny`). In `--goal` mode, unknown keys are still passed through, as before.
- **Optional parameters must also be non-empty strings.** The model is told to omit unknown values rather than send `""`.
- **Two Sprint 1/2 test assertions were adapted** for the additive fields (section 2). This was unavoidable: `asdict` and dataclass equality include the new fields.
- **Correction to the Sprint 5 handoff:** it reported "251 earlier tests plus 43 CLI tests". The correct split was 253 earlier tests plus 41 CLI tests; the 294 total was right.

**Known limitations:**
- **Live behaviour untested:** the live provider behaviour and the default model are unverified (section 7).
- **One-shot, single goal:** one goal per request; no chat, no follow-up questions and no retry for malformed output.
- **String-only parameters:** `value_type` supports only `"string"`.
- **Unrecognised requests:** a request that matches no goal is reported with whatever snake_case name the model chooses, e.g. `flight_booking`.
- **Cost and latency:** `--request` makes one paid Anthropic call per run, with a 30-second timeout and one SDK retry.
- **Carried over from earlier sprints:** the weather agent logs the resolved city name at INFO, and only the first geocoding match is used.

**Deferred to Sprint 7** (not implemented): `office`, `walk`, and other activity aliases; new styles such as `business_casual`; and any change to the clothes adviser rules. Requests for them are rejected with exit 3 today, and tests cover that.

## 9. AI-assisted development disclosure: updates needed

I didn't edit the README disclosure in this sprint; the final polish is scheduled for later. These facts should be added. They're recorded from this session, with no reviewer actions invented:

- **Tool and model:** Sprint 6 was implemented by Claude Code (VS Code extension) using Claude Opus 5.5 (`claude-opus-5-5`), with auto permission mode on, working from `SPRINT_06_GENERIC_NATURAL_LANGUAGE_INTENT.md` and a short prompt from the author.
- **Reference consulted:** before writing the adapter, Claude Code loaded the bundled Claude API reference skill (`claude-api`) for current SDK usage, the model ID, structured outputs, error classes and refusal fallbacks. It also inspected the installed `anthropic` 1.13.0 SDK directly.
- **What Claude Code produced:**
  - all Sprint 6 code, tests, CI changes, README changes and this handoff;
  - test runs: local, clean environment without the SDK, and mutation checks;
  - the manual checks described in section 7;
  - the push, PR #5 and the CI check.
- **Not done:** no live Anthropic request was made.
- **Facts to update:**
  - The disclosure says PRs "#1–#3 at the time of writing". PR #4 has since been merged, and #5 is open.
  - It should say that the optional `--request` feature itself calls an LLM at run time when the user configures a key.
- **Still `TODO` for the author:** who wrote the specs and with which tools; what you reviewed and ran yourself; whether you ran `--request` live with your own key, and the result; and time spent.
