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
