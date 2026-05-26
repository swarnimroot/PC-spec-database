"""AppTest coverage for the Stage 11 Phase 3 Browse redesign.

Browse runs a strict Brand → Series → Product picker resolving the
``(product, year)``-PK identity triple, then renders year + status pill
toggles and a union identity strip + union spec table over the filtered
row set. First paint with the DB seeded shows only the Brand selectbox.
Year and status toggles only appear once Product is locked in. The
table collapses to byte-identical single-row HTML when N=1.
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

    ``product`` (the PK column) defaults to ``model_code`` so legacy
    fixtures keep working; new tests that need two rows sharing the same
    logical product across years pass it explicitly. ``status`` is an
    optional plain string ("Active" / "Discontinued") wrapped in a
    bundle; omit for the NULL-status case. ``extra_fields`` is a dict
    of ``{field_name: scalar_value}`` so each test can diverge on one
    visible spec leaf for the union renderer.
    """
    conn = connect(db_path)
    try:
        with transaction(conn):
            product_pk = product if product is not None else model_code
            # Pre-insert the (product, year) row so subsequent writes via the
            # legacy ``{"model_code", "year"}`` pk resolve to this row's
            # product slug instead of falling back to ``product = model_code``
            # (which would create separate logical products per year).
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
    statuses_per_year=None,
):
    """Seed two rows sharing one ``product`` across two years.

    ``extra_fields_per_year`` maps year -> {field: scalar} so callers
    can diverge a display leaf year-by-year. ``statuses_per_year`` maps
    year -> "Active" / "Discontinued" / ``None`` (None leaves
    ``status`` unset so the NULL-as-Active rule applies).
    """
    extra_fields_per_year = extra_fields_per_year or {}
    statuses_per_year = statuses_per_year or {}
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
            status=statuses_per_year.get(year),
        )


def _key(at, key):
    return [s for s in at.selectbox if s.key == key]


def _browse_buttons(at, suffix):
    """Return all buttons under the ``browse.<suffix>.*`` keyspace."""
    prefix = f"browse.{suffix}."
    return [b for b in at.button if b.key and b.key.startswith(prefix)]


def test_browse_empty_db_shows_info_banner(empty_db):
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    info_messages = [i.value for i in at.info]
    assert any("No products" in msg for msg in info_messages)
    # No picker rungs render against an empty DB.
    assert _key(at, "browse.brand") == []


