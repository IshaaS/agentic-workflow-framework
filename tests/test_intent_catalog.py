"""Sprint 06 catalog tests: goals and parameters derived from capability metadata."""

import pytest

from agentctl_core import (
    AgentManifest,
    AgentRegistry,
    BaseAgent,
    Capability,
    CapabilityPlanner,
    GoalSpec,
    InputSpec,
    IntentCatalogError,
    build_intent_catalog,
    discover_agents,
)


class MetaAgent(BaseAgent):
    def __init__(self, name, *capabilities):
        self._manifest = AgentManifest(name, "1.0", f"{name} agent", list(capabilities))

    @property
    def manifest(self):
        return self._manifest

    def run(self, inputs, context):
        raise AssertionError("catalog building must never run agents")


def registry_of(*capabilities):
    registry = AgentRegistry()
    for index, capability in enumerate(capabilities):
        registry.register(MetaAgent(f"agent{index}", capability))
    return registry


def extract(**extra):
    return Capability(
        "document.extract",
        requires=["document_path"],
        produces=["extracted_text"],
        input_specs=[InputSpec("document_path", "Path of the document to read")],
        **extra,
    )


def summarize(**extra):
    defaults = dict(
        optional_inputs=["tone"],
        input_specs=[InputSpec("tone", "Summary tone", allowed_values=["brief", "detailed"])],
        goals=[GoalSpec("summary", "Summarize a document")],
    )
    defaults.update(extra)
    return Capability("document.summarize", requires=["extracted_text"], produces=["summary"], **defaults)


# Discovery of goals and parameters ------------------------------------------------


def test_goal_parameters_come_from_its_capability_chain():
    catalog = build_intent_catalog(registry_of(summarize(), extract()))

    goal = catalog.goals["summary"]
    assert goal.description == "Summarize a document"
    assert goal.steps == ["document.extract", "document.summarize"]
    assert list(goal.parameters) == ["document_path", "tone"]
    assert goal.required == ["document_path"]
    tone = goal.parameters["tone"]
    assert (tone.required, tone.allowed_values, tone.value_type) == (False, ["brief", "detailed"], "string")


def test_unadvertised_outputs_are_not_goals():
    catalog = build_intent_catalog(registry_of(summarize(), extract()))

    assert list(catalog.goals) == ["summary"]  # extracted_text is producible but not advertised


def test_unrelated_agents_add_no_parameters():
    translate = Capability(
        "text.translate",
        requires=["source_text", "language"],
        produces=["translation"],
        input_specs=[InputSpec("source_text", "Text"), InputSpec("language", "Target language")],
        goals=[GoalSpec("translation", "Translate text")],
    )
    catalog = build_intent_catalog(registry_of(summarize(), extract(), translate))

    assert list(catalog.goals["summary"].parameters) == ["document_path", "tone"]
    assert list(catalog.goals["translation"].parameters) == ["source_text", "language"]


def test_intermediate_outputs_are_not_parameters():
    catalog = build_intent_catalog(registry_of(summarize(), extract()))

    assert "extracted_text" not in catalog.goals["summary"].parameters


def test_to_dict_is_json_ready():
    data = build_intent_catalog(registry_of(summarize(), extract())).to_dict()

    assert data == {
        "goals": [
            {
                "name": "summary",
                "description": "Summarize a document",
                "parameters": {
                    "document_path": {"type": "string", "description": "Path of the document to read", "required": True},
                    "tone": {
                        "type": "string",
                        "description": "Summary tone",
                        "required": False,
                        "allowed_values": ["brief", "detailed"],
                    },
                },
            }
        ]
    }


def test_plugins_without_metadata_give_an_empty_catalog_but_still_plan():
    registry = registry_of(
        Capability("document.extract", ["document_path"], ["extracted_text"]),
        Capability("document.summarize", ["extracted_text"], ["summary"]),
    )

    assert build_intent_catalog(registry).goals == {}
    plan = CapabilityPlanner(registry).plan_for_goal("summary", {"document_path": "a"}, {"document_path"})
    assert plan.steps == ["document.extract", "document.summarize"]


