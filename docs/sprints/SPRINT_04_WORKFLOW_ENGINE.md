# Sprint 04 — Capability Planner and Generic Sequential Orchestrator

**Project:** Agentic Workflow Framework  
**Status:** Architecture and scope approved; implementation specification  
**Read alongside:** `AGENTIC_WORKFLOW_FRAMEWORK_MASTER_PLAN.md`, Sprint 1–3 handoffs, and **the actual merged repository**.  
**Goal:** Connect independently discovered agent capabilities into validated execution plans and execute those plans sequentially, using generic core code with no weather/clothes/shelf imports.

> **Coding-assistant instructions:** Implement **Sprint 04 only**. Inspect the actual SDK, registries, entry-point discovery, and agent implementations first; preserve existing public interfaces and package contracts. Do not add the generic `agentctl` CLI, GitHub Actions, LLM resolver, chat, RAG, persistent session memory, distributed execution, retries, or event bus. Run existing and new tests, then produce a detailed handoff.

## 1. Existing state to preserve

- `framework/` is installable as `agentctl-core`, imported via `agentctl_core`.
- SDK types are already shipped:
  ```python
  @dataclass
  class Capability:
      name: str
      requires: list[str]
      produces: list[str]

  @dataclass
  class WorkflowDefinition:
      name: str
      description: str
      steps: list[str]  # ordered capability names

  @dataclass
  class WorkflowPlan:
      steps: list[str]  # ordered capability names
      source: str      # "named" or "generated"

  class BaseAgent(ABC):
      @property
      @abstractmethod
      def manifest(self) -> AgentManifest: ...

      @abstractmethod
      def run(self, inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]: ...
  ```
- `RuntimeContext(session_id, workflow_id, inputs, results={}, memory={}, events=[], logger=...)` already exists.
- `AgentRegistry.find_by_capability(name)` returns a registered agent or `None`; `AgentRegistry.list_agents()` returns agents. `WorkflowRegistry.get_workflow(name)` returns a definition or `None`.
- `discover_agents(registry)` and `discover_workflows(registry)` use Python entry points. No hardcoded application imports in core.
- Installed capabilities are currently:
  
  | Capability | Requires | Produces |
  |---|---|---|
  | `weather.forecast` | `city` | `weather` |
  | `clothes.advise` | `weather`, `activity` | `clothing_requirements` |
  | `shelf.match` | `clothing_requirements` | `outfit` |
- The independently registered workflow `outfit_advisor` has ordered steps `weather.forecast`, `clothes.advise`, `shelf.match`.
- All agents already work individually. Agents **return** top-level output dictionaries; they do **not** mutate `context.results`.
- Clothes adviser accepts optional `style` from its input dictionary even though it is not in its manifest's required keys.
- Shelf requires `SHELF_DB_PATH` or an explicitly configured `db_path`, and existing init command `agentctl-shelf-init --db ./wardrobe.db --seed` prepares the sample database.
- Sprint 3 reported 203 passing tests; do not regress them.

## 2. Component boundaries (mandatory)

Implement inside `agentctl_core` (suggested modules `planner.py` and `orchestrator.py`, plus small error types as needed):

1. **Capability planner:** Receives a target output goal plus original structured inputs, examines only the discovered agent registry, resolves prerequisites recursively, and returns a `WorkflowPlan(source="generated")` in dependency order.
2. **Named-workflow plan validator:** Resolves an independent `WorkflowDefinition` into a `WorkflowPlan(source="named")`, verifying that installed capabilities exist and their required inputs can be satisfied **in the declared order**. Do **not** silently reorder named plans.
3. **Generic orchestrator:** Accepts either validated plan form, original input dictionary, agent registry, and execution context; invokes each registered agent in sequence, validates outputs, updates context, logs and records lifecycle events, returns final state or raises a structured error.
4. **Typed errors:** Explain planning and execution failures in machine-readable fields and readable exception strings. Caller-facing formatting is deferred to Sprint 5 CLI.

**The core must never import or reference any concrete application plugin or workflow package.** Both plan sources feed the exact same execution engine.

## 3. Planning input and outcome contract

Suggested public usage (specific symbol names may be adapted to match the repository, but report deviations):

```python
agent_registry = AgentRegistry()
discover_agents(agent_registry)

planner = CapabilityPlanner(agent_registry)
plan = planner.plan_for_goal(
    goal="outfit",  # target produced DATA FIELD, not a class name
    inputs={"city": "Dallas", "activity": "outdoor_walk", "style": "casual"},
    external_inputs={"city", "activity", "style"},
)
assert plan.steps == ["weather.forecast", "clothes.advise", "shelf.match"]
assert plan.source == "generated"
```

