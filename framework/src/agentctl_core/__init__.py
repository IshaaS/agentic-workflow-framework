"""Generic SDK contracts for the Agentic Workflow Framework."""

from agentctl_core.context import RuntimeContext
from agentctl_core.sdk import (
    AgentManifest,
    BaseAgent,
    Capability,
    WorkflowDefinition,
    WorkflowPlan,
)

__version__ = "0.1.0"

__all__ = [
    "AgentManifest",
    "BaseAgent",
    "Capability",
    "RuntimeContext",
    "WorkflowDefinition",
    "WorkflowPlan",
]
