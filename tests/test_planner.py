"""Sprint 04 planner tests using test-local fake agents (no plugins, no I/O)."""

import pytest

from agentctl_core import (
    AgentManifest,
    AgentRegistry,
    AmbiguousProviderError,
    BaseAgent,
    Capability,
    CapabilityPlanner,
    CircularDependencyError,
    InvalidWorkflowPlanError,
    MissingCapabilityError,
    MissingInputError,
    PlanningError,
    UnknownGoalError,
    WorkflowDefinition,
    WorkflowPlan,
)


class FakeAgent(BaseAgent):
    def __init__(self, name: str, *capabilities: Capability):
        self._manifest = AgentManifest(name, "0.0.1", f"fake {name}", list(capabilities))

    @property
    def manifest(self) -> AgentManifest:
        return self._manifest

    def run(self, inputs, context):
        raise AssertionError("the planner must never run agents")


def cap(name, requires, produces):
    return Capability(name=name, requires=list(requires), produces=list(produces))


def registry_of(*capabilities: Capability) -> AgentRegistry:
    registry = AgentRegistry()
    for index, capability in enumerate(capabilities):
        registry.register(FakeAgent(f"agent_{index}", capability))
    return registry


# Same shape as the real outfit plugins, but generic test names.
FORECAST = cap("w.forecast", ["city"], ["weather"])
ADVISE = cap("c.advise", ["weather", "activity"], ["clothing_requirements"])
MATCH = cap("s.match", ["clothing_requirements"], ["outfit"])
EXTERNAL = {"city", "activity", "style"}
INPUTS = {"city": "Dallas", "activity": "outdoor_walk"}


@pytest.fixture
def planner() -> CapabilityPlanner:
    # Registered out of dependency order to show ordering comes from requires/produces.
    return CapabilityPlanner(registry_of(MATCH, FORECAST, ADVISE))


# Goal planning ---------------------------------------------------------------


def test_plan_for_goal_orders_dependencies_first(planner):
    plan = planner.plan_for_goal("outfit", INPUTS, EXTERNAL)

    assert plan == WorkflowPlan(steps=["w.forecast", "c.advise", "s.match"], source="generated")


def test_optional_style_does_not_change_plan(planner):
    with_style = planner.plan_for_goal("outfit", {**INPUTS, "style": "formal"}, EXTERNAL)

    assert with_style == planner.plan_for_goal("outfit", INPUTS, EXTERNAL)


def test_intermediate_goal_plans_only_what_is_needed(planner):
    assert planner.plan_for_goal("weather", INPUTS, EXTERNAL).steps == ["w.forecast"]


def test_supplied_key_skips_its_producer(planner):
    plan = planner.plan_for_goal("outfit", {"weather": {}, "activity": "theatre"}, EXTERNAL)

    assert plan.steps == ["c.advise", "s.match"]


def test_goal_already_supplied_gives_empty_plan(planner):
    assert planner.plan_for_goal("outfit", {"outfit": {}}, EXTERNAL) == WorkflowPlan([], "generated")


def test_external_input_with_producer_uses_producer_when_absent():
    planner = CapabilityPlanner(registry_of(cap("geo.locate", [], ["city"]), FORECAST))

    assert planner.plan_for_goal("weather", {}, {"city"}).steps == ["geo.locate", "w.forecast"]
    assert planner.plan_for_goal("weather", {"city": "Paris"}, {"city"}).steps == ["w.forecast"]


def test_shared_dependency_planned_once_in_stable_order():
    planner = CapabilityPlanner(registry_of(
        cap("d.final", ["left", "right"], ["final"]),
        cap("b.left", ["base"], ["left"]),
        cap("c.right", ["base"], ["right"]),
        cap("a.base", ["seed"], ["base"]),
    ))

    for _ in range(3):
        plan = planner.plan_for_goal("final", {"seed": 1}, {"seed"})
        assert plan.steps == ["a.base", "b.left", "c.right", "d.final"]


def test_planner_does_not_mutate_inputs(planner):
    inputs = dict(INPUTS)
    planner.plan_for_goal("outfit", inputs, EXTERNAL)

    assert inputs == INPUTS


# Goal planning errors ----------------------------------------------------------


def test_unknown_goal(planner):
    with pytest.raises(UnknownGoalError, match="'party_plan'") as excinfo:
        planner.plan_for_goal("party_plan", INPUTS, EXTERNAL)

    assert excinfo.value.goal == "party_plan"


def test_missing_external_input(planner):
    with pytest.raises(MissingInputError) as excinfo:
        planner.plan_for_goal("outfit", {"activity": "theatre"}, EXTERNAL)

    assert excinfo.value.input_name == "city"
    assert excinfo.value.required_by == "w.forecast"
    assert "missing required input 'city'" in str(excinfo.value)


def test_missing_key_not_declared_external_is_a_missing_capability(planner):
    # Without external_inputs the planner does not guess that 'city' is a user field.
    with pytest.raises(MissingCapabilityError) as excinfo:
        planner.plan_for_goal("outfit", {"activity": "theatre"})

    assert excinfo.value.missing_output == "city"
    assert excinfo.value.required_by == "w.forecast"


def test_missing_intermediate_provider():
    planner = CapabilityPlanner(registry_of(FORECAST, MATCH))

    with pytest.raises(MissingCapabilityError) as excinfo:
        planner.plan_for_goal("outfit", INPUTS, EXTERNAL)

    assert excinfo.value.missing_output == "clothing_requirements"
    assert excinfo.value.required_by == "s.match"


