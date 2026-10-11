# Limitations and future enhancements

This is a small prototype. The first section describes what the current code
does and doesn't do. The last section lists possible enhancements, none of
which are implemented. Several of them, such as RAG, cross-run session memory,
an event bus and interactive chat, were recorded as optional stretch goals in
the [master plan](AGENTIC_WORKFLOW_FRAMEWORK_MASTER_PLAN.md), not as
requirements.

## Current limitations

### Shared wardrobe and lack of user-specific inventory

- **One database:** the Shelf Manager uses a single SQLite wardrobe database,
  selected with `SHELF_DB_PATH` (or the `ShelfAgent(db_path=...)` constructor
  argument).
- **Shared sample items:** the demo uses 19 seeded sample clothing items. They
  are shared sample inventory, not clothing associated with individual user
  accounts.
- **No users:** there is no user authentication, no per-user inventory
  isolation and no user-specific wardrobe selection.
- **Session IDs:** runtime session IDs identify workflow executions. They are
  not user identities.
- **Editing:** the only built-in way to change the wardrobe is
  `agentctl-shelf-init` (create the table and add the seed items). There is no
  inventory API or CRUD command; other changes need direct SQL.

### Clothing rules and vocabulary

The clothes adviser accepts the following values (from
`agents/clothes-agent/src/agentctl_agents/clothes/agent.py`):

| Input | Canonical values | Also accepted |
|---|---|---|
| `activity` (required) | `outdoor_walk`, `theatre`, `casual`, `office` | `walk`, `walking` → `outdoor_walk`; `work`, `office_meeting` → `office` |
| `style` (optional) | `casual` (default), `business_casual`, `formal` | — |

- **Normalization:** the agent ignores case and treats runs of spaces, hyphens
  and underscores as one underscore, so `Office Meeting` and `business casual`
  are accepted. Anything else is rejected with the list of canonical values.
  There is no fuzzy matching and no open-ended activity support.
- **Request mode:** values must be among the advertised `allowed_values`. The
  canonical values plus `walk`, `walking`, `work` and `office_meeting` are
  advertised, and formatting variants are canonicalized.
- **Structured mode:** in `--goal` or named runs, values are checked by the
  agent when it runs. An unsupported activity is therefore reported at the
  clothes step (exit 4), after the weather call.

The rules are deterministic and small:
- **Weather bands:** cold is below 10°C, mild is 10–20°C, and warm is above
  20°C.
- **Weather flags:**
  - wet: rainy or stormy, or a chance of rain of at least 50%;
  - snowy;
  - windy: at least 30 km/h.
- **Dress level:**
  - relaxed: a walk or casual activity in `casual` style;
  - smart: theatre or office below `formal`, or a walk or casual activity in
    `business_casual` or `formal` style;
  - formal: theatre or office in `formal` style.
- **Rain:** theatre is treated as indoors, so rain alone doesn't add a rain
  jacket. Office assumes a commute, so rain adds a rain jacket and cold rain
  adds boots.
- **Output:** each category (`top`, `bottom`, `outerwear`, `footwear`) is a
  list of clothing types, best first. An empty `outerwear` list means no
  jacket is needed.

**What the rules don't consider:** the shelf manager matches by clothing type
only. It picks the lowest-ID available item of the first preferred type and
ignores colour, coordination and personal preferences beyond `style`. It
gives no explanation for its choices; a category with no match is `null`.

### Natural-language requests

- **One-shot, single goal:** there are no follow-up questions, no chat and no
  conversation history.
- **String parameters:** `InputSpec.value_type` must be `"string"`, and the
  validator only checks for non-empty strings and exact allowed values. There
  are no numbers, dates, ranges or nested values.
- **Meaning:** it comes only from the model and the declared `allowed_values`.
  The framework's own mapping is limited to formatting
  (`Outdoor walk` → `outdoor_walk`).
- **Live testing:** live behaviour depends on the model. Only a small number
  of live requests have been run (see [TESTING.md](TESTING.md#recorded-results)).
  Automated tests use scripted answers.
- **Costs and dependencies:** request mode needs `ANTHROPIC_API_KEY`, network
  access and the optional `anthropic` SDK. Each request is a billed API call
  with a 30-second timeout and one SDK retry.

### Planning and execution

- **Exact key matching:**
  - capabilities connect only through identical data key names (`weather`,
    `clothing_requirements`);
  - there are no schemas, types or versioning for the values that pass
    between agents;
  - each agent validates its own inputs.
- **One producer per key:** if two installed capabilities produce a key that a
  plan needs, planning fails with `AmbiguousProviderError`. Providers are not
  ranked or selected. Duplicate agent or capability names are rejected at
  discovery.
- **Sequential only:** steps run one at a time in a single process. There is
  no branching, looping, parallelism or conditional steps.
- **No retries or recovery:**
  - the orchestrator stops at the first failure;
  - the weather agent makes one attempt with a 10-second timeout;
  - there is no resume, checkpointing or compensation.
- **One goal per run.**

### Plugins and security

- **Trusted plugins only:** discovery imports and runs code from every
  installed `agentctl.agents` and `agentctl.workflows` entry point. There is
  no sandboxing, signing or permission model.
- **Not on PyPI:** plugins depend on `agentctl-core`, which is not published
  on PyPI. Install `./framework` before installing plugins.
- **One plugin set per environment:** the repository's test suite assumes
  only the bundled plugins are installed (see
  [EXTENDING.md](EXTENDING.md#5-test-the-plugin)).

### Storage, network and environment

- **SQLite:** a local, single-file store, suitable for a demo. It is not
  multi-user, networked storage.
- **Open-Meteo:** live runs need network access.
  - The first geocoding match is used, so ambiguous city names may resolve to
    an unexpected place.
  - Only the current local hour is read.
  - Open-Meteo's free API is for non-commercial use.
- **Python versions:** 3.10 is verified only in CI. Local runs used 3.11 and
  3.12.

### Observability, events and memory

- **Logging:** plain standard-library logs to stderr. There are no metrics,
  tracing or log shipping.
- **Events:** an in-memory list on the `RuntimeContext`. They are not
  published to a bus and are discarded when the process exits; the CLI does
  not print them.
- **Memory:** `RuntimeContext.memory` exists for a single run, but none of the
  bundled agents use it. Nothing persists between runs, and the CLI has no
  `--session-id` option.

## Possible future enhancements (not implemented)

- **Multi-user wardrobes:** user IDs on wardrobe records, per-user selection,
  authentication, and an inventory API or CRUD commands.
- **Richer wardrobe data:** more items and attributes such as warmth,
  waterproofing, formality and colour, used for better matching and for
  explanations.
- **Richer input schemas:** typed parameters (numbers, dates, enums with
  descriptions) and, if needed, typed data contracts between capabilities.
- **More independent agents:** for example a calendar agent that supplies the
  activity, or a packing-list agent, added as separate distributions.
- **Workflow execution:** conditional steps, parallel independent steps,
  per-step retries with backoff, timeouts, and selection among several
  providers.
- **Persistence:** stored run history and events, and session memory that
  carries over between invocations with the same session ID.
- **RAG:** a retrieval interface, for example for wardrobe descriptions or
  style guidance.
- **Event bus:** typed in-process publish/subscribe of lifecycle events in
  place of the plain list.
- **Interactive chat:** an `agentctl chat` command that asks follow-up
  questions when required parameters are missing.