**Terminology:** `goal="outfit"` means *produce the top-level output key `outfit`*. The future CLI / optional natural-language intent resolver can convert user language into this structured request; **do not implement intent extraction in Sprint 4**.

### Distinguishing a missing user value from an unavailable producer

The current SDK declares capabilities' `requires`/`produces`, but it **does not identify which missing keys are expected from the user**. Without such metadata, a planner cannot reliably distinguish `city` missing from an unavailable agent that should produce `weather`. Do **not** fake this distinction via application-specific names inside the core.

For this sprint use an **explicit generic `external_inputs` set** supplied by the caller / application configuration:

- Key absent from inputs, no agent produces it, **and** it is declared in `external_inputs` ⇒ `MissingInputError` with `input_name` and `required_by`.
- Key absent and no producer exists, **and** not declared external ⇒ `MissingCapabilityError` with `missing_output` and `required_by`.
- The planner must **never infer** missing fields are user fields from names like `city` or `activity`.
- If a declared external key has a producing capability too, a supplied value can satisfy the dependency; if absent, use the producer when resolvable (document the deterministic rule used).
- Keep `external_inputs` optional for generic callers; without it, unresolved leaves may be reported as missing capability rather than incorrectly labeled missing user inputs.

This is a minimal planner API input, **not a new persistent user-input schema or modification to Sprint 1 SDK types**. The future CLI should supply the names of its supported structured inputs.

### Backward dependency resolution

- Begin at the requested goal/output key. If already present in the provided inputs, an empty plan is valid; document handling (or explicitly reject a no-op goal if simpler, but test and explain).
- Find registered capabilities whose `produces` contains that output.
- For each required key: if available from original inputs, it's satisfied; otherwise recursively find a provider and resolve its dependencies.
- Append the provider's capability **after** its dependencies (topological order).
- Deduplicate capabilities when multiple dependencies share a provider.
- Never invent missing capabilities or reorder based on application-specific special cases.
- Detect circular dependencies using the current recursion path; return a readable cycle path.
- Determinism: registry iteration should be stable; if multiple **distinct** capabilities claim the same produced key, reject ambiguity with a diagnostic error rather than arbitrarily choosing a provider. The existing registry already rejects duplicate capability names, not necessarily duplicate produced data keys.
- The generated plan should include all three agents for `goal="outfit"` and inputs `city, activity`.
- `style` is optional and should not change dependency planning.

### Named workflow planning

```python
workflow = workflow_registry.get_workflow("outfit_advisor")
plan = planner.plan_from_workflow(
    workflow,
    inputs={"city": "Dallas", "activity": "outdoor_walk", "style": "casual"},
    external_inputs={"city", "activity", "style"},
)
assert plan.source == "named"
```

- Load workflows through the registry; the framework has no built-in `outfit_advisor` constant.
- Each step string must resolve to a registered capability.
- For each step, check required keys against initial input keys **plus outputs produced by preceding steps**.
- A missing required key should produce an actionable error; never execute an incomplete plan.
- Do not mutate the registered `WorkflowDefinition` or SDK dataclasses.

## 4. Generic sequential orchestrator

Suggested usage:

```python
context = RuntimeContext(
    session_id="demo-session",
    workflow_id="demo-workflow",
    inputs={"city": "Dallas", "activity": "outdoor_walk", "style": "casual"},
)

result = SequentialOrchestrator(agent_registry).execute(plan, context)
# context.results contains produced top-level keys: weather, clothing_requirements, outfit
# result may be context itself or a well-documented result type; keep it minimal.
```

Execution rules:

