# Sprint 7 — Focused Clothes Adviser Enhancement

## Purpose
Improve the usability and demonstration quality of the **independently packaged Clothes Adviser** with one additional activity, one additional style, a few natural aliases, and targeted tests. **This is a small polish sprint, not a new fashion recommendation system.** The mandatory assessment framework is already implemented. Do not start the final documentation pass during this sprint.

## Source of truth and prerequisite
1. Read the current repository code and tests **before** editing, including `agents/clothes-agent`, the weather and shelf output contracts, `tests/test_clothes_agent.py`, the installed agent metadata and the Sprint 6 intent catalog/validator tests.
2. Start from updated `main` **only after Sprint 6 is merged**. Create `feat/clothes-adviser-polish`.
3. Follow the real implementation if its API differs from this plan; record deviations in the handoff rather than making speculative edits.
4. Preserve the successful Sprint 6 live intent workflow: `--request "What should I wear for an outdoor walk in Chicago?"`.

## In scope

### 1. Extend supported activity and style vocabulary
- Add canonical activity **`office`**, alongside the existing `outdoor_walk`, `theatre`, `casual`.
- Add canonical style **`business_casual`**, alongside `casual`, `formal`.
- Add a **small** set of obvious activity aliases (at minimum `walk`, `walking`, `outdoor walk` → `outdoor_walk`; `work`, `office meeting` → `office`). Normalize whitespace/case where safe. Avoid broad substring/fuzzy matching that could silently change intent.
- Optionally support the harmless style spelling `business casual` → `business_casual`. Preserve the existing `casual` and `formal` behavior.
- Unrecognized activities/styles must still fail with a **clear error listing supported canonical values**, not silently default to a different activity/style. Do not claim open-ended activity support.
- Leave default behavior unchanged: style may be omitted and defaults according to the existing agent implementation (reported as `casual`). `weather` and `activity` remain required. Preserve existing activity/style combinations and expected outputs unless there is a demonstrated bug.

### 2. Small deterministic recommendation rules
- Add a reasonable, weather-aware `office` recommendation rule compatible with existing output shape: `{"clothing_requirements": {"top": [...], "bottom": [...], "outerwear": [...], "footwear": [...]}}`.
- Handle `business_casual` as a style preference using **existing clothing types that the Shelf Manager and seeded SQLite wardrobe actually understand**. Inspect those types before choosing recommendations.
- Ensure office + business_casual produces sensible choices with the current seed wardrobe (e.g., polo or dress shirt, suitable pants, appropriate shoes), with weather-aware outerwear. Do not assume a specific item must always be selected; make assertions robust to temperature and inventory.
- Weather still meaningfully affects recommendations; activity and style should both meaningfully affect the result. Keep the rules simple and understandable rather than adding many branches.
- Do not modify SQLite schema, seed items, Weather Provider, Shelf Manager, or framework components for this enhancement. If you find a genuine compatibility blocker, report it and propose the smallest fix before expanding scope.

### 3. Metadata and natural-language integration
- Keep the existing generic metadata-driven Sprint 6 architecture. In the clothes agent manifest, advertise all actually supported input values. Prefer deriving `InputSpec.allowed_values` from one source of truth so metadata and validation cannot drift.
- **Account for Sprint 6's strict generic validator.** An LLM output is validated against advertised allowed values *before* reaching the Clothes Adviser. If aliases such as `walk` and `office meeting` should work through `--request`, they must be represented consistently in the agent's advertised accepted values (or mapped by a generic, metadata-driven mechanism already supported). Do not assume agent-side aliasing alone makes natural-language aliases work.
- Do not hardcode clothing synonyms, special activities, or prompts in `agentctl_core`. No changes to `planner.py`, `orchestrator.py`, `intent.py`, `intent_validation.py`, `intent_catalog.py`, Anthropic provider, SDK contracts, registry, discovery, or CLI unless a concrete compatibility issue is found; discuss/report such issues instead of silently changing them.
- `--request` remains optional and continues to require an Anthropic API key. Structured `--goal` and named workflows must remain usable without an Anthropic API key.

## Out of scope
- New AI agents or workflow steps; new capability IDs; LLM-based clothing recommendation rules.
- Open-ended activities, complex fashion scoring, new wardrobes, inventory editing, RAG, memory, chat, planner/orchestrator redesign.
- Documentation reorganization, final README or AI disclosure work. We will handle those **after** this PR is merged.

