"""Execution-scoped runtime context shared with agents during a workflow run."""

import logging
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeContext:
    """State for a single workflow execution.

    ``memory`` and ``events`` live only as long as this object; there is no
    persistence or pub/sub. The SDK never configures logging handlers; that
    is left to the runtime.
    """

    session_id: str
    workflow_id: str
    inputs: dict[str, Any]
    results: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("agentctl")
    )
