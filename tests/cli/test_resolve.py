"""Stage 5 happy-path tests for ``resolve`` (all four actions)."""

from __future__ import annotations

import argparse
import json

import pytest

from competitive_database.cli import resolve
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    read_offerings,
    read_scalar,
    write_offerings,
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


# ---------------------------------------------------------------------------
# Column-level offering paths (Stage 5 CLI gap fix)
#
# The ingest runner emits offering value_disagreement conflicts at the
# column level (e.g. ``field_path = "camera_offerings"``) — the full
# offerings list is the unit of disagreement, with per-leaf provenance
# bundles already embedded in ``existing_value`` / ``candidate_value``
# and ``*_provenance`` left NULL (see ingest/runner.py::_enqueue,
# list-level branch). The resolver now accepts this column-only path
# shape for accept_candidate / kept_existing / dropped; manual_override
# is rejected with a redirect to manual-edit on a leaf path.
# ---------------------------------------------------------------------------


def _seed_offering_list_disagreement(conn, column: str, existing_list, candidate_list) -> int:
    """Seed a column-level offering value_disagreement row mirroring
    runner._enqueue's list-level shape (provenance columns NULL).
    """
    write_offerings(conn, "products", _PK, column, existing_list)
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
            column,
            "value_disagreement",
            json.dumps(existing_list),
            None,
            json.dumps(candidate_list),
            None,
            "2026-05-11T00:00:00+00:00",
        ),
    )
    return cur.lastrowid


def test_resolve_accept_candidate_column_offering_writes_candidate_list(tmp_path):
    existing = [{"resolution": _scraped("720p")}]
    candidate = [{"resolution": _scraped("1080p")}]
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_offering_list_disagreement(
                conn, "camera_offerings", existing, candidate
            )
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="accept_candidate",
        value=None,
        value_json=None,
        note="row #18-style",
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    resolve.main(args)

    conn = connect(tmp_path / "rs.db")
    try:
        stored = read_offerings(conn, "products", _PK, "camera_offerings")
        row = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert stored == candidate  # whole list replaced
    assert row["resolution"] == "accepted_candidate"
    assert json.loads(row["resolution_value"]) == candidate
    assert row["resolver_note"] == "row #18-style"


def test_resolve_kept_existing_column_offering_does_not_touch(tmp_path):
    existing = [{"resolution": _scraped("720p")}]
    candidate = [{"resolution": _scraped("1080p")}]
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_offering_list_disagreement(
                conn, "camera_offerings", existing, candidate
            )
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
        stored = read_offerings(conn, "products", _PK, "camera_offerings")
        row = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert stored == existing  # untouched
    assert row["resolution"] == "kept_existing"
    assert json.loads(row["resolution_value"]) == existing


def test_resolve_dropped_column_offering_does_not_touch(tmp_path):
    existing = [{"resolution": _scraped("720p")}]
    candidate = [{"resolution": _scraped("1080p")}]
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_offering_list_disagreement(
                conn, "camera_offerings", existing, candidate
            )
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="dropped",
        value=None,
        value_json=None,
        note="bogus list",
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    resolve.main(args)

    conn = connect(tmp_path / "rs.db")
    try:
        stored = read_offerings(conn, "products", _PK, "camera_offerings")
        row = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert stored == existing  # untouched
    assert row["resolution"] == "dropped"
    assert row["resolution_value"] is None
    assert row["resolver_note"] == "bogus list"


def test_resolve_manual_override_column_offering_rejected(tmp_path):
    existing = [{"resolution": _scraped("720p")}]
    candidate = [{"resolution": _scraped("1080p")}]
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_offering_list_disagreement(
                conn, "camera_offerings", existing, candidate
            )
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="manual_override",
        value=None,
        value_json='[{"resolution": {"value": "1440p"}}]',
        note=None,
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    with pytest.raises(SystemExit) as exc:
        resolve.main(args)
    assert "manual_override not supported" in str(exc.value)
    assert "camera_offerings" in str(exc.value)