## Expected user-facing behavior
Examples are behavioral targets, not promises of specific wardrobe item IDs:

```bash
# Existing commands retain their behavior
agentctl run workflow --goal outfit --input city=Chicago --input activity=outdoor_walk
agentctl run workflow outfit_advisor --input city=Dallas --input activity=theatre --input style=formal

# New structured use cases
agentctl run workflow --goal outfit --input city=Chicago --input activity=office --input style=business_casual
agentctl run workflow --goal outfit --input city=Chicago --input activity=walk

# Natural-language request (requires ANTHROPIC_API_KEY for a real run)
agentctl run workflow --request "What should I wear to the office in Chicago? I prefer business casual."
```

The last request should be demonstrably *possible* under the advertised goal/parameter schema. Automated CI must validate it with a **scripted fake intent provider**, not a live LLM. Do not rely on live model wording to prove deterministic correctness.

## Testing and acceptance criteria
Add small, focused tests rather than broadly rewriting the existing suite:

1. **Backward compatibility:** previously supported `outdoor_walk`, `theatre`, `casual` and `casual`/`formal` style cases continue to pass; omitted `style` works.
2. **New rule behavior:** `office` + `business_casual` outputs valid, preference-ordered clothing types and adapts sensibly to mild/cold/rainy weather using the existing weather normalization.
3. **Alias handling:** canonical versus alias activity produces equivalent clothing requirements for controlled identical inputs (`walk`, `walking`, `outdoor walk`; `work`, `office meeting`). Case/whitespace handling where implemented. Unknown values still fail clearly.
4. **Schema integrity:** manifest-required inputs remain `weather`, `activity`; optional input remains `style`; `allowed_values` matches what the agent can really accept, including aliases that should be accepted in request mode.
5. **End-to-end, offline:** discover actual independent packages; use fake Open-Meteo transport and seeded temporary SQLite wardrobe; execute named and generated workflows with new inputs; verify valid outfit shape, no unexpected errors.
6. **Natural language, offline:** use existing injected `FakeIntentProvider` / mocked SDK with `goal="outfit"`, `activity="office"`, `style="business_casual"`, `city="Chicago"`; test through the actual intent catalog, strict validator, unchanged planner, and orchestrator; assert no clothing-specific core changes.
7. **Error scenarios:** unsupported activity or style gets a clear deterministic failure; corresponding request-mode schema validation rejects unknown values before running agents.
8. **Full regression:** `python -m pytest -q` passes on installed packages, and updated CI is green across the existing Python matrix. Preserve network-blocking tests; no API keys in CI.
9. **No architecture drift:** Git diff verifies that only the clothes agent package and relevant tests changed (and, if necessary, minimal adjacent test-fixture adjustments explained in the handoff).

Do not overfit unit tests to exact item IDs when the behavior being tested is clothing-type selection or compatibility with the seed inventory.

## Implementation guidance
- Inspect actual `ACTIVITIES`, `STYLES`, type-selection code and manifest first. Prefer a simple canonicalization helper and a small office rule.
- Keep canonical tokens separate from aliases where possible, but make the complete accepted vocabulary discoverable to the Sprint 6 validator for request-mode interoperability.
- Avoid adding a second general-purpose natural-language parser in the Clothes Adviser; it is still a deterministic agent.
- Keep user-friendly error messages and tests consistent with the existing error handling.
- Avoid unnecessary new dependencies or changes in GitHub Actions YAML; the current CI should pick up new tests automatically.

## Git and handoff
1. Branch from merged `main`: `git checkout main && git pull origin main && git checkout -b feat/clothes-adviser-polish`.
2. Implement and run focused tests, then the full suite.
3. Commit/push code and tests; open a PR **without merging**.
4. Provide a concise handoff **in the chat, not as a committed implementation-handoff Markdown file**, covering changed files, exact behavior, tests and CI, sample offline end-to-end results, limitations, commit, and PR link.
5. Do not start or commit the final documentation work in this sprint. Only after this PR is approved and merged will we return to the planned README and documentation/disclosure cleanup.

## Definition of done
- Old behavior preserved; office and business_casual work with real existing clothes/shelf contracts.
- Common activity aliases work in structured mode, and accepted values are discoverable and validated in natural-language mode.
- Generic framework code and interfaces remain unchanged.
- All automated tests and PR CI pass.
- Clear, compact handoff provided for review; PR not merged automatically.