1. Take one `WorkflowPlan` and `RuntimeContext`. Use `context.inputs` as the authoritative original inputs; do not require duplicated input arguments unless necessary.
2. For each ordered capability, resolve the agent and its `Capability` metadata from the registry.
3. Build `step_inputs = {**original_inputs, **previous_outputs}` to preserve optional fields such as `style`. **Before** merging, reject any collision between newly produced output keys and original inputs or already produced keys. Never silently overwrite existing user values or outputs.
4. Verify every capability's declared `requires` field is present before invoking the agent.
5. Invoke `agent.run(step_inputs, context)` exactly once for that step, sequentially. Do not call another agent from agent code.
6. Validate that the returned value is a `dict` and contains every key declared in the capability's `produces`. Reject undeclared extra **top-level** outputs for a predictable contract (or document a conservative choice with tests).
7. Store produced top-level keys in `context.results`, indexed **by output name**, not agent class or capability name: `context.results["weather"]`, `context.results["clothing_requirements"]`, `context.results["outfit"]`.
8. Append small **structured event records** (`workflow_started`, `agent_started`, `agent_completed`, `agent_failed`, `workflow_completed`, `workflow_failed`) to `context.events`. Include workflow/session identifiers and agent/capability when relevant.
9. Log lifecycle and failures via `context.logger`, including workflow/session ID, capability, step position and duration. Do not configure global log handlers in library code; do not log entire API responses or sensitive input payloads.
10. If a step fails, stop immediately. Preserve already committed outputs and event history in the same context; append failure events and raise `WorkflowExecutionError` with `capability`, `step_index` and exception cause. Do not retry or invent results.
11. Return a useful completion value, preferably the populated `RuntimeContext`, including final `context.results["outfit"]` for this use case.

**Collision nuance:** For every agent invocation, validate the output keys against the merged working state **before** saving them, so a failure cannot leave partially updated results. The initial inputs stay unchanged. The context's `memory` remains available for execution-scoped scratch data but must not substitute for declared output propagation.

**Duplicate capabilities in plans:** For this minimal sequential engine, reject repeated capability IDs at validation/execution unless there is a compelling documented case. This avoids accidental overwrites and ambiguous repeated effects. Do not implement loops.

## 5. Error handling and diagnostics

Create a small error hierarchy. Suggested names (can adapt with equivalent fields):

```python
class PlanningError(Exception): ...
class UnknownGoalError(PlanningError): ...
class MissingInputError(PlanningError): ...
class MissingCapabilityError(PlanningError): ...
class CircularDependencyError(PlanningError): ...
class AmbiguousProviderError(PlanningError): ...
class InvalidWorkflowPlanError(PlanningError): ...

class WorkflowExecutionError(Exception): ...
```

Required failures:

| Situation | Expected behavior |
|---|---|
| Unknown goal (no producer for target) | Planning error with goal name |
| Missing user-provided `city` (`external_inputs` contains city) | `MissingInputError(input_name="city", required_by="weather.forecast")` |
| Producer for `clothing_requirements` not installed | `MissingCapabilityError(missing_output="clothing_requirements", required_by="shelf.match")` |
| Provider dependency cycle | `CircularDependencyError` with cycle path |
| Multiple providers for same output name | `AmbiguousProviderError` rather than arbitrary choice |
| Named workflow references absent capability | `MissingCapabilityError` or equivalent with capability name and workflow step |
| Named steps in invalid order | Planning error identifying unmet prerequisite |
| Step's required input missing at runtime | Fail fast with step-specific execution error |
| Agent raises an exception (e.g. weather timeout, shelf DB missing) | `agent_failed`/`workflow_failed` events, logger error, wrapped execution error and exception cause |
| Agent returns non-dict, missing output or unexpected output key | Execution error; no partial commit of that step's outputs |
| Output would overwrite initial input / earlier output | Execution error; no overwrite |

**Important:** Planning error vs execution error must be distinguishable for the future CLI. Use readable exception messages plus programmatically accessible fields. We do **not** require a JSON response schema or terminal-specific printing in Sprint 4.

## 6. Tests / acceptance criteria

Add focused tests, e.g. `tests/test_planner.py`, `tests/test_orchestrator.py`, and a light integration-style orchestration test. Reuse tiny in-test fake agents for planning edge cases; use **actual installed entry-point plugins** to prove the working end-to-end path where practical.

**Planner tests:**
- Goal `outfit` + city/activity yields exactly `weather.forecast → clothes.advise → shelf.match`; source `generated`.
- `style` optional does not affect planned dependencies.
- Named workflow loads from independent workflow registry, yields same sequence, source `named`.
- Missing `city` produces typed missing input error with `required_by`.
- Missing clothes provider produces typed missing capability error.
- Unknown goal produces an error identifying the target.
- Circular graph is rejected; path is included.
- Ambiguous output producers are rejected.
- Shared dependencies are resolved once; deterministic order.
- Named steps reference missing capability or wrong order ⇒ clear planning errors.

