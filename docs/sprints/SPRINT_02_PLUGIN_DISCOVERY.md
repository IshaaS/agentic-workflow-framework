# Sprint 02 — Independent Plugins, Dynamic Discovery, and Registries

**Project:** Agentic Workflow Framework  
**Status:** Scope locked; ready for implementation  
**Read alongside:** `AGENTIC_WORKFLOW_FRAMEWORK_MASTER_PLAN.md` and Sprint 1 implementation in the repository  
**Goal:** Independently installable Python namespace packages register agents and an external workflow; the generic framework discovers and indexes them through Python distribution entry points, with no hardcoded application-specific imports.

> **Coding-assistant instruction:** Implement **only Sprint 02**. Use the **actual merged Sprint 1 code** as the source of truth for imports and contracts. The master plan provides context, not permission to build later sprints. Do not refactor Sprint 1's public contracts unless required to fix a demonstrated incompatibility; describe any deviation.

## 1. Confirmed Sprint 1 foundation

The merged Sprint 1 framework distribution lives at `framework/`, installs with `python -m pip install -e ./framework`, and exports the following from `agentctl_core`:

- `BaseAgent` with `manifest: AgentManifest` and `run(inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]`
- `Capability(name, requires, produces)`
- `AgentManifest(name, version, description, capabilities: list[Capability])`
- `WorkflowDefinition(name, description, steps: list[str])`
- `WorkflowPlan(steps: list[str], source: str)`
- `RuntimeContext(session_id, workflow_id, inputs, results, memory, events, logger)`

Existing files: `framework/src/agentctl_core/sdk.py`, `context.py`, `__init__.py`, `framework/pyproject.toml`, and `tests/test_sdk.py`. Continue using `agentctl_core`, **not** `agentctl.sdk`.

## 2. Architecture and boundaries

**Core distribution** (`agentctl-core`): registry and discovery logic, generic SDK types. Core knows only agent/workflow contracts and entry-point groups. It must **never** import `agentctl_agents.weather`, `agentctl_agents.clothes`, `agentctl_agents.shelf`, or `agentctl_workflows.outfit` by name.

**Independent agent distributions** (three separately installable distributions):

1. `agentctl-weather-agent` provides `agentctl_agents.weather`.
2. `agentctl-clothes-agent` provides `agentctl_agents.clothes`.
3. `agentctl-shelf-agent` provides `agentctl_agents.shelf`.

These share the **implicit PEP 420 namespace** `agentctl_agents`: do **not** create `agentctl_agents/__init__.py` in any plugin distribution. Each leaf package (e.g., `weather/`) may have its own `__init__.py`.

**Independent workflow distribution:** `agentctl-outfit-workflow`, providing `agentctl_workflows.outfit` and a named `WorkflowDefinition`. Keep `agentctl_workflows/` a native namespace without `__init__.py` at that root as well.

Separate package distributions are permitted in the **same Git repository**. A single `pip install` of the core alone should not implicitly install all plugins.

## 3. Files / package layout (suggested)

```text
framework/
  pyproject.toml
  src/agentctl_core/
    __init__.py
    sdk.py                    # Sprint 1: preserve public contracts
    context.py                # Sprint 1: preserve public contracts
    registry.py               # NEW: agent + workflow registries
    discovery.py              # NEW: entry-point plugin loading
agents/
  weather-agent/
    pyproject.toml
    src/agentctl_agents/weather/__init__.py
    src/agentctl_agents/weather/agent.py
  clothes-agent/
    pyproject.toml
    src/agentctl_agents/clothes/__init__.py
    src/agentctl_agents/clothes/agent.py
  shelf-agent/
    pyproject.toml
    src/agentctl_agents/shelf/__init__.py
    src/agentctl_agents/shelf/agent.py
workflows/
  outfit-workflow/
    pyproject.toml
    src/agentctl_workflows/outfit/__init__.py
    src/agentctl_workflows/outfit/definition.py
tests/
  test_sdk.py                 # existing, must continue passing
  test_registry.py            # NEW: registry behavior
  test_discovery.py           # NEW: real entry-point discovery smoke test
```

Names are selected to fit the master plan; small file-layout variations are acceptable if imports and distribution boundaries remain clear.

## 4. Core registry requirements

Implement `AgentRegistry` and `WorkflowRegistry` as generic Python runtime classes.

