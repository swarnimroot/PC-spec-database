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
    """Apply the bundled ``schema.sql`` to the given connection."""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