def test_installed_plugins_catalog():
    registry = AgentRegistry()
    discover_agents(registry)
    from agentctl_agents.clothes.agent import ACTIVITIES, STYLES

    goal = build_intent_catalog(registry).goals["outfit"]

    assert goal.steps == ["weather.forecast", "clothes.advise", "shelf.match"]
    assert goal.required == ["city", "activity"]
    assert goal.parameters["activity"].allowed_values == list(ACTIVITIES)
    assert goal.parameters["style"].required is False
    assert goal.parameters["style"].allowed_values == list(STYLES)
    assert "office" not in goal.parameters["activity"].allowed_values


# Metadata errors -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "capabilities, message",
    [
        (
            [summarize(goals=[GoalSpec("headline", "Not produced")]), extract()],
            "goal 'headline' is not one of its produces keys",
        ),
        (
            [summarize(), extract(goals=[GoalSpec("extracted_text", "x")]),
             Capability("other.summary", ["document_path"], ["summary"],
                        input_specs=[InputSpec("document_path", "Path of the document to read")],
                        goals=[GoalSpec("summary", "Another summary")])],
            "advertised by both",
        ),
        (
            [summarize(input_specs=[InputSpec("colour", "Not an input")]), extract()],
            "InputSpec 'colour' is neither in requires nor in optional_inputs",
        ),
        (
            [summarize(input_specs=[InputSpec("tone", "a"), InputSpec("tone", "b")]), extract()],
            "declared more than once",
        ),
        (
            [summarize(input_specs=[InputSpec("tone", "Tone", value_type="integer")]), extract()],
            "unsupported value_type 'integer'",
        ),
        (
            [summarize(input_specs=[InputSpec("tone", "Tone", allowed_values=[])]), extract()],
            "allowed_values must be a non-empty list",
        ),
        (
            [summarize(input_specs=[InputSpec("tone", "  ")]), extract()],
            "needs a description",
        ),
        (
            [summarize(optional_inputs=["extracted_text"]), extract()],
            "cannot be both required and optional",
        ),
        (
            [summarize(input_specs=[]), extract()],
            "no capability in its chain describes it",
        ),
        (
            # Missing provider: with no extractor, extracted_text would have to come from
            # the user, but nothing describes it, so the goal is rejected rather than guessed.
            [summarize()],
            "needs input 'extracted_text', but no capability in its chain describes it",
        ),
    ],
)
def test_invalid_metadata_is_rejected(capabilities, message):
    with pytest.raises(IntentCatalogError, match=message):
        build_intent_catalog(registry_of(*capabilities))


def test_conflicting_input_descriptions_in_one_chain():
    registry = registry_of(
        Capability(
            "document.extract",
            requires=["document_path", "language"],
            produces=["extracted_text"],
            input_specs=[InputSpec("document_path", "Path"), InputSpec("language", "Lang", allowed_values=["en"])],
        ),
        Capability(
            "document.summarize",
            requires=["extracted_text", "language"],
            produces=["summary"],
            input_specs=[InputSpec("language", "Lang", allowed_values=["en", "fr"])],
            goals=[GoalSpec("summary", "Summarize")],
        ),
    )
    with pytest.raises(IntentCatalogError, match="input 'language' for goal 'summary' is described differently"):
        build_intent_catalog(registry)


def test_ambiguous_provider_for_advertised_goal():
    registry = registry_of(
        summarize(),
        extract(),
        Capability("ocr.extract", ["document_path"], ["extracted_text"],
                   input_specs=[InputSpec("document_path", "Path of the document to read")]),
    )

    with pytest.raises(IntentCatalogError, match="more than one capability") as excinfo:
        build_intent_catalog(registry)
    assert excinfo.value.goal == "summary"


def test_cycle_in_advertised_goal_chain():
    registry = registry_of(
        Capability("a.make", ["b"], ["a"], goals=[GoalSpec("a", "A")]),
        Capability("b.make", ["a"], ["b"]),
    )

    with pytest.raises(IntentCatalogError, match="circular dependency"):
        build_intent_catalog(registry)
