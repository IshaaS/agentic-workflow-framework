"""SQLite wardrobe: schema, explicit initialization, demo seed data and matching."""

import sqlite3
from contextlib import closing
from os import PathLike
from pathlib import Path
from typing import Any

CATEGORIES = ("top", "bottom", "outerwear", "footwear")
OPTIONAL_CATEGORIES = ("outerwear",)

SCHEMA = """
CREATE TABLE IF NOT EXISTS clothing_items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    clothing_type TEXT NOT NULL,
    color TEXT NOT NULL,
    available INTEGER NOT NULL DEFAULT 1
);
"""

# Demo wardrobe. IDs are fixed so re-seeding is idempotent: seeding uses
# INSERT OR IGNORE, so an existing row with the same id (including one the
# user has edited) is never overwritten or duplicated.
# (id, name, category, clothing_type, color, available)
SEED_ITEMS = [
    (1, "White t-shirt", "top", "t_shirt", "white", 1),
    (2, "Navy polo", "top", "polo", "navy", 1),
    (3, "Gray long-sleeve shirt", "top", "long_sleeve_shirt", "gray", 1),
    (4, "Green wool sweater", "top", "sweater", "green", 1),
    (5, "White dress shirt", "top", "dress_shirt", "white", 1),
    (6, "Striped t-shirt", "top", "t_shirt", "red", 0),
    (7, "Khaki shorts", "bottom", "shorts", "khaki", 1),
    (8, "Blue jeans", "bottom", "jeans", "blue", 1),
    (9, "Black jeans", "bottom", "jeans", "black", 1),
    (10, "Olive chinos", "bottom", "pants", "olive", 1),
    (11, "Charcoal dress pants", "bottom", "dress_pants", "charcoal", 0),
    (12, "Beige light jacket", "outerwear", "light_jacket", "beige", 1),
    (13, "Yellow rain jacket", "outerwear", "rain_jacket", "yellow", 1),
    (14, "Black winter coat", "outerwear", "winter_coat", "black", 1),
    (15, "Navy blazer", "outerwear", "blazer", "navy", 1),
    (16, "White sneakers", "footwear", "sneakers", "white", 1),
    (17, "Brown walking shoes", "footwear", "walking_shoes", "brown", 1),
    (18, "Leather boots", "footwear", "boots", "brown", 1),
    (19, "Black dress shoes", "footwear", "dress_shoes", "black", 1),
]

INIT_HINT = "create it with: agentctl-shelf-init --db <path> --seed"


class ShelfDatabaseError(RuntimeError):
    """The wardrobe database is missing, uninitialized or unreadable."""


def initialize_database(path: str | PathLike[str], seed: bool = False) -> int:
    """Create the schema at ``path`` (creating the file) and optionally add demo items.

    Returns the number of seed rows inserted (0 when ``seed`` is False or all
    seed ids already exist).
    """
    try:
        with closing(sqlite3.connect(path)) as conn:
            with conn:
                conn.executescript(SCHEMA)
                if not seed:
                    return 0
                before = conn.total_changes
                conn.executemany(
                    "INSERT OR IGNORE INTO clothing_items "
                    "(id, name, category, clothing_type, color, available) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    SEED_ITEMS,
                )
                return conn.total_changes - before
    except sqlite3.Error as exc:
        raise ShelfDatabaseError(f"cannot initialize wardrobe database {str(path)!r}: {exc}") from exc


def open_existing(path: str | PathLike[str]) -> sqlite3.Connection:
    """Open an initialized database read-only. Never creates a file."""
    db_path = Path(path)
    if not db_path.is_file():
        raise ShelfDatabaseError(f"wardrobe database {str(path)!r} does not exist; {INIT_HINT}")
    try:
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ShelfDatabaseError(f"cannot open wardrobe database {str(path)!r}: {exc}") from exc
    try:
        found = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'clothing_items'"
        ).fetchone()
    except sqlite3.Error as exc:
        conn.close()
        raise ShelfDatabaseError(f"cannot read wardrobe database {str(path)!r}: {exc}") from exc
    if found is None:
        conn.close()
        raise ShelfDatabaseError(
            f"wardrobe database {str(path)!r} has no clothing_items table; {INIT_HINT}"
        )
    return conn


def find_item(conn: sqlite3.Connection, category: str, clothing_type: str) -> dict[str, Any] | None:
    """Lowest-id available item of ``clothing_type`` in ``category``, or None."""
    row = conn.execute(
        "SELECT id, name, clothing_type, color FROM clothing_items "
        "WHERE category = ? AND clothing_type = ? AND available = 1 "
        "ORDER BY id LIMIT 1",
        (category, clothing_type),
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "name": row[1], "clothing_type": row[2], "color": row[3]}


def match_outfit(
    conn: sqlite3.Connection, requirements: dict[str, list[str]]
) -> dict[str, dict[str, Any] | None]:
    """For each category, the item for the first preferred type that is available."""
    outfit: dict[str, dict[str, Any] | None] = {}
    for category in CATEGORIES:
        outfit[category] = None
        for clothing_type in requirements[category]:
            item = find_item(conn, category, clothing_type)
            if item is not None:
                outfit[category] = item
                break
    return outfit
