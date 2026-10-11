import pytest

from agentctl_core import RuntimeContext


@pytest.fixture
def context() -> RuntimeContext:
    return RuntimeContext(session_id="test-session", workflow_id="test-workflow", inputs={})


@pytest.fixture
def seeded_db(tmp_path):
    """A fresh wardrobe database with the demo seed items, unique per test."""
    from agentctl_agents.shelf.db import initialize_database

    path = tmp_path / "wardrobe.db"
    initialize_database(path, seed=True)
    return path
