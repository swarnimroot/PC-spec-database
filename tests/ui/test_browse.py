"""AppTest coverage for the Stage 10c Browse redesign.

Browse runs a strict Company → Sub-brand → Series → Year cascade. The
spec table is gated on all four rungs being explicitly picked; first
paint shows only the Company picker (or the empty-DB info banner).
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


def _key(at, key):
    return [s for s in at.selectbox if s.key == key]


def test_browse_empty_db_shows_info_banner(empty_db):
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    info_messages = [i.value for i in at.info]
    assert any("No products" in msg for msg in info_messages)
    # No cascade rungs render against an empty DB.
    assert _key(at, "browse.company") == []


def test_browse_first_paint_shows_only_company(empty_db):
    """Strict cascade: with the DB seeded but no user picks made, only the
    Company picker should render. Sub-brand / Series / Year stay hidden.
    """
    _seed_one(
        empty_db, model_code="dell-x", year=2026,
        brand="Dell", sub_brand="Alienware", series="m18",
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    assert len(_key(at, "browse.company")) == 1
    assert _key(at, "browse.sub_brand") == []
    assert _key(at, "browse.series") == []
    assert _key(at, "browse.year") == []
    # Spec table absent until the cascade completes.
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert 'class="cd-spec"' not in markdown_blob


def test_browse_after_company_picked_unlocks_sub_brand(empty_db):
    _seed_one(
        empty_db, model_code="dell-x", year=2026,
        brand="Dell", sub_brand="Alienware", series="m18",
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.run()
    company_box = _key(at, "browse.company")[0]
    company_box.set_value("Dell").run()
    assert not at.exception, [str(e) for e in at.exception]

    assert len(_key(at, "browse.sub_brand")) == 1
    assert _key(at, "browse.series") == []
    assert _key(at, "browse.year") == []


def test_browse_all_four_picked_renders_spec_table(empty_db):
    _seed_one(
        empty_db, model_code="dell-x", year=2026,
        brand="Dell", sub_brand="Alienware", series="m18",
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    # Pre-seed all four cascade keys to skip the click-through walk.
    at.session_state["browse.company"] = "Dell"
    at.session_state["browse.sub_brand"] = "Alienware"
    at.session_state["browse.series"] = "m18"
    at.session_state["browse.year"] = 2026
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # Series rung label must be present (not "Product").
    series_boxes = _key(at, "browse.series")
    assert len(series_boxes) == 1
    assert series_boxes[0].label == "Series"

    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert 'class="cd-spec"' in markdown_blob
    assert 'class="cd-identity"' in markdown_blob


def test_browse_uses_series_rung_label_not_product(empty_db):
    """Sub-brand and Series labels replace the legacy 'Product' rung."""
    _seed_one(
        empty_db, model_code="dell-x", year=2026,
        brand="Dell", sub_brand="Alienware", series="m18",
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.session_state["browse.company"] = "Dell"
    at.session_state["browse.sub_brand"] = "Alienware"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    labels = {s.label for s in at.selectbox}
    assert "Sub-brand" in labels
    assert "Series" in labels
    assert "Product" not in labels
