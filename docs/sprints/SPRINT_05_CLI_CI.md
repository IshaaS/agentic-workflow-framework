# Sprint 05 — Generic CLI, GitHub Actions CI, and Submission Readiness

**Project:** Agentic Workflow Framework  
**Status:** Scope and architecture approved; implementation instructions  
**Read with:** `AGENTIC_WORKFLOW_FRAMEWORK_MASTER_PLAN.md`, Sprint 1–4 specifications/handoffs, and the **actual merged repository**.  
**Goal:** Deliver the mandatory assessment interface and a reproducible submission: an installed `agentctl` command for discovery and workflow execution, GitHub Actions running the real end-to-end integration suite, and reviewer-friendly documentation.

> **Coding assistant:** Implement **Sprint 5 only**. Inspect the existing implementation before editing. Preserve public SDK interfaces, plugin entry points, namespace packaging, manifests, planner/orchestrator behavior, and tests. Avoid adding new framework abstractions unless needed for the exact CLI/CI deliverables. Do **not** add an `agentctl plan` command, LLM, `--request`, chat, RAG, event bus, persistent memory, retries, parallel orchestration, or production infrastructure.

## 1. Existing implementation: authoritative contracts

The repository uses `framework/` as the `agentctl-core` distribution with `src/agentctl_core/`, not the early draft `agentctl/sdk` layout. Independent plugins live in:

- `agents/weather-agent/` → `agentctl_agents.weather` (`weather.forecast`: requires `city`, produces `weather`)
- `agents/clothes-agent/` → `agentctl_agents.clothes` (`clothes.advise`: requires `weather`, `activity`, produces `clothing_requirements`)
- `agents/shelf-agent/` → `agentctl_agents.shelf` (`shelf.match`: requires `clothing_requirements`, produces `outfit`)
- `workflows/outfit-workflow/` → `agentctl_workflows.outfit` (`outfit_advisor`, ordered capability steps)

Actual SDK/runtime public API from the Sprint 4 handoff:

```python
from agentctl_core import (
    AgentRegistry, WorkflowRegistry, discover_agents, discover_workflows,
    CapabilityPlanner, SequentialOrchestrator, RuntimeContext,
    PlanningError, WorkflowExecutionError,
)

agents, workflows = AgentRegistry(), WorkflowRegistry()
discover_agents(agents)
discover_workflows(workflows)

planner = CapabilityPlanner(agents)
plan = planner.plan_for_goal(
    goal="outfit",
    inputs={"city": "Dallas", "activity": "outdoor_walk", "style": "casual"},
    external_inputs={"city", "activity", "style"},
)  # WorkflowPlan(steps=[...], source="generated")

named = workflows.get_workflow("outfit_advisor")
plan = planner.plan_from_workflow(
    named, inputs={"city": "Dallas", "activity": "outdoor_walk"},
    external_inputs={"city", "activity"},
)  # WorkflowPlan(..., source="named")

context = RuntimeContext(session_id="...", workflow_id="...", inputs={...})
context = SequentialOrchestrator(agents).execute(plan, context)
# Results indexed by top-level produced field: context.results["outfit"]
```

- Both planner methods **generate/validate plans only**, not execution.
- The orchestrator executes sequentially, puts validated top-level outputs into `context.results`, records lifecycle events, and logs via `context.logger`.
- `PlanningError` subclasses distinguish missing inputs, unknown goals, missing capabilities, circular dependencies, ambiguous providers, and invalid named plans.
- `WorkflowExecutionError` exposes `reason`, `step_index`, `capability`, `agent`, `workflow_id`, etc., with original cause attached.
- All three agents are real, while weather HTTP is mocked in tests; shelf DB is initialized separately with `agentctl-shelf-init --db PATH --seed` and accessed via `SHELF_DB_PATH`.
- Sprint 4 reported **253 passing tests**, including `tests/test_workflow_integration.py`. Preserve all of them.

## 2. Sprint boundaries / definition of done

Implement these mandatory CLI operations:

