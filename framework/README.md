# agentctl-core

Generic SDK contracts for the Agentic Workflow Framework. It has no runtime
dependencies and contains no application-specific code.

## Install

```bash
python -m pip install -e ./framework
```

## Public types

```python
from agentctl_core import (
    AgentManifest,       # agent metadata: name, version, description, capabilities
    BaseAgent,           # abstract base: implement `manifest` and `run(inputs, context)`
    Capability,          # name + data keys it `requires` and `produces`
    RuntimeContext,      # per-execution ids, inputs, results, memory, events, logger
    WorkflowDefinition,  # named, ordered list of capability ids
    WorkflowPlan,        # ordered capability ids to execute; source "named" or "generated"
)
```

The same types can also be imported from `agentctl_core.sdk` and
`agentctl_core.context`.

## Plugins and discovery

Agents and named workflows ship as separate distributions and register
Python entry points:

| Group | Entry point target |
|---|---|
| `agentctl.agents` | a `BaseAgent` subclass that takes no constructor arguments |
| `agentctl.workflows` | a zero-argument function returning a `WorkflowDefinition` |

```toml
[project.entry-points."agentctl.agents"]
example = "my_package.agent:ExampleAgent"
```

Load every installed plugin into fresh registries:

```python
from agentctl_core import AgentRegistry, WorkflowRegistry, discover_agents, discover_workflows

agents, workflows = AgentRegistry(), WorkflowRegistry()
discover_agents(agents)
discover_workflows(workflows)

agents.list_agents()                     # sorted by manifest name
agents.find_by_capability("demo.echo")   # agent or None
workflows.get_workflow("demo_flow")      # WorkflowDefinition or None
```

Entry points are loaded in `(name, value)` order. A plugin that fails to
import, has the wrong type, or duplicates an agent or capability name raises
`PluginDiscoveryError` naming the entry point.

Loading an entry point runs the plugin's code. Only install plugins you trust.

## Planning and running workflows

```python
from agentctl_core import CapabilityPlanner, RuntimeContext, SequentialOrchestrator

planner = CapabilityPlanner(agents)
inputs = {"text": "hello"}

# From a goal: the output key you want. Producers are resolved backwards.
plan = planner.plan_for_goal("echo", inputs, external_inputs={"text"})

# Or from a registered named workflow, validated in its declared order.
plan = planner.plan_from_workflow(workflows.get_workflow("demo_flow"), inputs, external_inputs={"text"})

context = RuntimeContext(session_id="s1", workflow_id="run-1", inputs=inputs)
SequentialOrchestrator(agents).execute(plan, context)
context.results   # produced outputs, keyed by output name
context.events    # workflow_started, agent_started/completed/failed, workflow_completed/failed
```

`external_inputs` names the keys the caller is expected to supply. A missing
key in that set raises `MissingInputError`; any other missing key raises
`MissingCapabilityError`. Planning failures are subclasses of `PlanningError`
and happen before any agent runs. Execution failures raise
`WorkflowExecutionError`, which has a `reason`, `capability` and
`step_index`, with the agent's original exception as `__cause__`.
