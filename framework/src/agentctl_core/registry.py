"""In-memory registries for agents and named workflows."""

from agentctl_core.sdk import AgentManifest, BaseAgent, Capability, WorkflowDefinition


def _is_blank(value: object) -> bool:
    return not isinstance(value, str) or not value.strip()


class AgentRegistry:
    """Agents indexed by manifest name and by capability name.

    Agent names and capability names must be unique across the registry.
    ``list_agents`` returns agents sorted by manifest name.
    """

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._capability_owners: dict[str, str] = {}

    def register(self, agent: BaseAgent) -> None:
        if not isinstance(agent, BaseAgent):
            raise TypeError(f"expected a BaseAgent instance, got {type(agent).__name__}")

        manifest = agent.manifest
        if not isinstance(manifest, AgentManifest):
            raise TypeError(
                f"{type(agent).__name__}.manifest must be an AgentManifest, "
                f"got {type(manifest).__name__}"
            )
        if _is_blank(manifest.name):
            raise ValueError(f"{type(agent).__name__} has a blank manifest name")
        if manifest.name in self._agents:
            raise ValueError(f"agent {manifest.name!r} is already registered")

        capability_names: list[str] = []
        for capability in manifest.capabilities:
            if not isinstance(capability, Capability):
                raise TypeError(
                    f"agent {manifest.name!r} declares a capability that is not a "
                    f"Capability: {capability!r}"
                )
            if _is_blank(capability.name):
                raise ValueError(f"agent {manifest.name!r} declares a blank capability name")
            if capability.name in capability_names:
                raise ValueError(
                    f"agent {manifest.name!r} declares capability "
                    f"{capability.name!r} more than once"
                )
            owner = self._capability_owners.get(capability.name)
            if owner is not None:
                raise ValueError(
                    f"capability {capability.name!r} declared by agent "
                    f"{manifest.name!r} is already provided by agent {owner!r}"
                )
            capability_names.append(capability.name)

        self._agents[manifest.name] = agent
        for name in capability_names:
            self._capability_owners[name] = manifest.name

    def list_agents(self) -> list[BaseAgent]:
        return [self._agents[name] for name in sorted(self._agents)]

    def get_agent(self, name: str) -> BaseAgent | None:
        return self._agents.get(name)

    def find_by_capability(self, capability_name: str) -> BaseAgent | None:
        owner = self._capability_owners.get(capability_name)
        return None if owner is None else self._agents[owner]


class WorkflowRegistry:
    """Named workflow definitions. ``list_workflows`` is sorted by name.

    Definitions are stored as metadata only; their steps are not validated
    against registered capabilities here.
    """

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowDefinition] = {}

    def register(self, workflow: WorkflowDefinition) -> None:
        if not isinstance(workflow, WorkflowDefinition):
            raise TypeError(
                f"expected a WorkflowDefinition, got {type(workflow).__name__}"
            )
        if _is_blank(workflow.name):
            raise ValueError("workflow definition has a blank name")
        if workflow.name in self._workflows:
            raise ValueError(f"workflow {workflow.name!r} is already registered")

        self._workflows[workflow.name] = workflow

    def list_workflows(self) -> list[WorkflowDefinition]:
        return [self._workflows[name] for name in sorted(self._workflows)]

    def get_workflow(self, name: str) -> WorkflowDefinition | None:
        return self._workflows.get(name)
