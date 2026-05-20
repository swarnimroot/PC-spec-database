"""AppTest coverage for the Find-products screen.

Stage 10c rewrite: the Find screen now exposes a strict cascade
Section → Feature → Match → Value, with optional Company / Series / Year
narrow-by chips. The behavioral core (``_distinct_values_for_template``
and ``_cell_matches``) is unchanged; these tests drive the new
presentation but cover the same outcomes.

Selectbox keys on this screen:
  - ``find.section``  — Section (orchestrator render order)
  - ``find.feature``  — Feature (friendly leaf labels for that section)
  - ``find.op_label`` — Match operator (plain-English label)
  - ``find.value_select`` — Value picker (only when op needs a value)
  - ``find.narrow.company`` / ``find.narrow.series`` / ``find.narrow.year``
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


def _section_box(at):
    return [s for s in at.selectbox if s.key == "find.section"][0]


def _feature_box(at):
    return [s for s in at.selectbox if s.key == "find.feature"][0]


def test_value_dropdown_populated_for_default_spec_field(empty_db):
    """Default Section/Feature lands on the first option (Identity / Vendor name).

    Seeds two products with distinct vendors and asserts the value
    selectbox carries those values, sorted casefold-alphabetically.
    """
    _seed_two_vendors(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    section_box = _section_box(at)
    feature_box = _feature_box(at)
    op_box = [s for s in at.selectbox if s.key == "find.op_label"][0]
    assert "Identity" in list(section_box.options)
    assert section_box.value == "Identity"
    assert "Vendor name" in list(feature_box.options)
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

    _section_box(at).set_value("Display").run()
    assert not at.exception, [str(e) for e in at.exception]
    feature_box = _feature_box(at)
    assert "Refresh rate" in list(feature_box.options), (
        f"missing 'Refresh rate' in feature options: "
        f"{list(feature_box.options)!r}"
    )
    feature_box.set_value("Refresh rate").run()
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

    # Flip to "Identity / Brand" — brand is NULL on the seeded product.
    _section_box(at).set_value("Identity").run()
    assert not at.exception, [str(e) for e in at.exception]
    feature_box = _feature_box(at)
    assert "Brand" in list(feature_box.options), (
        f"missing 'Brand' in feature options: {list(feature_box.options)!r}"
    )
    feature_box.set_value("Brand").run()
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

    _section_box(at).set_value("Display").run()
    _feature_box(at).set_value("Panel").run()
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

    _section_box(at).set_value("Display").run()
    _feature_box(at).set_value("Panel").run()
    assert not at.exception, [str(e) for e in at.exception]

    markdown_blob = "\n".join(m.value for m in at.markdown)
    # Two products match; the result count line carries the count text.
    assert "2 products match" in markdown_blob, (
        f"expected '2 products match' in markdown; got {markdown_blob!r}"
    )


# ---------------------------------------------------------------------------
# Stage 10c — cascade order + result cards + Open → wiring
# ---------------------------------------------------------------------------


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


def test_cascade_order_section_then_feature_then_match_then_value(empty_db):
    """Section / Feature / Match / Value selectboxes render in that order,
    with the four expected keys.
    """
    _seed_two_full_identity(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    keys_in_render_order = [s.key for s in at.selectbox]
    # Section/feature/op render unconditionally; value renders when the
    # current op needs one (default "equals" does, so it must appear).
    expected = ["find.section", "find.feature", "find.op_label", "find.value_select"]
    for k in expected:
        assert k in keys_in_render_order, (
            f"missing {k!r} in selectboxes: {keys_in_render_order!r}"
        )
    # Strict ordering of the leading four.
    leading = [k for k in keys_in_render_order if k in expected]
    assert leading[: len(expected)] == expected, (
        f"unexpected cascade order: {leading!r}"
    )


def test_narrow_by_renders_company_series_year(empty_db):
    _seed_two_full_identity(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    _section_box(at).set_value("Display").run()
    _feature_box(at).set_value("Panel").run()
    assert not at.exception, [str(e) for e in at.exception]

    keys = {s.key for s in at.selectbox}
    assert "find.narrow.company" in keys
    assert "find.narrow.series" in keys
    assert "find.narrow.year" in keys


def test_result_card_renders_identity_and_open_button(empty_db):
    _seed_two_full_identity(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    _section_box(at).set_value("Display").run()
    _feature_box(at).set_value("Panel").run()
    assert not at.exception, [str(e) for e in at.exception]

    markdown_blob = "\n".join(m.value for m in at.markdown)
    # Card layout class + identity crumbs for at least one seeded product.
    assert "cd-findcard" in markdown_blob
    assert "Dell" in markdown_blob
    assert "Alienware" in markdown_blob
    # Open → buttons keyed per matched product.
    open_buttons = [b for b in at.button if b.label.startswith("Open")]
    assert open_buttons, "expected at least one Open → button"


def test_open_button_sets_browse_session_state(empty_db):
    """Clicking ``Open →`` on a result card primes Browse's strict-cascade
    keys and switches the view to ``browse``.
    """
    _seed_two_full_identity(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    _section_box(at).set_value("Display").run()
    _feature_box(at).set_value("Panel").run()
    # Filter to the Dell row via the narrow-by so we click a deterministic card.
    [s for s in at.selectbox if s.key == "find.narrow.company"][0].set_value("Dell").run()
    assert not at.exception, [str(e) for e in at.exception]

    open_buttons = [b for b in at.button if b.label.startswith("Open")]
    assert open_buttons, "expected at least one Open → button"
    open_buttons[0].click().run()
    # Rerun lands on Browse — view flipped and the four cascade keys are set.
    assert at.session_state["view"] == "browse"
    assert at.session_state["browse.company"] == "Dell"
    assert at.session_state["browse.sub_brand"] == "Alienware"
    assert at.session_state["browse.series"] == "m18"
    assert at.session_state["browse.year"] == 2026
