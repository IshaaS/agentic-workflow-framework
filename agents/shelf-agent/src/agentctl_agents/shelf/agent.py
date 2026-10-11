"""Shelf manager: picks owned, available items that match clothing requirements."""

import os
from contextlib import closing
from os import PathLike
from typing import Any

from agentctl_core import AgentManifest, BaseAgent, Capability, RuntimeContext

from agentctl_agents.shelf.db import (
    CATEGORIES,
    INIT_HINT,
    OPTIONAL_CATEGORIES,
    ShelfDatabaseError,
    match_outfit,
    open_existing,
)

DB_PATH_ENV = "SHELF_DB_PATH"


class ShelfAgent(BaseAgent):
    """Returns ``{"outfit": {category: item dict or None}}`` for the four categories.

    The database path is ``db_path`` if given, otherwise the ``SHELF_DB_PATH``
    environment variable read at run time. There is no default path.
    """

    def __init__(self, db_path: str | PathLike[str] | None = None) -> None:
        self._db_path = db_path

    @property
    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="shelf_manager",
            version="0.1.0",
            description="Matches clothing requirements to items on the personal shelf",
            capabilities=[
                Capability(
                    name="shelf.match",
                    requires=["clothing_requirements"],
                    produces=["outfit"],
                )
            ],
        )

    def run(self, inputs: dict[str, Any], context: RuntimeContext) -> dict[str, Any]:
        requirements = _validate_requirements(inputs.get("clothing_requirements"))
        db_path = self._db_path or os.environ.get(DB_PATH_ENV)
        if not db_path:
            raise ShelfDatabaseError(
                f"no wardrobe database configured; set {DB_PATH_ENV} or pass db_path ({INIT_HINT})"
            )

        with closing(open_existing(db_path)) as conn:
            outfit = match_outfit(conn, requirements)

        for category, item in outfit.items():
            if item is None and requirements[category]:
                context.logger.warning(
                    "No available %s matches %s", category, ", ".join(requirements[category])
                )
        context.logger.info(
            "Selected items: %s",
            {category: item["id"] for category, item in outfit.items() if item is not None},
        )
        return {"outfit": outfit}


def _validate_requirements(requirements: Any) -> dict[str, list[str]]:
    if not isinstance(requirements, dict):
        raise ValueError(
            f"'clothing_requirements' must be a dict, got {type(requirements).__name__}"
        )
    unexpected = set(requirements) - set(CATEGORIES)
    if unexpected:
        raise ValueError(f"unexpected clothing categories: {', '.join(sorted(map(str, unexpected)))}")
    for category in CATEGORIES:
        if category not in requirements:
            raise ValueError(f"clothing_requirements is missing category {category!r}")
        types = requirements[category]
        if not isinstance(types, list) or not all(isinstance(t, str) and t for t in types):
            raise ValueError(f"clothing_requirements[{category!r}] must be a list of type names")
        if not types and category not in OPTIONAL_CATEGORIES:
            raise ValueError(f"clothing_requirements[{category!r}] must not be empty")
    return requirements
