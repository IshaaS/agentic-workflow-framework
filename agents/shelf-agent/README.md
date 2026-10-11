# agentctl-shelf-agent

Agent `shelf_manager`, capability `shelf.match`: `clothing_requirements` →
`outfit`.

For each category (`top`, `bottom`, `outerwear`, `footwear`), the agent picks
the first preferred clothing type that has an available item in the SQLite
wardrobe. If several items match, the one with the lowest `id` wins. A
category with no match, or an empty `outerwear` list, comes back as `None`.

```python
{"outfit": {"top": {"id": 2, "name": "Navy polo", "clothing_type": "polo", "color": "navy"},
            "bottom": {...}, "outerwear": None, "footwear": {...}}}
```

## Setting up the database

The agent never creates a database. Create one first:

```bash
agentctl-shelf-init --db ./wardrobe.db          # empty wardrobe
agentctl-shelf-init --db ./wardrobe.db --seed   # plus 19 demo items
export SHELF_DB_PATH=./wardrobe.db
```

`--seed` is safe to repeat. Demo items have fixed ids and are added with
`INSERT OR IGNORE`, so existing rows, including ones you've edited, are never
duplicated or overwritten.

The agent finds the database in this order:
1. The `ShelfAgent(db_path=...)` constructor argument.
2. The `SHELF_DB_PATH` environment variable, read when the agent runs.

There is no default path. A missing path, a missing file, or a file without
the `clothing_items` table raises `ShelfDatabaseError` explaining how to
create it. The agent opens the database read-only.

```sql
CREATE TABLE IF NOT EXISTS clothing_items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    clothing_type TEXT NOT NULL,
    color TEXT NOT NULL,
    available INTEGER NOT NULL DEFAULT 1
);
```
