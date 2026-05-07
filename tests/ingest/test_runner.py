"""Diff-and-write tests for ingest.runner."""

from __future__ import annotations

import json

from competitive_database.bridge.types import CandidateProduct
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import read_offerings, read_scalar
from competitive_database.ingest.runner import ingest, ingest_product


SOURCE_URL = "https://www.dell.com/en-us/shop/.../alienware-area-51-aa18250-gaming-laptop"
SCRAPER_ID = "dell.fetch_dell_product"


def _bundle(value, captured_at, status="verified"):
    return {
        "value": value,
        "source_url": SOURCE_URL,
        "captured_at": captured_at,
        "scraper_id": SCRAPER_ID,
        "status": status,
    }


def _conn(tmp_path):
    c = connect(tmp_path / "rt.db")
    with transaction(c):
        apply_schema(c)
    return c


PK = {"model_code": "aa18250", "year": 2026}


# ---------------------------------------------------------------------------
# Insert path
# ---------------------------------------------------------------------------


def test_ingest_new_product_writes_scalars_and_offerings(tmp_path):
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="aa18250", year=2026)
        cand.vendor_full_name = _bundle(
            "Alienware 18 Area-51", "2026-05-07T16:00:00+00:00"
        )
        cand.brand = _bundle("Dell", "2026-05-07T16:00:00+00:00")
        cand.memory_max_gb = _bundle(32, "2026-05-07T16:00:00+00:00")
        cand.display_offerings = [
            {
                "size_inches": _bundle(18.0, "2026-05-07T16:00:00+00:00"),
                "tier": _bundle("base", "2026-05-07T16:00:00+00:00"),
            }
        ]

        report = ingest(conn, cand)

        assert report.inserted_fields >= 3
        assert report.conflicts == 0
        assert report.low_confidence == 0

        got_brand = read_scalar(conn, "products", PK, "brand")
        assert got_brand["value"] == "Dell"
        got_mem = read_scalar(conn, "products", PK, "memory_max_gb")
        assert got_mem["value"] == 32
        got_disp = read_offerings(conn, "products", PK, "display_offerings")
        assert got_disp[0]["size_inches"]["value"] == 18.0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Refresh path (matching value, new captured_at)
# ---------------------------------------------------------------------------


def test_ingest_matching_value_refreshes_captured_at(tmp_path):
    conn = _conn(tmp_path)
    try:
        cand1 = CandidateProduct(model_code="aa18250", year=2026)
        cand1.vendor_full_name = _bundle(
            "Alienware 18", "2026-05-07T16:00:00+00:00"
        )
        cand1.memory_max_gb = _bundle(32, "2026-05-07T16:00:00+00:00")
        ingest(conn, cand1)

        cand2 = CandidateProduct(model_code="aa18250", year=2026)
        cand2.memory_max_gb = _bundle(32, "2026-06-15T09:00:00+00:00")
        report = ingest(conn, cand2)

        assert report.refreshed_fields >= 1
        assert report.conflicts == 0
        got = read_scalar(conn, "products", PK, "memory_max_gb")
        assert got["value"] == 32
        assert got["captured_at"] == "2026-06-15T09:00:00+00:00"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Conflict path (different value)
# ---------------------------------------------------------------------------


def test_ingest_value_disagreement_enqueues(tmp_path):
    conn = _conn(tmp_path)
    try:
        cand1 = CandidateProduct(model_code="aa18250", year=2026)
        cand1.vendor_full_name = _bundle("X", "2026-05-07T16:00:00+00:00")
        cand1.memory_max_gb = _bundle(32, "2026-05-07T16:00:00+00:00")
        ingest(conn, cand1)

        cand2 = CandidateProduct(model_code="aa18250", year=2026)
        cand2.memory_max_gb = _bundle(64, "2026-06-15T09:00:00+00:00")
        report = ingest(conn, cand2)

        assert report.conflicts == 1
        # Existing value untouched.
        got = read_scalar(conn, "products", PK, "memory_max_gb")
        assert got["value"] == 32

        rows = conn.execute(
            "SELECT conflict_type, field_path, candidate_value "
            "FROM review_queue WHERE product_model_code = ?",
            (PK["model_code"],),
        ).fetchall()
        types = [r["conflict_type"] for r in rows]
        assert "value_disagreement" in types
        # Locate the memory_max_gb queue entry.
        for r in rows:
            if r["field_path"] == "memory_max_gb":
                assert json.loads(r["candidate_value"])["value"] == 64
                break
        else:
            raise AssertionError("no queue row for memory_max_gb")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Low-confidence path
# ---------------------------------------------------------------------------


