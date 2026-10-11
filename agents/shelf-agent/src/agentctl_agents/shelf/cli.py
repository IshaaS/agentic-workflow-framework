"""``agentctl-shelf-init``: create the wardrobe database, optionally with demo items."""

import argparse
import sys

from agentctl_agents.shelf.db import SEED_ITEMS, ShelfDatabaseError, initialize_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agentctl-shelf-init",
        description="Create the shelf agent's SQLite wardrobe database.",
    )
    parser.add_argument("--db", required=True, help="path of the database file to create or update")
    parser.add_argument(
        "--seed",
        action="store_true",
        help=f"add the {len(SEED_ITEMS)} demo items; existing rows are kept",
    )
    args = parser.parse_args(argv)

    try:
        inserted = initialize_database(args.db, seed=args.seed)
    except ShelfDatabaseError as exc:
        print(f"agentctl-shelf-init: error: {exc}", file=sys.stderr)
        return 1

    message = f"Wardrobe database ready at {args.db}"
    if args.seed:
        message += f" ({inserted} demo item(s) added)"
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
