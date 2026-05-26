"""Stage 11 Phase 3 read-side query helpers.

Covers the five picker helpers in ``db.helpers``:
  - ``list_brand_options``
  - ``list_series_options`` (NULL surfaces as ``"—"``)
  - ``list_product_options`` (handles ``series=None``)
  - ``list_years_for_product`` (DESC order)
  - ``load_product_rows`` (empty year/status filters; NULL-as-Active rule)
"""

from __future__ import annotations

import json

from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    list_brand_options,
    list_product_options,
    list_series_options,
    list_years_for_product,
    load_product_rows,
)


def _bundle(value):
    return {"value": value, "source_note": "test", "entered_by": "test"}


def _insert_product(
    conn,
    *,
    product,
    year,
    model_code,
    brand,
    series,
    status=None,
):
    """Insert one ``products`` row with the brand/series/status shapes the
    picker helpers expect (bundles with ``$.value``).
    """
    brand_json = json.dumps(_bundle(brand))
    series_json = json.dumps(_bundle(series)) if series is not None else None
    status_json = json.dumps(_bundle(status)) if status is not None else None
    conn.execute(
        "INSERT INTO products (product, model_code, year, brand, series, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (product, model_code, year, brand_json, series_json, status_json),
    )


def _seeded_db(tmp_path):
    """Build a mini-DB with two brands, mixed series (incl. NULL), and a
    Discontinued status row so every filter rule can be exercised.
    """
    conn = connect(tmp_path / "picker.db")
    with transaction(conn):
        apply_schema(conn)
    with transaction(conn):
        # ASUS / ROG Strix — two years on the same product.
        _insert_product(
            conn,
            product="Strix G16",
            year=2025,
            model_code="rog-strix-g16-2025",
            brand="ASUS",
            series="ROG Strix",
        )
        _insert_product(
            conn,
            product="Strix G16",
            year=2024,
            model_code="rog-strix-g16-2024",
            brand="ASUS",
            series="ROG Strix",
        )
        # ASUS / TUF — separate series for the same brand.
        _insert_product(
            conn,
            product="TUF A16",
            year=2025,
            model_code="tuf-a16-2025",
            brand="ASUS",
            series="TUF",
        )
        # Lenovo / NULL series — surfaces as "—" sentinel.
        _insert_product(
            conn,
            product="Legion Pro 7 16",
            year=2025,
            model_code="legion-pro-7-16-gen-10",
            brand="Lenovo",
            series=None,
        )
        # Lenovo / Legion — has a Discontinued status to exercise filtering.
        _insert_product(
            conn,
            product="Legion 5 15",
            year=2023,
            model_code="legion-5-15-gen-8",
            brand="Lenovo",
            series="Legion",
            status="Discontinued",
        )
        # Lenovo / Legion — Active status on a different year.
        _insert_product(
            conn,
            product="Legion 5 15",
            year=2024,
            model_code="legion-5-15-gen-9",
            brand="Lenovo",
            series="Legion",
            status="Active",
        )
        # Lenovo / Legion — NULL status on a third year (NULL = Active rule).
        _insert_product(
            conn,
            product="Legion 5 15",
            year=2025,
            model_code="legion-5-15-gen-10",
            brand="Lenovo",
            series="Legion",
            status=None,
        )
    return conn


def test_list_brand_options_distinct_alphabetical(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        assert list_brand_options(conn) == ["ASUS", "Lenovo"]
    finally:
        conn.close()


def test_list_series_options_for_brand(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        assert list_series_options(conn, "ASUS") == ["ROG Strix", "TUF"]
    finally:
        conn.close()


def test_list_series_options_null_surfaces_as_em_dash(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        opts = list_series_options(conn, "Lenovo")
        assert "—" in opts
        assert "Legion" in opts
        # The NULL sentinel must not be dropped.
        assert len(opts) == 2
    finally:
        conn.close()


def test_list_product_options_with_real_series(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        # ASUS / ROG Strix has only "Strix G16" (DISTINCT across two years).
        assert list_product_options(conn, "ASUS", "ROG Strix") == ["Strix G16"]
    finally:
        conn.close()


def test_list_product_options_with_none_series(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        # Lenovo / NULL series must match the row whose series column IS NULL.
        assert list_product_options(conn, "Lenovo", None) == ["Legion Pro 7 16"]
    finally:
        conn.close()


def test_list_years_for_product_desc(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        assert list_years_for_product(conn, "ASUS", "ROG Strix", "Strix G16") == [
            2025,
            2024,
        ]
    finally:
        conn.close()


def test_list_years_for_product_with_none_series(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        assert list_years_for_product(conn, "Lenovo", None, "Legion Pro 7 16") == [
            2025,
        ]
    finally:
        conn.close()


def test_load_product_rows_empty_years_returns_all_years(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        rows = load_product_rows(
            conn, "ASUS", "ROG Strix", "Strix G16", years=[], statuses=[]
        )
        years = [r["year"] for r in rows]
        assert sorted(years) == [2024, 2025]
    finally:
        conn.close()


def test_load_product_rows_empty_statuses_returns_all_rows(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        # Three Legion 5 15 rows exist (Discontinued / Active / NULL).
        rows = load_product_rows(
            conn, "Lenovo", "Legion", "Legion 5 15", years=[], statuses=[]
        )
        assert {r["year"] for r in rows} == {2023, 2024, 2025}
    finally:
        conn.close()


def test_load_product_rows_active_filter_includes_null_status(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        # statuses=["Active"] must keep the NULL-status row (NULL == Active rule).
        rows = load_product_rows(
            conn, "Lenovo", "Legion", "Legion 5 15", years=[], statuses=["Active"]
        )
        years = {r["year"] for r in rows}
        # 2024 (Active) and 2025 (NULL) included; 2023 (Discontinued) excluded.
        assert years == {2024, 2025}
    finally:
        conn.close()


def test_load_product_rows_active_filter_excludes_discontinued(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        rows = load_product_rows(
            conn, "Lenovo", "Legion", "Legion 5 15", years=[], statuses=["Active"]
        )
        statuses = {
            (r["status"]["value"] if r["status"] is not None else None) for r in rows
        }
        assert "Discontinued" not in statuses
    finally:
        conn.close()


def test_load_product_rows_year_filter(tmp_path):
    conn = _seeded_db(tmp_path)
    try:
        rows = load_product_rows(
            conn, "ASUS", "ROG Strix", "Strix G16", years=[2025], statuses=[]
        )
        assert [r["year"] for r in rows] == [2025]
    finally:
        conn.close()
