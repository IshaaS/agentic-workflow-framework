"""``agentctl``: list installed plugins and run workflows.

Exit codes: 0 success, 2 usage error, 3 planning error (including an unknown
workflow name), 4 execution error, 5 plugin discovery error.

Results are printed to stdout as JSON; logs and errors go to stderr.
"""

import argparse
import json
import logging
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from agentctl_core.context import RuntimeContext
from agentctl_core.discovery import PluginDiscoveryError, discover_agents, discover_workflows
from agentctl_core.errors import MissingInputError, PlanningError, WorkflowExecutionError
from agentctl_core.orchestrator import SequentialOrchestrator
from agentctl_core.planner import CapabilityPlanner
from agentctl_core.registry import AgentRegistry, WorkflowRegistry
from agentctl_core.sdk import WorkflowPlan

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PLANNING = 3
EXIT_EXECUTION = 4
EXIT_PLUGIN = 5

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class CLIError(Exception):
    def __init__(self, exit_code: int, message: str) -> None:
        self.exit_code = exit_code
        super().__init__(message)


def main(argv: list[str] | None = None) -> int:
    parser, run_workflow_parser = build_parser()
    try:
        args = parser.parse_args(argv)
        inputs = parse_inputs(args.input) if args.command == "run" else {}
        if args.command == "run" and (args.name is None) == (args.goal is None):
            raise ValueError("give exactly one of a workflow NAME or --goal")
    except SystemExit as exc:  # argparse already printed usage or help
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    except ValueError as exc:
        try:
            run_workflow_parser.error(str(exc))
        except SystemExit as usage_exit:
            return usage_exit.code

    with _stderr_logging():
        try:
            if args.command == "list":
                return list_agents() if args.what == "agents" else list_workflows()
            return run_workflow(args.name, args.goal, inputs)
        except CLIError as exc:
            print(f"agentctl: error: {exc}", file=sys.stderr)
            return exc.exit_code


def build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    parser = argparse.ArgumentParser(
        prog="agentctl",
        description="List installed agents and workflows, and run workflows.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    list_parser = commands.add_parser("list", help="list installed agents or workflows")
    list_targets = list_parser.add_subparsers(dest="what", required=True, metavar="TARGET")
    list_targets.add_parser("agents", help="show agent manifests and capabilities")
    list_targets.add_parser("workflows", help="show named workflows and their steps")

    run_parser = commands.add_parser("run", help="run a workflow")
    run_targets = run_parser.add_subparsers(dest="what", required=True, metavar="TARGET")
    run_workflow_parser = run_targets.add_parser(
        "workflow",
        help="run a named workflow, or a plan generated for --goal",
        description=(
            "Run a registered workflow by NAME, or generate a plan that produces "
            "the output key given by --goal. Give exactly one of the two."
        ),
    )
    run_workflow_parser.add_argument("name", nargs="?", help="registered workflow name")
    run_workflow_parser.add_argument("--goal", help="output key to produce with a generated plan")
    run_workflow_parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="workflow input; repeat for several (values are strings)",
    )
    return parser, run_workflow_parser


def parse_inputs(pairs: list[str]) -> dict[str, str]:
    """Parse repeated ``KEY=VALUE`` strings, splitting at the first ``=``."""
    inputs: dict[str, str] = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        key = key.strip()
        if not separator:
            raise ValueError(f"--input {pair!r} must have the form KEY=VALUE")
        if not key:
            raise ValueError(f"--input {pair!r} has an empty key")
        if key in inputs:
            raise ValueError(f"--input {key!r} was given more than once")
        inputs[key] = value
    return inputs


def external_inputs(agents: AgentRegistry, inputs: dict[str, Any]) -> set[str]:
    """Keys the user is expected to supply.

    Plugins do not mark which keys come from users, so any required key that
    no installed capability produces is treated as a user input, along with
    every key the user actually passed.
    """
    required: set[str] = set()
    produced: set[str] = set()
    for agent in agents.list_agents():
        for capability in agent.manifest.capabilities:
            required.update(capability.requires)
            produced.update(capability.produces)
    return (required - produced) | set(inputs)


