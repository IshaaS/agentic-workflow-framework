"""Named outfit workflow. Steps are capability ids, resolved by the framework."""

from agentctl_core import WorkflowDefinition


def get_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        name="outfit_advisor",
        description="Recommend clothing using weather and a personal shelf",
        steps=["weather.forecast", "clothes.advise", "shelf.match"],
    )
