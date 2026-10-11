# Limitations and future enhancements

This is a working prototype intended to demonstrate independent agents, capability-based planning, and end-to-end execution. The following boundaries are intentional; the enhancements listed at the end are not implemented.

## Shared sample wardrobe

The Shelf Manager reads one SQLite database configured by `SHELF_DB_PATH` or `ShelfAgent(db_path=...)`. The demo seeds **19 sample items**. Items are not associated with individual users, and session IDs identify workflow runs, not user accounts. There is no authentication, per-user inventory selection, or inventory-management API. Beyond the seed command (`agentctl-shelf-init`), inventory changes require direct SQL.

Matching uses clothing type and preference order. It selects the lowest-ID available item of the first matching type, without considering color coordination or personal history. Categories with no matching item return `null`.

## Clothes Adviser

The agent uses deterministic rules rather than open-ended fashion reasoning.

| Input | Supported values |
|---|---|
| Required `activity` | `outdoor_walk`, `theatre`, `casual`, `office` |
| Activity aliases | `walk`, `walking` → `outdoor_walk`; `work`, `office_meeting` → `office` |
| Optional `style` | `casual` (default), `business_casual`, `formal` |

Activity and style values ignore case and normalize spaces, hyphens, and underscores. Unsupported values are rejected; there is no fuzzy matching. Weather thresholds and activity-specific assumptions are intentionally simple. For example, office clothing assumes a commute, while theatre is treated as indoors.

In named or `--goal` workflows, an invalid activity is rejected when the Clothes Adviser runs, potentially after a weather lookup. In `--request` mode, advertised allowed values are checked before execution.

## Natural-language requests

`--request` handles **one goal per invocation**, with string parameters only. There is no conversation history, clarification loop, or interactive chat. The Anthropic provider interprets the request; the generic framework only normalizes equivalent formatting and validates declared values. Model responses can still be incorrect or incomplete.

Request mode requires an Anthropic API key, the optional SDK, network access, and a billed API call. Structured runs do not require Anthropic.

## Planning and execution

- Capabilities connect through exactly matching `requires`/`produces` data-key names. There is no shared schema or versioning for values passed between agents.
- If multiple capabilities can produce a required key, planning reports ambiguity instead of choosing automatically.
- Execution is sequential and single-process, with no branches, parallel steps, orchestration retries, checkpoints, or resume behavior.
- The first agent failure stops the workflow. Agents are responsible for validating their own inputs.

## Security, storage, and observability

- Installed entry-point plugins run as trusted Python code. There is no sandbox, signing, or plugin permissions model.
- SQLite is local storage rather than a multi-user service. The weather agent requires network access to Open-Meteo; ambiguous city names use the first geocoding match.
- Observability is standard-library logging to stderr, plus in-memory lifecycle events. There are no distributed traces, metrics, or durable event records.
- `RuntimeContext.memory` is available during one run, but the sample agents do not use it. Memory and events do not survive process exit, and the CLI does not accept a persistent `--session-id`.
- The framework and plugins are installed from this repository, not published as packages on PyPI.

## Possible future enhancements (not implemented)

Potential next steps include per-user wardrobes and inventory CRUD, richer garment attributes and matching explanations, typed data contracts, persistence and session reuse, retries and timeouts per step, conditional or parallel workflows, plugin security controls, more independent agents, a RAG interface, an event bus, and interactive chat. RAG, cross-run session memory, event-driven communication, and chat were stretch goals in the assessment, not core functionality claimed here.
