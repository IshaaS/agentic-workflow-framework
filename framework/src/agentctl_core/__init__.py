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
    IntentCatalogError,
    IntentProviderConfigError,
    IntentProviderError,
    IntentValidationError,
    InvalidWorkflowPlanError,
    MissingCapabilityError,
    MissingInputError,
    PlanningError,
    UnknownGoalError,
    WorkflowExecutionError,
)
from agentctl_core.intent import IntentProvider, ResolvedIntent
from agentctl_core.intent_catalog import IntentCatalog, build_intent_catalog
from agentctl_core.intent_validation import ValidatedIntent, validate_intent
from agentctl_core.orchestrator import SequentialOrchestrator
from agentctl_core.planner import CapabilityPlanner
from agentctl_core.registry import AgentRegistry, WorkflowRegistry
from agentctl_core.sdk import (
    AgentManifest,
    BaseAgent,
    Capability,
    GoalSpec,
    InputSpec,
    WorkflowDefinition,
    WorkflowPlan,
)

__version__ = "0.1.0"

__all__ = [
    "AGENT_ENTRY_POINT_GROUP",
    "AgentManifest",
    "AgentRegistry",
    "AmbiguousProviderError",
    "BaseAgent",
    "Capability",
    "CapabilityPlanner",
    "CircularDependencyError",
    "GoalSpec",
    "InputSpec",
    "IntentCatalog",
    "IntentCatalogError",
    "IntentProvider",
    "IntentProviderConfigError",
    "IntentProviderError",
    "IntentValidationError",
    "InvalidWorkflowPlanError",
    "MissingCapabilityError",
    "MissingInputError",
    "PlanningError",
    "PluginDiscoveryError",
    "ResolvedIntent",
    "RuntimeContext",
    "SequentialOrchestrator",
    "UnknownGoalError",
    "ValidatedIntent",
    "WORKFLOW_ENTRY_POINT_GROUP",
    "WorkflowDefinition",
    "WorkflowExecutionError",
    "WorkflowPlan",
    "WorkflowRegistry",
    "build_intent_catalog",
    "discover_agents",
    "discover_workflows",
    "validate_intent",
]