**Orchestrator tests:**
- Executes a valid plan in order and passes outputs between steps; agents receive optional original `style`.
- Populates `context.results` keyed by produced output names.
- Produces `workflow_started`, each step's `agent_started`/`agent_completed`, and `workflow_completed` events; logs expected metadata.
- Missing required runtime input, malformed returned data, and output collisions are rejected with structured failure information.
- A failing agent stops subsequent steps, preserves previous outputs and events, logs failure, and retains original exception as cause.
- No global logging handlers are configured by the SDK or orchestrator.

**Real-plugin integration (in this sprint):**
- Build registries by calling `discover_agents` and `discover_workflows`; do not import concrete agent classes into core.
- Initialize a **temporary SQLite DB** using existing `agentctl_agents.shelf.db.initialize_database` from the test (the application test may import plugins; core must not).
- Configure `SHELF_DB_PATH` for the discovered shelf agent.
- Replace live weather I/O with a deterministic fake **without changing core plugin-discovery logic** (e.g. patch the weather transport used by the discovered agent) so automated tests never contact the internet.
- Generate a plan from the `outfit` goal using the discovered capabilities, then run it through `SequentialOrchestrator` and assert real `outfit` items and all three output fields.
- Also verify execution from the independently registered named workflow.
- Do not build the formal GitHub Actions integration requirement in this sprint; Sprint 6 will run/extend this path in CI.

**Regression:** Run all Sprint 1–3 tests as well. Report full counts and clean install commands. Python 3.10 is a declared target and should be tested in CI later if feasible.

## 7. Out of scope

- Generic `agentctl` commands, argument parsing and terminal formatting (Sprint 5).
- GitHub Actions CI workflow (Sprint 6).
- LLM/Anthropic intent extraction, chat, natural-language routing.
- RAG, persistent cross-execution session memory, event subscription bus, distributed workers, parallel agents, retries, workflow persistence, conditional/looping steps.
- Modifying agent manifests, core SDK dataclass signatures, namespace packaging, weather rules, or SQLite inventory rules unless fixing a proven compatibility issue, which must be reported.

## 8. Proposed files (adapt to actual repository)

```text
framework/src/agentctl_core/
    planner.py             # Goal dependency resolution + named workflow plan validation
    orchestrator.py        # Generic sequential execution + context/events/logging
    errors.py              # Typed planning and execution diagnostics (optional separate module)
    __init__.py            # Export new public types as appropriate

tests/
    test_planner.py
    test_orchestrator.py
    test_workflow_integration.py   # Optional split of realistic in-process execution test
```

Do not create any `agentctl_agents` imports in framework core. Do not add additional distributions.

## 9. Definition of done

- [ ] Generic planner produces a valid dependency-ordered `WorkflowPlan` from goal/output and installed agent capabilities.
- [ ] Independent named workflow resolves to the same plan format.
- [ ] Missing inputs, missing capabilities, cycles, unknown goals, ambiguities, and invalid plans fail with clear structured diagnostics.
- [ ] Generic orchestrator executes all three real agent plugins sequentially and propagates data correctly.
- [ ] Original user inputs and previous outputs cannot be silently overwritten.
- [ ] Context results, lifecycle events, and contextual logging are correct, including on failures.
- [ ] Failure stops the workflow without executing subsequent agents.
- [ ] End-to-end in-process integration test uses discovered plugins, mocked network and temporary SQLite data.
- [ ] Existing Sprint 1–3 tests still pass.
- [ ] No CLI, CI, or post-MVP features added.

## 10. Coding assistant handoff (required)

After implementation, report:

1. **Files changed** and each one's responsibility.
2. **Public planner/orchestrator APIs** and small examples for `plan_for_goal`, `plan_from_workflow`, and `execute`.
3. **Detailed planner behavior**, including handling of `external_inputs`, ambiguity, cycles and invalid named workflows.
4. **Runtime data propagation** and optional `style` behavior, output collision checks, lifecycle event schema and log fields.
5. **Error hierarchy** with actionable diagnostic attributes and example messages.
6. **Unit and in-process integration tests**, exact command, counts, and results. Confirm tests made no live API calls.
7. **Deviations** from spec and reasons, remaining limitations, and follow-up implications for Sprint 5 CLI.
8. **Git branch and commit** (do not push or merge unless instructed).

**Implementation prompt:** Read the master plan and the real Sprint 1–3 implementation before coding. Implement only the scope specified above. Prefer a compact, understandable solution over abstraction for its own sake. Do not begin Sprint 5.
