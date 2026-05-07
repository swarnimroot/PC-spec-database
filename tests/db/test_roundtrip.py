"""Stage 1 round-trip tests for db.helpers.

Covers:
  - schema applies cleanly (four tables exist)
  - scraped scalar bundle round-trips through write_scalar / read_scalar
  - manual scalar bundle round-trips
  - display_offerings list-of-dicts-of-bundles round-trips
  - reading a never-written field returns None
"""

from __future__ import annotations

from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_manual_bundle,
    make_scraped_bundle,
    read_offerings,
    read_scalar,
    write_offerings,
    write_scalar,
)


SAMPLE_PK = {"model_code": "alienware-m18", "year": 2026}


def _fresh_db(tmp_path):
    conn = connect(tmp_path / "rt.db")
    with transaction(conn):
        apply_schema(conn)
    return conn


def test_schema_creates_four_tables(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r[0] for r in rows}
        assert {"cpu_catalog", "gpu_catalog", "products", "review_queue"} <= names
    finally:
        conn.close()


def test_scraped_scalar_bundle_roundtrip(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        bundle = make_scraped_bundle(
            value="Alienware",
            source_url="https://www.dell.com/en-us/shop/dell-laptops/alienware-m18",
            captured_at="2026-05-06T14:32:11Z",
            scraper_id="dell.fetch_dell_product",
            status="verified",
        )
        with transaction(conn):
            write_scalar(conn, "products", SAMPLE_PK, "brand", bundle)
        got = read_scalar(conn, "products", SAMPLE_PK, "brand")
        assert got == bundle
    finally:
        conn.close()


def test_manual_scalar_bundle_roundtrip(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        bundle = make_manual_bundle(
            value="flagship",
            entered_by="swarnim",
            source_note="market positioning",
            status="vouched",
            entered_at="2026-05-06T15:00:00+00:00",
        )
        with transaction(conn):
            write_scalar(conn, "products", SAMPLE_PK, "segment", bundle)
        got = read_scalar(conn, "products", SAMPLE_PK, "segment")
        assert got == bundle
    finally:
        conn.close()


def test_display_offerings_roundtrip(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        captured_at = "2026-05-06T14:32:11Z"
        url = "https://www.dell.com/en-us/shop/dell-laptops/alienware-m18"
        scraper_id = "dell.fetch_dell_product"

        offering_a = {
            "size_inches": make_scraped_bundle(18, url, captured_at, scraper_id),
            "nits_peak": make_scraped_bundle(500, url, captured_at, scraper_id),
        }
        offering_b = {
            "size_inches": make_scraped_bundle(18, url, captured_at, scraper_id),
            "nits_peak": make_scraped_bundle(
                600, url, captured_at, scraper_id, status="needs-review"
            ),
        }
        offerings = [offering_a, offering_b]

        with transaction(conn):
            write_offerings(conn, "products", SAMPLE_PK, "display_offerings", offerings)
        got = read_offerings(conn, "products", SAMPLE_PK, "display_offerings")
        assert got == offerings
    finally:
        conn.close()


def test_read_missing_field_returns_none(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        # Row does not exist at all.
        assert read_scalar(conn, "products", SAMPLE_PK, "brand") is None
        assert read_offerings(conn, "products", SAMPLE_PK, "display_offerings") is None

        # Row exists, but this column was never written.
        with transaction(conn):
            write_scalar(
                conn,
                "products",
                SAMPLE_PK,
                "brand",
                make_scraped_bundle(
                    "Alienware",
                    "https://example.com",
                    "2026-05-06T14:32:11Z",
                    "dell.fetch_dell_product",
                ),
            )
        assert read_scalar(conn, "products", SAMPLE_PK, "segment") is None
        assert (
            read_offerings(conn, "products", SAMPLE_PK, "display_offerings") is None
        )
    finally:
        conn.close()
