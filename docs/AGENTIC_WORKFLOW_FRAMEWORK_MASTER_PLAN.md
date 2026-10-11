# Agentic Workflow Framework — Master Project Specification

**Status:** Proposed architecture and scope for review. No implementation is assumed complete.  
**Purpose:** Source-of-truth context for an AI-assisted coding agent and for subsequent sprint plans.  
**Target:** Small, demonstrably working Python prototype within an approximately four-hour assessment window.  
**Change policy:** Record decisions/changes here before asking the coding assistant to make broad architectural changes. Sprint-specific implementation prompts will be written separately, one sprint at a time.

---

## 1. Assessment brief and success criteria

Build a small Python **Agentic Workflow Framework** that supports independently developed agents, workflow execution, a CLI, and a full-path integration test in GitHub Actions.

### Mandatory functionality

1. Python SDK, CLI, agent metadata/manifest, runtime context (session, events, execution memory; optional RAG).
2. Independent agents distributed as **separate Python namespace packages**, dynamically discovered through a plugin mechanism.
3. Simplified observability using logging.
4. Three working agent implementations:
   - **Weather provider** calls a real external weather API for forecast data.
   - **Clothes adviser** uses weather, user parameters/preferences, and activity to recommend appropriate clothing types.
   - **Personal shelf manager** queries a **database** of clothes and returns matching owned items.
5. Generic **sequential workflow runner** that executes a plan step-by-step, passing outputs appropriately.
6. A usable entry point via `agentctl run workflow` (interactive chat is optional).
7. CLI supports: list agents (including manifests), list workflows, run workflow by name **or** from a router-generated plan.
8. One end-to-end integration test in CI: **discover plugins → router produces plan involving all three agents → orchestrator executes → useful outputs are produced**.
9. GitHub Actions CI runs the test.
10. Submission explains assumptions and **discloses AI-assisted coding setup in detail**. Implementer must be able to explain the final result.

### Explicit stretch goals — NOT part of initial MVP

- RAG capability abstraction (interface or stub), perhaps used by shelf agent.
- Session-scoped memory retained across multiple calls with the same `session_id`.
- Multiplexed typed event bus / event-driven in-process communication.
- Interactive `agentctl chat --session-id`.

**Distinction:** MVP still includes `session_id`, per-execution context, basic event records, and an in-execution `memory` dictionary. A cross-invocation session store or pub/sub bus remains stretch.

### Definition of done

From a clean clone, a reviewer can install the framework and independent plugins, list agents/workflows, run an outfit recommendation that calls a real weather API and reads SQLite, and run CI/tests that prove the complete discovery-to-output path (with mocked weather HTTP for reproducibility).

---

## 2. Architectural principles and locked decisions

1. **Generic framework:** No weather, clothing, or wardrobe-specific logic or imports in SDK, runtime, planner, orchestrator, or general CLI.
2. **Framework vs. independent plugins:** Generic contracts, discovery, routing/planning, execution, context, logging, and CLI are in the core framework distribution; the three agents are separate installable distributions. The named outfit workflow definition lives **outside** core, ideally in a fourth independent workflow distribution.
3. **One plan representation:** Both named workflow execution and generated plans resolve into the same generic `WorkflowPlan` consumed by the same executor.
4. **Real capability-based planning:** Router/planner consults discovered agent manifests (required inputs and provided outputs), resolves dependencies, and returns ordered steps. It must not simply return an unconditional hardcoded three-agent list.
5. **Deterministic MVP, no LLM required:** Use explicit goal/structured parameters and small dependency-resolution algorithm. Natural-language intent classification is not mandatory. This is a reasonable interpretation, not a guaranteed evaluator preference.
6. **Sequential/deterministic:** No parallel scheduler, durable queue, graph engine, or distributed execution.
7. **Python standard library first:** `abc`, `dataclasses`, `argparse`, `importlib.metadata`, `logging`, `sqlite3` where practical; use a small HTTP library (`httpx` or `requests`) and `pytest`. Avoid adding LangChain/LangGraph unless a proven need emerges.
8. **Plugin discovery via distribution entry points:** Namespace packaging alone does not perform discovery; use both native namespace packages and Python entry-point metadata.
9. **Capability resolution rather than concrete class names:** Workflow definitions refer to declared capabilities/data contracts, and registry resolves them to installed agent implementations.
10. **Prioritize demonstrable progress:** Do not let optional features delay a working vertical slice and integration test.

