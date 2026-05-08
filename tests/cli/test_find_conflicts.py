"""Stage 5 happy-path tests for ``find-conflicts``."""

from __future__ import annotations

import argparse

from competitive_database.cli import find_conflicts
from competitive_database.db.connection import apply_schema, connect, transaction


def _fresh_db(tmp_path):
    conn = connect(tmp_path / "fc.db")
    with transaction(conn):
        apply_schema(conn)
    return conn


def _insert_queue_row(conn, **cols):
    keys = ", ".join(cols.keys())
    placeholders = ", ".join("?" * len(cols))
    conn.execute(
        f"INSERT INTO review_queue ({keys}) VALUES ({placeholders})",
        list(cols.values()),
    )


def test_find_conflicts_lists_only_unresolved(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            _insert_queue_row(
                conn,
                product_model_code="alpha",
                product_year=2026,
                field_path="audio_jack",
                conflict_type="value_disagreement",
                existing_value='"yes"',
                candidate_value='"no"',
                detected_at="2026-05-07T00:00:00+00:00",
            )
            _insert_queue_row(
                conn,
                product_model_code="beta",
                product_year=2026,
                field_path="cpu_tdp_max",
                conflict_type="value_disagreement",
                existing_value="100",
                candidate_value="120",
                detected_at="2026-05-07T00:00:00+00:00",
                resolved_at="2026-05-07T00:01:00+00:00",
                resolution="kept_existing",
            )
    finally:
        conn.close()

    args = argparse.Namespace(product=None, db=str(tmp_path / "fc.db"))
    find_conflicts.main(args)
    out = capsys.readouterr().out

    assert "1 unresolved conflict(s)" in out
    assert "alpha-2026" in out
    assert "audio_jack" in out
    # Resolved row excluded
    assert "beta-2026" not in out


def test_find_conflicts_filter_by_product(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            _insert_queue_row(
                conn,
                product_model_code="alpha",
                product_year=2026,
                field_path="f1",
                conflict_type="value_disagreement",
                detected_at="2026-05-07T00:00:00+00:00",
            )
            _insert_queue_row(
                conn,
                product_model_code="beta",
                product_year=2026,
                field_path="f2",
                conflict_type="value_disagreement",
                detected_at="2026-05-07T00:00:00+00:00",
            )
    finally:
        conn.close()

    args = argparse.Namespace(product="beta", db=str(tmp_path / "fc.db"))
    find_conflicts.main(args)
    out = capsys.readouterr().out

    assert "1 unresolved conflict(s)" in out
    assert "beta-2026" in out
    assert "alpha-2026" not in out


def test_find_conflicts_empty(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    conn.close()

    args = argparse.Namespace(product=None, db=str(tmp_path / "fc.db"))
    find_conflicts.main(args)
    out = capsys.readouterr().out
    assert "(no unresolved conflicts)" in out
