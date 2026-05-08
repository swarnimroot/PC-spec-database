"""Tests for ingest.catalog_resolve."""

from __future__ import annotations

import json

from competitive_database.bridge.types import CandidateProduct
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.ingest.catalog_resolve import resolve_catalog


CAPTURED_AT = "2026-05-07T16:00:00+00:00"
SOURCE_URL = "https://www.dell.com/en-us/shop/.../alienware-area-51-aa18250-gaming-laptop"
SCRAPER_ID = "dell.fetch_dell_product"


def _bundle(value, status="verified"):
    return {
        "value": value,
        "source_url": SOURCE_URL,
        "captured_at": CAPTURED_AT,
        "scraper_id": SCRAPER_ID,
        "status": status,
    }


def _conn(tmp_path):
    c = connect(tmp_path / "rt.db")
    with transaction(c):
        apply_schema(c)
    return c


def test_unknown_cpu_inserts_stub_and_queue_row(tmp_path):
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="aa18250", year=2026)
        cand.cpu_offerings = [{"model": _bundle("Core Ultra 9 285HX")}]

        with transaction(conn):
            report = resolve_catalog(conn, cand)

        assert report["new_cpus"] == ["Core Ultra 9 285HX"]
        assert report["new_gpus"] == []

        rows = conn.execute(
            "SELECT model, catalog_status, brand FROM cpu_catalog"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["model"] == "Core Ultra 9 285HX"
        assert rows[0]["catalog_status"] == "needs-review"
        brand_bundle = json.loads(rows[0]["brand"])
        assert brand_bundle["value"] == "Intel"

        queue = conn.execute(
            "SELECT product_model_code, product_year, conflict_type, field_path "
            "FROM review_queue"
        ).fetchall()
        assert len(queue) == 1
        assert queue[0]["product_model_code"] == "aa18250"
        assert queue[0]["product_year"] == 2026
        assert queue[0]["conflict_type"] == "new_chip_unverified"
        assert queue[0]["field_path"] == "cpu_offerings.0.model"
    finally:
        conn.close()


def test_known_cpu_is_left_alone(tmp_path):
    conn = _conn(tmp_path)
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO cpu_catalog (model, catalog_status) VALUES (?, ?)",
                ("Core Ultra 9 285HX", "vouched"),
            )

        cand = CandidateProduct(model_code="aa18250", year=2026)
        cand.cpu_offerings = [{"model": _bundle("Core Ultra 9 285HX")}]
        with transaction(conn):
            report = resolve_catalog(conn, cand)

        assert report["new_cpus"] == []
        # No queue inserts for already-known chips.
        n = conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0]
        assert n == 0
        # Existing row is unchanged.
        row = conn.execute(
            "SELECT catalog_status FROM cpu_catalog WHERE model = ?",
            ("Core Ultra 9 285HX",),
        ).fetchone()
        assert row["catalog_status"] == "vouched"
    finally:
        conn.close()


def test_unknown_gpu_inserts_stub(tmp_path):
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="aa18250", year=2026)
        cand.boards = [
            {
                "label": _bundle("MB1"),
                "tpp_max": _bundle(None, status="vendor-doesn't-publish"),
                "tgp_max": _bundle(None, status="vendor-doesn't-publish"),
                "gpus": [_bundle("RTX 5090")],
            }
        ]

        with transaction(conn):
            report = resolve_catalog(conn, cand)

        assert report["new_gpus"] == ["RTX 5090"]
        rows = conn.execute(
            "SELECT model, catalog_status, brand FROM gpu_catalog"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["model"] == "RTX 5090"
        brand = json.loads(rows[0]["brand"])
        assert brand["value"] == "NVIDIA"
    finally:
        conn.close()


def test_needs_review_cpu_does_not_pollute_catalog(tmp_path):
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="aa18250", year=2026)
        cand.cpu_offerings = [
            {"model": _bundle("Mystery garbage", status="needs-review")}
        ]
        with transaction(conn):
            report = resolve_catalog(conn, cand)

        assert report["new_cpus"] == []
        n = conn.execute("SELECT COUNT(*) FROM cpu_catalog").fetchone()[0]
        assert n == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Vendor chip-spec seeding (Session 7)
# ---------------------------------------------------------------------------


