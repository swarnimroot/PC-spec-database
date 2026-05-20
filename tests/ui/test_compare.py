"""AppTest coverage for the Stage 10c Compare redesign.

Compare runs a strict Company → Sub-brand → Series → Year cascade per
column, with each picker stack preceded by a blank offset column so the
dropdowns line up with the comparison-grid value columns underneath.
The ``+`` button is restyled, vertically centered over a faint rail line
that runs behind it across the picker stack.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from competitive_database.db.connection import connect, transaction
from competitive_database.db.helpers import make_scraped_bundle, write_scalar
from tests.ui.conftest import APP_SCRIPT


_CAPTURED_AT = "2026-05-20T00:00:00+00:00"
_SOURCE_URL = "https://example.com/test"
_SCRAPER_ID = "test"


def _bundle(value):
    return make_scraped_bundle(
        value=value,
        source_url=_SOURCE_URL,
        captured_at=_CAPTURED_AT,
        scraper_id=_SCRAPER_ID,
    )


def _seed_one(db_path, *, model_code, year, brand, sub_brand, series):
    conn = connect(db_path)
    try:
        with transaction(conn):
            pk = {"model_code": model_code, "year": year}
            write_scalar(conn, "products", pk, "brand", _bundle(brand))
            write_scalar(conn, "products", pk, "sub_brand", _bundle(sub_brand))
            write_scalar(conn, "products", pk, "series", _bundle(series))
            write_scalar(
                conn, "products", pk, "vendor_full_name",
                _bundle(f"{brand} {series} {year}"),
            )
    finally:
        conn.close()


def _seed_two(db_path):
    _seed_one(
        db_path, model_code="dell-x", year=2026,
        brand="Dell", sub_brand="Alienware", series="m18",
    )
    _seed_one(
        db_path, model_code="hp-y", year=2026,
        brand="HP", sub_brand="OMEN", series="Transcend",
    )


def _key(at, key):
    return [s for s in at.selectbox if s.key == key]


def test_compare_empty_db_shows_info_banner(empty_db):
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    info_messages = [i.value for i in at.info]
    assert any("No products" in msg for msg in info_messages)


def test_compare_first_paint_only_company_visible(empty_db):
    """Strict cascade: first paint of each column shows only Company."""
    _seed_two(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # One column by default; only its Company picker visible.
    assert len(_key(at, "compare.col1.company")) == 1
    assert _key(at, "compare.col1.sub_brand") == []
    assert _key(at, "compare.col1.series") == []
    assert _key(at, "compare.col1.year") == []


def test_compare_add_button_is_present_and_restyled(empty_db):
    _seed_two(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    add_buttons = [b for b in at.button if b.key == "compare.add"]
    assert len(add_buttons) == 1
    assert add_buttons[0].label == "+"

    # The restyle CSS class must be in the rendered markdown so the
    # ``+`` button picks up the faint accent fill + rail-line layering.
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert "cd-cmp-add-wrap" in markdown_blob
    assert "cd-cmp-rail" in markdown_blob


def test_compare_uses_series_rung_label_not_product(empty_db):
    """Compare columns use the Series rung mode, not the legacy Product."""
    _seed_two(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.session_state["compare.col1.company"] = "Dell"
    at.session_state["compare.col1.sub_brand"] = "Alienware"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    labels = {s.label for s in at.selectbox}
    assert "Sub-brand" in labels
    assert "Series" in labels
    assert "Product" not in labels


def test_compare_offset_column_renders_without_cta(empty_db):
    """Each picker stack is preceded by an empty offset column. The
    offset carries no text/CTA — its job is purely visual alignment with
    the comparison-grid value column underneath.
    """
    _seed_two(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # No "Add" / "+ another" call-to-action button anywhere in the offset
    # area — only the trailing ``compare.add`` button at the right.
    add_like = [
        b for b in at.button
        if b.key != "compare.add" and b.label.strip() in ("+", "Add")
    ]
    assert add_like == [], f"unexpected CTA buttons in offset: {add_like!r}"
