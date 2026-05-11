"""SQLite connection + transaction helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Union


_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open (or create) a SQLite DB at ``db_path``.

    Enables foreign-key enforcement and uses ``sqlite3.Row`` as the row
    factory so columns can be accessed by name.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Context manager that commits on success, rolls back on exception."""
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def apply_schema(conn: sqlite3.Connection) -> None:
    """Apply the bundled ``schema.sql`` and any in-place migrations.

    The base ``CREATE TABLE IF NOT EXISTS`` statements are idempotent for fresh
    DBs but do NOT add new columns to a table that already exists. For each
    post-Stage-1 column addition we issue an ``ALTER TABLE ... ADD COLUMN``
    guarded by a ``PRAGMA table_info`` check so the migration is idempotent.
    """
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    _migrate_products_add_lenovo_merge_columns(conn)


def _migrate_products_add_lenovo_merge_columns(conn: sqlite3.Connection) -> None:
    """Stage 7 T7.0a M1: add ``family_code`` and ``source_model_codes`` to
    ``products`` if missing. Both columns are NULL on existing rows.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
    if "family_code" not in existing:
        conn.execute("ALTER TABLE products ADD COLUMN family_code TEXT")
    if "source_model_codes" not in existing:
        conn.execute("ALTER TABLE products ADD COLUMN source_model_codes TEXT")
