"""Tests for ``views.load.load_product``.

The loader has to know which products columns are plain scalars (or
plain JSON literals) versus provenance bundles. M1 added two plain
columns — ``family_code`` (TEXT) and ``source_model_codes`` (a JSON
array of strings stored as TEXT). Before this fix, ``load_product``
tried to ``json.loads`` ``family_code`` and crashed on any merged
Lenovo row.
"""

from __future__ import annotations

import json

from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import make_scraped_bundle, write_scalar
from competitive_database.views.load import load_product


_CAPTURED = "2026-05-08T12:00:00+00:00"
_SCRAPER = "test"
_URL = "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16IRX10"


def _scraped(value):
    return make_scraped_bundle(
        value=value,
        source_url=_URL,
        captured_at=_CAPTURED,
        scraper_id=_SCRAPER,
        status="verified",
    )


def test_load_product_decodes_m1_columns(tmp_path):
    """family_code stays plain TEXT; source_model_codes decodes to a
    Python list. Neither column should crash json.loads."""
    conn = connect(tmp_path / "load.db")
    try:
        with transaction(conn):
            apply_schema(conn)
            pk = {"model_code": "legion-pro-5-16-gen-10", "year": 2025}
            # Need at least one scalar bundle so the row exists.
            write_scalar(conn, "products", pk, "brand", _scraped("Lenovo"))
            conn.execute(
                "UPDATE products SET family_code = ?, source_model_codes = ? "
                "WHERE model_code = ? AND year = ?",
                (
                    "legion-pro-5-16-gen-10",
                    json.dumps(["16IRX10", "16ADR10"]),
                    "legion-pro-5-16-gen-10",
                    2025,
                ),
            )

        product = load_product(conn, "legion-pro-5-16-gen-10", year=2025)
    finally:
        conn.close()

    # family_code is plain text — comes back as-is.
    assert product["family_code"] == "legion-pro-5-16-gen-10"
    # source_model_codes is JSON-encoded TEXT — comes back decoded as a list.
    assert product["source_model_codes"] == ["16IRX10", "16ADR10"]
    # brand (a bundle column) still decodes to a dict.
    assert isinstance(product["brand"], dict)
    assert product["brand"]["value"] == "Lenovo"
