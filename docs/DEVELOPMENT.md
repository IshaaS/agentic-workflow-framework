# Development approach and design decisions

This project was built incrementally around the assessment's core requirements: a Python Agent SDK, independently installed agents, dynamic discovery, capability-based workflows, a CLI, logging, and an end-to-end CI test. The original assessment brief is not stored in the repository; the [master plan](../AGENTIC_WORKFLOW_FRAMEWORK_MASTER_PLAN.md) records the initial interpretation. RAG, persistent session memory, an event bus, and interactive chat were treated as stretch goals.

For implementation details, see [Architecture](ARCHITECTURE.md). For AI-assisted development, see [AI usage](AI_USAGE.md).

## Delivery milestones

Each sprint had a specification describing interfaces, tests, acceptance criteria, and out-of-scope work. The specifications remain in [docs/sprints/](sprints/).

| Sprint | Delivered | PR |
|---|---|---|
| [1: Core SDK](sprints/SPRINT_01_CORE_SDK.md) | Agent and workflow contracts, capabilities, runtime context | Committed to `main` |
| [2: Discovery](sprints/SPRINT_02_PLUGIN_DISCOVERY.md) | Entry-point discovery, registries, independently packaged plugins | #1 |
| [3: Agents](sprints/SPRINT_03_AGENTS.md) | Open-Meteo weather provider, clothes adviser, SQLite shelf manager | #2 |
| [4: Workflow engine](sprints/SPRINT_04_WORKFLOW_ENGINE.md) | Dependency planner, sequential orchestrator, integration tests | #3 |
| [5: CLI and CI](sprints/SPRINT_05_CLI_CI.md) | `agentctl` commands, logging, exit codes, GitHub Actions | #4 |
| [6: Natural-language intent](sprints/SPRINT_06_GENERIC_NATURAL_LANGUAGE_INTENT.md) | Optional Anthropic intent extraction and metadata-based validation | #5 |
| [7: Clothes adviser polish](sprints/SPRINT_07_CLOTHES_ADVISER_POLISH.md) | Office, business-casual, and activity aliases; no core changes | #6 |

## Design decisions

### Keep the framework independent of the example application

Weather, clothing rules, and wardrobe queries belong to their respective plugins, not `agentctl-core`. Agents declare capabilities through `requires` and `produces`, and Python entry points register them independently. Adding an unrelated reading-time agent demonstrated that the existing framework could discover and run another domain without core changes. See [Extending](EXTENDING.md).

This modular structure requires installing the core and plugin distributions separately, but it makes the extension mechanism explicit.

### Prefer deterministic planning

The capability planner resolves dependencies from declared metadata. It can detect missing inputs, cycles, and competing producers, and does not need an LLM to produce execution steps. Named workflows retain their declared step order; generated workflows derive the order from the requested output.

Sprint 6 added optional natural-language input. Anthropic extracts a goal and parameters from plugin metadata, but validation, planning, and execution remain deterministic. This avoids giving the model direct authority over workflow steps, at the cost of supporting only capabilities that plugins explicitly declare.

### Use one sequential executor

Named and generated workflows both produce a `WorkflowPlan` consumed by the same `SequentialOrchestrator`. For the sample workflow, weather → clothing advice → wardrobe matching is a dependency chain, so parallel execution would not help. The engine stops on failure rather than attempting retries or recovery.

### Favor a reproducible prototype

SQLite keeps the wardrobe example self-contained, and Open-Meteo provides real external data without a paid weather service. The Anthropic SDK is an optional `[llm]` dependency: named and goal-based workflows do not need an API key. Automated tests replace network calls and use temporary databases, so GitHub Actions runs without secrets.

## Issues uncovered during testing

Live Sprint 6 testing showed that the language model sometimes omitted the required `activity` field. Investigation led to clearer intent instructions and a structured-output schema with parameter keys in catalog order. A subsequent live request succeeded.

Sprint 7 exposed a separate metadata detail: advertising equivalent spellings such as `outdoor_walk` and `outdoor walk` would make generic normalization ambiguous. The agent advertises distinct aliases and lets formatting normalization handle equivalent spellings.

During the final documentation pass, tests were found to assume that no additional plugins were installed. Those assumptions were corrected without changing production discovery behavior. The suite subsequently passed both with and without an independently installed reading-time plugin.

## Scope and trade-offs

This is a single-process prototype, not a production workflow platform. It has sequential execution, per-run memory and events, standard logging, and a shared sample wardrobe. It does not implement user isolation, persistent sessions, retries, parallel execution, RAG, or interactive chat. These boundaries and potential extensions are described in [Limitations](LIMITATIONS.md).

The [master plan](../AGENTIC_WORKFLOW_FRAMEWORK_MASTER_PLAN.md) is a historical planning artifact; when its proposed layout or behavior differs from the implementation, the source code and [Architecture](ARCHITECTURE.md) describe the final design.