```text
agentctl list agents
agentctl list workflows
agentctl run workflow outfit_advisor --input city=Dallas --input activity=outdoor_walk
agentctl run workflow --goal outfit --input city=Dallas --input activity=outdoor_walk
```

- Both execution paths use the existing `CapabilityPlanner` and the **same** `SequentialOrchestrator`.
- `agentctl list agents` displays useful manifest fields, including description, version, capability IDs, required inputs, produced outputs.
- `agentctl list workflows` displays workflow names, descriptions, and ordered steps (or step count plus accessible steps).
- A single GitHub Actions workflow installs **all five distributions** and runs all tests (including the end-to-end tests), without API keys, network weather calls, or an external DB service.
- A top-level README allows an unfamiliar reviewer to install, initialize, run, and test the project; includes assumptions/limitations and a **truthful** detailed GenAI-use disclosure.
- Add focused CLI tests; all pre-existing tests must still pass.

**Out of scope:** `agentctl plan`, interactive `chat`, LLM natural-language intent extraction, `--request`, additional workflow types, external web UI, RAG, persistent sessions, event bus, advanced tracing, deployment, containers, retries.

## 3. CLI packaging and boundaries

Add `framework/src/agentctl_core/cli.py`. Extend `framework/pyproject.toml`:

```toml
[project.scripts]
agentctl = "agentctl_core.cli:main"
```

**Check the existing `pyproject.toml` first** and merge this entry without replacing metadata/version discovery or existing configuration. Use `argparse` from the Python standard library. Installing `framework/` provides the generic CLI; agents/workflows are still installed independently. Do not create a sixth distribution.

The CLI may import only generic core contracts/runtime/discovery. It must **not** import `agentctl_agents.*` or `agentctl_workflows.*`, mention specific application agents in its logic, or hardcode names like `outfit`, `city`, or `activity` in dispatch rules.

### 3.1 Exact CLI syntax

```bash
agentctl --help
agentctl list agents
agentctl list workflows

# Run a registered named workflow:
agentctl run workflow outfit_advisor \
  --input city=Dallas \
  --input activity=outdoor_walk \
  --input style=casual

# Dynamically generate a plan from a desired output key:
agentctl run workflow --goal outfit \
  --input city=Dallas \
  --input activity=outdoor_walk \
  --input style=casual
```

- **Exactly one** of the positional workflow name and `--goal` must be provided for `run workflow`; reject neither/both using `argparse`-style usage errors (exit 2).
- `--input KEY=VALUE` is repeatable, parsed by splitting at the **first** `=`; values remain strings (current agents expect string fields). Permit an `=` in the value. Reject missing `=`, empty key, and duplicate keys rather than silently overwriting.
- Do not add outfit-specific flags (`--city`, `--activity`). No interactive prompting.
- `list` and `run` initialize registries and call existing entry-point discovery. `list agents` needs only agent discovery; `list workflows` needs workflow discovery (and optionally agent discovery if required by implementation, but no hardcoded imports).
- `run workflow` always discovers agents; for named execution it also discovers workflows; for `--goal` no named workflow is required.
- Unknown named workflow: explain it clearly and exit nonzero (recommend planning exit 3); don't crash with `AttributeError`.
- Optional `--session-id` for `run workflow` is **not necessary**; if implemented, keep it a simple identifier field, **not** session persistence or chat. Default to a freshly generated session ID per run. Create a unique workflow ID for each execution (e.g. `uuid.uuid4().hex`).

### 3.2 Deriving `external_inputs` without app-specific rules

The Sprint 4 planner requires `external_inputs` to distinguish missing user fields from missing producer capabilities. Compute an MVP convention using manifests:

```python
all_required = set()
all_produced = set()
for agent in agent_registry.list_agents():
    for cap in agent.manifest.capabilities:
        all_required.update(cap.requires)
        all_produced.update(cap.produces)

external_inputs = (all_required - all_produced) | set(user_inputs)
```

Pass this set to both planner methods. **Document its limitation:** plugin metadata doesn't explicitly tag required fields as external, so an unresolved required key without a producer is assumed to come from the user. This is acceptable for the prototype; do not modify Sprint 1 dataclasses to add schemas now.

