"""Compare side-by-side — Stage 11 Phase 4 picker columns + union grid.

Replaces the Stage 10c four-rung cascade per column with the Phase 3
3-rung Brand → Series → Product picker + year/status pill toggles.
Each column resolves a ``(brand, series, product)`` identity triple and
a filtered row-set; the comparison grid below renders those row-sets as
columns of union-rolled cells (Policy B ``·`` joins, worst marker per
cell). One populated column is enough to render the grid (single-column
union case collapses to byte-identical content with ``union_spec_table_html``
modulo the Compare outer shell).
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
    brand_series_product_picker,
    comparison_union_grid_html,
    inject_compare_styles,
    status_toggle_block,
    year_toggle_block,
)
from competitive_database.views import load as views_load

_MAX_COLUMNS = 4
_STATE_IDS = "compare.column_ids"

# Width of the empty offset column placed to the LEFT of every picker
# stack. The comparison grid below allots 12% to the section label and
# 18% to the feature label, so the picker dropdowns line up with the
# value column once those two prefix columns are accounted for. A single
# 1/10-width spacer column (≈10%) is the closest Streamlit ``columns``
# can get to "just shy of section + feature" without going wider than
# the spec-detail value column underneath.
_PICKER_OFFSET_WEIGHT = 1
_PICKER_BODY_WEIGHT = 5
_ADD_COL_WEIGHT = 1


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
    # Stage 11 Phase 4 keyspace: brand/series/product/years/status.
    # Legacy ``company`` / ``sub_brand`` / ``year`` keys went away with
    # the Phase 3 picker; nothing else writes them so no cleanup needed.
    for suffix in ("brand", "series", "product", "years", "status"):
        st.session_state.pop(f"compare.col{cid}.{suffix}", None)


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the Compare side-by-side screen.

    Stage 11 Phase 4: per column, run the Phase 3 strict 3-rung picker
    (Brand → Series → Product), then year + status pill toggles over
    the resolved identity. Each column contributes a filtered row-set
    to the union comparison grid. The grid renders as soon as ≥1
    column is populated (a single-column union still surfaces value).
    """
    del db_path  # chrome handles attribution; no internal IDs leak here.
    st.title("Compare side-by-side")

    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        st.info("No products in the database yet.")
        return

    inject_compare_styles()

    ids = _column_ids()
    n = len(ids)

    # Each picker column becomes a pair: [offset, body]. Trailing slim
    # column hosts the ``+`` button. Widths echo the comparison-grid
    # below so dropdowns sit above the value column, not over the
    # section/feature label prefix.
    weights: list[int] = []
    for _ in ids:
        weights.extend([_PICKER_OFFSET_WEIGHT, _PICKER_BODY_WEIGHT])
    weights.append(_ADD_COL_WEIGHT)
    cols = st.columns(weights)

    columns_rows: list[list[dict[str, Any]]] = []
    for i, cid in enumerate(ids):
        # Offset column: intentionally empty — pure visual padding so the
        # cascade dropdowns line up with the comparison-grid columns.
        _offset_col = cols[2 * i]
        body_col = cols[2 * i + 1]
        with body_col:
            # Tiny ``×`` affordance to drop this column; hidden at N=1.
            if n > 1:
                if st.button(
                    "×",
                    key=f"compare.remove.{cid}",
                    help="Remove this product",
                ):
                    _remove_column(cid)
                    st.rerun()
            picked = brand_series_product_picker(
                conn, key_prefix=f"compare.col{cid}", strict=True
            )
            if picked is None:
                # Cascade not yet complete for this column; it contributes
                # an empty row-set to the union grid (rendered as ``—``).
                columns_rows.append([])
                continue
            brand = picked["brand"]
            series = picked["series"]
            product = picked["product"]
            years = list_years_for_product(conn, brand, series, product)
            active_years = year_toggle_block(
                years, key_prefix=f"compare.col{cid}"
            )
            active_statuses = status_toggle_block(
                key_prefix=f"compare.col{cid}"
            )
            rows = load_product_rows(
                conn, brand, series, product, active_years, active_statuses
            )
            columns_rows.append(rows)

    with cols[-1]:
        # Wrapper carries the faint rail (CSS pseudo-element) + centers
        # the ``+`` button vertically over the picker stack.
        st.markdown(
            '<div class="cd-cmp-add-wrap" id="cd-cmp-add-wrap">',
            unsafe_allow_html=True,
        )
        if n < _MAX_COLUMNS:
            if st.button(
                "+",
                key="compare.add",
                help="Add another product to compare",
            ):
                _add_column()
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # Faint rail line spanning the picker block, sitting behind the ``+``
    # button. Rendered as a full-width div whose horizontal extent is
    # masked by the page padding + the offset/body column layout above.
    # Drawn here so it lands BELOW the picker stack in DOM order but is
    # styled to sit at the vertical center via negative margin.
    st.markdown(
        '<div class="cd-cmp-rail"></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="height:var(--cd-space-lg)"></div>',
        unsafe_allow_html=True,
    )

    # Render the grid as soon as ≥1 column has rows — single-column union
    # still surfaces value; user-confirmed Phase 4 threshold.
    if not any(col for col in columns_rows):
        st.info("Pick a product to start comparing.")
        return

    cpu_catalog = views_load.load_cpu_catalog(conn)
    gpu_catalog = views_load.load_gpu_catalog(conn)
    st.markdown(
        comparison_union_grid_html(
            columns_rows,
            cpu_catalog=cpu_catalog,
            gpu_catalog=gpu_catalog,
        ),
        unsafe_allow_html=True,
    )