def test_chip_specs_seed_into_empty_catalog_cell_no_queue(tmp_path):
    """Stub-add path: brand-new CPU + chip specs → both stub and the
    spec cells land in one go. No review_queue rows for the spec cells
    (only the standard ``new_chip_unverified`` for the model itself)."""
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="rog-zephyrus-g16-2026", year=2026)
        cand.cpu_offerings = [{"model": _bundle("Core Ultra 9 386H")}]
        cand.cpu_chip_specs = {
            "Core Ultra 9 386H": {"npu_tops": "50", "cores": "16"}
        }

        with transaction(conn):
            resolve_catalog(conn, cand)

        row = conn.execute(
            "SELECT npu_tops, cores, catalog_status FROM cpu_catalog WHERE model = ?",
            ("Core Ultra 9 386H",),
        ).fetchone()
        assert row["npu_tops"] == "50"
        assert row["cores"] == "16"
        assert row["catalog_status"] == "needs-review"

        # Only the new_chip_unverified row should exist; no per-cell
        # value_disagreement entries (catalog cells were empty).
        rows = conn.execute(
            "SELECT conflict_type FROM review_queue"
        ).fetchall()
        types = [r["conflict_type"] for r in rows]
        assert types == ["new_chip_unverified"]
    finally:
        conn.close()


def test_chip_specs_no_op_when_needs_review_cell_matches(tmp_path):
    """Pre-existing needs-review row with a matching cell value → no
    overwrite, no queue."""
    conn = _conn(tmp_path)
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO cpu_catalog (model, catalog_status, cores) "
                "VALUES (?, ?, ?)",
                ("Core Ultra 9 386H", "needs-review", "16"),
            )

        cand = CandidateProduct(model_code="rog-zephyrus-g16-2026", year=2026)
        cand.cpu_offerings = [{"model": _bundle("Core Ultra 9 386H")}]
        cand.cpu_chip_specs = {"Core Ultra 9 386H": {"cores": "16"}}

        with transaction(conn):
            resolve_catalog(conn, cand)

        row = conn.execute(
            "SELECT cores FROM cpu_catalog WHERE model = ?",
            ("Core Ultra 9 386H",),
        ).fetchone()
        assert row["cores"] == "16"
        # No queue rows: model already exists (no new_chip_unverified)
        # and cell matched (no value_disagreement).
        n = conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0]
        assert n == 0
    finally:
        conn.close()


def test_chip_specs_overwrite_and_queue_when_needs_review_cell_disagrees(tmp_path):
    """Pre-existing needs-review row with a different cell value →
    overwrite (freshest extraction wins) AND queue value_disagreement so
    the user can see the conflict."""
    conn = _conn(tmp_path)
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO cpu_catalog (model, catalog_status, cores) "
                "VALUES (?, ?, ?)",
                ("Core Ultra 9 285HX", "needs-review", "16"),
            )

        cand = CandidateProduct(model_code="some-laptop", year=2026)
        cand.cpu_offerings = [{"model": _bundle("Core Ultra 9 285HX")}]
        cand.cpu_chip_specs = {"Core Ultra 9 285HX": {"cores": "24"}}

        with transaction(conn):
            resolve_catalog(conn, cand)

        # Overwrite happened.
        row = conn.execute(
            "SELECT cores FROM cpu_catalog WHERE model = ?",
            ("Core Ultra 9 285HX",),
        ).fetchone()
        assert row["cores"] == "24"

        # Queue row recorded the disagreement.
        rows = conn.execute(
            "SELECT conflict_type, field_path, existing_value, candidate_value "
            "FROM review_queue WHERE conflict_type = 'value_disagreement'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["field_path"] == "cpu_catalog.Core Ultra 9 285HX.cores"
        assert json.loads(rows[0]["existing_value"]) == {"value": "16"}
        assert json.loads(rows[0]["candidate_value"]) == {"value": "24"}
    finally:
        conn.close()


def test_chip_specs_keep_and_queue_when_vouched_cell_disagrees(tmp_path):
    """Pre-existing vouched row with a different cell value → existing
    value preserved; queue value_disagreement."""
    conn = _conn(tmp_path)
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO cpu_catalog (model, catalog_status, cores) "
                "VALUES (?, ?, ?)",
                ("Core Ultra 9 285HX", "vouched", "16"),
            )

        cand = CandidateProduct(model_code="some-laptop", year=2026)
        cand.cpu_offerings = [{"model": _bundle("Core Ultra 9 285HX")}]
        cand.cpu_chip_specs = {"Core Ultra 9 285HX": {"cores": "24"}}

        with transaction(conn):
            resolve_catalog(conn, cand)

        # Existing vouched value preserved.
        row = conn.execute(
            "SELECT cores, catalog_status FROM cpu_catalog WHERE model = ?",
            ("Core Ultra 9 285HX",),
        ).fetchone()
        assert row["cores"] == "16"
        assert row["catalog_status"] == "vouched"

        rows = conn.execute(
            "SELECT conflict_type, field_path FROM review_queue"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["conflict_type"] == "value_disagreement"
        assert rows[0]["field_path"] == "cpu_catalog.Core Ultra 9 285HX.cores"
    finally:
        conn.close()
