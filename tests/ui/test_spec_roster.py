"""AppTest coverage for the Spec Roster page (Browse + Compare merged).

Spec Roster resolves each column's product via the single-search
``Brand · Series · Product`` combobox, then year + status toggles filter
the row set. One populated column renders the roomy union view
(``cd-spec``); two or more render the comparison grid (``cd-cmp``).
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from competitive_database.db.connection import connect, transaction
from competitive_database.db.helpers import make_scraped_bundle, write_scalar
from tests.ui.conftest import APP_SCRIPT

_CAPTURED_AT = "2026-05-20T00:00:00+00:00"


def _bundle(value):
    return make_scraped_bundle(
        value=value,
        source_url="https://example.com/test",
        captured_at=_CAPTURED_AT,
        scraper_id="test",
    )


def _seed_one(
    db_path,
    *,
    model_code,
    year,
    brand,
    series,
    product,
    sub_brand="X",
    status=None,
):
    conn = connect(db_path)
    try:
        with transaction(conn):
            conn.execute(
                "INSERT OR IGNORE INTO products (product, year, model_code) "
                "VALUES (?, ?, ?)",
                (product, year, model_code),
            )
            pk = {"model_code": model_code, "year": year}
            write_scalar(conn, "products", pk, "brand", _bundle(brand))
            write_scalar(conn, "products", pk, "sub_brand", _bundle(sub_brand))
            write_scalar(conn, "products", pk, "series", _bundle(series))
            if status is not None:
                write_scalar(conn, "products", pk, "status", _bundle(status))
    finally:
        conn.close()


def _run() -> AppTest:
    return AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)


def test_spec_roster_empty_db_shows_banner(empty_db):
    at = _run()
    at.session_state["view"] = "spec_roster"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert "Spec Roster" in [t.value for t in at.title]
    assert any("No products" in i.value for i in at.info)


def test_spec_roster_first_paint_shows_search_box(empty_db):
    _seed_one(
        empty_db, model_code="tuf-16-2025", year=2025,
        brand="ASUS", series="TUF", product="TUF 16",
    )
    at = _run()
    at.session_state["view"] = "spec_roster"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    search = [s for s in at.selectbox if s.key == "spec_roster.col1.search"]
    assert len(search) == 1
    assert any("Search for a product" in i.value for i in at.info)


def test_spec_roster_pick_renders_union_view(empty_db):
    _seed_one(
        empty_db, model_code="tuf-16-2025", year=2025,
        brand="ASUS", series="TUF", product="TUF 16",
    )
    at = _run()
    at.session_state["view"] = "spec_roster"
    at.session_state["spec_roster.col1.search"] = "ASUS · TUF · TUF 16"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    blob = "\n".join(m.value for m in at.markdown)
    assert "cd-spec" in blob
    assert not any("Search for a product" in i.value for i in at.info)


def test_spec_roster_two_products_render_comparison_grid(empty_db):
    _seed_one(
        empty_db, model_code="tuf-16-2025", year=2025,
        brand="ASUS", series="TUF", product="TUF 16",
    )
    _seed_one(
        empty_db, model_code="legion-pro-5-16-2025", year=2025,
        brand="Lenovo", series="Legion", product="Legion Pro 5 16",
    )
    at = _run()
    at.session_state["view"] = "spec_roster"
    at.session_state["spec_roster.column_ids"] = [1, 2]
    at.session_state["spec_roster.col1.search"] = "ASUS · TUF · TUF 16"
    at.session_state["spec_roster.col2.search"] = (
        "Lenovo · Legion · Legion Pro 5 16"
    )
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    blob = "\n".join(m.value for m in at.markdown)
    assert "cd-cmp" in blob
