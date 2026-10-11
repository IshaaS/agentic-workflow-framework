# Sprint 03 — Working Weather, Clothes Adviser, and Shelf Agents

**Project:** Agentic Workflow Framework  
**Status:** Scope locked; ready for AI-assisted implementation  
**Read alongside:** `AGENTIC_WORKFLOW_FRAMEWORK_MASTER_PLAN.md`, `SPRINT_02_PLUGIN_DISCOVERY.md`, and the **actual merged repository**  
**Goal:** Replace the three Sprint 2 placeholder `run()` implementations with small, useful, independently testable agents. Keep the generic core and plugin architecture unchanged.

> **Coding-assistant instruction:** Implement **only Sprint 03**. Treat the merged Sprint 1/2 source and public contracts as the authority. Do not implement the capability planner, orchestrator, generic `agentctl` CLI, CI pipeline, LLM resolver, RAG, event bus, or chat. Avoid unrelated refactoring. Execute all tests and provide a detailed handoff.

## 1. Existing foundation (do not change)

- Generic core distribution: `framework/` → Python import `agentctl_core`.
- Public interfaces:
  ```python
  class BaseAgent(ABC):
      @property
      @abstractmethod
      def manifest(self) -> AgentManifest: ...

      @abstractmethod
      def run(self, inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]: ...

  @dataclass
  class Capability:
      name: str
      requires: list[str]
      produces: list[str]
  ```
- `RuntimeContext` has `session_id`, `workflow_id`, `inputs`, `results`, `memory`, `events`, and `logger`.
- Agent entry-point group: `agentctl.agents`. Workflow entry-point group: `agentctl.workflows`.
- Existing independent agent distributions and import paths:
  - `agents/weather-agent` → `agentctl_agents.weather.agent:WeatherAgent`
  - `agents/clothes-agent` → `agentctl_agents.clothes.agent:ClothesAgent`
  - `agents/shelf-agent` → `agentctl_agents.shelf.agent:ShelfAgent`
- Independent workflow distribution: `workflows/outfit-workflow` → existing `outfit_advisor` definition.
- Preserve these manifests **exactly**:

  | Agent | Capability | Requires | Produces |
  |---|---|---|---|
  | `weather_provider` | `weather.forecast` | `city` | `weather` |
  | `clothes_adviser` | `clothes.advise` | `weather`, `activity` | `clothing_requirements` |
  | `shelf_manager` | `shelf.match` | `clothing_requirements` | `outfit` |

- Existing core registry and entry-point discovery must remain functional. Package shells remain separate Python namespace distributions (no `agentctl_agents/__init__.py`).

## 2. Overall input/output contract

Each agent accepts **top-level keys** via `inputs`, and returns a dictionary with its manifest's **top-level produced key**. The orchestrator added later will merge produced keys into working execution inputs for subsequent steps.

**Illustrative flow:**

```python
weather_agent.run({"city": "Dallas"}, context)
# -> {"weather": {"temperature_c": 22.0, "condition": "rainy",
#                  "precipitation_probability": 65, "wind_speed_kmh": 15.0}}

clothes_agent.run({
    "weather": {"temperature_c": 22.0, "condition": "rainy",
                "precipitation_probability": 65, "wind_speed_kmh": 15.0},
    "activity": "outdoor_walk",
    "style": "casual",  # optional
}, context)
# -> {"clothing_requirements": {"top": ["t_shirt", "polo"],
#      "bottom": ["pants", "jeans"],
#      "outerwear": ["rain_jacket", "light_jacket"],
#      "footwear": ["walking_shoes", "sneakers"]}}

shelf_agent.run({"clothing_requirements": { ... }}, context)
# -> {"outfit": {"top": {...}, "bottom": {...},
#                 "outerwear": {...} or None, "footwear": {...}}}
```

These values are **examples**, not a requirement to hardcode the same recommendations for all weather. All component implementations should validate malformed inputs with clear errors and **must not return invented success data when a required dependency fails**.

## 3. Weather Agent

### Responsibility

Use an actual external weather API to obtain the current-hour forecast for a supplied city, then return a small normalized weather object, decoupled from upstream API field names.

### Inputs and output