def test_ingest_needs_review_candidate_skips_db_and_queues(tmp_path):
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="aa18250", year=2026)
        cand.vendor_full_name = _bundle(
            "Alienware 18 Area-51", "2026-05-07T16:00:00+00:00"
        )
        cand.memory_max_gb = _bundle(
            None, "2026-05-07T16:00:00+00:00", status="needs-review"
        )
        report = ingest(conn, cand)

        assert report.low_confidence >= 1
        # Memory cell did NOT land in the products table.
        assert read_scalar(conn, "products", PK, "memory_max_gb") is None

        rows = conn.execute(
            "SELECT conflict_type FROM review_queue WHERE field_path = 'memory_max_gb'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["conflict_type"] == "low_confidence_extraction"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Catalog auto-add
# ---------------------------------------------------------------------------


def test_ingest_auto_adds_unknown_cpu_stub(tmp_path):
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="aa18250", year=2026)
        cand.vendor_full_name = _bundle("X", "2026-05-07T16:00:00+00:00")
        cand.cpu_offerings = [
            {"model": _bundle("Core Ultra 9 285HX", "2026-05-07T16:00:00+00:00")}
        ]
        report = ingest(conn, cand)

        assert "Core Ultra 9 285HX" in report.new_cpus
        rows = conn.execute("SELECT model FROM cpu_catalog").fetchall()
        assert any(r["model"] == "Core Ultra 9 285HX" for r in rows)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# year_inferred routing (Decision 1)
# ---------------------------------------------------------------------------


def test_ingest_year_inferred_routes_to_dedicated_queue(tmp_path):
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="aa18250", year=2026)
        cand.year_was_inferred = True
        cand.vendor_full_name = _bundle(
            "Alienware 18 Area-51 Gaming Laptop",
            "2026-05-07T16:00:00+00:00",
            status="needs-review",
        )
        report = ingest(conn, cand)

        assert report.year_inferred == 1
        assert report.low_confidence == 0

        rows = conn.execute(
            "SELECT conflict_type, field_path FROM review_queue"
        ).fetchall()
        # Should be exactly one row, of type year_inferred.
        assert len(rows) == 1
        assert rows[0]["conflict_type"] == "year_inferred"
        assert rows[0]["field_path"] == "vendor_full_name"
    finally:
        conn.close()


def test_ingest_needs_review_without_inferred_year_still_low_confidence(tmp_path):
    """If year_was_inferred is False, vendor_full_name needs-review still
    routes to low_confidence_extraction (the old path)."""
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="aa18250", year=2026)
        cand.year_was_inferred = False
        cand.vendor_full_name = _bundle(
            "Alienware 18 Area-51 Gaming Laptop",
            "2026-05-07T16:00:00+00:00",
            status="needs-review",
        )
        report = ingest(conn, cand)

        assert report.year_inferred == 0
        assert report.low_confidence == 1

        rows = conn.execute(
            "SELECT conflict_type FROM review_queue"
        ).fetchall()
        assert rows[0]["conflict_type"] == "low_confidence_extraction"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Cross-tile merge for offerings (Decision 3)
# ---------------------------------------------------------------------------


def test_ingest_product_unions_cpu_offerings_across_tiles(tmp_path):
    """Two snapshots with different CPUs → one product row, unioned cpu_offerings."""
    conn = _conn(tmp_path)
    try:
        cand1 = CandidateProduct(model_code="aa18250", year=2026)
        cand1.vendor_full_name = _bundle(
            "Alienware 18 Area-51", "2026-05-07T16:00:00+00:00"
        )
        cand1.cpu_offerings = [
            {"model": _bundle("Core Ultra 9 285HX", "2026-05-07T16:00:00+00:00")}
        ]
        cand2 = CandidateProduct(model_code="aa18250", year=2026)
        cand2.vendor_full_name = _bundle(
            "Alienware 18 Area-51", "2026-05-07T16:00:00+00:00"
        )
        cand2.cpu_offerings = [
            {"model": _bundle("Core Ultra 9 290HX Plus", "2026-05-07T16:00:00+00:00")}
        ]

        report = ingest_product(conn, [cand1, cand2])

        # No value_disagreement on cpu_offerings — they unioned.
        assert report.conflicts == 0

        cpus = read_offerings(conn, "products", PK, "cpu_offerings")
        assert cpus is not None
        names = sorted(o["model"]["value"] for o in cpus)
        assert names == ["Core Ultra 9 285HX", "Core Ultra 9 290HX Plus"]
    finally:
        conn.close()