The user can supply optional fields like `style`, which the orchestrator already propagates to agents. If a user supplies a key that would be produced by a workflow step (e.g. `weather`), preserve the Sprint 4 planner's existing output-conflict check, rather than secretly dropping or overriding that input.

### 3.3 Run flow — one thin adapter

1. Parse command and `--input` values.
2. Discover installed plugin metadata into fresh registries. Convert `PluginDiscoveryError` (and expected plugin configuration errors) into concise user-facing errors.
3. Compute `external_inputs` from capability metadata and user input keys.
4. Construct plan by **either** `plan_for_goal(goal, inputs, external_inputs)` **or** `plan_from_workflow(registered_definition, inputs, external_inputs)`.
5. Create a fresh `RuntimeContext(session_id=..., workflow_id=..., inputs=inputs)` and set up a logger.
6. Execute `SequentialOrchestrator(agents).execute(plan, context)`; no extra execution logic in the CLI.
7. Print final JSON to stdout; do not print logs to stdout.

**Result-selection rule:**

- Goal run: print `context.results[goal]`; if the generated plan is empty because the user already supplied the goal, print `context.inputs[goal]` instead.
- Named run: resolve the **last plan step** back to its registered capability's declared output field(s), and print the output of that final step. If exactly one field, print that field's value; if more than one, print an object mapping those declared output keys to values. Do not hardcode `outfit` as the final field.
- JSON serialize with `json.dumps(..., indent=2)` (or equivalent). Assume current agents return JSON-compatible values. If a result isn't serializable, show a clear execution/presentation error rather than printing a Python repr. Do not silently stringify arbitrary objects.
- Successful CLI exit = 0. Lists should print readable deterministic tables or JSON; simple text tables are sufficient, but **manifest descriptions and capability fields must be visible**.

### 3.4 Failure behavior and exit codes

Use a small CLI exception boundary; avoid catching `Exception` broadly without preserving diagnostics. Recommended codes:

| Outcome | Exit |
|---|---:|
| Success | 0 |
| Invalid syntax or `--input` | 2 |
| Planning failure / unknown named workflow | 3 |
| Workflow execution failure | 4 |
| Plugin discovery/configuration failure | 5 |

- Print human-readable errors to **stderr**. Don't dump traceback for expected user/configuration errors; the logger may include tracebacks for agent failures.
- Include `MissingInputError.input_name`, `MissingCapabilityError` details, or execution `capability`/`step_index` when useful. Use established exception `str(err)` and attributes; don't invent new framework error contracts.
- Set up Python logging **once at the CLI boundary**. Configure a `StreamHandler(sys.stderr)` (or `logging.basicConfig(stream=sys.stderr, ...)`) without duplicates, with INFO-level lifecycle details and ERROR-level failures. Preserve framework behavior that does **not** configure global handlers on import.
- Do not leak API credentials, raw API responses, or user input values through framework logs. The Weather Agent's existing log may mention resolved city; document that limitation if necessary.
- Weather live failures (timeouts, unknown city) and uninitialized/missing wardrobe DB should surface as workflow execution errors, not fake outfit output.

## 4. GitHub Actions CI

Create `.github/workflows/ci.yml`:

- Trigger on `push` to `main` and `pull_request` targeting `main`; add `workflow_dispatch` if convenient.
- Use `actions/checkout` and `actions/setup-python` with pinned **major action versions** appropriate to the environment (prefer current maintained releases, avoid untrusted third-party actions).
- Python matrix: **3.11 and 3.12** (both already tested locally per handoffs; 3.10 optional if time allows).
- Install from the repository root, respecting the monorepo layout:

```bash
python -m pip install --upgrade pip
python -m pip install -e './framework[dev]' \
  -e ./agents/weather-agent \
  -e ./agents/clothes-agent \
  -e ./agents/shelf-agent \
  -e ./workflows/outfit-workflow
python -m pytest -q
```