---

## 3. Logical architecture

```text
                 ┌─────────────────────────────────────┐
                 │                CLI                  │
                 │             agentctl               │
                 │ list agents | list workflows | run  │
                 └──────────────────┬──────────────────┘
                                    │
            ┌───────────────────────▼────────────────────────┐
            │           GENERIC FRAMEWORK CORE              │
            │                                               │
            │  SDK/contracts: BaseAgent, AgentManifest,      │
            │  RuntimeContext, WorkflowDefinition/Plan      │
            │                                               │
            │  Plugin discovery → Agent/Workflow Registries │
            │                       │                       │
            │    Named workflow ────┼─── Capability Planner │
            │                       ▼                       │
            │               Validated WorkflowPlan          │
            │                       │                       │
            │                Sequential Executor            │
            │             (shared context/results)          │
            │                                               │
            │  Cross-cutting: logging + lifecycle events    │
            └───────────────────────┬────────────────────────┘
                                    │ generic plugin contracts
            ┌───────────────────────┴────────────────────────┐
            │             INDEPENDENT PACKAGES             │
            │  agentctl_agents.weather      external API    │
            │  agentctl_agents.clothes      rule logic      │
            │  agentctl_agents.shelf        SQLite          │
            │  agentctl_workflows.outfit    plan definition │
            └────────────────────────────────────────────────┘

        pytest full-path integration test ── GitHub Actions CI
```

### Terminology

- **SDK:** Public contracts used by plugin developers.
- **Registry/discovery:** Loads installed plugin entry points, reads manifests, validates duplicate IDs/capabilities.
- **Router/planner:** Determines which capability steps can achieve a requested output/goal using declared input/output contracts; returns plan or a clear error.
- **Named workflow:** Externally defined, reusable ordered capability list; it is a *definition*, not an execution engine.
- **Orchestrator/executor:** Validates/resolves steps and runs them sequentially, with shared context and logging. Unaware of business semantics.

---

## 4. Proposed repository and distribution boundaries

A monorepo is acceptable; independent packaging remains real.

```text
repo/
├── framework/
│   ├── pyproject.toml              # distribution: agentctl-core
│   └── src/agentctl_core/
│       ├── __init__.py
│       ├── sdk.py                   # public contracts
│       ├── context.py
│       ├── discovery.py
│       ├── registry.py
│       ├── planner.py
│       ├── orchestrator.py
│       ├── observability.py
│       └── cli.py                  # console script: agentctl
├── plugins/
│   ├── weather/
│   │   ├── pyproject.toml          # distribution: agentctl-weather
│   │   └── src/agentctl_agents/weather/... 
│   ├── clothes/
│   │   ├── pyproject.toml          # distribution: agentctl-clothes
│   │   └── src/agentctl_agents/clothes/...
│   └── shelf/
│       ├── pyproject.toml          # distribution: agentctl-shelf
│       └── src/agentctl_agents/shelf/...
├── workflows/
│   └── outfit/
│       ├── pyproject.toml          # distribution: agentctl-outfit-workflow
│       └── src/agentctl_workflows/outfit/...
├── tests/
│   └── test_end_to_end.py
├── .github/workflows/ci.yml
├── README.md
└── AI_USAGE.md                    # truthful setup/process disclosure
```

**Namespace packaging:** `agentctl_agents` (and optionally `agentctl_workflows`) should be a native PEP 420 namespace, without `__init__.py` at the shared namespace root. Each plugin has its own `pyproject.toml`, depends on `agentctl-core`, and declares an entry point in a group such as `agentctl.agents`. Workflow plugins use `agentctl.workflows`. Python `importlib.metadata.entry_points(group=...)` discovers installed registrations. Exact packaging/import conventions should be validated with a clean environment and installation test.

Example registration concepts (illustrative, not finalized API):

```toml
[project.entry-points."agentctl.agents"]
weather = "agentctl_agents.weather.plugin:WeatherAgent"
```

