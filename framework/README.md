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