def test_cycle_reports_path():
    planner = CapabilityPlanner(registry_of(
        cap("a.make", ["b"], ["a"]),
        cap("b.make", ["c"], ["b"]),
        cap("c.make", ["a"], ["c"]),
    ))

    with pytest.raises(CircularDependencyError) as excinfo:
        planner.plan_for_goal("a", {})

    assert excinfo.value.cycle == ["a.make", "b.make", "c.make", "a.make"]
    assert "a.make -> b.make -> c.make -> a.make" in str(excinfo.value)


def test_self_cycle():
    planner = CapabilityPlanner(registry_of(cap("x.loop", ["x"], ["x"])))

    with pytest.raises(CircularDependencyError) as excinfo:
        planner.plan_for_goal("x", {})

    assert excinfo.value.cycle == ["x.loop", "x.loop"]


def test_ambiguous_provider_rejected():
    planner = CapabilityPlanner(registry_of(FORECAST, cap("z.forecast", ["city"], ["weather"])))

    with pytest.raises(AmbiguousProviderError) as excinfo:
        planner.plan_for_goal("weather", INPUTS, EXTERNAL)

    assert excinfo.value.output == "weather"
    assert excinfo.value.providers == ["w.forecast", "z.forecast"]


def test_ambiguity_ignored_when_key_not_needed():
    planner = CapabilityPlanner(registry_of(
        FORECAST, cap("z.forecast", ["city"], ["weather"]), ADVISE, MATCH
    ))

    plan = planner.plan_for_goal("outfit", {**INPUTS, "weather": {}}, EXTERNAL)

    assert plan.steps == ["c.advise", "s.match"]


def test_multi_output_step_cannot_overwrite_an_input():
    planner = CapabilityPlanner(registry_of(cap("m.both", ["seed"], ["first", "second"])))

    with pytest.raises(InvalidWorkflowPlanError, match="would overwrite 'first'"):
        planner.plan_for_goal("second", {"seed": 1, "first": 0})


def test_all_planning_errors_share_a_base_class():
    for error in (
        UnknownGoalError,
        MissingInputError,
        MissingCapabilityError,
        CircularDependencyError,
        AmbiguousProviderError,
        InvalidWorkflowPlanError,
    ):
        assert issubclass(error, PlanningError)


# Named workflows ---------------------------------------------------------------


def workflow(*steps, name="demo_flow"):
    return WorkflowDefinition(name=name, description="test workflow", steps=list(steps))


def test_named_workflow_validates_in_declared_order(planner):
    definition = workflow("w.forecast", "c.advise", "s.match")

    plan = planner.plan_from_workflow(definition, {**INPUTS, "style": "casual"}, EXTERNAL)

    assert plan == WorkflowPlan(steps=["w.forecast", "c.advise", "s.match"], source="named")
    assert plan.steps is not definition.steps
    assert definition.steps == ["w.forecast", "c.advise", "s.match"]


def test_named_and_generated_plans_match(planner):
    named = planner.plan_from_workflow(workflow("w.forecast", "c.advise", "s.match"), INPUTS, EXTERNAL)
    generated = planner.plan_for_goal("outfit", INPUTS, EXTERNAL)

    assert named.steps == generated.steps
    assert (named.source, generated.source) == ("named", "generated")


def test_named_workflow_unknown_capability(planner):
    with pytest.raises(MissingCapabilityError) as excinfo:
        planner.plan_from_workflow(workflow("w.forecast", "x.missing"), INPUTS, EXTERNAL)

    error = excinfo.value
    assert (error.capability, error.workflow, error.step_index) == ("x.missing", "demo_flow", 1)
    assert "step 2 references capability 'x.missing'" in str(error)


def test_named_workflow_wrong_order_is_not_reordered(planner):
    with pytest.raises(InvalidWorkflowPlanError) as excinfo:
        planner.plan_from_workflow(workflow("c.advise", "w.forecast", "s.match"), INPUTS, EXTERNAL)

    error = excinfo.value
    assert (error.step_index, error.capability, error.keys) == (0, "c.advise", ["weather"])
    assert "only produced by a later step ('w.forecast')" in str(error)


def test_named_workflow_missing_external_input(planner):
    with pytest.raises(MissingInputError) as excinfo:
        planner.plan_from_workflow(workflow("w.forecast", "c.advise"), {"city": "Oslo"}, EXTERNAL)

    assert (excinfo.value.input_name, excinfo.value.required_by) == ("activity", "c.advise")


def test_named_workflow_unmet_prerequisite(planner):
    with pytest.raises(InvalidWorkflowPlanError, match="no earlier step produces") as excinfo:
        planner.plan_from_workflow(workflow("s.match"), INPUTS, EXTERNAL)

    assert excinfo.value.keys == ["clothing_requirements"]


def test_named_workflow_duplicate_step(planner):
    with pytest.raises(InvalidWorkflowPlanError, match="repeats capability 'w.forecast'") as excinfo:
        planner.plan_from_workflow(workflow("w.forecast", "w.forecast"), INPUTS, EXTERNAL)

    assert excinfo.value.step_index == 1


def test_named_workflow_empty(planner):
    with pytest.raises(InvalidWorkflowPlanError, match="has no steps"):
        planner.plan_from_workflow(workflow(), INPUTS, EXTERNAL)


def test_named_workflow_step_would_overwrite_input(planner):
    with pytest.raises(InvalidWorkflowPlanError, match="would overwrite 'weather'"):
        planner.plan_from_workflow(
            workflow("w.forecast", "c.advise"), {**INPUTS, "weather": {}}, EXTERNAL
        )
