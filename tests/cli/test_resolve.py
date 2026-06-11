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


_PK = {"product": "alienware-m18", "year": 2026}


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
            "alienware-m18",
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
            "alienware-m18",
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


# ---------------------------------------------------------------------------
# new_chip_unverified — catalog-vouching workflow
#
# The queue row's candidate_value JSON ({"table","model","value"}) points
# at the catalog stub inserted at ingest time. The resolver routes off
# that payload rather than field_path, so depth-3
# (cpu_offerings.N.model) and depth-4 (boards.N.gpus.M) share one
# dispatch. accept_candidate flips catalog_status to 'vouched'; dropped
# resolves the queue row without touching the catalog. kept_existing and
# manual_override are rejected (existing_value is always NULL here).
# ---------------------------------------------------------------------------


def _seed_new_chip(
    conn, *, table: str, model: str, field_path: str
) -> int:
    conn.execute(
        f"INSERT INTO {table} (model, catalog_status) VALUES (?, ?)",
        (model, "needs-review"),
    )
    cur = conn.execute(
        """
        INSERT INTO review_queue (
            product_model_code, product_year, field_path, conflict_type,
            existing_value, existing_provenance,
            candidate_value, candidate_provenance, detected_at
        )
        VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?)
        """,
        (
            "alienware-m18",
            _PK["year"],
            field_path,
            "new_chip_unverified",
            json.dumps({"table": table, "model": model, "value": model}),
            json.dumps(_scraped(model)),
            "2026-05-08T00:00:00+00:00",
        ),
    )
    return cur.lastrowid


def _catalog_status(conn, table: str, model: str):
    row = conn.execute(
        f"SELECT catalog_status FROM {table} WHERE model = ?", (model,)
    ).fetchone()
    return None if row is None else row["catalog_status"]


