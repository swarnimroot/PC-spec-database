"""Spec Roster — view one product or compare several (Browse + Compare merged).

One page replaces the old Browse and Compare screens. A column is one
product (resolved by the single-search ``Brand · Series · Product``
combobox) plus its year + status multi-select toggles. With one populated
column the page renders the roomy union identity strip + spec table; with
two or more it renders the side-by-side comparison grid. Year-variants
within a column union into that column (the "merged" default).
"""

from __future__ import annotations

import sqlite3
from typing import Any

import streamlit as st

from competitive_database.db.helpers import (
    list_years_for_product,
    load_product_rows,
)
from competitive_database.ui._components import (
    comparison_union_grid_html,
    inject_compare_styles,
    product_search_picker,
    status_toggle_block,
    union_identity_strip_html,
    union_spec_table_html,
    year_toggle_block,
)
from competitive_database.views import load as views_load

_MAX_COLUMNS = 4
_STATE_IDS = "spec_roster.column_ids"


def _column_ids() -> list[int]:
    ids = st.session_state.get(_STATE_IDS)
    if not isinstance(ids, list) or not ids:
        ids = [1]
        st.session_state[_STATE_IDS] = ids
    return ids


def _add_column() -> None:
    ids = _column_ids()
    if len(ids) >= _MAX_COLUMNS:
        return
    ids.append(max(ids) + 1)
    st.session_state[_STATE_IDS] = ids


def _remove_column(cid: int) -> None:
    ids = _column_ids()
    if cid not in ids or len(ids) <= 1:
        return
    ids.remove(cid)
    st.session_state[_STATE_IDS] = ids
    for suffix in ("search", "years", "status"):
        st.session_state.pop(f"spec_roster.col{cid}.{suffix}", None)


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the Spec Roster screen.

    Per column: single-search combobox → identity, then year + status
    multi-select toggles → a filtered row-set. One populated column renders
    the roomy union view; two or more render the comparison grid. The
    column add/remove caps at four.
    """
    del db_path  # chrome handles attribution.
    st.title("Spec Roster")

    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        st.info("No products in the database yet.")
        return

    ids = _column_ids()
    n = len(ids)
    cols = st.columns(n + 1)

    columns_rows: list[list[dict[str, Any]]] = []
    for i, cid in enumerate(ids):
        with cols[i]:
            if n > 1:
                if st.button(
                    "×",
                    key=f"spec_roster.remove.{cid}",
                    help="Remove this product",
                ):
                    _remove_column(cid)
                    st.rerun()
            picked = product_search_picker(
                conn, key_prefix=f"spec_roster.col{cid}"
            )
            if picked is None:
                columns_rows.append([])
                continue
            brand = picked["brand"]
            series = picked["series"]
            product = picked["product"]
            years = list_years_for_product(conn, brand, series, product)
            active_years = year_toggle_block(
                years, key_prefix=f"spec_roster.col{cid}"
            )
            active_statuses = status_toggle_block(
                key_prefix=f"spec_roster.col{cid}"
            )
            rows = load_product_rows(
                conn, brand, series, product, active_years, active_statuses
            )
            columns_rows.append(rows)

    with cols[-1]:
        if n < _MAX_COLUMNS:
            if st.button(
                "➕",
                key="spec_roster.add",
                help="Add another product to compare",
            ):
                _add_column()
                st.rerun()

    populated = [rows for rows in columns_rows if rows]

    st.markdown(
        '<div style="height:var(--cd-space-lg)"></div>',
        unsafe_allow_html=True,
    )

    if not populated:
        st.info("Search for a product to begin.")
        return

    cpu_catalog = views_load.load_cpu_catalog(conn)
    gpu_catalog = views_load.load_gpu_catalog(conn)

    if len(populated) == 1:
        rows = populated[0]
        st.markdown(union_identity_strip_html(rows), unsafe_allow_html=True)
        st.markdown(
            union_spec_table_html(
                rows, cpu_catalog=cpu_catalog, gpu_catalog=gpu_catalog
            ),
            unsafe_allow_html=True,
        )
        return

    inject_compare_styles()
    st.markdown(
        comparison_union_grid_html(
            populated, cpu_catalog=cpu_catalog, gpu_catalog=gpu_catalog
        ),
        unsafe_allow_html=True,
    )