```toml
[project.entry-points."agentctl.workflows"]
outfit = "agentctl_workflows.outfit.definition:get_workflow"
```

An entry point references importable executable Python code; only load **trusted installed plugins**.

---

## 5. Core SDK contract (planned, not code-complete)

Keep SDK small and stable across plugins. Exact signatures are to be finalized in Sprint 1.

### Agent contract

```python
class BaseAgent(ABC):
    manifest: AgentManifest

    @abstractmethod
    def run(self, inputs: dict, context: RuntimeContext) -> dict:
        ...
```

Agents take **resolved step inputs** plus generic context and return a structured `dict`. Agents do not directly instantiate/invoke other agents. SDK contract may later evolve to stronger typing; avoid doing so during MVP unless necessary.

### Agent manifest

Proposed minimum fields:

| Field | Meaning |
|---|---|
| `name` | Stable unique agent ID |
| `version` | Semantic-ish version string |
| `description` | Human-facing purpose |
| `capabilities` | Declared actions/capabilities (one per example agent) |
| `requires` | Input data keys required for execution |
| `produces` | Output data keys produced by execution |

**Important contract choice:** The dependency planner reasons about *data keys* (e.g. `weather`, `clothing_requirements`, `outfit`) and maps them to agents/capabilities. Clarify whether `requires/produces` live per-capability or per-agent in Sprint 1. Because each MVP agent implements one capability, an agent-level representation is sufficient initially; design should permit future multi-capability agents.

Example capabilities/data dependencies:

| Agent | Capability | Requires | Produces |
|---|---|---|---|
| Weather | `weather.forecast` | `city` | `weather` |
| Clothes | `clothes.advise` | `weather`, `activity` | `clothing_requirements` |
| Shelf | `shelf.match` | `clothing_requirements` | `outfit` |

User `style`/preferences are optional inputs (defaulted) rather than mandatory graph dependencies.

### RuntimeContext (MVP)

- `session_id`: provided or generated per invocation.
- `workflow_id`: unique ID per execution (distinct from workflow *name*).
- `inputs`: original structured request parameters.
- `results`: per-step structured outputs, keyed by capability/step ID.
- `memory`: mutable **execution-scoped** dictionary accessible during the run.
- `events`: simple in-process list of typed lifecycle records (not event bus).
- `logger`: shared/configured framework logger (ideally contextualized with IDs).

**Input passing:** Orchestrator builds each agent's inputs by merging initial user inputs with produced data keys from prior completed steps. It checks that required keys exist before calling an agent. Avoid ambiguous collisions: explicit policy (reject collisions or deterministic override) should be chosen in Sprint 1/4. Keep `results` separate as an audit-friendly record of each step.

### Workflow structures

- `WorkflowDefinition`: externally declared name, description, ordered capability steps (for named execution), optional required request parameters.
- `WorkflowPlan`: validated executable steps, each referencing a capability and resolved registered agent ID; may include provenance (`named` or `generated`).

**Important:** A workflow definition lives in a plugin package; SDK provides its schema. The orchestrator receives a plan and does not know outfit-specific semantics.

---

## 6. Router/planner and orchestration behavior

### Two supported entry paths

**Path A — named workflow:** CLI names `outfit_advisor` → registered external workflow definition → validate/resolve every capability against discovered agent manifests → produce `WorkflowPlan` → execute.

**Path B — generated plan:** CLI supplies `--goal outfit` with structured inputs → inspect registered capabilities/required and produced keys → backward-resolve the required producers → create valid topologically ordered steps → execute.

The two paths converge on **one identical plan format and one executor**. The router does not merely select a hardcoded list.

### Deterministic planner MVP rules

1. Requested `goal` denotes a desired **output data key**, e.g. `outfit`.
2. If initial inputs already satisfy a dependency, no producer step is required for that key.
3. Otherwise find a registered agent that produces the needed key, recursively satisfy its `requires`, then append its capability (dependency-first).
4. Deduplicate steps while preserving dependency order.
5. Fail clearly for missing producers, missing required user input, circular dependencies, and ambiguous providers. A tiny implementation need only support one unique provider per output key.
6. Verify generated plan includes all three example agents for `goal=outfit` with `city` and `activity` supplied.

