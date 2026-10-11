"""Sprint 06 validation tests: proposed intents are checked against the catalog."""

import pytest

from agentctl_core import (
    AgentManifest,
    AgentRegistry,
    BaseAgent,
    Capability,
    GoalSpec,
    InputSpec,
    IntentValidationError,
    PlanningError,
    ResolvedIntent,
    build_intent_catalog,
    validate_intent,
)


class MetaAgent(BaseAgent):
    def __init__(self, name, capability):
        self._manifest = AgentManifest(name, "1.0", name, [capability])

    @property
    def manifest(self):
        return self._manifest

    def run(self, inputs, context):
        raise AssertionError("validation must never run agents")


@pytest.fixture(scope="module")
def catalog():
    registry = AgentRegistry()
    registry.register(MetaAgent("extractor", Capability(
        "document.extract", ["document_path"], ["extracted_text"],
        input_specs=[InputSpec("document_path", "Path of the document")],
    )))
    registry.register(MetaAgent("summarizer", Capability(
        "document.summarize", ["extracted_text", "audience"], ["summary"],
        optional_inputs=["tone"],
        input_specs=[
            InputSpec("audience", "Who will read it"),
            InputSpec("tone", "Summary tone", allowed_values=["brief", "detailed"]),
        ],
        goals=[GoalSpec("summary", "Summarize a document")],
    )))
    registry.register(MetaAgent("translator", Capability(
        "text.translate", ["source_text", "language"], ["translation"],
        input_specs=[InputSpec("source_text", "Text"), InputSpec("language", "Target language")],
        goals=[GoalSpec("translation", "Translate text")],
    )))
    return build_intent_catalog(registry)


VALID = {"document_path": "report.pdf", "audience": "managers"}


def test_valid_intent(catalog):
    result = validate_intent(ResolvedIntent("summary", {**VALID, "tone": "brief"}), catalog)

    assert (result.goal, result.inputs) == ("summary", {**VALID, "tone": "brief"})


def test_optional_parameter_may_be_omitted(catalog):
    assert validate_intent(ResolvedIntent("summary", VALID), catalog).inputs == VALID


def test_mapping_intent_is_accepted(catalog):
    assert validate_intent({"goal": "summary", "parameters": VALID}, catalog).goal == "summary"


def test_validation_errors_are_planning_errors():
    assert issubclass(IntentValidationError, PlanningError)


# Structure ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "intent, message",
    [
        (["summary"], "intent must be an object"),
        ({"goal": "summary", "parameters": {}, "steps": ["x"]}, "unexpected fields: steps"),
        (ResolvedIntent(None, {}), "goal must be a non-empty string"),
        (ResolvedIntent("   ", {}), "goal must be a non-empty string"),
        (ResolvedIntent(7, {}), "goal must be a non-empty string"),
        ({"parameters": {}}, "goal must be a non-empty string"),
        (ResolvedIntent("summary", ["document_path"]), "parameters must be an object"),
        (ResolvedIntent("summary", {1: "x"}), "parameter names must be strings"),
    ],
)
def test_malformed_intent(catalog, intent, message):
    with pytest.raises(IntentValidationError, match=message):
        validate_intent(intent, catalog)


# Goal and parameters --------------------------------------------------------------


def test_unknown_goal(catalog):
    with pytest.raises(IntentValidationError) as excinfo:
        validate_intent(ResolvedIntent("flight_booking", {}), catalog)

    assert str(excinfo.value) == (
        "unsupported natural-language goal 'flight_booking' (available: summary, translation)"
    )
    assert excinfo.value.goal == "flight_booking"


def test_unadvertised_but_producible_output_is_not_a_goal(catalog):
    with pytest.raises(IntentValidationError, match="unsupported natural-language goal 'extracted_text'"):
        validate_intent(ResolvedIntent("extracted_text", {"document_path": "a"}), catalog)


