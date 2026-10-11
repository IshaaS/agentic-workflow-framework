"""Show what the Anthropic intent provider extracts from a request, without running agents.

Usage (needs ANTHROPIC_API_KEY and the [llm] extra; makes one paid API call):

    python scripts/debug_intent.py "What should I wear for an outdoor walk in Chicago?"

Safe to share: the API key and the request text are never printed. Values of
parameters that have allowed_values are shown (they are meant to come from a
fixed list); other values are shown only as their length unless --show-values
is given.
"""

import argparse
import sys

from agentctl_core import (
    AgentRegistry,
    IntentProviderError,
    IntentValidationError,
    build_intent_catalog,
    discover_agents,
    validate_intent,
)
from agentctl_core.intent import canonicalize_intent
from agentctl_core.providers.anthropic import AnthropicIntentProvider


def describe(intent, catalog, show_values):
    goal = catalog.goals.get(intent.goal) if isinstance(intent.goal, str) else None
    print(f"  goal: {intent.goal!r}")
    if not isinstance(intent.parameters, dict):
        print(f"  parameters: not an object ({type(intent.parameters).__name__})")
        return
    if not intent.parameters:
        print("  parameters: (none)")
    for name, value in intent.parameters.items():
        spec = goal.parameters.get(name) if goal else None
        if show_values or (spec is not None and spec.allowed_values):
            shown = repr(value)
        else:
            shown = f"<{type(value).__name__}, {len(value) if isinstance(value, str) else '?'} chars>"
        print(f"  parameters[{name!r}]: {shown}")
    if goal:
        missing = [name for name in goal.required if name not in intent.parameters]
        print(f"  required parameters not returned: {', '.join(missing) or 'none'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("request")
    parser.add_argument("--show-values", action="store_true", help="also print free-text values")
    args = parser.parse_args()

    registry = AgentRegistry()
    discover_agents(registry)
    catalog = build_intent_catalog(registry)
    try:
        provider = AnthropicIntentProvider.from_environment()
    except IntentProviderError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    print(f"model: {provider.model}; request: {len(args.request)} characters")

    try:
        intent = provider.resolve(args.request, catalog)
    except IntentProviderError as exc:
        print(f"provider error: {exc}")
        return 1

    print("parsed intent returned by the model:")
    describe(intent, catalog, args.show_values)

    canonical, changed = canonicalize_intent(intent, catalog)
    print(f"canonicalized parameters: {', '.join(changed) or 'none'}")
    try:
        validated = validate_intent(canonical, catalog)
    except IntentValidationError as exc:
        print(f"validation: REJECTED - {exc}")
        return 1
    print(f"validation: OK - goal {validated.goal!r} with parameters {', '.join(sorted(validated.inputs))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
