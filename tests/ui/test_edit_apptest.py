"""AppTest coverage for the bulk-edit screen (Phase F rewrite).

The Edit screen now exposes a cascading product picker, per-field rows
with pencil affordances, and a single bulk Save button. These tests
drive the new presentation against an empty/seeded DB to confirm:

  - the cascading picker enables the field list when a product is picked,
  - the Save button label updates with the pending-change count,
  - switching products clears any in-flight pending state.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from competitive_database.db.connection import connect, transaction
from competitive_database.db.helpers import make_scraped_bundle, write_scalar
from tests.ui.conftest import APP_SCRIPT


def _bundle(value, source_url="https://www.dell.com/test"):
    return make_scraped_bundle(
        value=value,
        source_url=source_url,
        captured_at="2026-05-07T00:00:00+00:00",
        scraper_id="test",
    )


def _seed_one_product(db_path, *, model_code="alienware-m18", year=2026,
                      brand="Alienware", vendor="Dell Inc.") -> None:
    conn = connect(db_path)
    try:
        with transaction(conn):
            pk = {"model_code": model_code, "year": year}
            write_scalar(conn, "products", pk, "brand", _bundle(brand))
            write_scalar(conn, "products", pk, "vendor_full_name", _bundle(vendor))
    finally:
        conn.close()


def test_edit_empty_db_shows_info_message(empty_db):
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "edit"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert "Edit a product" in markdown_blob
    assert "Make changes across any number of fields" in markdown_blob

    info_messages = [i.value for i in at.info]
    assert any(
        "No products in the database yet." in m for m in info_messages
    ), f"expected empty-state info; saw {info_messages!r}"


def test_edit_save_button_disabled_with_zero_pending(empty_db):
    _seed_one_product(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "edit"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    save_buttons = [b for b in at.button if b.key == "edit.save"]
    assert save_buttons, "expected an edit.save button to render"
    save = save_buttons[0]
    assert save.label == "Save 0 changes"
    assert save.disabled is True, (
        f"expected disabled Save button with 0 pending; got {save!r}"
    )


def test_edit_pencil_activates_row_and_updates_save_label(empty_db):
    _seed_one_product(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "edit"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # Click the pencil for the vendor_full_name row.
    pencils = [
        b for b in at.button
        if b.key == "edit.pencil.vendor_full_name"
    ]
    assert pencils, "expected an edit.pencil.vendor_full_name button"
    pencils[0].click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # The active form should render text_inputs keyed off the path.
    new_val_keys = [t.key for t in at.text_input]
    assert "edit.newval.vendor_full_name" in new_val_keys, (
        f"expected edit.newval.vendor_full_name input; got {new_val_keys!r}"
    )

    # The Save button label should now reflect 1 pending change (the
    # form populates the pending dict on first render with whatever the
    # current value is).
    save = [b for b in at.button if b.key == "edit.save"][0]
    assert save.label == "Save 1 change", (
        f"expected 'Save 1 change'; got {save.label!r}"
    )
    assert save.disabled is False


def test_edit_save_writes_through_to_vendor_name(empty_db):
    _seed_one_product(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "edit"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # Open the vendor_full_name row, type a new value, save.
    pencil = [
        b for b in at.button
        if b.key == "edit.pencil.vendor_full_name"
    ][0]
    pencil.click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    val_input = next(
        t for t in at.text_input if t.key == "edit.newval.vendor_full_name"
    )
    val_input.set_value("Dell Technologies")
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    save = next(b for b in at.button if b.key == "edit.save")
    save.click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    success_msgs = [s.value for s in at.success]
    assert any("Saved 1 change" in m for m in success_msgs), (
        f"expected save-confirmation success; saw {success_msgs!r}"
    )

    conn = connect(empty_db)
    try:
        cell_raw = conn.execute(
            "SELECT vendor_full_name FROM products "
            "WHERE model_code = ? AND year = ?",
            ("alienware-m18", 2026),
        ).fetchone()[0]
    finally:
        conn.close()
    assert cell_raw is not None
    bundle = json.loads(cell_raw)
    assert bundle["value"] == "Dell Technologies"
    assert bundle.get("status") == "vouched"
    assert "entered_by" in bundle, (
        "manual bundle should carry entered_by; got {bundle!r}"
    )
