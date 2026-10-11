# Sprint 01 — Core SDK Contracts

**Project:** Agentic Workflow Framework  
**Status:** Approved scope; implementation not started  
**Read alongside:** `AGENTIC_WORKFLOW_FRAMEWORK_MASTER_PLAN.md`  
**Goal:** Produce a minimal, installable, generic Python SDK that independently developed agents and workflow packages can use without importing application-specific code.

> **Instructions for the AI coding assistant:** Implement **only Sprint 01**. Treat the master plan as architecture context, not permission to implement later sprints. If something is ambiguous, choose the smallest implementation consistent with the interfaces below; report the choice rather than expanding scope.

## 1. Architectural role

The SDK provides public **contracts**, not an execution system. The core distribution may eventually also contain the runtime (registry, planner, orchestrator, CLI), but this sprint implements none of those runtime subsystems.

- SDK does **not** know about weather, clothing, wardrobe, external APIs, databases, or LLMs.
- Independent agent distributions will import `BaseAgent`, `AgentManifest`, `Capability`, and `RuntimeContext`.
- Independent workflow distributions will import `WorkflowDefinition`.
- The future deterministic planner will examine `Capability.requires` and `Capability.produces` to build dependency-ordered workflow plans.
- The future orchestrator will accept the SDK's `WorkflowPlan` and invoke agents via the `BaseAgent.run` contract.

**Repository convention:** Follow the master plan's `framework/src/agentctl_core/` layout, rather than the earlier illustrative `agentctl/sdk/` layout. The pip distribution is named `agentctl-core`, while the Python import package is `agentctl_core`. Future CLI executable will be `agentctl`, but **do not implement the CLI in this sprint**.

## 2. Scope: five public components

### 2.1 `Capability`

A frozen or ordinary dataclass is acceptable, provided the API is stable and the three fields below are present:

```python
@dataclass
class Capability:
    name: str
    requires: list[str]
    produces: list[str]
```

- `name`: unique capability identifier, e.g. `weather.forecast`.
- `requires`: data keys that must be available before execution, e.g. `city`.
- `produces`: data keys the agent promises to return, e.g. `weather`.
- The framework **does not** interpret these as Python classes or business concepts.
- For the MVP, assume one primary capability per agent, but keep the manifest capable of declaring multiple.
- Avoid duplicating `requires`/`produces` at the manifest level; they are properties **of each capability**. This resolves a minor ambiguity in the master plan.

### 2.2 `AgentManifest`

```python
@dataclass
class AgentManifest:
    name: str
    version: str
    description: str
    capabilities: list[Capability]
```

Manifest metadata must be inspectable without running an agent. Keep it easy to print/serialize later using standard `dataclasses` tools. Do not build a complex metadata schema or a plugin registry yet.

### 2.3 `BaseAgent`

Use `abc.ABC` and `@abstractmethod`. The public contract is:

```python
class BaseAgent(ABC):
    @property
    @abstractmethod
    def manifest(self) -> AgentManifest:
        ...

    @abstractmethod
    def run(self, inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]:
        ...
```

- Agent implementation must supply a manifest and `run` method.
- `inputs` contains resolved step inputs; the future orchestrator constructs it.
- `context` holds execution-scoped shared state and a logger.
- `run` returns a dictionary keyed by declared output data keys.
- Agents should not call other agents directly; workflow coordination belongs to the future orchestrator.
- The SDK does not validate actual runtime results yet. That belongs to the orchestrator sprint.

### 2.4 `RuntimeContext`

```python
@dataclass
class RuntimeContext:
    session_id: str
    workflow_id: str
    inputs: dict[str, Any]
    results: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("agentctl")
    )
```

- `session_id`: identifies the session; **not** a persistent session store.
- `workflow_id`: identifies one execution; distinct from named workflow name.
- `inputs`: original user inputs. `results`: completed step results, filled in later by orchestrator.
- `memory`: mutable, *execution-scoped* working dictionary (stretch-goal persistence deferred).
- `events`: simple lifecycle records stored as dictionaries; **not** a pub/sub event bus.
- `logger`: usable standard-library logger; **do not** configure global logging handlers in the SDK. Centralized logging configuration and emission belong to the runtime sprint.
- Use `default_factory` for mutable fields so different contexts never share defaults.
- No automatic session persistence, serialization engine, timers, or async behavior.

### 2.5 Workflow types

```python
@dataclass
class WorkflowDefinition:
    name: str
    description: str
    steps: list[str]  # ordered capability identifiers

@dataclass
class WorkflowPlan:
    steps: list[str]  # ordered capability identifiers
    source: str       # "named" or "generated"
```

- The SDK defines these **generic types only**. An actual `outfit_advisor` definition belongs in an independent workflow package in a later sprint.
- Keep one plan representation for both named and capability-generated plans.
- The future registry/executor will resolve each step's capability identifier into an installed agent; do not put concrete agent objects inside the plan.
- A minimal optional plan identifier/goal field is not needed now. Avoid adding fields that are not required for Sprint 01.

