"""Shared fixtures for ``tests/ui/`` — DB seeding + ``AppTest`` factory.

The Streamlit UI boots from ``competitive_database/ui/app.py``, which
reads ``COMPETITIVE_DB_PATH`` at render time and falls back to
``competitive.db`` in cwd. The fixture builds an isolated temp DB with
the full schema applied, points the env var at it, and yields the path
so individual tests can seed rows before running ``AppTest``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from competitive_database.db.connection import apply_schema, connect, transaction


# Stable path to the Streamlit entry script — resolved once at import.
APP_SCRIPT: Path = (
    Path(__file__).resolve().parents[2]
    / "competitive_database"
    / "ui"
    / "app.py"
)


@pytest.fixture
def empty_db(tmp_path, monkeypatch):
    """Schema applied, no rows. Env var set so ``ui/app.py`` finds it."""
    db_path = tmp_path / "ui_smoke.db"
    conn = connect(db_path)
    try:
        with transaction(conn):
            apply_schema(conn)
    finally:
        conn.close()
    monkeypatch.setenv("COMPETITIVE_DB_PATH", str(db_path))
    return db_path