def test_ingest_product_unions_boards_by_label_with_unioned_gpus(tmp_path):
    """Two tiles: one MB1 with RTX 5070 Ti, another MB1 with RTX 5090.
    Result: ONE MB1 board with BOTH GPUs."""
    conn = _conn(tmp_path)
    try:
        captured = "2026-05-07T16:00:00+00:00"

        def _board(label, gpus):
            return {
                "label": _bundle(label, captured),
                "tpp_max": _bundle(None, captured, status="vendor-doesn't-publish"),
                "tgp_max": _bundle(None, captured, status="vendor-doesn't-publish"),
                "gpus": [_bundle(g, captured) for g in gpus],
            }

        cand1 = CandidateProduct(model_code="aa18250", year=2026)
        cand1.vendor_full_name = _bundle("X", captured)
        cand1.boards = [_board("MB1", ["RTX 5070 Ti"])]

        cand2 = CandidateProduct(model_code="aa18250", year=2026)
        cand2.vendor_full_name = _bundle("X", captured)
        cand2.boards = [_board("MB1", ["RTX 5090"])]

        cand3 = CandidateProduct(model_code="aa18250", year=2026)
        cand3.vendor_full_name = _bundle("X", captured)
        cand3.boards = [_board("MB1", ["RTX 5070 Ti"])]  # duplicate

        report = ingest_product(conn, [cand1, cand2, cand3])

        assert report.conflicts == 0

        boards = read_offerings(conn, "products", PK, "boards")
        assert boards is not None
        assert len(boards) == 1
        assert boards[0]["label"]["value"] == "MB1"
        gpu_names = sorted(g["value"] for g in boards[0]["gpus"])
        assert gpu_names == ["RTX 5070 Ti", "RTX 5090"]
    finally:
        conn.close()


def test_ingest_product_keeps_needs_review_offering_separate(tmp_path):
    """A needs-review offering must NOT silently merge with a verified one."""
    conn = _conn(tmp_path)
    try:
        cand1 = CandidateProduct(model_code="aa18250", year=2026)
        cand1.vendor_full_name = _bundle("X", "2026-05-07T16:00:00+00:00")
        cand1.cpu_offerings = [
            {"model": _bundle("Core Ultra 9 285HX", "2026-05-07T16:00:00+00:00")}
        ]
        cand2 = CandidateProduct(model_code="aa18250", year=2026)
        cand2.vendor_full_name = _bundle("X", "2026-05-07T16:00:00+00:00")
        cand2.cpu_offerings = [
            {
                "model": _bundle(
                    "Core Ultra 9 285HX",
                    "2026-05-07T16:00:00+00:00",
                    status="needs-review",
                )
            }
        ]

        # Don't write — the needs-review offering forces the offerings list
        # into the low_confidence path. We're really asserting the merge
        # didn't collapse the two entries before the diff ran.
        report = ingest_product(conn, [cand1, cand2])
        assert report.low_confidence >= 1
        # Inspect the candidate_value JSON in the queue row to verify the
        # merged list still carried both entries.
        rows = conn.execute(
            "SELECT candidate_value FROM review_queue "
            "WHERE field_path = 'cpu_offerings'"
        ).fetchall()
        assert len(rows) == 1
        cand_list = json.loads(rows[0]["candidate_value"])
        assert len(cand_list) == 2
    finally:
        conn.close()


def test_ingest_product_single_candidate_falls_through_to_ingest(tmp_path):
    """The list-of-1 case must behave exactly like single ingest()."""
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="aa18250", year=2026)
        cand.vendor_full_name = _bundle("X", "2026-05-07T16:00:00+00:00")
        cand.memory_max_gb = _bundle(32, "2026-05-07T16:00:00+00:00")

        report = ingest_product(conn, [cand])
        assert report.inserted_fields >= 2
    finally:
        conn.close()


def test_ingest_product_storage_max_gb_takes_max_across_tiles(tmp_path):
    """Two tiles publish 1000 GB and 2000 GB → merged storage_max_gb = 2000."""
    conn = _conn(tmp_path)
    try:
        captured = "2026-05-07T16:00:00+00:00"

        cand1 = CandidateProduct(model_code="aa18250", year=2026)
        cand1.vendor_full_name = _bundle("X", captured)
        cand1.storage_max_gb = _bundle(1000, captured)

        cand2 = CandidateProduct(model_code="aa18250", year=2026)
        cand2.vendor_full_name = _bundle("X", captured)
        cand2.storage_max_gb = _bundle(2000, captured)

        report = ingest_product(conn, [cand1, cand2])

        # No conflicts — the ceiling-merge took max() rather than queueing.
        assert report.conflicts == 0

        got = read_scalar(conn, "products", PK, "storage_max_gb")
        assert got is not None
        assert got["value"] == 2000
    finally:
        conn.close()


def test_ingest_product_rejects_mismatched_pk(tmp_path):
    conn = _conn(tmp_path)
    try:
        c1 = CandidateProduct(model_code="aa18250", year=2026)
        c1.vendor_full_name = _bundle("X", "2026-05-07T16:00:00+00:00")
        c2 = CandidateProduct(model_code="m18r2", year=2025)
        c2.vendor_full_name = _bundle("Y", "2026-05-07T16:00:00+00:00")
        try:
            ingest_product(conn, [c1, c2])
        except ValueError as e:
            assert "share a PK" in str(e)
        else:
            raise AssertionError("expected ValueError")
    finally:
        conn.close()