def test_browse_first_paint_shows_only_brand_picker(empty_db):
    """Strict cascade: with the DB seeded but no user picks made, only
    Brand renders. Series + Product dropdowns and year / status pill
    rows stay hidden.
    """
    _seed_one(
        empty_db, model_code="dell-x", year=2026,
        brand="Dell", sub_brand="Alienware", series="m18",
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    assert len(_key(at, "browse.brand")) == 1
    assert _key(at, "browse.series") == []
    assert _key(at, "browse.product") == []
    # No year / status pills until Product is picked.
    assert _browse_buttons(at, "year_btn") == []
    assert _browse_buttons(at, "status_btn") == []
    # Spec table absent.
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert 'class="cd-spec"' not in markdown_blob


def test_browse_brand_picked_unlocks_series(empty_db):
    _seed_one(
        empty_db, model_code="dell-x", year=2026,
        brand="Dell", sub_brand="Alienware", series="m18",
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.run()
    brand_box = _key(at, "browse.brand")[0]
    brand_box.set_value("Dell").run()
    assert not at.exception, [str(e) for e in at.exception]

    assert len(_key(at, "browse.series")) == 1
    assert _key(at, "browse.product") == []
    # Year + status pills still gated.
    assert _browse_buttons(at, "year_btn") == []
    assert _browse_buttons(at, "status_btn") == []


def test_browse_all_three_picked_renders_year_buttons(empty_db):
    """Full cascade renders N year buttons where N = distinct years."""
    _seed_two_years_same_product(
        empty_db, product="alienware-m18", years=(2025, 2026),
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.session_state["browse.brand"] = "Dell"
    at.session_state["browse.series"] = "m18"
    at.session_state["browse.product"] = "alienware-m18"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    year_buttons = _browse_buttons(at, "year_btn")
    assert len(year_buttons) == 2
    # Latest year is pre-toggled (filled pill); older is empty.
    labels_by_year = {b.key.split(".")[-1]: b.label for b in year_buttons}
    assert labels_by_year["2026"].startswith("●")
    assert labels_by_year["2025"].startswith("○")


def test_browse_year_buttons_default_to_latest_only(empty_db):
    """First paint with product picked seeds {max(years)} into
    ``browse.years`` (the year_toggle_block contract).
    """
    _seed_two_years_same_product(
        empty_db, product="alienware-m18", years=(2025, 2026),
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.session_state["browse.brand"] = "Dell"
    at.session_state["browse.series"] = "m18"
    at.session_state["browse.product"] = "alienware-m18"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["browse.years"] == {2026}


def test_browse_status_buttons_default_to_active_only(empty_db):
    _seed_two_years_same_product(
        empty_db, product="alienware-m18", years=(2025, 2026),
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.session_state["browse.brand"] = "Dell"
    at.session_state["browse.series"] = "m18"
    at.session_state["browse.product"] = "alienware-m18"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["browse.status"] == {"Active"}


def test_browse_union_renders_both_years_when_both_toggled(empty_db):
    """Toggling both years on surfaces both per-year display values in
    the rendered union spec table HTML.
    """
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
    at.session_state["view"] = "browse"
    at.session_state["browse.brand"] = "Dell"
    at.session_state["browse.series"] = "m18"
    at.session_state["browse.product"] = "alienware-m18"
    at.session_state["browse.years"] = {2025, 2026}
    at.session_state["browse.status"] = {"Active"}
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert 'class="cd-spec"' in markdown_blob
    # Both per-year divergent values surface in the rolled-up Audio row.
    assert "TUNEBRAND-OLD" in markdown_blob
    assert "TUNEBRAND-NEW" in markdown_blob


def test_browse_status_filter_excludes_discontinued(empty_db):
    """Default Active-only filter drops the Discontinued row."""
    _seed_two_years_same_product(
        empty_db,
        product="alienware-m18",
        years=(2025, 2026),
        extra_fields_per_year={
            2025: {"tuning_brand": "TUNEBRAND-OLD"},
            2026: {"tuning_brand": "TUNEBRAND-NEW"},
        },
        statuses_per_year={2025: "Active", 2026: "Discontinued"},
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.session_state["browse.brand"] = "Dell"
    at.session_state["browse.series"] = "m18"
    at.session_state["browse.product"] = "alienware-m18"
    # Toggle both years on so the only filter that can drop a row is status.
    at.session_state["browse.years"] = {2025, 2026}
    at.session_state["browse.status"] = {"Active"}
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert "TUNEBRAND-OLD" in markdown_blob  # Active row's value present
    assert "TUNEBRAND-NEW" not in markdown_blob  # Discontinued filtered out


def test_browse_all_null_status_renders_all_rows(empty_db):
    """Both rows have NULL status. The default Active filter still
    shows both — NULL is treated as Active per load_product_rows.
    """
    _seed_two_years_same_product(
        empty_db,
        product="alienware-m18",
        years=(2025, 2026),
        extra_fields_per_year={
            2025: {"tuning_brand": "TUNEBRAND-OLD"},
            2026: {"tuning_brand": "TUNEBRAND-NEW"},
        },
        # No statuses_per_year → both rows leave status NULL.
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.session_state["browse.brand"] = "Dell"
    at.session_state["browse.series"] = "m18"
    at.session_state["browse.product"] = "alienware-m18"
    at.session_state["browse.years"] = {2025, 2026}
    at.session_state["browse.status"] = {"Active"}
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert "TUNEBRAND-OLD" in markdown_blob
    assert "TUNEBRAND-NEW" in markdown_blob


def test_browse_zero_rows_after_filter_shows_banner(empty_db):
    """A year selection that matches no DB rows surfaces the info
    banner in place of the spec table.

    ``load_product_rows`` treats an empty ``years`` list as "all years"
    (so toggling every pill off shows the full set, not zero rows), so
    we force a deterministic empty result by seeding the session-state
    year set to one that doesn't exist in the DB.
    """
    _seed_two_years_same_product(
        empty_db, product="alienware-m18", years=(2025, 2026),
    )
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "browse"
    at.session_state["browse.brand"] = "Dell"
    at.session_state["browse.series"] = "m18"
    at.session_state["browse.product"] = "alienware-m18"
    at.session_state["browse.years"] = {1999}
    at.session_state["browse.status"] = {"Active"}
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    info_messages = [i.value for i in at.info]
    assert any("No rows match" in msg for msg in info_messages)
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert 'class="cd-spec"' not in markdown_blob
