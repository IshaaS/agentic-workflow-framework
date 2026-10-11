"""The boundary between a natural-language request and the deterministic framework.

An intent provider only picks a goal and extracts parameters. It never plans
steps or runs agents; its answer is validated before anything executes.
"""

import re
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


def canonicalize_intent(intent: ResolvedIntent, catalog: IntentCatalog) -> tuple[ResolvedIntent, list[str]]:
    """Replace provider values that differ from an allowed value only in formatting.

    Two strings count as the same when they are equal after lowercasing and
    treating runs of spaces, hyphens and underscores as one underscore, so
    ``"Outdoor walk"`` becomes ``"outdoor_walk"`` if that is an allowed value.
    Meaning is never inferred here: a value that matches no allowed value, or
    more than one, is left unchanged for validation to reject. Returns the new
    intent and the names of the parameters that changed.
    """
    if not isinstance(intent, ResolvedIntent) or not isinstance(intent.parameters, dict):
        return intent, []
    goal = catalog.goals.get(intent.goal) if isinstance(intent.goal, str) else None
    if goal is None:
        return intent, []

    parameters = dict(intent.parameters)
    changed = []
    for name, value in intent.parameters.items():
        spec = goal.parameters.get(name)
        if spec is None or not spec.allowed_values or not isinstance(value, str):
            continue
        if value in spec.allowed_values:
            continue
        matches = [allowed for allowed in spec.allowed_values if _format_key(allowed) == _format_key(value)]
        if len(matches) == 1:
            parameters[name] = matches[0]
            changed.append(name)
    return ResolvedIntent(goal=intent.goal, parameters=parameters), changed


def _format_key(value: str) -> str:
    return re.sub(r"[\s_-]+", "_", value.strip().lower())