def test_unknown_parameter(catalog):
    with pytest.raises(IntentValidationError) as excinfo:
        validate_intent(ResolvedIntent("summary", {**VALID, "fashion_score": "9"}), catalog)

    assert str(excinfo.value) == "unknown parameter 'fashion_score' for selected goal 'summary' (from request)"
    assert excinfo.value.parameter == "fashion_score"


def test_parameter_of_another_goal_is_unknown(catalog):
    with pytest.raises(IntentValidationError, match="unknown parameter 'language'"):
        validate_intent(ResolvedIntent("summary", {**VALID, "language": "fr"}), catalog)


@pytest.mark.parametrize("value", [3, 2.5, True, None, ["a"], {"x": 1}])
def test_wrong_type_is_not_coerced(catalog, value):
    with pytest.raises(IntentValidationError, match="parameter 'audience' must be a string"):
        validate_intent(ResolvedIntent("summary", {**VALID, "audience": value}), catalog)


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_string_rejected(catalog, value):
    with pytest.raises(IntentValidationError, match="parameter 'document_path' must not be empty"):
        validate_intent(ResolvedIntent("summary", {**VALID, "document_path": value}), catalog)


@pytest.mark.parametrize("value", ["short", "Brief", "brief "])
def test_allowed_values_are_exact(catalog, value):
    with pytest.raises(IntentValidationError) as excinfo:
        validate_intent(ResolvedIntent("summary", {**VALID, "tone": value}), catalog)

    assert str(excinfo.value).startswith("parameter 'tone' must be one of: brief, detailed;")


def test_missing_required_parameter(catalog):
    with pytest.raises(IntentValidationError) as excinfo:
        validate_intent(ResolvedIntent("summary", {"audience": "managers"}), catalog)

    assert str(excinfo.value) == (
        "missing required input 'document_path' for goal 'summary'; supply --input document_path=VALUE"
    )


def test_several_missing_parameters_are_all_named(catalog):
    with pytest.raises(IntentValidationError, match="missing required inputs 'document_path', 'audience'"):
        validate_intent(ResolvedIntent("summary", {}), catalog)


def test_unrelated_goal_inputs_are_never_required(catalog):
    # translation's source_text/language are not demanded for summary.
    assert validate_intent(ResolvedIntent("summary", VALID), catalog).inputs == VALID


# Explicit --input values ----------------------------------------------------------------


def test_explicit_input_wins_over_extracted_value(catalog):
    result = validate_intent(
        ResolvedIntent("summary", {**VALID, "tone": "detailed"}), catalog, {"tone": "brief"}
    )

    assert result.inputs["tone"] == "brief"


def test_explicit_input_fills_missing_parameter(catalog):
    result = validate_intent(ResolvedIntent("summary", {"audience": "board"}), catalog, {"document_path": "q3.pdf"})

    assert result.inputs == {"audience": "board", "document_path": "q3.pdf"}


def test_explicit_input_replaces_invalid_extracted_value(catalog):
    result = validate_intent(ResolvedIntent("summary", {**VALID, "tone": "short"}), catalog, {"tone": "brief"})

    assert result.inputs["tone"] == "brief"


def test_explicit_input_must_still_be_valid(catalog):
    with pytest.raises(IntentValidationError, match=r"must be one of: brief, detailed; got 'loud' \(from --input\)"):
        validate_intent(ResolvedIntent("summary", VALID), catalog, {"tone": "loud"})


def test_explicit_unknown_input_rejected(catalog):
    with pytest.raises(IntentValidationError, match=r"unknown parameter 'colour' .* \(from --input\)"):
        validate_intent(ResolvedIntent("summary", VALID), catalog, {"colour": "red"})


def test_validation_does_not_mutate_arguments(catalog):
    proposed, explicit = dict(VALID), {"tone": "brief"}
    validate_intent(ResolvedIntent("summary", proposed), catalog, explicit)

    assert proposed == VALID and explicit == {"tone": "brief"}
