"""Browse one product — Stage 11 Phase 3 picker + year/status toggles + union view.

Replaces the legacy Stage 10c four-rung cascade. Identity is now the
``(brand, series, product)`` triple (PK is ``(product, year)``): the
picker resolves that triple, then year-toggle + status-toggle pills
filter the row set and we render the union identity strip + union spec
table. The strip and table render byte-identical to the single-row
versions when exactly one row passes the filters.
"""

from __future__ import annotations

import sqlite3

import streamlit as st

from competitive_database.db.helpers import (
    list_years_for_product,
    load_product_rows,
)
from competitive_database.ui._components import (
    brand_series_product_picker,
    status_toggle_block,
    union_identity_strip_html,
    union_spec_table_html,
    year_toggle_block,
)
from competitive_database.views import load as views_load


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the Browse-one-product screen.

    Stage 11 Phase 3: strict Brand → Series → Product cascade resolves
    the (product, year)-PK identity triple. Year + status pill toggles
    filter the row set; union strip + union spec table render the result
    (collapses to byte-identical single-row HTML when N=1). Empty filter
    set surfaces an info banner in place of the table.
    """
    st.title("Browse one product")

    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        st.info("No products in the database yet.")
        return

    picked = brand_series_product_picker(conn, key_prefix="browse")
    if picked is None:
        # Cascade not yet complete; the picker has rendered whatever
        # rungs are unlocked. Year/status toggles only appear once a
        # product is locked in.
        return

    brand = picked["brand"]
    series = picked["series"]
    product = picked["product"]

    years = list_years_for_product(conn, brand, series, product)
    active_years = year_toggle_block(years, key_prefix="browse")
    active_statuses = status_toggle_block(key_prefix="browse")

    rows = load_product_rows(
        conn, brand, series, product, active_years, active_statuses
    )

    # Visual breathing room between picker / toggles and the data band.
    st.markdown(
        '<div style="height:var(--cd-space-xl)"></div>',
        unsafe_allow_html=True,
    )

    if not rows:
        st.info("No rows match the selected year + status filters.")
        return

    cpu_catalog = views_load.load_cpu_catalog(conn)
    gpu_catalog = views_load.load_gpu_catalog(conn)
    st.markdown(union_identity_strip_html(rows), unsafe_allow_html=True)
    st.markdown(
        union_spec_table_html(
            rows, cpu_catalog=cpu_catalog, gpu_catalog=gpu_catalog
        ),
        unsafe_allow_html=True,
    )