- Input: `city`: nonempty string.
- Output: `{"weather": {"temperature_c": float, "condition": str, "precipitation_probability": int, "wind_speed_kmh": float}}`.
- `condition`: use a documented limited vocabulary, e.g. `clear`, `cloudy`, `rainy`, `snowy`, `stormy`, and `unknown`. Be consistent with clothing rules.
- Temperature is **Celsius**, precipitation probability **0–100 percent**, wind speed **km/h**.
- Current-hour forecast in the **destination's local timezone**, not the computer's timezone. No date/time CLI input in the MVP.

### API and implementation

Use **Open-Meteo**:

1. Geocode `city` using `https://geocoding-api.open-meteo.com/v1/search` to get coordinates (e.g., `name=<city>&count=1`).
2. Fetch `https://api.open-meteo.com/v1/forecast` using the returned coordinates, `timezone=auto`, and hourly variables `temperature_2m,weather_code,precipitation_probability,wind_speed_10m` with explicit compatible units (`temperature_unit=celsius`, `wind_speed_unit=kmh`).
3. Select the forecast for the **current local hour** using the response timezone and hourly time values; don't assume the first hourly row is current. Consider requesting a limited hourly range (or filtering the returned list) and handling timestamp/timezone mismatches defensively.
4. Map WMO weather codes to the limited `condition` vocabulary and normalize numeric values.
5. Return only the agreed output data; optional extra metadata may be logged rather than added to the stable response.

Use a small HTTP library (`requests` or Python standard library) with explicit timeouts, check HTTP status, and validate required response fields. Keep dependencies **inside the weather-agent distribution** instead of adding unnecessary core dependencies. Do not silently use static weather on live API failures. The API service's published free/non-commercial usage conditions apply.

**Errors:** empty/invalid city → `ValueError`; unknown city, HTTP failure/timeout, or malformed upstream payload → clear descriptive exception (`WeatherAPIError` or similar is acceptable). The exception should be loggable by a future orchestrator.

**Reference:** https://open-meteo.com/en/docs and https://open-meteo.com/en/docs/geocoding-api .

## 4. Clothes Adviser

### Responsibility

Produce sensible **types of clothing**, not specific inventory items. Implement deterministic Python rules, **not an LLM**.

### Inputs

- `weather`: normalized weather dictionary from Section 3.
- `activity`: required, one of `outdoor_walk`, `theatre`, `casual`.
- `style`: optional, `casual` or `formal`, default `casual`. This is an **optional input**, so it does **not** alter the manifest's required `requires` list.

### Output

```python
{
    "clothing_requirements": {
        "top": ["t_shirt", "polo"],
        "bottom": ["pants", "jeans"],
        "outerwear": ["rain_jacket", "light_jacket"],
        "footwear": ["walking_shoes", "sneakers"],
    }
}
```

- These are preference-ordered lists, best fit first; do not use free-form natural-language descriptions.
- Output always has the same four keys, each containing `list[str]`.
- Empty `outerwear` list means no jacket is required; all other categories should normally have at least one option.
- Keep a **small controlled vocabulary**, aligned exactly with sample SQLite `clothing_type` values.
- Reasonable rules: cold (<10°C) favors heavier layers; mild (10–20°C) favors long sleeves/light outerwear; warm (>20°C) favors lighter clothes. Heavy wind may justify a layer. Rain/rain probability should favor rain protection for outdoor activities. Theatre preferences should be dressier than an outdoor walk; the `style` choice may influence suggestions. Define and document precise thresholds and precedence in code/tests.
- No complicated outfit scoring, ML model, external API, or additional package dependencies required.

**Validation:** reject missing/malformed weather data and unsupported activity/style with descriptive `ValueError`. Guard against a silent mismatch between the weather condition vocabulary and adviser rules.

## 5. Personal Shelf Manager

### Responsibility

Read an actual SQLite clothing inventory, then choose the highest-ranked **available** clothing item in each category based on the adviser's ordered preferences. The agent does **not** decide what is weather-appropriate.

### Input/output

Input:

```python
{
    "clothing_requirements": {
        "top": ["t_shirt", "polo"],
        "bottom": ["pants", "jeans"],
        "outerwear": ["rain_jacket", "light_jacket"],
        "footwear": ["walking_shoes", "sneakers"],
    }
}
```