**AgentRegistry:**
- `register(agent: BaseAgent) -> None`: check contract, nonblank manifest name, unique agent name, and **unique capability name across registered agents**. Reject duplicate capability declarations within an agent as well.
- `list_agents() -> list[BaseAgent]`: stable deterministic order (sort by manifest name, or document insertion order).
- `get_agent(name: str) -> BaseAgent | None`.
- `find_by_capability(capability_name: str) -> BaseAgent | None`.
- Prefer a clear `ValueError` (or a small domain-specific exception) on conflicts. No silent overrides.

**WorkflowRegistry:**
- `register(workflow: WorkflowDefinition) -> None`: validate unique, nonblank workflow name; reject duplicates.
- `list_workflows() -> list[WorkflowDefinition]`: deterministic order.
- `get_workflow(name: str) -> WorkflowDefinition | None`.

A workflow definition is metadata only. **Do not execute or validate step dependencies in Sprint 2**. That belongs to the planner/orchestrator sprint. The agent registry may check capability-name uniqueness, but should not attempt graph planning.

Do not introduce a new registry contract into the SDK or require agents to import registry classes.

## 5. Plugin discovery requirements

Implement generic discovery using `importlib.metadata.entry_points`:

- Agent entry-point group: `agentctl.agents`.
- Workflow entry-point group: `agentctl.workflows`.
- Discover only **installed distributions**. No filesystem scans, manual imports, fixed known plugin lists, or dynamically importing by user-provided strings.
- Each agent entry point points to an agent **class** that can be instantiated without constructor arguments. Load it, instantiate it, and register the instance.
- Each workflow entry point points to a **zero-argument factory** returning `WorkflowDefinition`, such as `get_workflow()`.
- Keep the loader's general behavior separate from registration so tests can validate both.
- Discover entries in a deterministic order (e.g. sort on `ep.name` and `ep.value`) for repeatable diagnostics.
- On bad plugin/import/factory/contract/duplicate capability, raise a meaningful error that identifies the entry point; do not silently ignore it. Keep the implementation small (no plugin isolation, sandboxing, or retry system).
- May expose `discover_agents(registry)` and `discover_workflows(registry)` or one `discover_plugins(agent_registry, workflow_registry)`; choose a clear API and document it. Export useful entry points from `agentctl_core.__init__` if sensible.
- Use trusted, locally installed plugins only. Python entry-point loading executes third-party code.

Example `pyproject.toml` registration in the weather distribution:

```toml
[project.entry-points."agentctl.agents"]
weather = "agentctl_agents.weather.agent:WeatherAgent"
```

In the clothing and shelf distributions use the same group with different names and targets. In the workflow distribution:

```toml
[project.entry-points."agentctl.workflows"]
outfit = "agentctl_workflows.outfit.definition:get_workflow"
```

Each plugin distribution depends on `agentctl-core>=0.1.0` and uses setuptools with a `src/` layout. **Ensure setuptools actually includes namespace packages** (e.g. `find = {namespaces = true, where = ["src"]}` if appropriate). Verify via normal non-editable package installation at least once; editable installs alone can conceal packaging mistakes.

## 6. Three independent agent *shells* (no real implementation yet)

Write classes `WeatherAgent`, `ClothesAgent`, and `ShelfAgent` implementing the Sprint 1 `BaseAgent` interface and returning the following manifests. Agent implementations in this sprint are intentionally placeholders; full behavior is Sprint 3.

| Agent manifest name | Capability | Requires | Produces |
|---|---|---|---|
| `weather_provider` | `weather.forecast` | `city` | `weather` |
| `clothes_adviser` | `clothes.advise` | `weather`, `activity` | `clothing_requirements` |
| `shelf_manager` | `shelf.match` | `clothing_requirements` | `outfit` |

For the MVP, activity and city are required input fields. Optional style/preferences may be added as part of Sprint 3 only if implemented consistently across CLI and agent behavior. Do **not** make them required in Sprint 2.

Agent `run` methods should **raise `NotImplementedError` with an explanatory message** so nobody mistakes placeholder output for working weather, advice, or database behavior. They remain concrete subclasses because `run` is implemented (by raising). Tests must not run these placeholder methods as if they were functional integrations.

Manifest objects should be inspectable without running agent business logic. No API calls, SQLite, LLMs, RAG, or environment secrets in this sprint.

## 7. External named workflow plugin

The independent `agentctl-outfit-workflow` distribution exposes a factory returning:

```python
WorkflowDefinition(
    name="outfit_advisor",
    description="Recommend clothing using weather and a personal shelf",
    steps=["weather.forecast", "clothes.advise", "shelf.match"],
)
```

