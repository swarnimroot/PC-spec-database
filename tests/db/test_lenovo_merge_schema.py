"""Stage 7 T7.0a M1 schema-migration tests.

Covers the two new plain-scalar columns on ``products``:
  - ``family_code`` (canonical family identifier, e.g. "legion-pro-5-16-gen-10")
  - ``source_model_codes`` (JSON-array TEXT of per-vendor machine codes)

These columns are NULL for legacy rows and only populated later (M5 backfill).
"""

from __future__ import annotations

import json
import sqlite3

from competitive_database.db.connection import apply_schema, connect, transaction


def _fresh_db(tmp_path):
    conn = connect(tmp_path / "merge_schema.db")
    with transaction(conn):
        apply_schema(conn)
    return conn


def test_products_has_lenovo_merge_columns(tmp_path):
    """After fresh init, the two new columns exist on ``products``."""
    conn = _fresh_db(tmp_path)
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
        assert "family_code" in cols
        assert "source_model_codes" in cols
    finally:
        conn.close()


def test_family_code_and_source_model_codes_roundtrip(tmp_path):
    """Write the two new columns directly and read them back unchanged."""
    conn = _fresh_db(tmp_path)
    try:
        source_codes = ["16IRX10", "16ADR10"]
        with transaction(conn):
            conn.execute(
                "INSERT INTO products (model_code, year, family_code, "
                "source_model_codes) VALUES (?, ?, ?, ?)",
                (
                    "legion-pro-5-16-gen-10",
                    2025,
                    "legion-pro-5-16-gen-10",
                    json.dumps(source_codes),
                ),
            )
        row = conn.execute(
            "SELECT family_code, source_model_codes FROM products "
            "WHERE model_code = ? AND year = ?",
            ("legion-pro-5-16-gen-10", 2025),
        ).fetchone()
        assert row["family_code"] == "legion-pro-5-16-gen-10"
        assert json.loads(row["source_model_codes"]) == source_codes
    finally:
        conn.close()


def test_legacy_insert_leaves_new_columns_null(tmp_path):
    """An INSERT that omits the new columns reads back NULL for both —
    confirms the migration didn't break legacy write paths.
    """
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO products (model_code, year) VALUES (?, ?)",
                ("alienware-m18", 2026),
            )
        row = conn.execute(
            "SELECT family_code, source_model_codes FROM products "
            "WHERE model_code = ? AND year = ?",
            ("alienware-m18", 2026),
        ).fetchone()
        assert row["family_code"] is None
        assert row["source_model_codes"] is None
    finally:
        conn.close()


def test_apply_schema_is_idempotent(tmp_path):
    """Running ``apply_schema`` a second time on the same DB must not error
    (covers the ALTER-on-startup idempotency check) and the columns stay put.
    """
    db_path = tmp_path / "idem.db"
    conn = connect(db_path)
    try:
        with transaction(conn):
            apply_schema(conn)
        # Second application — must not raise "duplicate column" or similar.
        with transaction(conn):
            apply_schema(conn)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
        assert "family_code" in cols
        assert "source_model_codes" in cols
    finally:
        conn.close()


def test_migration_upgrades_preexisting_db_missing_columns(tmp_path):
    """Simulate a legacy DB created before M1: build the full Stage-1
    ``products`` table (so existing indexes remain valid) minus the two new
    columns, then run ``apply_schema`` and confirm it adds them without
    dropping the existing row.
    """
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Minimal pre-M1 ``products`` shape: just the columns referenced by
        # the Stage-1 indexes (brand, year, status, segment) plus the PK.
        # Other bundle columns are irrelevant for this test.
        conn.execute(
            "CREATE TABLE products ("
            "model_code TEXT NOT NULL, "
            "year INTEGER NOT NULL, "
            "brand TEXT, "
            "status TEXT, "
            "segment TEXT, "
            "PRIMARY KEY (model_code, year))"
        )
        conn.execute(
            "INSERT INTO products (model_code, year) VALUES (?, ?)",
            ("legacy-row", 2024),
        )
        conn.commit()

        # Pre-condition: legacy DB lacks the two new columns.
        pre = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
        assert "family_code" not in pre
        assert "source_model_codes" not in pre

        with transaction(conn):
            apply_schema(conn)

        cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
        assert "family_code" in cols
        assert "source_model_codes" in cols

        row = conn.execute(
            "SELECT family_code, source_model_codes FROM products "
            "WHERE model_code = ? AND year = ?",
            ("legacy-row", 2024),
        ).fetchone()
        assert row["family_code"] is None
        assert row["source_model_codes"] is None
    finally:
        conn.close()