Output:

```python
{
    "outfit": {
        "top": {"id": 1, "name": "Blue polo", "clothing_type": "polo", "color": "blue"},
        "bottom": {"id": 3, "name": "Black jeans", "clothing_type": "jeans", "color": "black"},
        "outerwear": {"id": 4, "name": "Gray rain jacket", "clothing_type": "rain_jacket", "color": "gray"},
        "footwear": {"id": 5, "name": "Walking shoes", "clothing_type": "walking_shoes", "color": "black"},
    }
}
```

An unmatched category returns `None`, not a fake item. An empty optional `outerwear` preference returns `None` without error. Preserve all four category keys; do not silently omit missing required categories.

### SQLite schema

Use Python built-in `sqlite3` with exactly one essential table:

```sql
CREATE TABLE IF NOT EXISTS clothing_items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    clothing_type TEXT NOT NULL,
    color TEXT NOT NULL,
    available INTEGER NOT NULL DEFAULT 1
);
```

Categories: `top`, `bottom`, `outerwear`, `footwear`.

Matching algorithm per category:

1. Iterate preferred `clothing_type` values in order.
2. For each type, query available rows with matching `category` **and** `clothing_type` (`available = 1`).
3. When multiple rows match, choose the one with the lowest `id` for deterministic behavior.
4. Choose the first preferred type having a match.
5. If no match, return `None` for that category; do not silently substitute unrelated clothing.

Use parameterized SQL queries; do not interpolate user-provided values into SQL. Open and close database connections safely (including on exceptions). Do not require an external database server.

### Configuration

- Support `SHELF_DB_PATH` environment variable to choose the database file.
- A documented simple default is allowed, but **avoid a working-directory-dependent database implicitly created on agent `run()`**. It should fail clearly if the configured database does not exist or lacks the table; document how to initialize it.
- Tests must use temporary independent databases.

### Explicit database initialization (selected Option B)

Create a standalone setup entry point **owned by the shelf distribution**, not the generic `agentctl` CLI:

```bash
agentctl-shelf-init --db ./wardrobe.db --seed
```

- Add `[project.scripts] agentctl-shelf-init = "...:main"` to `agents/shelf-agent/pyproject.toml` with the actual implementation path.
- `--db` chooses the database path; `--seed` opt-in inserts a small demo wardrobe.
- No implicit demo seeding during agent runs.
- Repeated `--seed` must be idempotent: no duplicate seed rows; preserve existing rows. Use deterministic seed IDs or a uniqueness/upsert policy documented in the source; do not overwrite user-edited data on subsequent seeding.
- Sample inventory must include at least one valid outfit under the weather/clothing fixtures used in tests, plus unavailable and fallback-choice items to prove matching logic.
- For normal operation, either `SHELF_DB_PATH=./wardrobe.db` or an explicit constructor parameter may supply the path. **Preserve the zero-argument `ShelfAgent()` constructor**, since Sprint 2 entry-point discovery instantiates it without arguments.

## 6. Logging and context

- Keep framework-wide logging configuration and workflow lifecycle logs for a later sprint.
- Agents may call `context.logger.info(...)`, `warning(...)`, or `error(...)` for useful events such as forecast lookup and database matching; never configure global handlers inside agent packages.
- Do not expose credentials, sensitive data, or entire API payloads in logs.
- Agents should **return** their produced data rather than relying on `context.results` side effects. The orchestrator (Sprint 4) will merge outputs and manage lifecycle events.
- Do not implement persistent session memory or the optional event bus.

## 7. Suggested files (adjust to actual source layout; do not reorganize existing distributions)

```text
agents/
  weather-agent/
    pyproject.toml
    src/agentctl_agents/weather/agent.py
    # optional weather API helper module
  clothes-agent/
    pyproject.toml
    src/agentctl_agents/clothes/agent.py
  shelf-agent/
    pyproject.toml
    src/agentctl_agents/shelf/agent.py
    src/agentctl_agents/shelf/db.py            # schema, initialization, matching helpers
    src/agentctl_agents/shelf/cli.py           # agentctl-shelf-init entry point

tests/
  test_weather_agent.py
  test_clothes_agent.py
  test_shelf_agent.py
  test_agent_contracts.py                  # optional small cross-agent data-shape check
```

