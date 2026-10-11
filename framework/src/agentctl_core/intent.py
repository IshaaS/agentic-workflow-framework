"""The boundary between a natural-language request and the deterministic framework.

An intent provider only picks a goal and extracts parameters. It never plans
steps or runs agents; its answer is validated before anything executes.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from agentctl_core.intent_catalog import IntentCatalog


@dataclass
class ResolvedIntent:
    """A provider's proposal: one goal and the parameters it found in the request."""

    goal: Any
    parameters: Any = field(default_factory=dict)


class IntentProvider(Protocol):
    def resolve(self, request: str, catalog: IntentCatalog) -> ResolvedIntent:
        """Map ``request`` to a goal and parameters from ``catalog``.

        Raises ``IntentProviderConfigError`` when the provider is not usable as
        configured and ``IntentProviderError`` for run-time failures.
        """
        ...
