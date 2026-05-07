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
