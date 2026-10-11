# Development approach and design decisions

This document explains how the project was built and why it is shaped the way
it is. For how it works, see [ARCHITECTURE.md](ARCHITECTURE.md). For who did
what, including the AI tools, see [AI_USAGE.md](AI_USAGE.md).

## Requirements and scope

The original assessment text is not stored in this repository. Its
requirements were captured as an "assessment brief" in section 1 of the
[master plan](AGENTIC_WORKFLOW_FRAMEWORK_MASTER_PLAN.md), which was written
before implementation:
- a Python SDK, CLI, agent manifests and a runtime context (session, events,
  execution memory);
- independently developed agents distributed as separate namespace packages
  and discovered dynamically through a plugin mechanism;
- simplified observability through logging;
- three working agents: a weather provider calling a real external API, a
  clothes adviser, and a personal shelf manager backed by a database;
- a generic sequential workflow runner;
- an `agentctl run workflow` entry point that can list agents (with
  manifests) and workflows, and run a workflow by name or from a generated
  plan;
- an end-to-end integration test (discover plugins → plan with all three
  agents → execute → useful output) running in GitHub Actions;
- documented assumptions and a detailed disclosure of AI-assisted coding.

The plan treated RAG, cross-call session memory, an event bus and interactive
chat as optional stretch goals. It also recorded the main interpretation: the
"router" is a deterministic planner driven by declared capabilities, and an
LLM is not required.

The master plan is kept as a historical planning document. Its "Status" and
"Next action" lines describe the project before Sprint 1. Some proposed
details changed during implementation:
- plugins live under `agents/`, not `plugins/`;
- there is no separate `observability.py`;
- the disclosure is in `docs/AI_USAGE.md`;
- `RuntimeContext.results` is keyed by output name, not by step.

## Incremental, sprint-based delivery

Each sprint had a bounded specification with explicit contracts, exclusions,
tests and acceptance criteria. The specification was handed to the coding
assistant. The resulting branch was reviewed and merged through a pull request
before the next sprint started. The specifications are kept unchanged in
[docs/sprints/](sprints/).