def test_resolve_accept_new_chip_cpu_vouches_catalog(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_new_chip(
                conn,
                table="cpu_catalog",
                model="Core Ultra 9 386H",
                field_path="cpu_offerings.0.model",
            )
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="accept_candidate",
        value=None,
        value_json=None,
        note="seen in vendor spec sheet",
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    resolve.main(args)

    conn = connect(tmp_path / "rs.db")
    try:
        status = _catalog_status(conn, "cpu_catalog", "Core Ultra 9 386H")
        row = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert status == "vouched"
    assert row["resolution"] == "accepted_candidate"
    payload = json.loads(row["resolution_value"])
    assert payload == {
        "table": "cpu_catalog",
        "model": "Core Ultra 9 386H",
        "value": "Core Ultra 9 386H",
    }
    assert row["resolver_note"] == "seen in vendor spec sheet"


def test_resolve_accept_new_chip_gpu_depth4_vouches_catalog(tmp_path):
    # Depth-4 path (boards.N.gpus.M) — would have been rejected by the
    # path parser pre-vouching; routing off candidate_value sidesteps it.
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_new_chip(
                conn,
                table="gpu_catalog",
                model="RTX 5070 Ti",
                field_path="boards.0.gpus.0",
            )
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="accept_candidate",
        value=None,
        value_json=None,
        note=None,
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    resolve.main(args)

    conn = connect(tmp_path / "rs.db")
    try:
        status = _catalog_status(conn, "gpu_catalog", "RTX 5070 Ti")
        row = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert status == "vouched"
    assert row["resolution"] == "accepted_candidate"


def test_resolve_dropped_new_chip_leaves_catalog_at_needs_review(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_new_chip(
                conn,
                table="cpu_catalog",
                model="Core Ultra 9 290HX Plus",
                field_path="cpu_offerings.0.model",
            )
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="dropped",
        value=None,
        value_json=None,
        note="scraper misread",
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    resolve.main(args)

    conn = connect(tmp_path / "rs.db")
    try:
        status = _catalog_status(conn, "cpu_catalog", "Core Ultra 9 290HX Plus")
        row = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert status == "needs-review"
    assert row["resolution"] == "dropped"
    assert row["resolution_value"] is None
    assert row["resolver_note"] == "scraper misread"


def test_resolve_kept_existing_new_chip_rejected(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_new_chip(
                conn,
                table="cpu_catalog",
                model="Core Ultra 9 386H",
                field_path="cpu_offerings.0.model",
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
    with pytest.raises(SystemExit) as exc:
        resolve.main(args)
    assert "new_chip_unverified" in str(exc.value)
    assert "kept_existing" in str(exc.value)


def test_resolve_manual_override_new_chip_rejected(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_new_chip(
                conn,
                table="gpu_catalog",
                model="RTX 5080",
                field_path="boards.0.gpus.1",
            )
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="manual_override",
        value="RTX 5080 Mobile",
        value_json=None,
        note=None,
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    with pytest.raises(SystemExit) as exc:
        resolve.main(args)
    assert "new_chip_unverified" in str(exc.value)
    assert "manual_override" in str(exc.value)


def test_resolve_accept_new_chip_missing_catalog_row_errors(tmp_path):
    # Defensive: queue row references a catalog stub that no longer exists.
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_new_chip(
                conn,
                table="cpu_catalog",
                model="Core Ultra 9 386H",
                field_path="cpu_offerings.0.model",
            )
            conn.execute(
                "DELETE FROM cpu_catalog WHERE model = ?",
                ("Core Ultra 9 386H",),
            )
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="accept_candidate",
        value=None,
        value_json=None,
        note=None,
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    with pytest.raises(SystemExit) as exc:
        resolve.main(args)
    assert "no cpu_catalog row" in str(exc.value)


def _seed_catalog_text_disagreement(
    conn,
    *,
    table: str,
    model: str,
    column: str,
    existing_val: str,
    candidate_val: str,
) -> int:
    conn.execute(
        f"INSERT INTO {table} (model, {column}, catalog_status) VALUES (?, ?, ?)",
        (model, existing_val, "vouched"),
    )
    field_path = f"{table}.{model}.{column}"
    cur = conn.execute(
        """
        INSERT INTO review_queue (
            product_model_code, product_year, field_path, conflict_type,
            existing_value, existing_provenance,
            candidate_value, candidate_provenance, detected_at
        )
        VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        (
            "alienware-m18",
            _PK["year"],
            field_path,
            "value_disagreement",
            json.dumps({"value": existing_val}),
            json.dumps({"value": candidate_val}),
            json.dumps(_scraped(candidate_val)),
            "2026-05-15T00:00:00+00:00",
        ),
    )
    return cur.lastrowid


def test_resolve_accept_candidate_catalog_text_unwraps_bundled_value(tmp_path):
    # Catalog disagreement rows store candidate_value as JSON-encoded
    # {"value": "..."} (see ingest/catalog_resolve.py::_enqueue_catalog_disagreement).
    # accept_candidate must unwrap the dict to a plain string before
    # writing the catalog cell, or sqlite3 rejects the dict bind (T9.6).
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            qid = _seed_catalog_text_disagreement(
                conn,
                table="cpu_catalog",
                model="Core Ultra 9 285HX",
                column="cores",
                existing_val="16",
                candidate_val="24",
            )
    finally:
        conn.close()

    args = argparse.Namespace(
        id=qid,
        action="accept_candidate",
        value=None,
        value_json=None,
        note="vendor updated cores count",
        entered_by=None,
        db=str(tmp_path / "rs.db"),
    )
    resolve.main(args)

    conn = connect(tmp_path / "rs.db")
    try:
        row = conn.execute(
            "SELECT cores FROM cpu_catalog WHERE model = ?",
            ("Core Ultra 9 285HX",),
        ).fetchone()
        qrow = _resolved_row(conn, qid)
    finally:
        conn.close()

    assert row["cores"] == "24"
    assert qrow["resolution"] == "accepted_candidate"