def list_agents() -> int:
    agents = _discover_agents()
    if not agents.list_agents():
        print("No agents installed.")
    for agent in agents.list_agents():
        manifest = agent.manifest
        print(f"{manifest.name} {manifest.version}")
        print(f"  {manifest.description}")
        for capability in manifest.capabilities:
            print(f"  capability: {capability.name}")
            print(f"    requires: {', '.join(capability.requires) or '-'}")
            print(f"    produces: {', '.join(capability.produces) or '-'}")
    return EXIT_OK


def list_workflows() -> int:
    workflows = _discover_workflows()
    if not workflows.list_workflows():
        print("No workflows installed.")
    for workflow in workflows.list_workflows():
        print(workflow.name)
        print(f"  {workflow.description}")
        print(f"  steps: {' -> '.join(workflow.steps)}")
    return EXIT_OK


def run_workflow(name: str | None, goal: str | None, inputs: dict[str, str]) -> int:
    agents = _discover_agents()
    planner = CapabilityPlanner(agents)
    external = external_inputs(agents, inputs)

    try:
        if goal is not None:
            plan = planner.plan_for_goal(goal, inputs, external)
        else:
            workflows = _discover_workflows()
            definition = workflows.get_workflow(name)
            if definition is None:
                installed = ", ".join(w.name for w in workflows.list_workflows()) or "none"
                raise CLIError(
                    EXIT_PLANNING, f"unknown workflow {name!r} (installed workflows: {installed})"
                )
            plan = planner.plan_from_workflow(definition, inputs, external)
    except MissingInputError as exc:
        raise CLIError(
            EXIT_PLANNING, f"{exc}; pass it with --input {exc.input_name}=VALUE"
        ) from exc
    except PlanningError as exc:
        raise CLIError(EXIT_PLANNING, str(exc)) from exc

    context = RuntimeContext(
        session_id=uuid.uuid4().hex, workflow_id=uuid.uuid4().hex, inputs=inputs
    )
    try:
        SequentialOrchestrator(agents).execute(plan, context)
    except WorkflowExecutionError as exc:
        raise CLIError(EXIT_EXECUTION, str(exc)) from exc

    result = select_result(plan, context, agents, goal)
    try:
        output = json.dumps(result, indent=2)
    except (TypeError, ValueError) as exc:
        raise CLIError(EXIT_EXECUTION, f"workflow result is not JSON-serializable: {exc}") from exc
    print(output)
    return EXIT_OK


def select_result(
    plan: WorkflowPlan, context: RuntimeContext, agents: AgentRegistry, goal: str | None
) -> Any:
    """The value to print: the goal's value, or the last step's declared outputs."""
    if goal is not None:
        return context.results[goal] if plan.steps else context.inputs[goal]

    last = plan.steps[-1]
    agent = agents.find_by_capability(last)
    capability = next(c for c in agent.manifest.capabilities if c.name == last)
    if len(capability.produces) == 1:
        return context.results[capability.produces[0]]
    return {key: context.results[key] for key in capability.produces}


def _discover_agents() -> AgentRegistry:
    registry = AgentRegistry()
    try:
        discover_agents(registry)
    except PluginDiscoveryError as exc:
        raise CLIError(EXIT_PLUGIN, str(exc)) from exc
    return registry


def _discover_workflows() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    try:
        discover_workflows(registry)
    except PluginDiscoveryError as exc:
        raise CLIError(EXIT_PLUGIN, str(exc)) from exc
    return registry


@contextmanager
def _stderr_logging() -> Iterator[None]:
    """Send ``agentctl`` logs at INFO and above to stderr for one CLI call, then undo it."""
    logger = logging.getLogger("agentctl")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


if __name__ == "__main__":
    sys.exit(main())
