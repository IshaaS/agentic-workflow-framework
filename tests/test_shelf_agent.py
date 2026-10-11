"""Sprint 03 shelf manager tests. Every test uses its own temporary database."""

import logging
import sqlite3
from contextlib import closing

import pytest

from agentctl_agents.shelf import cli
from agentctl_agents.shelf.agent import ShelfAgent
from agentctl_agents.shelf.db import (
    SEED_ITEMS,
    ShelfDatabaseError,
    initialize_database,
)

REQUIREMENTS = {
    "top": ["t_shirt", "polo"],
    "bottom": ["pants", "jeans"],
    "outerwear": ["rain_jacket", "light_jacket"],
    "footwear": ["walking_shoes", "sneakers"],
}


def make_db(tmp_path, rows):
    """An initialized database holding exactly ``rows`` (id, name, category, type, color, available)."""
    path = tmp_path / "custom.db"
    initialize_database(path)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executemany("INSERT INTO clothing_items VALUES (?, ?, ?, ?, ?, ?)", rows)
    return path


def rows_in(path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT * FROM clothing_items ORDER BY id").fetchall()


def requirements(**overrides):
    return {**REQUIREMENTS, **overrides}


# Initialization and seeding -------------------------------------------------


def test_init_command_creates_empty_database(tmp_path, capsys):
    path = tmp_path / "wardrobe.db"

    assert cli.main(["--db", str(path)]) == 0
    assert rows_in(path) == []
    assert "Wardrobe database ready" in capsys.readouterr().out


def test_init_command_seeds(tmp_path, capsys):
    path = tmp_path / "wardrobe.db"

    assert cli.main(["--db", str(path), "--seed"]) == 0
    assert rows_in(path) == SEED_ITEMS
    assert f"{len(SEED_ITEMS)} demo item(s) added" in capsys.readouterr().out


def test_reseeding_neither_duplicates_nor_overwrites(tmp_path, capsys):
    path = tmp_path / "wardrobe.db"
    cli.main(["--db", str(path), "--seed"])
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE clothing_items SET name = 'My favourite polo', available = 0 WHERE id = 2")
        conn.execute("INSERT INTO clothing_items VALUES (100, 'Own scarf', 'outerwear', 'scarf', 'red', 1)")
    capsys.readouterr()

    assert cli.main(["--db", str(path), "--seed"]) == 0

    rows = rows_in(path)
    assert len(rows) == len(SEED_ITEMS) + 1
    assert rows[1] == (2, "My favourite polo", "top", "polo", "navy", 0)
    assert rows[-1] == (100, "Own scarf", "outerwear", "scarf", "red", 1)
    assert "0 demo item(s) added" in capsys.readouterr().out


def test_init_command_reports_unwritable_path(tmp_path, capsys):
    assert cli.main(["--db", str(tmp_path / "no-such-dir" / "w.db")]) == 1
    assert "cannot initialize wardrobe database" in capsys.readouterr().err


def test_init_command_requires_db(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2


def test_seed_data_has_unavailable_and_duplicate_type_items():
    assert any(item[5] == 0 for item in SEED_ITEMS)
    types = [(item[2], item[3]) for item in SEED_ITEMS if item[5] == 1]
    assert len(types) > len(set(types))


# Matching -------------------------------------------------------------------


def test_matches_seeded_wardrobe(context, seeded_db):
    result = ShelfAgent(db_path=seeded_db).run({"clothing_requirements": REQUIREMENTS}, context)

    assert result == {
        "outfit": {
            "top": {"id": 1, "name": "White t-shirt", "clothing_type": "t_shirt", "color": "white"},
            "bottom": {"id": 10, "name": "Olive chinos", "clothing_type": "pants", "color": "olive"},
            "outerwear": {"id": 13, "name": "Yellow rain jacket", "clothing_type": "rain_jacket", "color": "yellow"},
            "footwear": {"id": 17, "name": "Brown walking shoes", "clothing_type": "walking_shoes", "color": "brown"},
        }
    }


def test_falls_back_when_first_preference_absent(context, tmp_path):
    db = make_db(tmp_path, [
        (1, "Polo", "top", "polo", "navy", 1),
        (2, "Jeans", "bottom", "jeans", "blue", 1),
        (3, "Sneakers", "footwear", "sneakers", "white", 1),
    ])

    outfit = ShelfAgent(db).run({"clothing_requirements": REQUIREMENTS}, context)["outfit"]

    assert outfit["top"]["clothing_type"] == "polo"
    assert outfit["bottom"]["clothing_type"] == "jeans"
    assert outfit["footwear"]["clothing_type"] == "sneakers"


def test_falls_back_when_first_preference_unavailable(context, seeded_db):
    # Seed item 11 (dress_pants) is unavailable, so pants are chosen.
    outfit = ShelfAgent(seeded_db).run(
        {"clothing_requirements": requirements(bottom=["dress_pants", "pants"])}, context
    )["outfit"]

    assert outfit["bottom"]["id"] == 10


def test_unavailable_items_never_selected(context, tmp_path):
    db = make_db(tmp_path, [
        (1, "Lost t-shirt", "top", "t_shirt", "red", 0),
        (2, "Lost polo", "top", "polo", "blue", 0),
        (3, "Jeans", "bottom", "jeans", "blue", 1),
        (4, "Sneakers", "footwear", "sneakers", "white", 1),
    ])

    outfit = ShelfAgent(db).run({"clothing_requirements": REQUIREMENTS}, context)["outfit"]

    assert outfit["top"] is None


def test_lowest_id_wins_ties(context, tmp_path):
    db = make_db(tmp_path, [
        (7, "Second tee", "top", "t_shirt", "black", 1),
        (3, "First tee", "top", "t_shirt", "white", 1),
        (9, "Jeans", "bottom", "jeans", "blue", 1),
        (1, "Sneakers", "footwear", "sneakers", "white", 1),
    ])

    outfit = ShelfAgent(db).run({"clothing_requirements": REQUIREMENTS}, context)["outfit"]

    assert outfit["top"]["id"] == 3


def test_category_filtering(context, tmp_path):
    # A "polo" stored under footwear must not satisfy the top category.
    db = make_db(tmp_path, [
        (1, "Odd polo", "footwear", "polo", "blue", 1),
        (2, "Jeans", "bottom", "jeans", "blue", 1),
    ])

    outfit = ShelfAgent(db).run({"clothing_requirements": REQUIREMENTS}, context)["outfit"]

    assert outfit["top"] is None
    assert outfit["footwear"] is None


def test_unmatched_categories_are_none_and_keys_kept(context, tmp_path, caplog):
    db = make_db(tmp_path, [(1, "Jeans", "bottom", "jeans", "blue", 1)])

    with caplog.at_level(logging.WARNING, logger="agentctl"):
        outfit = ShelfAgent(db).run({"clothing_requirements": REQUIREMENTS}, context)["outfit"]

    assert list(outfit) == ["top", "bottom", "outerwear", "footwear"]
    assert outfit["top"] is None and outfit["outerwear"] is None and outfit["footwear"] is None
    assert "No available top" in caplog.text


def test_empty_outerwear_returns_none_without_warning(context, seeded_db, caplog):
    with caplog.at_level(logging.WARNING, logger="agentctl"):
        outfit = ShelfAgent(seeded_db).run(
            {"clothing_requirements": requirements(outerwear=[])}, context
        )["outfit"]

    assert outfit["outerwear"] is None
    assert outfit["top"] is not None
    assert "outerwear" not in caplog.text


def test_values_are_bound_not_interpolated(context, seeded_db):
    hostile = "t_shirt' OR '1'='1"
    outfit = ShelfAgent(seeded_db).run(
        {"clothing_requirements": requirements(top=[hostile])}, context
    )["outfit"]

    assert outfit["top"] is None
    assert len(rows_in(seeded_db)) == len(SEED_ITEMS)


# Database configuration -----------------------------------------------------


def test_reads_shelf_db_path_at_run_time(context, seeded_db, monkeypatch):
    agent = ShelfAgent()  # zero-argument constructor, as entry-point discovery uses
    monkeypatch.setenv("SHELF_DB_PATH", str(seeded_db))

    assert agent.run({"clothing_requirements": REQUIREMENTS}, context)["outfit"]["top"]["id"] == 1


def test_constructor_path_overrides_environment(context, seeded_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SHELF_DB_PATH", str(tmp_path / "elsewhere.db"))

    assert ShelfAgent(seeded_db).run({"clothing_requirements": REQUIREMENTS}, context)["outfit"]["top"]


def test_unconfigured_database_is_actionable(context, monkeypatch):
    monkeypatch.delenv("SHELF_DB_PATH", raising=False)

    with pytest.raises(ShelfDatabaseError, match="SHELF_DB_PATH.*agentctl-shelf-init"):
        ShelfAgent().run({"clothing_requirements": REQUIREMENTS}, context)


def test_missing_database_is_not_created(context, tmp_path):
    path = tmp_path / "missing.db"

    with pytest.raises(ShelfDatabaseError, match="does not exist.*agentctl-shelf-init"):
        ShelfAgent(path).run({"clothing_requirements": REQUIREMENTS}, context)
    assert not path.exists()


def test_uninitialized_database_is_actionable(context, tmp_path):
    path = tmp_path / "empty.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE other (id INTEGER)")

    with pytest.raises(ShelfDatabaseError, match="no clothing_items table.*agentctl-shelf-init"):
        ShelfAgent(path).run({"clothing_requirements": REQUIREMENTS}, context)


def test_non_database_file_is_reported(context, tmp_path):
    path = tmp_path / "notes.db"
    path.write_text("not a database")

    with pytest.raises(ShelfDatabaseError, match="cannot read wardrobe database"):
        ShelfAgent(path).run({"clothing_requirements": REQUIREMENTS}, context)


# Input validation -----------------------------------------------------------


@pytest.mark.parametrize(
    "bad, message",
    [
        (None, "must be a dict"),
        (["t_shirt"], "must be a dict"),
        ({k: v for k, v in REQUIREMENTS.items() if k != "footwear"}, "missing category 'footwear'"),
        (requirements(hats=["cap"]), "unexpected clothing categories: hats"),
        (requirements(top="t_shirt"), "list of type names"),
        (requirements(top=["t_shirt", 3]), "list of type names"),
        (requirements(top=[""]), "list of type names"),
        (requirements(bottom=[]), "'bottom'.*must not be empty"),
    ],
)
def test_malformed_requirements_rejected(context, seeded_db, bad, message):
    with pytest.raises(ValueError, match=message):
        ShelfAgent(seeded_db).run({"clothing_requirements": bad}, context)
