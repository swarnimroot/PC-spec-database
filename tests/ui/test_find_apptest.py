"""AppTest coverage for the Find-products screen.

Phase E rewrite: the Find screen now exposes a labelled query bar
(Spec field / Match / Value) with plain-English op labels and friendly
``"Section · Feature"`` spec-field options. The behavioral core
(``_distinct_values_for_template`` and ``_cell_matches``) is unchanged;
these tests drive the new presentation but cover the same outcomes.

Selectbox keys on this screen:
  - ``find.spec_field`` — Spec field (flat ``Section · Feature`` list)
  - ``find.op_label``   — Match operator (plain-English label)
  - ``find.value_select`` — Value picker (only when op needs a value)
  - ``find.narrow.company`` / ``find.narrow.year`` — narrow-by filters
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from competitive_database.db.connection import connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    write_offerings,
    write_scalar,
)
from tests.ui.conftest import APP_SCRIPT


_CAPTURED_AT = "2026-05-12T00:00:00+00:00"
_SOURCE_URL = "https://example.com/test"
_SCRAPER_ID = "test"


def _bundle(value):
    return make_scraped_bundle(
        value=value,
        source_url=_SOURCE_URL,
        captured_at=_CAPTURED_AT,
        scraper_id=_SCRAPER_ID,
    )


def _value_box(at):
    """Return the value selectbox (key=find.value_select) or None."""
    matches = [s for s in at.selectbox if s.key == "find.value_select"]
    return matches[0] if matches else None


def _seed_two_vendors(db_path) -> None:
    conn = connect(db_path)
    try:
        with transaction(conn):
            write_scalar(
                conn, "products",
                {"model_code": "dell-x", "year": 2026},
                "vendor_full_name", _bundle("Dell Inc."),
            )
            write_scalar(
                conn, "products",
                {"model_code": "hp-y", "year": 2026},
                "vendor_full_name", _bundle("HP Inc."),
            )
    finally:
        conn.close()


def _seed_three_refresh_rates(db_path) -> None:
    conn = connect(db_path)
    try:
        with transaction(conn):
            for mc, vendor, hz in [
                ("a-laptop", "Vendor A", 60),
                ("b-laptop", "Vendor B", 120),
                ("c-laptop", "Vendor C", 240),
            ]:
                pk = {"model_code": mc, "year": 2026}
                write_scalar(
                    conn, "products", pk,
                    "vendor_full_name", _bundle(vendor),
                )
                write_offerings(
                    conn, "products", pk,
                    "display_offerings",
                    [{"refresh_rate_hz": _bundle(hz)}],
                )
    finally:
        conn.close()


def _seed_only_vendor(db_path) -> None:
    conn = connect(db_path)
    try:
        with transaction(conn):
            write_scalar(
                conn, "products",
                {"model_code": "lonely-x", "year": 2026},
                "vendor_full_name", _bundle("Lonely Vendor"),
            )
    finally:
        conn.close()


def _seed_two_panel_variants(db_path) -> None:
    conn = connect(db_path)
    try:
        with transaction(conn):
            for mc, vendor, panel in [
                ("strict-ips", "Razer", "IPS"),
                ("legion-ips", "Lenovo", "IPS-level"),
            ]:
                pk = {"model_code": mc, "year": 2026}
                write_scalar(
                    conn, "products", pk,
                    "vendor_full_name", _bundle(vendor),
                )
                write_offerings(
                    conn, "products", pk,
                    "display_offerings",
                    [{"panel_type": _bundle(panel)}],
                )
    finally:
        conn.close()


def test_value_dropdown_populated_for_default_spec_field(empty_db):
    """Default Spec field is the first option (Identity · Vendor name).

    Seeds two products with distinct vendors and asserts the value
    selectbox carries those values, sorted casefold-alphabetically.
    """
    _seed_two_vendors(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # Default op label is "equals"; default spec field lands on first option.
    spec_box = [s for s in at.selectbox if s.key == "find.spec_field"][0]
    op_box = [s for s in at.selectbox if s.key == "find.op_label"][0]
    assert "Identity · Vendor name" in list(spec_box.options)
    assert op_box.value == "equals"

    value_box = _value_box(at)
    assert value_box is not None, "expected find.value_select to be rendered"
    assert list(value_box.options) == ["Dell Inc.", "HP Inc."], (
        f"unexpected dropdown options: {value_box.options!r}"
    )


def test_value_dropdown_numeric_sort_on_refresh_rate(empty_db):
    """Numeric leaf sorts numerically ascending, not alphabetically."""
    _seed_three_refresh_rates(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    spec_box = [s for s in at.selectbox if s.key == "find.spec_field"][0]
    target_label = "Display · Refresh rate"
    assert target_label in list(spec_box.options), (
        f"missing {target_label!r} in spec-field options: "
        f"{list(spec_box.options)!r}"
    )
    spec_box.set_value(target_label).run()
    assert not at.exception, [str(e) for e in at.exception]

    value_box = _value_box(at)
    assert value_box is not None
    assert list(value_box.options) == ["60", "120", "240"], (
        f"numeric sort broken: got {value_box.options!r}"
    )


def test_empty_field_shows_inline_message_and_no_results(empty_db):
    """When no product has a filled cell at the chosen template, an
    inline "No values to filter on" message renders and the value
    selectbox is absent. The result panel shows "No products match".
    """
    _seed_only_vendor(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    spec_box = [s for s in at.selectbox if s.key == "find.spec_field"][0]
    # Flip to "Identity · Brand" — brand is NULL on the seeded product.
    target = "Identity · Brand"
    assert target in list(spec_box.options), (
        f"missing {target!r} in spec-field options: {list(spec_box.options)!r}"
    )
    spec_box.set_value(target).run()
    assert not at.exception, [str(e) for e in at.exception]

    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert "No values to filter on for this field" in markdown_blob, (
        f"expected inline 'no values' message; saw markdown {markdown_blob!r}"
    )
    assert _value_box(at) is None, (
        "value selectbox should be absent when no values exist"
    )
    assert "No products match this query." in markdown_blob


def test_panel_type_canonicalizes_ips_level_to_ips(empty_db):
    """T9.2: dropdown shows a single canonical "IPS" entry for products
    that store either "IPS" or "IPS-level".
    """
    _seed_two_panel_variants(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    spec_box = [s for s in at.selectbox if s.key == "find.spec_field"][0]
    spec_box.set_value("Display · Panel").run()
    assert not at.exception, [str(e) for e in at.exception]

    value_box = _value_box(at)
    assert value_box is not None
    assert list(value_box.options) == ["IPS"], (
        f"canonical collapse broken: got {value_box.options!r}"
    )


def test_panel_type_canonical_pick_matches_both_stored_variants(empty_db):
    """T9.2: picking "IPS" matches both the product that stores "IPS"
    raw and the one that stores "IPS-level".
    """
    _seed_two_panel_variants(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    spec_box = [s for s in at.selectbox if s.key == "find.spec_field"][0]
    spec_box.set_value("Display · Panel").run()
    assert not at.exception, [str(e) for e in at.exception]

    markdown_blob = "\n".join(m.value for m in at.markdown)
    # Two products match; the result count line carries the count text.
    assert "2 products match" in markdown_blob, (
        f"expected '2 products match' in markdown; got {markdown_blob!r}"
    )
