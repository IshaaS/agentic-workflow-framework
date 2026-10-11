"""Check a provider's proposed intent against the catalog before anything runs.

Values from explicit ``--input`` arguments take precedence over values the
provider extracted, and both are checked against the same rules. Nothing is
coerced or remapped: a value either matches the declared type and allowed
values exactly or the intent is rejected.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agentctl_core.errors import IntentValidationError
from agentctl_core.intent import ResolvedIntent
from agentctl_core.intent_catalog import IntentCatalog


@dataclass
class ValidatedIntent:
    goal: str
    inputs: dict[str, str]


def validate_intent(
    intent: ResolvedIntent | Mapping[str, Any],
    catalog: IntentCatalog,
    explicit_inputs: Mapping[str, str] | None = None,
) -> ValidatedIntent:
    goal, proposed = _structure(intent)

    entry = catalog.goals.get(goal)
    if entry is None:
        available = ", ".join(catalog.goals) or "none"
        raise IntentValidationError(
            f"unsupported natural-language goal {goal!r} (available: {available})", goal=goal
        )

    sources = {key: "request" for key in proposed}
    sources.update({key: "--input" for key in explicit_inputs or {}})
    merged = {**proposed, **(explicit_inputs or {})}

    for key, value in merged.items():
        spec = entry.parameters.get(key)
        where = f" (from {sources[key]})"
        if spec is None:
            raise IntentValidationError(
                f"unknown parameter {key!r} for selected goal {goal!r}{where}", goal=goal, parameter=key
            )
        if not isinstance(value, str):
            raise IntentValidationError(
                f"parameter {key!r} must be a {spec.value_type}, got {type(value).__name__}{where}",
                goal=goal,
                parameter=key,
            )
        if not value.strip():
            raise IntentValidationError(
                f"parameter {key!r} must not be empty{where}", goal=goal, parameter=key
            )
        if spec.allowed_values is not None and value not in spec.allowed_values:
            raise IntentValidationError(
                f"parameter {key!r} must be one of: {', '.join(spec.allowed_values)}; "
                f"got {value!r}{where}",
                goal=goal,
                parameter=key,
            )

    missing = [name for name in entry.required if name not in merged]
    if missing:
        names = ", ".join(repr(name) for name in missing)
        hint = " ".join(f"--input {name}=VALUE" for name in missing)
        noun = "input" if len(missing) == 1 else "inputs"
        raise IntentValidationError(
            f"missing required {noun} {names} for goal {goal!r}; supply {hint}",
            goal=goal,
            parameter=missing[0],
        )
    return ValidatedIntent(goal=goal, inputs=dict(merged))


def _structure(intent: ResolvedIntent | Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if isinstance(intent, ResolvedIntent):
        goal, parameters = intent.goal, intent.parameters
    elif isinstance(intent, Mapping):
        unexpected = sorted(set(map(str, intent)) - {"goal", "parameters"})
        if unexpected:
            raise IntentValidationError(f"intent has unexpected fields: {', '.join(unexpected)}")
        goal, parameters = intent.get("goal"), intent.get("parameters", {})
    else:
        raise IntentValidationError(f"intent must be an object, got {type(intent).__name__}")

    if not isinstance(goal, str) or not goal.strip():
        raise IntentValidationError(f"intent goal must be a non-empty string, got {goal!r}")
    if not isinstance(parameters, Mapping):
        raise IntentValidationError(
            f"intent parameters must be an object, got {type(parameters).__name__}", goal=goal
        )
    for key in parameters:
        if not isinstance(key, str):
            raise IntentValidationError(f"intent parameter names must be strings, got {key!r}", goal=goal)
    return goal, dict(parameters)
