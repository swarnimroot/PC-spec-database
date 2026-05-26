"""AppTest coverage for the Stage 11 Phase 4 Compare redesign.

Compare now runs the Phase 3 strict 3-rung Brand → Series → Product
picker per column plus year + status pill toggles, and renders the spec
table as a multi-column UNION grid. The grid renders as soon as ≥1
column is populated (a single-column union still surfaces value). Each
column's session-state lives under ``compare.col{cid}.{brand|series|
product|years|status}``.
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


def _seed_one(
    db_path,
    *,
    model_code,
    year,
    brand,
    sub_brand,
    series,
    product=None,
    extra_fields=None,
    status=None,
):
    """Seed one ``(product, year)`` row with brand/sub_brand/series identity.

    ``product`` (the PK column) defaults to ``model_code`` so two-year
    fixtures that share one logical product can pin a common slug.
    Mirrors the Browse-test seed helper byte-for-byte so the two screens
    test against identical row shapes.
    """
    conn = connect(db_path)
    try:
        with transaction(conn):
            product_pk = product if product is not None else model_code
            conn.execute(
                "INSERT OR IGNORE INTO products (product, year, model_code) "
                "VALUES (?, ?, ?)",
                (product_pk, year, model_code),
            )
            pk = {"model_code": model_code, "year": year}
            write_scalar(conn, "products", pk, "brand", _bundle(brand))
            write_scalar(conn, "products", pk, "sub_brand", _bundle(sub_brand))
            write_scalar(conn, "products", pk, "series", _bundle(series))
            write_scalar(
                conn, "products", pk, "vendor_full_name",
                _bundle(f"{brand} {series} {year}"),
            )
            if status is not None:
                write_scalar(conn, "products", pk, "status", _bundle(status))
            for field, value in (extra_fields or {}).items():
                write_scalar(conn, "products", pk, field, _bundle(value))
    finally:
        conn.close()


def _seed_two_years_same_product(
    db_path,
    *,
    product,
    years,
    brand="Dell",
    sub_brand="Alienware",
    series="m18",
    extra_fields_per_year=None,
):
    """Seed two rows sharing one ``product`` across two years."""
    extra_fields_per_year = extra_fields_per_year or {}
    for year in years:
        _seed_one(
            db_path,
            model_code=f"{product}-{year}",
            year=year,
            brand=brand,
            sub_brand=sub_brand,
            series=series,
            product=product,
            extra_fields=extra_fields_per_year.get(year),
        )


def _seed_two_products(db_path):
    """Two distinct logical products for the two-column populated tests."""
    _seed_one(
        db_path, model_code="dell-x", year=2026,
        brand="Dell", sub_brand="Alienware", series="m18",
        product="alienware-m18",
    )
    _seed_one(
        db_path, model_code="hp-y", year=2026,
        brand="HP", sub_brand="OMEN", series="Transcend",
        product="omen-transcend",
    )


def _key(at, key):
    return [s for s in at.selectbox if s.key == key]


def _buttons(at, prefix):
    return [b for b in at.button if b.key and b.key.startswith(prefix)]


def test_compare_empty_db_shows_info_banner(empty_db):
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    info_messages = [i.value for i in at.info]
    assert any("No products" in msg for msg in info_messages)


def test_compare_first_paint_only_brand_visible(empty_db):
    """Strict cascade: first paint of each column shows only Brand."""
    _seed_two_products(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # One column by default; only its Brand picker visible.
    assert len(_key(at, "compare.col1.brand")) == 1
    assert _key(at, "compare.col1.series") == []
    assert _key(at, "compare.col1.product") == []
    # No year / status pills until Product is picked.
    assert _buttons(at, "compare.col1.year_btn.") == []
    assert _buttons(at, "compare.col1.status_btn.") == []


def test_compare_add_button_is_present_and_restyled(empty_db):
    _seed_two_products(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    add_buttons = [b for b in at.button if b.key == "compare.add"]
    assert len(add_buttons) == 1
    assert add_buttons[0].label == "+"

    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert "cd-cmp-add-wrap" in markdown_blob
    assert "cd-cmp-rail" in markdown_blob


def test_compare_full_cascade_renders_year_and_status_toggles(empty_db):
    """Cascade complete → Phase 3 year + status pill blocks appear with
    their default seeds (latest year ON, Active ON)."""
    _seed_two_years_same_product(
        empty_db, product="alienware-m18", years=(2025, 2026),
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.session_state["compare.col1.brand"] = "Dell"
    at.session_state["compare.col1.series"] = "m18"
    at.session_state["compare.col1.product"] = "alienware-m18"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    year_buttons = _buttons(at, "compare.col1.year_btn.")
    assert len(year_buttons) == 2
    status_buttons = _buttons(at, "compare.col1.status_btn.")
    assert len(status_buttons) == 2
    # Phase 3 defaults: latest year ON, Active ON.
    assert at.session_state["compare.col1.years"] == {2026}
    assert at.session_state["compare.col1.status"] == {"Active"}


def test_compare_one_populated_column_renders_union_grid(empty_db):
    """One populated column already crosses the ≥1 threshold."""
    _seed_two_years_same_product(
        empty_db, product="alienware-m18", years=(2025, 2026),
        extra_fields_per_year={
            2026: {"tuning_brand": "TUNEBRAND-NEW"},
        },
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.session_state["compare.col1.brand"] = "Dell"
    at.session_state["compare.col1.series"] = "m18"
    at.session_state["compare.col1.product"] = "alienware-m18"
    at.session_state["compare.col1.years"] = {2026}
    at.session_state["compare.col1.status"] = {"Active"}
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert 'class="cd-cmp"' in markdown_blob
    assert "TUNEBRAND-NEW" in markdown_blob


def test_compare_two_populated_columns_isolated_state(empty_db):
    """Two columns render side-by-side; per-column state is isolated."""
    _seed_two_products(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    # Add a second column.
    at.session_state["compare.column_ids"] = [1, 2]
    at.session_state["compare.col1.brand"] = "Dell"
    at.session_state["compare.col1.series"] = "m18"
    at.session_state["compare.col1.product"] = "alienware-m18"
    at.session_state["compare.col1.years"] = {2026}
    at.session_state["compare.col1.status"] = {"Active"}
    at.session_state["compare.col2.brand"] = "HP"
    at.session_state["compare.col2.series"] = "Transcend"
    at.session_state["compare.col2.product"] = "omen-transcend"
    at.session_state["compare.col2.years"] = {2026}
    at.session_state["compare.col2.status"] = {"Active"}
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert 'class="cd-cmp"' in markdown_blob

    # Each column's session-state lives under its own key prefix —
    # changing one column's year doesn't bleed into the other.
    assert at.session_state["compare.col1.years"] == {2026}
    assert at.session_state["compare.col2.years"] == {2026}
    at.session_state["compare.col1.years"] = {2025}
    assert at.session_state["compare.col1.years"] == {2025}
    assert at.session_state["compare.col2.years"] == {2026}


def test_compare_year_toggle_merges_union_for_column(empty_db):
    """Toggling a second year on for one column merges the two per-year
    display values via ``·`` in that column's cells."""
    _seed_two_years_same_product(
        empty_db,
        product="alienware-m18",
        years=(2025, 2026),
        extra_fields_per_year={
            2025: {"tuning_brand": "TUNEBRAND-OLD"},
            2026: {"tuning_brand": "TUNEBRAND-NEW"},
        },
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.session_state["compare.col1.brand"] = "Dell"
    at.session_state["compare.col1.series"] = "m18"
    at.session_state["compare.col1.product"] = "alienware-m18"
    at.session_state["compare.col1.years"] = {2025, 2026}
    at.session_state["compare.col1.status"] = {"Active"}
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_blob = "\n".join(m.value for m in at.markdown)
    # Both per-year values surface in the rolled-up Audio row, joined
    # by the Policy B ``·`` separator.
    assert "TUNEBRAND-OLD" in markdown_blob
    assert "TUNEBRAND-NEW" in markdown_blob


def test_compare_remove_column_cleans_all_state_keys(empty_db):
    """``_remove_column`` pops every Phase 4 state key for the removed cid."""
    _seed_two_products(empty_db)
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "compare"
    at.session_state["compare.column_ids"] = [1, 2]
    # Pre-seed all five Phase 4 state keys for the column we're about to drop.
    at.session_state["compare.col2.brand"] = "HP"
    at.session_state["compare.col2.series"] = "Transcend"
    at.session_state["compare.col2.product"] = "omen-transcend"
    at.session_state["compare.col2.years"] = {2026}
    at.session_state["compare.col2.status"] = {"Active"}
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # Click the ``×`` button for column 2.
    remove_btns = [b for b in at.button if b.key == "compare.remove.2"]
    assert len(remove_btns) == 1
    remove_btns[0].click().run()
    assert not at.exception, [str(e) for e in at.exception]

    # All five keys gone; column 2 fully removed.
    for suffix in ("brand", "series", "product", "years", "status"):
        assert f"compare.col2.{suffix}" not in at.session_state, (
            f"compare.col2.{suffix} should have been popped"
        )
    assert at.session_state["compare.column_ids"] == [1]