- Explicitly exercise `tests/test_workflow_integration.py` as part of the run; running the whole pytest suite includes it. You may have a separate named integration-test step for auditability, even if it repeats tests.
- Don't initialize a real repository-owned wardrobe database in CI. Existing agent/integration tests use temporary SQLite fixtures.
- All weather traffic and error cases in tests remain mocked. **No live weather requests in CI** and no secrets required.
- Confirm a CI run is green **on GitHub**, not just that the YAML parses. If access is unavailable, report that honestly instead of asserting a green workflow.
- Do not weaken existing tests, alter them to depend on network, or silently skip plugin discovery checks.

## 5. CLI and CI tests to add

Create `tests/test_cli.py` (and optionally an additional focused CI/config smoke test only if useful). Tests should include:

1. `agentctl --help`/parser help exposes the commands.
2. `list agents` uses real installed plugin discovery and reports all three manifest names, versions, descriptions/capabilities, requirements and outputs.
3. `list workflows` discovers `outfit_advisor` via the installed workflow entry point.
4. `run workflow --goal outfit --input ...` calls the real planner and orchestrator; verifies final JSON and the outcome contains seeded SQLite items. Replace live weather HTTP with the existing fake transport pattern and set `SHELF_DB_PATH` to a temporary initialized database.
5. Named `run workflow outfit_advisor --input ...` executes via the same engine and produces JSON.
6. Missing `city` yields exit code 3, useful stderr, and no agent execution.
7. Unknown goal or unknown workflow yields exit code 3; malformed `--input`, duplicate input keys and name-plus-goal yield 2.
8. Weather failure / nonexistent wardrobe DB yields exit code 4, identifies failed capability, and doesn't print fake success JSON.
9. Empty goal-generated plan (requested output supplied in inputs) behaves consistently; user-supplied output conflicts are not silently overwritten.
10. Logs go to stderr; stdout contains only parseable JSON on successful runs. CLI doesn't configure handlers merely on importing the core package.
11. CLI behavior remains generic: tests with synthetic registry/plugins may verify no outfit-specific assumptions in result selection and input parsing.

**Testing practicality:** For tests needing fake HTTP within the same process, call `agentctl_core.cli.main(argv)` with `capsys` / `monkeypatch` rather than launching a subprocess that cannot share patches. Separately add a subprocess smoke test for the installed `agentctl` executable (e.g. `list agents` or `--help`). Preserve the actual entry-point discovery in at least one CLI path, and preserve the full Sprint 4 integration test.

Don't use an actual network weather call for any pytest invocation. Test timeouts/errors by fakes. Keep tests deterministic on clean installs.

## 6. README and reviewer experience

Add root `README.md` and keep existing package READMEs. Include:

1. **What this is:** a generic Agentic Workflow Framework prototype; its core is independent of example agent and workflow plugins.
2. **Architecture:** short diagram (Markdown/Mermaid or ASCII) showing CLI → discovery/registries → planner → orchestrator → independent agents; workflow plugins provide named plans.
3. **Monorepo/package layout:** `framework`, three agent distributions, one workflow distribution, tests.
4. **Prerequisites:** Python >=3.10 (locally verified on 3.11/3.12), pip, internet only for live weather.
5. **Install commands:** install all five distributions from repo root (same commands as CI).
6. **Database setup:** `agentctl-shelf-init --db ./wardrobe.db --seed`, `SHELF_DB_PATH` environment variable (with examples for common shells if desired); clarify DB won't be created automatically on workflow run.
7. **Usage:** `agentctl list agents`, `agentctl list workflows`, named run and `--goal` run; show `--input KEY=VALUE`; note `outfit` is an output key, not the registered workflow name.
8. **Representative output:** label as illustrative unless copied from an actual local run.
9. **Routing rationale:** generated plans use manifests and backwards dependency resolution; predefined workflows are independently packaged; no LLM required for the MVP.
10. **Testing:** `python -m pytest -q`, mocked weather in automated tests, integration test path, GitHub Actions workflow.
11. **Observability:** context-based INFO/ERROR logs, event records, stderr vs stdout, fail-fast semantics, and exit codes.
12. **Assumptions/limitations:** one provider per capability; explicit string CLI inputs; one goal/output key; dependency planner is deterministic; optional `style`; no arbitrary natural-language intent parser, no LLM, no persistent session memory, no advanced workflow features; plugin import executes trusted third-party code; first geocoding result selection; no retries; app sample wardrobe.
13. **How to write/install a new plugin:** concise examples of `BaseAgent`, `AgentManifest`, `Capability`, namespace package, `[project.entry-points."agentctl.agents"]`, and a workflow entry point; no changes needed in core.
14. **GenAI assistance disclosure:** a dedicated subsection stating the actual tools used, their configuration/setup in meaningful detail, what tasks they helped with (architecture/spec authoring, code generation, testing, review), what you personally reviewed/ran, and known limitations. **Do not invent tool names, model versions, settings, hours, verification steps, or claims of complete manual authorship.** Use clearly marked placeholders for unknown facts that the user must fill in before submission.
15. **Quick start** tested from a new clone or clean virtual environment; note the root is a monorepo and `pip install -e .` from repo root does not work unless a root package was added (which is not required).

