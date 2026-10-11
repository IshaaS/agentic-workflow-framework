# Testing

```bash
python -m pytest -q                      # full suite (from the repository root, in the installed environment)
python -m pytest -q tests/test_planner.py
```

Install the five distributions first, as described in the
[README](../README.md#quick-start). Install `./framework[llm]` too if you want
the Anthropic adapter tests to run instead of being skipped. The suite needs
no API keys, network access or pre-created database.

## What runs offline and what doesn't

| Kind | Network | Where |
|---|---|---|
| Automated tests (local and CI) | Never; blocked by a fixture | `tests/` |
| Manual structured runs (`--goal`, named workflow) | Open-Meteo only | Your shell |
| Manual `--request` runs, `scripts/debug_intent.py` | Open-Meteo and the Anthropic API (paid, needs `ANTHROPIC_API_KEY`) | Your shell |

No live Anthropic or Open-Meteo request is part of the automated tests or
GitHub Actions.

## Test organization

| File | Covers |
|---|---|
| `test_sdk.py` | SDK dataclasses, `BaseAgent` contract, `RuntimeContext` defaults, no logging handlers on import |
| `test_registry.py` | Agent and workflow registries: uniqueness, type checks, sorting |
| `test_discovery.py` | Entry points declared by the installed distributions, namespace packages, discovery errors, no plugin references in the core |
| `test_weather_agent.py` | Open-Meteo parsing, current local hour, WMO code mapping, HTTP/timeout/malformed-response errors |
| `test_clothes_agent.py` | Clothing rules across a weather grid, office/business_casual, aliases and normalization, rejection messages, manifest values |
| `test_shelf_agent.py` | Schema, idempotent seeding, matching and fallbacks, SQL parameter binding, missing/uninitialized database errors, `agentctl-shelf-init` |
| `test_agent_contracts.py` | Each agent's output is valid input for the next; every recommendable type exists in the seed wardrobe |
| `test_planner.py`, `test_orchestrator.py` | Planning and execution with test-local fake agents (no plugins, no I/O): ordering, cycles, ambiguity, conflicts, events, failures |
| `test_workflow_integration.py` | Discovered plugins → generated and named plans → orchestrator, with fake weather HTTP and a seeded SQLite file |
| `test_cli.py` | `agentctl` in-process and as an installed subprocess: output, logging to stderr, exit codes, error messages |
| `test_intent_catalog.py`, `test_intent_validation.py`, `test_intent_normalization.py` | Catalog derivation from metadata, strict validation, formatting-only canonicalization, prompt wording |
| `test_anthropic_intent.py` | The Anthropic adapter with a replaced SDK client: request parameters, schema, parsing, error translation, no secrets in logs |
| `test_cli_request.py` | `--request` with a fake provider through real discovery, catalog, validation, planner and orchestrator |
| `test_intent_integration.py` | Cross-domain proof with fake document agents, and the outfit plugins through the Anthropic adapter |
| `test_office_outfit_integration.py` | Sprint 7: office, business_casual and aliases through structured and request modes |

### End-to-end tests

`test_workflow_integration.py`, `test_cli.py`, `test_cli_request.py`,
`test_intent_integration.py` and `test_office_outfit_integration.py` use the
real installed plugins:
- agents and workflows are loaded with `discover_agents` and
  `discover_workflows` from entry points; no registry is built by hand;
- the planner generates
  `weather.forecast → clothes.advise → shelf.match`, or validates
  `outfit_advisor`;
- the orchestrator runs all three agents, and the tests assert on actual
  seeded wardrobe items and the lifecycle events.

Only the weather HTTP transport and, in request mode, the language model are
replaced.

### Other installed plugins

The suite also passes when other plugins are installed in the same
environment:
- **Discovery-based tests:** they assert that the bundled agents, workflow and
  `outfit` goal are present, not that nothing else is installed. For example,
  `outfit_advisor` must appear in the listed workflows.
- **Exact assertions:** tests that need an exact registry, catalog or schema
  build a controlled one. Examples are the fake document agents, and the
  response-schema test, which uses a catalog holding only the discovered
  `outfit` goal.

### Cross-domain tests

These prove that the framework itself is generic:
- **Planner and orchestrator:** `test_planner.py` and `test_orchestrator.py`
  use made-up capabilities unrelated to clothing.
- **Natural-language path:** `test_intent_integration.py` runs a document
  "extract → summarize" goal through the catalog, validator, planner,
  orchestrator and CLI.
- **Source checks:** `test_discovery.py`, `test_cli.py` and
  `test_office_outfit_integration.py` search the core source to confirm it has
  no plugin imports, application names or clothing vocabulary.

## Test doubles and fixtures

All of these are in [tests/conftest.py](../tests/conftest.py) unless noted.

- **`no_network` (autouse):** replaces `socket.connect`, `connect_ex` and
  `getaddrinfo` so that any connection attempt fails the test.
  `test_cli.py::test_network_is_blocked_in_tests` checks that it works.
- **`fake_weather_http`:** replaces `urlopen` in the weather agent's Open-Meteo
  client. It returns a fixed geocoding result and a rainy 22°C forecast for
  every hour from yesterday to tomorrow, and records the hosts that were
  requested.
- **`seeded_db`:** creates a fresh wardrobe in pytest's `tmp_path` with the
  real `initialize_database(..., seed=True)`. Tests point `SHELF_DB_PATH` at
  it.
- **`FakeIntentProvider` (`fake_intent`):** returns a scripted
  `ResolvedIntent` (or raises) and records each call. It is passed to
  `cli.main(..., intent_provider=...)`.
- **Scripted Anthropic client:** `test_anthropic_intent.py`,
  `test_intent_integration.py` and `test_intent_normalization.py` pass a fake
  SDK client to `AnthropicIntentProvider(client=...)`. The real adapter code
  then builds the request and parses a fixed JSON answer. Tests that build real
  SDK exception objects need the `anthropic` package and are skipped without
  it.

## Error scenarios covered

- **Planning:** missing required input, unknown goal or workflow, missing
  capability, cycle, ambiguous provider, steps out of order, repeated step,
  output overwriting an input.
- **Execution:** agent exceptions, missing or undeclared outputs, output
  conflicts, Open-Meteo errors and timeouts, a missing or uninitialized
  wardrobe database.
- **CLI:** malformed or duplicate `--input`, conflicting run modes, plugin load
  failures, a non-JSON result, the exit codes documented in
  [ARCHITECTURE.md](ARCHITECTURE.md#errors-and-exit-codes).
- **Natural language:**
  - missing key or SDK;
  - rejected credentials, rate limits, timeouts and refusals;
  - malformed model answers;
  - an unknown goal or parameter;
  - a value outside the allowed values, which is rejected before any agent or
    HTTP call runs.

## GitHub Actions

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on pushes and
pull requests to `main`, and on manual dispatch, with Python 3.10, 3.11 and
3.12. Each job:
1. installs `./framework[dev,llm]` and the four plugin distributions in
   editable mode;
2. confirms the `anthropic` SDK imports (no key is used);
3. smoke-tests `agentctl --help`, `list agents` and `list workflows`;
4. runs the integration and CLI tests by name
   (`test_workflow_integration.py`, `test_cli.py`, `test_cli_request.py`,
   `test_intent_integration.py`);
5. runs the full suite with `python -m pytest -q`.

The workflow uses no secrets and no services.

## Manual testing

These calls use the network, and they are how live behaviour was checked.

```bash
# Live weather only (no API key):
export SHELF_DB_PATH=./wardrobe.db
agentctl run workflow --goal outfit --input city=Chicago --input activity=office --input style=business_casual
agentctl run workflow --goal outfit --input city=Chicago --input activity=hiking       # exit 4, lists supported activities
agentctl run workflow --goal outfit --input activity=office                            # exit 3, missing 'city'

# Natural language (needs the [llm] extra and ANTHROPIC_API_KEY; each call is billed):
python scripts/debug_intent.py "What should I wear to the office in Chicago? I prefer business casual."
agentctl run workflow --request "What should I wear to the office in Chicago? I prefer business casual."
```

`scripts/debug_intent.py` makes one Anthropic call and runs no agents. It
prints what the model extracted, what was canonicalized and the validation
result, without printing the key or the request text.

## Recorded results

These are the results that have been run and recorded:

| What | Result | Source |
|---|---|---|
| Full suite with only the bundled plugins, and again with the [EXTENDING.md](EXTENDING.md) reading-time plugin also installed (Python 3.11, `[llm]` extra) | 538 passed in both environments | Run while fixing test isolation on the documentation branch |
| CI on `main` after merging Sprint 7 (`ae7c7be`) | Success on Python 3.10, 3.11 and 3.12; 537 passed in each job | [GitHub Actions run 38179268445](https://github.com/IshaaS/agentic-workflow-framework/actions/runs/38179268445) |
| Fresh clone of `main` (`ae7c7be`), new virtual environment, Python 3.11, installed exactly as in the README without the `[llm]` extra | `503 passed, 34 skipped` (Anthropic adapter tests skipped) | Run during this documentation pass |
| Same environment: README quick-start and run commands, live Open-Meteo | All succeeded. The office/business_casual run for Chicago (clear, 20.3°C) chose polo, chinos, no outerwear and dress shoes. `activity=hiking` exited 4; a missing `city` exited 3; `--request` without a key exited 5 | Run during this documentation pass |
| Live `--request "What should I wear for an outdoor walk in Chicago?"` with `claude-opus-5-5` | Exit 0. The model returned `activity=outdoor_walk` and left `style` unset; the planner generated the three-step plan; items 3, 8, 12 and 17 were selected for 18.2°C | Run by the author during Sprint 6 (see [AI_USAGE.md](AI_USAGE.md#debugging-lessons)) |
| Live office/business-casual `--request` after Sprint 7 | Succeeded end to end through Anthropic, validation, planning, all three agents and SQLite | Reported by the author; the output is not stored in the repository |

Python 3.10 has only been run in CI. Test counts change as tests are added, so
run the suite rather than relying on the numbers above.