**Planner limitations (disclose):** Explicit-goal routing only; not natural language understanding, optimal planning, arbitrary multi-output negotiation, or complex branching.

### Generic sequential orchestrator

1. Receive a `WorkflowPlan` and a new `RuntimeContext`.
2. Log workflow start and record event.
3. For each step: resolve plugin via registry, validate inputs, log start, call `run`, validate minimal output keys, merge declared outputs into working data, store step result, record completion/duration.
4. On an exception: log with traceback/context, record failure event, stop with meaningful nonzero CLI exit status.
5. On success: return final output and execution summary; log completion.

No agent should need to import or directly call another agent.

---

## 7. Three agent plugin behaviors

### Weather provider (`weather.forecast`)

- Input: `city` (MVP: supported human-readable city/location query; weather API may require geocoding first).
- Output: stable `weather` dictionary such as `{temperature_c, condition, precipitation_probability?, ...}`.
- Must make a **real external API request in actual CLI use**. Candidate: Open-Meteo (geocoding + forecast), subject to choosing/confirming current API details during implementation.
- Add HTTP timeout and comprehensible error on invalid city/API failure. Minimal response parsing.
- Integration test replaces HTTP boundary with a deterministic fake response; CI must not rely on public internet API uptime.

### Clothes adviser (`clothes.advise`)

- Inputs: `weather`, `activity`, optional `style` (or other small preference).
- Output: `clothing_requirements` as normalized clothing categories and relevant attributes (e.g. top, bottoms, outerwear, shoes; warmth/rain suitability).
- Implement straightforward deterministic Python rules for a couple of activities (e.g. outdoor walk, theatre) and temperature/rain bands; document defaults.
- No LLM needed.

### Personal shelf manager (`shelf.match`)

- Input: `clothing_requirements` plus context/config for DB path (avoid hardcoded user filesystem paths).
- Output: `outfit` consisting of specific items present in the clothes registry and explanation/missing categories if not available.
- Use **SQLite** via `sqlite3`: lightweight local relational registry, no separate server required.
- Small table concept: `clothes(id, name, category, style, warmth, rain_suitable, available)`; exact schema to be decided in agent sprint.
- Provide deterministic seed data for sample CLI runs and temporary seeded DB for tests.
- Use SQL parameters, not string-formatted SQL.

### Example flow (values illustrative)

Input: `city=Dallas`, `activity=outdoor_walk`, `style=casual` → weather agent returns forecast → clothes agent returns appropriate categories → shelf agent selects owned item IDs/names → CLI prints final outfit and optionally execution trace.

---

## 8. CLI contract (proposed, not mandated literal syntax)

Assessment mandates these operations, but does not prescribe every flag. Proposed commands:

```bash
agentctl list agents
agentctl list workflows
agentctl run workflow outfit_advisor --input city=Dallas --input activity=outdoor_walk
agentctl run workflow --goal outfit --input city=Dallas --input activity=outdoor_walk
```

Optional preference: `--input style=casual`. Optional `--session-id` for trace labeling even before session-persistent memory exists.

**CLI design constraint:** The core CLI must not hardcode `--city`, `--activity`, or clothing-related flags. A generic repeated `--input key=value` (or `--input-json`) keeps it reusable. `argparse` is enough.

- `list agents` should show manifest fields, not just names.
- `list workflows` should show workflow name/description/steps.
- Invalid workflow, unmatched goal, or missing inputs should give clear errors and nonzero exit code.
- Logs should go to stderr, and user-facing result to stdout, when practical.
- `chat --session-id` is stretch and omitted from MVP.

---

## 9. Observability and basic events (MANDATORY)

Logging belongs in the generic framework runtime; agents may log through `context.logger`. Use Python `logging` configured once by CLI/runtime, with consistent fields including `workflow_id` and `session_id` when available.

Minimum log points:

| Moment | Level | Fields |
|---|---|---|
| Plugin discovered | INFO | plugin ID, version |
| Planning decision | INFO | requested goal, selected capabilities |
| Workflow started | INFO | workflow ID, session ID, source (`named`/`generated`) |
| Step started | INFO | workflow ID, step index, capability, agent ID |
| Step completed | INFO | step ID, duration |
| Step failed | ERROR | step ID, error + exception trace |
| Workflow completed/failed | INFO/ERROR | workflow ID, status, duration |