Update package READMEs and dependency declarations where necessary. Do not move manifests into core or create `__init__.py` in the shared namespace root. Existing independently registered workflow definition remains unchanged.

## 8. Tests and acceptance criteria

### Weather agent

- Valid city returns normalized weather using **mocked** geocoding and forecast HTTP responses.
- Forecast selection picks the **current local hour**, not always the first hourly entry.
- Test weather-code mapping and numeric units.
- Blank city raises `ValueError`; unknown city, network timeout/failure, bad/missing fields produce descriptive errors.
- **No live network dependency in automated tests.** Live smoke check is optional, separate, and documented.

### Clothes adviser

- At least cold, mild, warm, rainy outdoor, and theatre scenarios.
- Optional style default works; invalid activities/weather/style fail clearly.
- All four categories use preference-ordered lists; optional outerwear can be `[]`.
- Recommendations use clothing types present in the seeded vocabulary.

### Shelf manager

- Explicit setup command creates the database and optional seed records.
- Re-running seed does not duplicate or overwrite existing items.
- Chooses preferred available type; falls back to second preference when first absent/unavailable.
- Correct category filtering; `available=0` never selected; deterministic lowest-ID tie-break.
- Missing required category returns `None`; optional empty outerwear returns `None`.
- Missing/uninitialized database produces an actionable error rather than silently creating an empty database.
- Uses temporary databases and ensures test isolation.
- Entry-point discovery can still instantiate `ShelfAgent()` with no args.

### Regression and packaging

- Run all Sprint 1/2 tests without breaking manifests/registries/entry-point discovery.
- Editable install of **each agent distribution** and workflow continues to work.
- Confirm core package has no imports from `agentctl_agents` or `agentctl_workflows`.
- Validate each agent independently by calling `.run(inputs, RuntimeContext(...))` directly; **do not implement an orchestrator just for these tests**.

**Definition of done:** The three independently packaged agents contain working implementations, each is unit-tested, Open-Meteo is called in normal weather operation, SQLite is used by the shelf manager, database setup is a separate explicit command, previous tests still pass, and the agent contracts remain consistent for Sprint 4 orchestration.

## 9. Explicitly excluded in Sprint 3

- Capability-based workflow planning, workflow orchestration, named workflow execution.
- Generic `agentctl` CLI commands (`list agents`, `list workflows`, `run workflow`). The **separate** `agentctl-shelf-init` setup command is in scope.
- End-to-end cross-agent execution or GitHub Actions CI (later sprint).
- Anthropic/OpenAI LLM use in the Clothes Adviser; post-MVP LLM-based natural-language intent extraction.
- RAG, chat, event-driven communication, persistent session memory, microservices, web UI, database migrations/CRUD suite.

## 10. Handoff required from coding assistant

After implementing **only Sprint 3**, provide:

1. List of created/modified files and responsibilities.
2. Final public `run()` signatures, manifest confirmation, and exact result dictionaries.
3. Open-Meteo request approach, time-zone/current-hour choice, normalization, timeout/error decisions.
4. Clothes Adviser rules and controlled category/type vocabulary.
5. SQLite schema, database path precedence, init command, seed behavior, match algorithm.
6. Test commands, count and results, with explicit indication if any tests contact the network.
7. Installation steps and one manual command to initialize a sample wardrobe.
8. All deviations from the spec, unresolved issues, and known limitations.
9. Branch name, commit hash, and push/merge status.
10. Confirmation no router, orchestrator, framework CLI, LLM, CI, or stretch goal was implemented.

### Suggested coding assistant instruction

> Read the master plan and `SPRINT_03_AGENTS.md`, then inspect the existing Sprint 1/2 implementation. Implement **Sprint 3 only**, retaining the `agentctl_core` API and entry-point-based plugin discovery. Build and test all three agents, with a separate SQLite initialization CLI, mocked network tests, and clear error handling. Preserve manifests and all prior tests. Do not start Sprint 4. At the end, return the exact handoff requested in Section 10.
