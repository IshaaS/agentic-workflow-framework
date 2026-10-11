"""Sprint 06 integration: natural-language intent -> catalog -> validation -> real planner/orchestrator.

1. Cross-domain proof with fake document agents (no clothing code involved).
2. The installed outfit plugins, driven through the Anthropic adapter with a
   mocked SDK client, faked weather HTTP and a temporary seeded wardrobe.
"""

import json
from types import SimpleNamespace

import pytest

from agentctl_core import (
    AgentManifest,
    AgentRegistry,
    BaseAgent,
    Capability,
    CapabilityPlanner,
    GoalSpec,
    InputSpec,
    ResolvedIntent,
    RuntimeContext,
    SequentialOrchestrator,
    build_intent_catalog,
    cli,
    validate_intent,
)
from agentctl_core.providers.anthropic import AnthropicIntentProvider


class DocumentAgent(BaseAgent):
    def __init__(self, name, capability, behaviour):
        self._manifest = AgentManifest(name, "1.0", name, [capability])
        self.behaviour = behaviour
        self.calls = []

    @property
    def manifest(self):
        return self._manifest

    def run(self, inputs, context):
        self.calls.append(dict(inputs))
        return self.behaviour(inputs)


@pytest.fixture
def documents():
    extractor = DocumentAgent(
        "extractor",
        Capability(
            "document.extract", ["document_path"], ["extracted_text"],
            input_specs=[InputSpec("document_path", "Path of the document to summarize")],
        ),
        lambda i: {"extracted_text": f"text of {i['document_path']}"},
    )
    summarizer = DocumentAgent(
        "summarizer",
        Capability(
            "document.summarize", ["extracted_text"], ["summary"],
            goals=[GoalSpec("summary", "Summarize a document")],
        ),
        lambda i: {"summary": f"summary of [{i['extracted_text']}]"},
    )
    registry = AgentRegistry()
    registry.register(summarizer)
    registry.register(extractor)
    return registry, extractor, summarizer


# Cross-domain proof -------------------------------------------------------------------------


def test_document_goal_end_to_end_with_generic_core(documents, fake_intent):
    registry, extractor, summarizer = documents
    provider = fake_intent(ResolvedIntent("summary", {"document_path": "report.pdf"}))

    catalog = build_intent_catalog(registry)
    assert list(catalog.goals) == ["summary"]
    assert catalog.goals["summary"].required == ["document_path"]

    intent = provider.resolve("Please summarize report.pdf", catalog)
    validated = validate_intent(intent, catalog)
    plan = CapabilityPlanner(registry).plan_for_goal(validated.goal, validated.inputs, {"document_path"})
    assert (plan.steps, plan.source) == (["document.extract", "document.summarize"], "generated")

    context = RuntimeContext("s", "w", validated.inputs)
    SequentialOrchestrator(registry).execute(plan, context)

    assert context.results["summary"] == "summary of [text of report.pdf]"
    assert len(extractor.calls) == len(summarizer.calls) == 1


def test_document_goal_through_the_cli(documents, fake_intent, capsys, monkeypatch):
    registry, _, _ = documents
    monkeypatch.setattr(cli, "_discover_agents", lambda: registry)
    provider = fake_intent(ResolvedIntent("summary", {"document_path": "report.pdf"}))

    code = cli.main(["run", "workflow", "--request", "Summarize report.pdf"], intent_provider=provider)
    out, err = capsys.readouterr()

    assert code == 0
    assert json.loads(out) == "summary of [text of report.pdf]"
    assert "steps: document.extract, document.summarize" in err


def test_invalid_document_intent_runs_no_agents(documents, fake_intent, capsys, monkeypatch):
    registry, extractor, summarizer = documents
    monkeypatch.setattr(cli, "_discover_agents", lambda: registry)

    code = cli.main(
        ["run", "workflow", "--request", "Summarize something"],
        intent_provider=fake_intent(ResolvedIntent("summary", {})),
    )

    assert code == cli.EXIT_PLANNING
    assert "missing required input 'document_path' for goal 'summary'" in capsys.readouterr().err
    assert extractor.calls == summarizer.calls == []


# Installed outfit plugins via the Anthropic adapter (mocked SDK client) ------------------------


class ScriptedClaude:
    """Replaces the Anthropic SDK client and returns a fixed JSON answer."""

    def __init__(self, answer):
        response = SimpleNamespace(
            stop_reason="end_turn",
            model="claude-opus-5-5",
            _request_id="req_offline",
            content=[SimpleNamespace(type="text", text=json.dumps(answer))],
        )
        self.requests = []
        create = lambda **kwargs: (self.requests.append(kwargs), response)[1]  # noqa: E731
        self.messages = SimpleNamespace(create=create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


@pytest.fixture
def wardrobe(seeded_db, monkeypatch):
    monkeypatch.setenv("SHELF_DB_PATH", str(seeded_db))


def anthropic_provider(answer):
    client = ScriptedClaude(answer)
    return AnthropicIntentProvider(api_key="sk-ant-offline-test", client=client), client


def test_outfit_request_through_anthropic_adapter(capsys, fake_weather_http, wardrobe):
    pytest.importorskip("anthropic")
    provider, client = anthropic_provider(
        {"goal": "outfit", "parameters": {"city": "Dallas", "activity": "theatre", "style": "casual"}}
    )

    code = cli.main(
        ["run", "workflow", "--request", "Suggest an outfit for a casual theatre visit in Dallas"],
        intent_provider=provider,
    )
    out, err = capsys.readouterr()

    assert code == 0
    outfit = json.loads(out)
    assert {category: item["id"] for category, item in outfit.items() if item} == {
        "top": 2, "bottom": 10, "footwear": 19,  # polo, chinos, dress shoes: smart theatre outfit
    }
    assert outfit["outerwear"] is None
    assert fake_weather_http == ["geocoding-api.open-meteo.com", "api.open-meteo.com"]
    assert "steps: weather.forecast, clothes.advise, shelf.match" in err
    (request,) = client.requests
    assert "Suggest an outfit for a casual theatre visit in Dallas" in request["messages"][0]["content"]


def test_unsupported_office_request_never_runs_agents(capsys, fake_weather_http, wardrobe):
    pytest.importorskip("anthropic")
    provider, _ = anthropic_provider(
        {"goal": "outfit", "parameters": {"city": "Dallas", "activity": "office", "style": "business_casual"}}
    )

    code = cli.main(
        ["run", "workflow", "--request", "What should I wear to the office in Dallas, business casual?"],
        intent_provider=provider,
    )
    out, err = capsys.readouterr()

    assert code == cli.EXIT_PLANNING
    assert out == ""
    assert "parameter 'activity' must be one of: outdoor_walk, theatre, casual; got 'office'" in err
    assert fake_weather_http == []
