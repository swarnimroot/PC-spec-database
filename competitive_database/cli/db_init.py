"""``db-init`` CLI subcommand — bootstrap a SQLite DB with the full schema."""

from __future__ import annotations

import argparse

from ..db.connection import apply_schema, connect, transaction


def main(args: argparse.Namespace) -> None:
    """Open (or create) the DB at ``args.path`` and apply the schema."""
    conn = connect(args.path)
    try:
        with transaction(conn):
            apply_schema(conn)
    finally:
        conn.close()
    print(f"Initialized {args.path}")
