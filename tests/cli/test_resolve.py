"""Stage 5 happy-path tests for ``resolve`` (all four actions)."""

from __future__ import annotations

import argparse
import json

import pytest

from competitive_database.cli import resolve
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    read_scalar,
    write_scalar,
)


_PK = {"model_code": "alienware-m18", "year": 2026}


def _fresh_db(tmp_path):
    conn = connect(tmp_path / "rs.db")
    with transaction(conn):
        apply_schema(conn)
    return conn


def _scraped(value, status="verified"):
    return make_scraped_bundle(
        value=value,
        source_url="https://example.com",
        captured_at="2026-05-07T00:00:00+00:00",
        scraper_id="test",
        status=status,
    )


def _seed_value_disagreement(conn, field_path: str, existing_val, candidate_val) -> int:
    existing_bundle = _scraped(existing_val)
    candidate_bundle = _scraped(candidate_val)
    write_scalar(conn, "products", _PK, field_path, existing_bundle)
    cur = conn.execute(
        """
        INSERT INTO review_queue (
            product_model_code, product_year, field_path, conflict_type,
            existing_value, existing_provenance,
            candidate_value, candidate_provenance, detected_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _PK["model_code"],
            _PK["year"],
            field_path,
            "value_disagreement",
            json.dumps(existing_val),
            json.dumps(existing_bundle),
            json.dumps(candidate_val),
            json.dumps(candidate_bundle),
            "2026-05-07T00:00:00+00:00",
        ),
    )
    return cur.lastrowid


def _resolved_row(conn, qid: int):
    return conn.execute(
        "SELECT resolved_at, resolution, resolution_value, resolver_note "
        "FROM review_queue WHERE id = ?",
        (qid,),
    ).fetchone()


def test_resolve_accept_candidate_writes_candidate_bundle(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_value_disagreement(conn, "cpu_tdp_max", 100, 120)
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="accept_candidate",
        value=None,
        value_json=None,
        note="reviewer ok",
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    resolve.main(args)

    conn = connect(tmp_path / "rs.db")
    try:
        bundle = read_scalar(conn, "products", _PK, "cpu_tdp_max")
        row = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert bundle["value"] == 120  # candidate value now stored
    assert row["resolved_at"] is not None
    assert row["resolution"] == "accepted_candidate"
    assert json.loads(row["resolution_value"]) == 120
    assert row["resolver_note"] == "reviewer ok"


def test_resolve_kept_existing_does_not_touch_product(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_value_disagreement(conn, "cpu_tdp_max", 100, 120)
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="kept_existing",
        value=None,
        value_json=None,
        note=None,
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    resolve.main(args)

    conn = connect(tmp_path / "rs.db")
    try:
        bundle = read_scalar(conn, "products", _PK, "cpu_tdp_max")
        row = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert bundle["value"] == 100  # untouched
    assert row["resolution"] == "kept_existing"
    assert json.loads(row["resolution_value"]) == 100


def test_resolve_manual_override_writes_manual_bundle(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_value_disagreement(conn, "cpu_tdp_max", 100, 120)
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="manual_override",
        value="135",
        value_json=None,
        note="from review article",
        entered_by="tester",
        db=str(tmp_path / "rs.db"),
    )
    resolve.main(args)

    conn = connect(tmp_path / "rs.db")
    try:
        bundle = read_scalar(conn, "products", _PK, "cpu_tdp_max")
        row = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert bundle["value"] == 135  # int-coerced
    assert bundle["entered_by"] == "tester"
    assert bundle["status"] == "vouched"
    assert row["resolution"] == "manual_override"
    assert json.loads(row["resolution_value"]) == 135


def test_resolve_dropped_does_not_touch_product(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_value_disagreement(conn, "cpu_tdp_max", 100, 120)
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="dropped",
        value=None,
        value_json=None,
        note="bogus scrape",
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    resolve.main(args)

    conn = connect(tmp_path / "rs.db")
    try:
        bundle = read_scalar(conn, "products", _PK, "cpu_tdp_max")
        row = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert bundle["value"] == 100  # untouched
    assert row["resolution"] == "dropped"
    assert row["resolution_value"] is None
    assert row["resolver_note"] == "bogus scrape"


def test_resolve_rejects_already_resolved(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_value_disagreement(conn, "cpu_tdp_max", 100, 120)
            conn.execute(
                "UPDATE review_queue SET resolved_at = ?, resolution = ? WHERE id = ?",
                ("2026-05-07T00:00:30+00:00", "kept_existing", qid),
            )
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="dropped",
        value=None,
        value_json=None,
        note=None,
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    with pytest.raises(SystemExit) as exc:
        resolve.main(args)
    assert "already resolved" in str(exc.value)


def test_resolve_rejects_missing_id(tmp_path):
    conn = _fresh_db(tmp_path)
    conn.close()

    args = argparse.Namespace(
        id=999,
        action="dropped",
        value=None,
        value_json=None,
        note=None,
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    with pytest.raises(SystemExit) as exc:
        resolve.main(args)
    assert "no review_queue row" in str(exc.value)


def test_resolve_manual_override_requires_value(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_value_disagreement(conn, "cpu_tdp_max", 100, 120)
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="manual_override",
        value=None,
        value_json=None,
        note=None,
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    with pytest.raises(SystemExit) as exc:
        resolve.main(args)
    assert "manual_override" in str(exc.value)