| Sprint | Specification | Delivered | PR |
|---|---|---|---|
| 1 | [Core SDK contracts](sprints/SPRINT_01_CORE_SDK.md) | `agentctl-core` with `BaseAgent`, `AgentManifest`, `Capability`, `RuntimeContext`, `WorkflowDefinition`, `WorkflowPlan` | none (on `main` before PR #1) |
| 2 | [Plugin discovery](sprints/SPRINT_02_PLUGIN_DISCOVERY.md) | Entry-point discovery, agent and workflow registries, four plugin distribution shells in shared namespaces | #1 |
| 3 | [Working agents](sprints/SPRINT_03_AGENTS.md) | Open-Meteo weather agent, rule-based clothes adviser, SQLite shelf manager with seed data | #2 |
| 4 | [Workflow engine](sprints/SPRINT_04_WORKFLOW_ENGINE.md) | Capability planner (generated and named plans), sequential orchestrator, events, typed errors, end-to-end integration tests | #3 |
| 5 | [CLI and CI](sprints/SPRINT_05_CLI_CI.md) | `agentctl` CLI, exit codes, stderr logging, GitHub Actions matrix, first README | #4 |
| 6 | [Natural-language intent](sprints/SPRINT_06_GENERIC_NATURAL_LANGUAGE_INTENT.md) | Optional `--request` mode: metadata-driven goal catalog, Anthropic adapter, generic validation, then the unchanged planner | #5 |
| 7 | [Clothes adviser polish](sprints/SPRINT_07_CLOTHES_ADVISER_POLISH.md) | `office` activity, `business_casual` style, activity aliases, advertised in the manifest; no framework changes | #6 |

A final documentation pass, covering this document and the others in `docs/`,
followed Sprint 7.

Sprint 1 was committed directly to `main`. Sprints 2–7 were merged through
pull requests #1–#6. All seven sprint specifications are in
[docs/sprints/](sprints/), and none are missing. Implementation handoff reports
were deliberately not kept in the repository. The Sprint 6 handoff was briefly
committed, then replaced by its specification, and is still in the Git
history.

## Key design decisions

### Deterministic planning instead of LLM-generated plans

The planner derives the step order from each capability's `requires` and
`produces`. For the same installed plugins and inputs it always produces the
same plan, it can explain its failures (missing input, missing capability,
cycle, ambiguity), and it can be tested without a model.

When natural-language support was added in Sprint 6, the LLM's role was kept
deliberately narrow: it picks a goal and extracts parameter values from a
catalog, and the framework validates them. It never chooses agents or steps.
Model mistakes therefore lead to a clear validation error before anything
runs, never to a wrong or unsafe execution plan. The cost is that the system
can only do what installed capabilities declare. It cannot improvise new
workflows.

### Independently packaged agents

Each agent is its own distribution with its own `pyproject.toml` and entry
point, inside a shared PEP 420 namespace. This matches the requirement for
independently developed plugins. It also lets a missing or broken agent
surface as a clear discovery or planning error, and lets tests prove that the
core works with plugins it has never imported. The cost is a longer install
command, five editable installs instead of one, and a required install order
(core first).

### One plan format and one executor

Named workflows and generated plans both become a `WorkflowPlan` and run
through the same `SequentialOrchestrator`. Named workflows are validated in
their declared order but never reordered, so a workflow author's intent is
preserved and mistakes are reported, not silently fixed.

### Sequential execution and SQLite

- **Sequential execution:** the demo workflow is a strict dependency chain
  (weather → advice → items), so parallelism would add complexity without
  benefit.
- **SQLite:** it ships with Python, needs no server, can be created per test
  in a temporary directory, and is enough for a single-user demo wardrobe.

Both choices are easy to replace behind the same agent contract if
requirements grow.

### Anthropic as an optional dependency

Structured commands (`--goal`, named workflows) need no API key and no LLM
SDK.
- **Packaging:** the Anthropic SDK is an optional `[llm]` extra, imported only
  when `--request` is used.
- **Without a key:** a missing key gives exit code 5 and a message showing the
  structured commands.
- **Swappable provider:** the provider is behind a one-method
  `IntentProvider` protocol, so tests use a fake and another provider could be
  added without changing the planner or orchestrator.

This keeps the mandatory functionality reproducible offline and in CI.

### Generic core, application knowledge in plugins

The core contains no weather, clothing or wardrobe code. Clothing-specific
facts, such as supported activities, aliases and goal descriptions, are
declared by plugins as metadata (`InputSpec`, `GoalSpec`). Sprint 7
demonstrated this: new activities, styles and aliases became available in
both structured and natural-language modes by changing only the clothes agent
package.

### How new agents fit without redesign

A new agent declares the keys it consumes and produces and registers an entry
point. The planner then includes it whenever a requested goal needs one of its
outputs. A new named workflow is another small distribution. Neither requires
changes to the core. See [EXTENDING.md](EXTENDING.md) for a worked
non-clothing example.

## Notable issues found during development

- **Sprint 6 live testing:** the model did not return `activity` for "What
  should I wear for an outdoor walk in Chicago?". Two causes were found: prompt
  wording that discouraged mapping a phrase to an allowed value, and a response
  schema whose all-optional, sorted keys let the model skip `activity`. Both
  were fixed (`9cbf33a`, `98941df`), and a later live run succeeded. Details
  are in [AI_USAGE.md](AI_USAGE.md#debugging-lessons).
- **Sprint 7 aliases:** advertising both `outdoor_walk` and `outdoor walk`
  would have made the generic formatting canonicalizer ambiguous and broken an
  existing flow. So only aliases that differ after normalization (`walk`,
  `walking`, `work`, `office_meeting`) are advertised.

## Implemented prototype versus production improvements

What exists is a single-process prototype with:
- deterministic planning;
- sequential, fail-fast execution;
- in-memory events and per-run memory;
- standard-library logging;
- one shared SQLite wardrobe;
- an optional one-shot LLM intent step.

Production-oriented improvements are listed separately in
[LIMITATIONS.md](LIMITATIONS.md#possible-future-enhancements-not-implemented).
They include per-user data, persistence, retries, richer schemas, an event
bus, chat and plugin trust controls. None of them are implemented.
