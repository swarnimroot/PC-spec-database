"""T8.8 — AppTest write-path coverage for the manual-edit screen.

Seeds one product, drives the form against the default Identity /
``vendor_full_name`` cascade selection, asserts the manual_edit_cell
library handler ran and the new bundle landed in the products row.

Identity is the first section in
``views.orchestrator._SECTION_REGISTRY`` and ``vendor_full_name`` is
the first leaf in ``_IDENTITY_LEAVES`` — so the default selectbox
positions deterministically pick a writable scalar field with no
offerings cascade, no vendor-specific shape, and no JSON coercion.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from competitive_database.db.connection import connect, transaction
from competitive_database.db.helpers import make_scraped_bundle, write_scalar
from tests.ui.conftest import APP_SCRIPT


_PK = {"model_code": "alienware-m18", "year": 2026}
_VAL_KEY = f"edit-val-{_PK['model_code']}-{_PK['year']}"
_NEW_VALUE = "Dell Inc."


def _seed_one_product(db_path) -> None:
    conn = connect(db_path)
    try:
        with transaction(conn):
            write_scalar(
                conn, "products", _PK, "brand",
                make_scraped_bundle(
                    value="Alienware",
                    source_url="https://www.dell.com/test",
                    captured_at="2026-05-07T00:00:00+00:00",
                    scraper_id="test",
                ),
            )
    finally:
        conn.close()


def test_edit_save_writes_through_to_default_field(empty_db):
    _seed_one_product(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "edit"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # Sanity: cascade defaults landed on Identity / vendor_full_name.
    section_box = next(s for s in at.selectbox if s.key == "edit-section")
    field_box = next(s for s in at.selectbox if s.key == "edit-template")
    assert section_box.value == "Identity", (
        f"expected default section 'Identity'; got {section_box.value!r}"
    )
    assert field_box.value == "vendor_full_name", (
        f"expected default field 'vendor_full_name'; got {field_box.value!r}"
    )

    val_input = next(t for t in at.text_input if t.key == _VAL_KEY)
    val_input.set_value(_NEW_VALUE)

    save = next(b for b in at.button if b.label == "Save manual edit")
    save.click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    success_msgs = [s.value for s in at.success]
    assert any(
        "Wrote `vendor_full_name`" in m and _PK["model_code"] in m
        for m in success_msgs
    ), f"missing 'Wrote vendor_full_name' confirmation; saw {success_msgs}"

    conn = connect(empty_db)
    try:
        cell_raw = conn.execute(
            "SELECT vendor_full_name FROM products "
            "WHERE model_code = ? AND year = ?",
            (_PK["model_code"], _PK["year"]),
        ).fetchone()[0]
    finally:
        conn.close()
    assert cell_raw is not None, "vendor_full_name still NULL after save"
    bundle = json.loads(cell_raw)
    assert bundle["value"] == _NEW_VALUE, (
        f"new value not written through; cell now {bundle!r}"
    )
    assert bundle.get("status") == "vouched", (
        f"expected default 'vouched' status on manual bundle; got {bundle!r}"
    )