## 3. Directory and package structure

Create only the following baseline (small differences such as test filenames are acceptable):

```text
repo/
├── framework/
│   ├── pyproject.toml
│   └── src/
│       └── agentctl_core/
│           ├── __init__.py
│           ├── sdk.py         # BaseAgent, AgentManifest, Capability,
│           │                  # WorkflowDefinition, WorkflowPlan
│           └── context.py     # RuntimeContext
└── tests/
    └── test_sdk.py
```

`agentctl_core/__init__.py` may re-export stable public types; document the import pattern in a short framework README if useful. `sdk.py` may import `RuntimeContext` from `context.py`. Avoid circular imports.

**Packaging:** A minimal PEP 621 `pyproject.toml` using setuptools, with `src` package discovery, Python >= 3.10. The distribution should install using `python -m pip install -e ./framework`. Keep runtime dependencies empty for Sprint 01. `pytest` can be used as a development/testing dependency. Do not create plugin namespace packages yet; they are Sprint 02 work.

## 4. Contract usage example (illustrative only)

A test-local dummy agent should be possible:

```python
from agentctl_core.sdk import BaseAgent, AgentManifest, Capability

class DummyAgent(BaseAgent):
    @property
    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="dummy",
            version="0.1.0",
            description="A tiny SDK contract test",
            capabilities=[Capability(name="demo.echo", requires=["text"], produces=["echo"])],
        )

    def run(self, inputs, context):
        context.events.append({"type": "agent_ran", "agent": self.manifest.name})
        context.memory["last_text"] = inputs["text"]
        return {"echo": inputs["text"]}
```

This agent exists **inside the SDK unit test only**, not as a real installed plugin or product use case. `DummyAgent` must be instantiable, and `BaseAgent` alone must not be.

## 5. Tests and definition of done

Write small `pytest` unit tests (no API calls, database, network access, plugin entry points, CLI, or orchestration). Verify:

1. The framework distribution installs locally in editable mode.
2. `BaseAgent` cannot be instantiated while a valid dummy subclass can.
3. Dummy agent returns the expected dictionary through `run(inputs, context)`.
4. `AgentManifest` stores required metadata and structured capability dependencies accurately.
5. Two `RuntimeContext` instances have independent `results`, `memory`, and `events` dictionaries/lists (no mutable default leakage).
6. The context exposes a usable `logging.Logger` without configuring a global handler.
7. `WorkflowDefinition` and `WorkflowPlan` can be constructed and inspected; they contain capability IDs, not instantiated agents.
8. Public SDK imports work from the installed distribution.

Expected commands from the repo root:

```bash
python -m pip install -e ./framework
python -m pip install pytest
python -m pytest tests/test_sdk.py -q
```

**Completion condition:** All tests pass; the SDK is installable and generic; no app-specific code or later-sprint runtime exists.

## 6. Explicitly out of scope

Do **not** implement any of the following in Sprint 01:

- Agent/workflow plugin packages; Python namespace package layout; entry-point discovery; registries.
- Capability dependency router/planner or workflow orchestrator.
- `agentctl` CLI commands.
- Weather provider or external HTTP API; clothes adviser; shelf manager; SQLite database.
- Integration test and GitHub Actions CI (planned for later sprint).
- Natural-language intent resolution / LLM API calls.
- RAG abstractions, session-persistent memory store, event bus, or interactive chat.
- Production logging configuration, retries, distributed execution, async orchestration, monitoring services.

## 7. Design choices and boundaries to preserve

- The SDK must remain business-agnostic; weather/outfit names may appear **only in documentation examples**, not implementation branches.
- Keep distinct: **capability description** (`requires`/`produces`) versus **workflow definition** (ordered capability list) versus **execution plan** (ordered steps supplied to executor).
- Basic `memory`/`events` fields are mandatory runtime context shape; persistence and event-driven messaging remain stretch goals.
- Avoid adding a premature `IntentResolver`. Later, an optional LLM resolver can transform natural language into a structured `{goal, parameters}` object consumed by the already-defined planner; it is *not* critical path.
- The next sprint can implement discovery and registries without changing these public interfaces.
- If the coding assistant detects a conflict between this sprint and the master plan, report it. **Sprint 01's per-capability `requires/produces` and `agentctl_core` layout are intentional refinements.**

## 8. Required response from AI coding assistant

After implementation, provide:

1. A concise summary of files created/modified.
2. Exact commands to install and run tests, with actual observed pass/fail result.
3. A short explanation of how each public SDK type is used.
4. Any assumptions/deviations and why they were necessary.
5. A statement confirming that later-sprint features were not implemented.

**Stop after Sprint 01.** Do not automatically proceed to the plugin system or agent implementations.
