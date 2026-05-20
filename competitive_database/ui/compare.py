"""Compare side-by-side — N vertical picker columns + comparison grid."""

from __future__ import annotations

import html
import sqlite3
from typing import Any

import streamlit as st

from competitive_database.ui._components import (
    cascading_picker,
    comparison_grid_html,
    inject_compare_styles,
)
from competitive_database.ui.theme import PALETTE
from competitive_database.views import load as views_load
from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_VENDOR_NO_PUB,
    display_value,
    marker_for_bundle,
)

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
    for suffix in ("company", "sub_brand", "series", "product", "year"):
        st.session_state.pop(f"compare.col{cid}.{suffix}", None)


def _segment_line_html(product: dict[str, Any]) -> str:
    bundle = product.get("segment")
    if isinstance(bundle, dict):
        marker = marker_for_bundle(bundle)
        if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB):
            value = "—"
        else:
            value = display_value(bundle) or "—"
    else:
        value = "—"
    return (
        f'<div style="'
        f'margin-top:var(--cd-space-xs);'
        f'font-size:var(--cd-size-xs);'
        f'color:{PALETTE["text_muted"]};'
        f'">'
        f'<span style="color:{PALETTE["text_faint"]}">Segment:</span> '
        f"{html.escape(value)}"
        f"</div>"
    )


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the Compare side-by-side screen.

    Stage 10c: strict-cascade Series-rung pickers, each preceded by a
    blank offset column so the dropdowns line up with the comparison
    grid's value column underneath. The ``+`` button parks at the right
    and is centered on a faint rail line that runs behind it across the
    picker stack.
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

    picked_products: list[dict[str, Any]] = []
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
            picked = cascading_picker(
                conn,
                key_prefix=f"compare.col{cid}",
                vertical=True,
                strict_cascade=True,
                rung_mode="series",
            )
            if picked is not None:
                st.markdown(
                    _segment_line_html(picked["row"]),
                    unsafe_allow_html=True,
                )
                picked_products.append(picked["row"])

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
        f'<div style="height:var(--cd-space-lg)"></div>',
        unsafe_allow_html=True,
    )

    if len(picked_products) < 2:
        st.info("Pick at least two products to compare.")
        return

    cpu_catalog = views_load.load_cpu_catalog(conn)
    gpu_catalog = views_load.load_gpu_catalog(conn)
    st.markdown(
        comparison_grid_html(
            picked_products,
            cpu_catalog=cpu_catalog,
            gpu_catalog=gpu_catalog,
        ),
        unsafe_allow_html=True,
    )
