"""Generic SDK contracts for the Agentic Workflow Framework."""

from agentctl_core.context import RuntimeContext
from agentctl_core.discovery import (
    AGENT_ENTRY_POINT_GROUP,
    WORKFLOW_ENTRY_POINT_GROUP,
    PluginDiscoveryError,
    discover_agents,
    discover_workflows,
)
from agentctl_core.errors import (
    AmbiguousProviderError,
    CircularDependencyError,
    InvalidWorkflowPlanError,
    MissingCapabilityError,
    MissingInputError,
    PlanningError,
    UnknownGoalError,
    WorkflowExecutionError,
)
from agentctl_core.orchestrator import SequentialOrchestrator
from agentctl_core.planner import CapabilityPlanner
from agentctl_core.registry import AgentRegistry, WorkflowRegistry
from agentctl_core.sdk import (
    AgentManifest,
    BaseAgent,
    Capability,
    WorkflowDefinition,
    WorkflowPlan,
)

__version__ = "0.1.0"

__all__ = [
    "AGENT_ENTRY_POINT_GROUP",
    "WORKFLOW_ENTRY_POINT_GROUP",
    "AgentManifest",
    "AgentRegistry",
    "AmbiguousProviderError",
    "BaseAgent",
    "Capability",
    "CapabilityPlanner",
    "CircularDependencyError",
    "InvalidWorkflowPlanError",
    "MissingCapabilityError",
    "MissingInputError",
    "PlanningError",
    "PluginDiscoveryError",
    "RuntimeContext",
    "SequentialOrchestrator",
    "UnknownGoalError",
    "WorkflowDefinition",
    "WorkflowExecutionError",
    "WorkflowPlan",
    "WorkflowRegistry",
    "discover_agents",
    "discover_workflows",
]