Minimal structured lifecycle events retained in `context.events`:

- `workflow_started`, `agent_started`, `agent_completed`, `agent_failed`, `workflow_completed`, `workflow_failed`.

These are **records**, not asynchronous pub/sub. No external observability stack required. Do not log credentials or unnecessarily dump potentially personal inputs.

---

## 10. Testing and GitHub Actions acceptance

### One required full-path integration test

Test should use actually installed plugin distributions/entry points — **do not** fake registry construction by directly instantiating each agent.

1. Discover three agent plugins and outfit workflow plugin.
2. Assert expected manifest metadata and capabilities are visible.
3. Supply `goal=outfit`, `city`, `activity`; ask planner to generate plan.
4. Assert plan includes `weather.forecast` → `clothes.advise` → `shelf.match` in dependency order.
5. Run plan via generic orchestrator with new runtime context.
6. Stub/mock only the external weather HTTP boundary; ensure reproducible weather.
7. Use a temporary seeded SQLite database; assert selected outfit refers to actual seeded wardrobe items.
8. Assert final output structure and (if straightforward) workflow/agent completion events or log records.

Unit tests for planner edge cases are useful but secondary to required full-path test.

### GitHub Actions CI

A small workflow (push/pull_request): checkout → setup Python → install framework and each separate plugin in test environment → install pytest/test dependencies → execute `pytest`. Tests must not require secrets or live external weather availability.

**Reproducibility check:** Locally test from clean virtual environment at least once, not only editable development installation with imports accidentally resolving from the repository tree.

---

## 11. Implementation increments (high-level only)

**Do not generate the entire repository from this document in one prompt.** Each increment will have its own later-reviewed Markdown sprint brief with tasks, acceptance criteria, tests, files touched, and an AI coding prompt.

1. **Sprint 1 — Core contracts/context/observability foundations:** `BaseAgent`, manifests, basic runtime context/events, plan/definition shapes, logging contract, basic tests.
2. **Sprint 2 — Plugin packaging/discovery:** separate PEP 420 agent distributions and entry-point discovery; a workflow plugin registry. Early smoke test.
3. **Sprint 3 — Concrete agents:** real external weather integration, deterministic clothing advice, SQLite shelf matching and seed data.
4. **Sprint 4 — Routing/workflow execution:** dependency-based plan generation, named workflow plan loading, generic sequential orchestrator, output passing, errors.
5. **Sprint 5 — CLI/testing/CI/docs:** commands, full-path integration test, GitHub Actions, README, demonstration, AI disclosure.

**Execution note:** Implement or at least stub a minimal vertical slice early, then improve it; avoid saving all integration work until the final sprint. The sequence above is a decomposition, not a rigid ban on a smoke test earlier. Allocate time based on risk, not equal-duration sprints.

---

## 12. Non-goals and time protection

Do **not** add to MVP unless mandatory work is complete:

- LLM routing, embeddings/vector DB, tool-use autonomy, LangChain/LangGraph.
- RAG retrieval, session-persistent memory, event bus/pub-sub, interactive chat.
- Parallel execution, distributed workers, retries framework, graphical UI/web server.
- Cloud database, ORM, container orchestration, complex auth/permissions, elaborate configuration system.
- Many example workflows, complicated personalization, fashion ML.

Reasonable minimum robustness: input validation, clear failure messages, HTTP timeouts, safe SQL parameters, duplicate plugin/capability errors, missing dependency errors, cycle detection.

---

## 13. Risks, ambiguities, and decisions to confirm per sprint

