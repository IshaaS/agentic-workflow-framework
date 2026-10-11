"""Discover agent and workflow plugins from installed distribution entry points.

Loading an entry point imports and runs code from the distribution that
declared it, so only install plugins you trust.
"""

import logging
from importlib.metadata import EntryPoint, entry_points

from agentctl_core.registry import AgentRegistry, WorkflowRegistry
from agentctl_core.sdk import BaseAgent, WorkflowDefinition

AGENT_ENTRY_POINT_GROUP = "agentctl.agents"
WORKFLOW_ENTRY_POINT_GROUP = "agentctl.workflows"

logger = logging.getLogger("agentctl.discovery")


class PluginDiscoveryError(Exception):
    """A plugin entry point could not be loaded or registered."""


def _describe(entry_point: EntryPoint) -> str:
    dist = getattr(entry_point, "dist", None)
    source = f" from distribution {dist.name!r}" if dist is not None else ""
    return (
        f"entry point {entry_point.name!r} = {entry_point.value!r} "
        f"in group {entry_point.group!r}{source}"
    )


def _sorted_entry_points(group: str) -> list[EntryPoint]:
    return sorted(entry_points(group=group), key=lambda ep: (ep.name, ep.value))


def load_agent(entry_point: EntryPoint) -> BaseAgent:
    """Load an agent class from ``entry_point`` and instantiate it with no arguments."""
    try:
        target = entry_point.load()
        if not (isinstance(target, type) and issubclass(target, BaseAgent)):
            raise TypeError(f"{target!r} is not a BaseAgent subclass")
        return target()
    except Exception as exc:
        raise PluginDiscoveryError(
            f"failed to load agent from {_describe(entry_point)}: {exc}"
        ) from exc


def load_workflow(entry_point: EntryPoint) -> WorkflowDefinition:
    """Load a zero-argument factory from ``entry_point`` and return its WorkflowDefinition."""
    try:
        factory = entry_point.load()
        if not callable(factory):
            raise TypeError(f"{factory!r} is not callable")
        workflow = factory()
        if not isinstance(workflow, WorkflowDefinition):
            raise TypeError(
                f"factory returned {type(workflow).__name__}, expected WorkflowDefinition"
            )
        return workflow
    except Exception as exc:
        raise PluginDiscoveryError(
            f"failed to load workflow from {_describe(entry_point)}: {exc}"
        ) from exc


def discover_agents(registry: AgentRegistry) -> None:
    """Load every installed ``agentctl.agents`` entry point into ``registry``."""
    for entry_point in _sorted_entry_points(AGENT_ENTRY_POINT_GROUP):
        agent = load_agent(entry_point)
        try:
            registry.register(agent)
        except (TypeError, ValueError) as exc:
            raise PluginDiscoveryError(
                f"failed to register agent from {_describe(entry_point)}: {exc}"
            ) from exc
        logger.info(
            "Discovered agent %s %s (%s)",
            agent.manifest.name,
            agent.manifest.version,
            entry_point.value,
        )


def discover_workflows(registry: WorkflowRegistry) -> None:
    """Load every installed ``agentctl.workflows`` entry point into ``registry``."""
    for entry_point in _sorted_entry_points(WORKFLOW_ENTRY_POINT_GROUP):
        workflow = load_workflow(entry_point)
        try:
            registry.register(workflow)
        except (TypeError, ValueError) as exc:
            raise PluginDiscoveryError(
                f"failed to register workflow from {_describe(entry_point)}: {exc}"
            ) from exc
        logger.info("Discovered workflow %s (%s)", workflow.name, entry_point.value)