It **references capabilities**, not Python classes or import paths. It does not instantiate agents and does not contain execution code. The framework runtime must load this through `agentctl.workflows` entry-point discovery, not a direct import.

This predefined workflow is deliberately independent of the future **capability planner**. In Sprint 4, the planner must be able to derive the same order from `requires`/`produces` when asked for goal `outfit`. A named workflow and a generated plan will both become `WorkflowPlan` objects then.

## 8. Sprint 2 tests and acceptance criteria

Add focused tests covering:

- Agent registry register/list/get/capability lookup; duplicate names, duplicate capability providers, missing identifier handling.
- Workflow registry register/list/get; duplicate workflow names.
- Discovery of installed entry points for all **three** agent distributions and the **one** workflow distribution, without hardcoded imports in the discovery implementation.
- The three manifests contain the expected capabilities and `requires`/`produces` contracts.
- The named workflow definition contains the ordered capabilities above and is returned by workflow discovery.
- Namespace import behavior: independently installed distributions under `agentctl_agents` coexist, with no namespace-root `__init__.py`.
- Running tests repeatedly doesn't depend on registry global state; prefer fresh registry instances per test.
- Existing Sprint 1 SDK tests continue passing.

**Important distinction:** Test discovery against **real installed distributions and their entry-point metadata**, not only monkeypatched entry points or manual `register(WeatherAgent())` calls. Unit tests may use fake agents for duplicate-validation tests, but the plugin discovery smoke test must exercise the actual packaging mechanism. Install the four plugins into the test environment first; if absent, tests should fail clearly with setup instructions, not silently skip the entire discovery requirement.

Suggested local setup from repository root (adjust the optional dev extra if supported):

```bash
python -m pip install -e './framework[dev]'
python -m pip install -e ./agents/weather-agent
python -m pip install -e ./agents/clothes-agent
python -m pip install -e ./agents/shelf-agent
python -m pip install -e ./workflows/outfit-workflow
python -m pytest -v
```

Also validate a clean installation using regular `pip install ./...` paths, then confirm that the installed entry points are discoverable. Document any environment assumptions.

**Definition of done:** From a clean Python environment with the four plugin distributions installed, a generic core discovery API returns exactly the three expected agents and the named workflow; registries provide lookup and manifest access; all Sprint 1 + Sprint 2 tests pass. Extra plugins already present in an environment should not be assumed absent in generic APIs; tests may filter for required plugin IDs rather than asserting global exclusivity unless the environment is isolated.

## 9. Explicit exclusions

**Do not implement:**

- Real weather API requests, rule-based wardrobe advice, or SQLite storage (Sprint 3).
- Capability dependency planning, intent resolution, workflow execution, step input/output binding, or failure propagation (Sprint 4).
- CLI executable or CLI commands (later sprint).
- Framework-wide logging configuration or full observability (later sprint; normal diagnostic messages in discovery are fine).
- GitHub Actions CI/end-to-end workflow integration test (later sprint).
- LLM-based natural-language extraction, interactive chat, persistent session memory, event bus, and RAG (optional/post-MVP).

Do not add arbitrary frameworks, DI containers, network services, or use an LLM simply to discover plugins.

## 10. Implementation order

1. Review merged Sprint 1 code and tests; do not change its public SDK API.
2. Implement and test the two registries.
3. Implement generic entry-point discovery.
4. Create three separate agent distribution shells and their entry points.
5. Create the independent outfit workflow distribution and its entry point.
6. Install all distributions locally, verify real discovery, then run full tests.
7. Report exact results and any assumptions or deviations.

## 11. Required coding-assistant handoff

Return a concise **Sprint 2 Implementation Handoff** containing:

1. Files created/modified and purpose.
2. Final public registry/discovery API signatures.
3. Distribution names, import paths, and declared entry-point groups.
4. Confirmation that three plugins and one workflow are discoverable from installed package metadata (not manual imports).
5. Test commands, passed/failed counts, and packaging installation results (editable and at least one normal installation).
6. Any deviations from this specification, known issues, and security/trust assumptions.
7. Branch name and commit hash (if committed). **Do not start Sprint 3.**

---

**Architectural north star:** `agentctl-core` is independent of the application. Independent plugin distributions depend on SDK contracts; the framework discovers their entry points, registers their declared capabilities, and later the planner/orchestrator will consume these registries without application-specific imports.