| Topic | Current interpretation | When to finalize |
|---|---|---|
| What “router” means | Deterministic capability-dependency plan from explicit output goal | Sprint 4 |
| Exact manifest structure | Agent-level capabilities + requires/produces initially | Sprint 1 |
| Output merge/collision behavior | Fail on ambiguous providers; make key overwrite policy explicit | Sprints 1 & 4 |
| Workflow plugin packaging | Fourth independently installable distribution, entry-point registration | Sprint 2 |
| `list workflows` | Lists externally registered named definitions (not all possible generated plans) | Sprints 2 & 5 |
| User preferences | At least optional `style`; activity required | Sprint 3 |
| Weather endpoint / geocoding | Real public API; choose documented endpoint and error handling | Sprint 3 |
| Shelf DB | SQLite with configurable DB path and seed data | Sprint 3 |
| Session/events/memory overlap | Runtime context has ID, event list and per-run memory; cross-run session store is stretch | Sprint 1 |
| CLI parameter format | Generic repeated `--input KEY=VALUE`, perhaps optional JSON | Sprint 5 |
| Test weather | Mock HTTP only; genuine discovery/plan/executor/SQLite | Sprints 3–5 |

**Assessment ambiguity:** It does not explicitly require an LLM or free-form text intent parser, and allows assumptions. We should disclose deterministic explicit-goal planning as a deliberate simplification. Named workflow support is also required by the CLI wording; it is not a substitute for the router-generated-plan integration test.

---

## 14. Deliverables/checklist for handoff

- [ ] Separate installable core framework distribution with `agentctl` console script.
- [ ] Three independently installable native namespace agent packages, dynamically discovered using entry points.
- [ ] External named outfit workflow definition installed/discovered independently.
- [ ] SDK manifest, agent contract, runtime session/events/working memory.
- [ ] Deterministic planner creates an outfit plan from discovered capability input/output dependencies.
- [ ] Generic executor can run named and generated plans sequentially.
- [ ] Weather agent calls external API during real runs; clothes adviser returns rule-based requirements; SQLite shelf returns actual items.
- [ ] Framework-controlled logging and meaningful failure reporting.
- [ ] `agentctl list agents`, `list workflows`, `run workflow` paths demonstrated.
- [ ] Full-path integration test using real plugin discovery, mocked weather boundary, seeded SQLite.
- [ ] GitHub Actions CI running integration test.
- [ ] README installation, example commands/output, architecture, limitations, test instructions.
- [ ] AI_USAGE.md truthful tool/model/editor setup, extent of assistance, validation performed by implementer.

---

## 15. Instructions for AI-assisted coding assistant

Use this as **design context, not authorization to build everything immediately**.

1. Wait for a separately approved sprint brief. Work only on the named sprint and acceptance criteria.
2. Respect generic framework boundaries: no importing business-specific plugins into framework core.
3. Preserve real package isolation, entry-point discovery, and namespace package semantics.
4. Implement simple, readable Python; avoid unnecessary dependencies and abstractions.
5. Prefer small edits and explain what files changed, why, and how to test them.
6. Write or run tests relevant to the sprint. Never claim code/tests pass unless actually executed.
7. Ask before making a major design change that contradicts this file; document chosen tradeoffs.
8. Do not implement stretch goals unless a sprint explicitly authorizes them.
9. Do not fabricate API responses in production code; mocking is limited to tests/demo fixtures explicitly identified as such.
10. Keep comments and documentation accurate, and document assumptions/limitations.
11. Preserve provenance of AI-generated work for the final assessment disclosure.
12. Favor code the candidate can explain in a technical review over clever/opaque solutions.

---

## 16. AI-assisted development disclosure template (fill with truth, don't invent)

Create `AI_USAGE.md` with:

- **Coding assistant(s):** product/editor, model if known, relevant settings/extensions.
- **Planning assistance:** architecture discussion, project/sprint scoping, interface recommendations.
- **Code assistance:** which modules/tests/docs were generated or substantially edited; how prompts/reference files were used.
- **Human review:** design choices made, code inspected, tests executed, bugs fixed, what can be explained/demonstrated.
- **Limitations:** incomplete features, outside help/dependencies, any known test failures.

Example statement *only if accurate after work*: “I used ChatGPT for requirements interpretation and sprint planning and [coding tool] for draft implementation. I reviewed the generated code, ran the test suite, and validated the CLI examples before submission.”

---

## 17. Current status and next action

**Current status:** Architecture proposed; no sprints approved or implemented.  
**Next action:** Review and approve this master file. Then create **Sprint 1 Markdown brief** specifying exact contracts and acceptance tests. Subsequent sprint briefs follow one by one.

**Reminder:** This plan describes how to implement the assessment; it is **not** proof that the software has already been built or tested.
