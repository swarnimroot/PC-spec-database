"""AppTest coverage for the Find-products screen.

The query is one searchable "Section · Feature" combobox + a Match
operator + a Value; narrow-by uses the single-search product combobox +
Year + Status toggles. Results render as a table; per-row ``Open →``
loads one product into Spec Roster, and "Open top N" loads up to four
matches as Spec Roster compare columns.

Widget keys on this screen:
  - ``find.field``        — searchable Section · Feature combobox (index=None)
  - ``find.op_label``     — Match operator (plain-English label)
  - ``find.value_select`` — Value picker (only when op needs a value)
  - ``find.narrow.search``— narrow-by product combobox
  - ``find.year_btn.<yr>`` / ``find.status_btn.<name>`` — toggle pills
  - ``find.open.<mc>.<yr>`` — per-row Open →; ``find.open_top`` — Open top N
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


def _run(view: str = "find") -> AppTest:
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = view
    return at


def _field_box(at):
    return [s for s in at.selectbox if s.key == "find.field"][0]


def _pick_field(at, needle: str):
    """Select the first Section · Feature option containing ``needle``."""
    box = _field_box(at)
    opt = next(o for o in box.options if needle in o)
    box.set_value(opt).run()
    return opt


def _value_box(at):
    matches = [s for s in at.selectbox if s.key == "find.value_select"]
    return matches[0] if matches else None


def _blob(at) -> str:
    return "\n".join(m.value for m in at.markdown)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


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


def _seed_two_full_identity(db_path):
    conn = connect(db_path)
    try:
        with transaction(conn):
            for mc, brand, sub, series, panel in [
                ("dell-x", "Dell", "Alienware", "m18", "IPS"),
                ("hp-y", "HP", "OMEN", "Transcend", "OLED"),
            ]:
                pk = {"model_code": mc, "year": 2026}
                write_scalar(conn, "products", pk, "brand", _bundle(brand))
                write_scalar(conn, "products", pk, "sub_brand", _bundle(sub))
                write_scalar(conn, "products", pk, "series", _bundle(series))
                write_scalar(
                    conn, "products", pk, "vendor_full_name",
                    _bundle(f"{brand} {series}"),
                )
                write_offerings(
                    conn, "products", pk,
                    "display_offerings",
                    [{"panel_type": _bundle(panel)}],
                )
    finally:
        conn.close()


def _seed_dell_two_years_and_hp(db_path):
    conn = connect(db_path)
    try:
        with transaction(conn):
            for mc, year, brand, sub, series, panel in [
                ("dell-x-2025", 2025, "Dell", "Alienware", "m18", "IPS"),
                ("dell-x-2026", 2026, "Dell", "Alienware", "m18", "IPS"),
                ("hp-y-2026", 2026, "HP", "OMEN", "Transcend", "OLED"),
            ]:
                pk = {"model_code": mc, "year": year}
                write_scalar(conn, "products", pk, "brand", _bundle(brand))
                write_scalar(conn, "products", pk, "sub_brand", _bundle(sub))
                write_scalar(conn, "products", pk, "series", _bundle(series))
                write_scalar(
                    conn, "products", pk, "vendor_full_name",
                    _bundle(f"{brand} {series} {year}"),
                )
                write_offerings(
                    conn, "products", pk,
                    "display_offerings",
                    [{"panel_type": _bundle(panel)}],
                )
    finally:
        conn.close()


def _seed_active_and_discontinued(db_path):
    conn = connect(db_path)
    try:
        with transaction(conn):
            for mc, sub, status in [
                ("dell-active", "Alienware", "Active"),
                ("dell-disc", "Inspiron", "Discontinued"),
            ]:
                pk = {"model_code": mc, "year": 2026}
                write_scalar(conn, "products", pk, "brand", _bundle("Dell"))
                write_scalar(conn, "products", pk, "sub_brand", _bundle(sub))
                write_scalar(conn, "products", pk, "series", _bundle("m18"))
                write_scalar(conn, "products", pk, "status", _bundle(status))
                write_scalar(
                    conn, "products", pk, "vendor_full_name",
                    _bundle(f"Dell {sub} m18"),
                )
                write_offerings(
                    conn, "products", pk,
                    "display_offerings",
                    [{"panel_type": _bundle("IPS")}],
                )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Query row: field combobox + match + value
# ---------------------------------------------------------------------------


def test_first_paint_prompts_for_a_spec_field(empty_db):
    _seed_two_vendors(empty_db)
    at = _run().run()
    assert not at.exception, [str(e) for e in at.exception]
    # index=None combobox: nothing picked yet → prompt, no value box.
    assert "find.field" in {s.key for s in at.selectbox}
    assert _value_box(at) is None
    assert any("Pick a spec field" in i.value for i in at.info)


def test_value_dropdown_for_vendor_field(empty_db):
    _seed_two_vendors(empty_db)
    at = _run().run()
    _pick_field(at, "Vendor name")
    assert not at.exception, [str(e) for e in at.exception]
    op_box = [s for s in at.selectbox if s.key == "find.op_label"][0]
    assert op_box.value == "equals"
    value_box = _value_box(at)
    assert value_box is not None
    assert list(value_box.options) == ["Dell Inc.", "HP Inc."]


def test_value_dropdown_numeric_sort_on_refresh_rate(empty_db):
    _seed_three_refresh_rates(empty_db)
    at = _run().run()
    _pick_field(at, "Refresh rate")
    assert not at.exception, [str(e) for e in at.exception]
    value_box = _value_box(at)
    assert value_box is not None
    assert list(value_box.options) == ["60", "120", "240"]


def test_empty_field_shows_inline_message_and_no_results(empty_db):
    _seed_only_vendor(empty_db)
    at = _run().run()
    _pick_field(at, "· Brand")  # brand is NULL on the seeded product
    assert not at.exception, [str(e) for e in at.exception]
    blob = _blob(at)
    assert "No values to filter on for this field" in blob
    assert _value_box(at) is None
    assert "No products match this query." in blob


def test_panel_type_canonicalizes_ips_level_to_ips(empty_db):
    _seed_two_panel_variants(empty_db)
    at = _run().run()
    _pick_field(at, "· Panel")
    assert not at.exception, [str(e) for e in at.exception]
    value_box = _value_box(at)
    assert value_box is not None
    assert list(value_box.options) == ["IPS"]


def test_panel_type_canonical_pick_matches_both_stored_variants(empty_db):
    _seed_two_panel_variants(empty_db)
    at = _run().run()
    _pick_field(at, "· Panel")
    assert not at.exception, [str(e) for e in at.exception]
    assert "2 products match" in _blob(at)


def test_query_row_has_field_match_value_selectboxes(empty_db):
    _seed_two_full_identity(empty_db)
    at = _run().run()
    _pick_field(at, "· Panel")
    assert not at.exception, [str(e) for e in at.exception]
    keys = [s.key for s in at.selectbox]
    for k in ("find.field", "find.op_label", "find.value_select"):
        assert k in keys, f"missing {k!r} in {keys!r}"
    leading = [k for k in keys if k in (
        "find.field", "find.op_label", "find.value_select"
    )]
    assert leading[:3] == ["find.field", "find.op_label", "find.value_select"]


# ---------------------------------------------------------------------------
# Narrow-by: product combobox + year/status toggles
# ---------------------------------------------------------------------------


def test_narrow_by_renders_product_picker_and_toggles(empty_db):
    _seed_two_full_identity(empty_db)
    at = _run().run()
    _pick_field(at, "· Panel")
    assert not at.exception, [str(e) for e in at.exception]
    keys = {s.key for s in at.selectbox}
    assert "find.narrow.search" in keys
    year_buttons = [
        b for b in at.button if b.key and b.key.startswith("find.year_btn.")
    ]
    status_buttons = [
        b for b in at.button if b.key and b.key.startswith("find.status_btn.")
    ]
    assert len(year_buttons) == 1
    assert len(status_buttons) == 2
    assert at.session_state["find.years"] == set()
    assert at.session_state["find.status"] == set()


def test_narrow_by_product_filters_to_that_product(empty_db):
    _seed_two_full_identity(empty_db)
    at = _run()
    at.session_state["find.op_label"] = "has any value"
    at.session_state["find.narrow.search"] = "Dell · m18 · dell-x"
    at.run()
    _pick_field(at, "· Panel")
    assert not at.exception, [str(e) for e in at.exception]
    blob = _blob(at)
    assert "1 product match" in blob
    assert "dell-x" in blob
    assert "hp-y" not in blob


def test_narrow_by_year_pill_filters_to_selected_years(empty_db):
    _seed_dell_two_years_and_hp(empty_db)
    at = _run()
    at.session_state["find.years"] = {2025}
    at.run()
    _pick_field(at, "· Panel")
    vbox = _value_box(at)
    vbox.set_value("IPS").run()
    assert not at.exception, [str(e) for e in at.exception]
    blob = _blob(at)
    assert "1 product match" in blob
    assert "dell-x-2025" in blob


def test_narrow_by_status_pill_filters_to_selected_statuses(empty_db):
    _seed_active_and_discontinued(empty_db)
    at = _run()
    at.session_state["find.status"] = {"Discontinued"}
    at.run()
    _pick_field(at, "· Panel")
    vbox = _value_box(at)
    vbox.set_value("IPS").run()
    assert not at.exception, [str(e) for e in at.exception]
    blob = _blob(at)
    assert "1 product match" in blob
    assert "dell-disc" in blob
    assert "dell-active" not in blob


def test_narrow_by_default_matches_all_query_results(empty_db):
    _seed_dell_two_years_and_hp(empty_db)
    at = _run().run()
    _pick_field(at, "· Panel")
    vbox = _value_box(at)
    vbox.set_value("IPS").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert "2 products match" in _blob(at)
    assert at.session_state["find.years"] == set()
    assert at.session_state["find.status"] == set()


# ---------------------------------------------------------------------------
# Results table + Spec Roster handoff
# ---------------------------------------------------------------------------


def test_results_table_renders_identity_and_open_buttons(empty_db):
    _seed_two_full_identity(empty_db)
    at = _run().run()
    _pick_field(at, "· Panel")
    assert not at.exception, [str(e) for e in at.exception]
    blob = _blob(at)
    assert "cd-findcard" not in blob  # cards retired
    assert "Dell" in blob and "m18" in blob and "dell-x" in blob
    row_opens = [b for b in at.button if b.label == "Open →"]
    assert row_opens, "expected at least one per-row Open → button"
    assert any(b.key == "find.open_top" for b in at.button)


def test_open_button_loads_one_product_into_spec_roster(empty_db):
    _seed_two_full_identity(empty_db)
    at = _run()
    at.session_state["find.op_label"] = "has any value"
    at.session_state["find.narrow.search"] = "Dell · m18 · dell-x"
    at.run()
    _pick_field(at, "· Panel")
    assert not at.exception, [str(e) for e in at.exception]
    row_opens = [b for b in at.button if b.label == "Open →"]
    assert len(row_opens) == 1
    row_opens[0].click().run()
    assert at.session_state["view"] == "hub"
    assert at.session_state["hub.section"] == "spec_roster"
    assert at.session_state["spec_roster.column_ids"] == [1]
    assert at.session_state["spec_roster.col1.search"] == "Dell · m18 · dell-x"


def test_open_top_loads_columns_into_spec_roster(empty_db):
    _seed_two_full_identity(empty_db)
    at = _run()
    at.session_state["find.op_label"] = "has any value"
    at.run()
    _pick_field(at, "· Panel")
    assert not at.exception, [str(e) for e in at.exception]
    assert "2 products match" in _blob(at)
    open_top = [b for b in at.button if b.key == "find.open_top"][0]
    open_top.click().run()
    assert at.session_state["view"] == "hub"
    assert at.session_state["hub.section"] == "spec_roster"
    assert at.session_state["spec_roster.column_ids"] == [1, 2]
    searches = {
        at.session_state["spec_roster.col1.search"],
        at.session_state["spec_roster.col2.search"],
    }
    assert searches == {"Dell · m18 · dell-x", "HP · Transcend · hp-y"}