No need for elaborate visuals or a hosted demo. A clean, credible reviewer experience is more important than extra infrastructure.

## 7. Suggested implementation order

1. Inspect merged repo; confirm public contracts and current test run.
2. Implement CLI packaging, parsing, discovery, input collection, routing, execution, output formatting, and errors.
3. Add CLI tests with fake external weather, temporary SQLite, and installed entry points.
4. Add GitHub Actions CI; ensure full test coverage and a genuinely passing GitHub run.
5. Write root README and accurate AI use disclosure placeholders.
6. Verify local clean-install commands and end-to-end manual CLI run (live weather only as a **manual** optional check), then commit/push/PR.

Keep the change set focused. Do not restructure packages or SDK types to add conveniences. If a small inconsistency from the Sprint 4 implementation is discovered, document and fix it minimally with tests.

## 8. Acceptance checklist

- [ ] Existing `agentctl-core` distribution installs a working `agentctl` console command.
- [ ] `agentctl list agents` discovers all three independent agent distributions and shows manifest metadata.
- [ ] `agentctl list workflows` discovers independently installed `outfit_advisor`.
- [ ] `agentctl run workflow outfit_advisor ...` plans and executes using the generic framework.
- [ ] `agentctl run workflow --goal outfit ...` **generates** a plan from actual installed capability manifests and executes it; no hardcoded sequence.
- [ ] Both paths return a correct JSON outfit using available seeded SQLite inventory.
- [ ] Planning failures are actionable; execution failures identify failed steps; predictable exit codes.
- [ ] INFO/ERROR logging appears on stderr, JSON results only on stdout.
- [ ] CLI handles missing inputs, unknown goals/names, malformed arguments, and missing DB sensibly.
- [ ] New CLI tests pass with network blocked; all prior Sprint 1–4 tests still pass.
- [ ] `.github/workflows/ci.yml` installs every distribution and executes pytest including the full real-plugin integration path.
- [ ] CI reports a successful run on GitHub (or clearly disclose if not independently verified).
- [ ] Root README includes a reproducible quick start, architecture, limitations, testing, and detailed truthful AI-use disclosure.
- [ ] No LLM, `agentctl plan`, chat, event bus, RAG, persistent memory, or other stretch feature slipped into scope.

## 9. Required Sprint 5 handoff format

After implementing and running tests, report:

1. Files added/changed, with purpose; include exact `agentctl` entry point.
2. CLI command syntax and a sample of each actual command's output (scrub credentials and other sensitive values).
3. How `external_inputs` is derived and how both run paths reach the same orchestrator.
4. CLI error codes and formatting; how stdout/stderr/logging are separated.
5. CLI tests and complete pytest test counts; record Python versions tested.
6. CI workflow triggers, matrix, install steps, integration test invocation; **link or run ID of an actual green GitHub run if available**.
7. Root README/quick-start summary and the **actual** AI setup/disclosure status; call out placeholders requiring completion.
8. Deviations from spec, known issues, limitations, and unresolved deliverables.
9. Branch name, commits, push and merge/PR status.

**Stop after Sprint 5.** Do not implement post-MVP LLM intent extraction unless explicitly planned later.
