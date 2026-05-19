"""Compare side-by-side — N vertical picker columns + comparison grid."""

from __future__ import annotations

import html
import sqlite3
from typing import Any

import streamlit as st

from competitive_database.ui._components import (
    cascading_picker,
    comparison_grid_html,
)
from competitive_database.ui.theme import PALETTE
from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_VENDOR_NO_PUB,
    display_value,
    marker_for_bundle,
)

_MAX_COLUMNS = 4
_STATE_IDS = "compare.column_ids"


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
    for suffix in ("company", "product", "year"):
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
    """Render the Compare side-by-side screen."""
    del db_path  # chrome handles attribution; no internal IDs leak here.
    st.title("Compare side-by-side")

    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        st.info("No products in the database yet.")
        return

    ids = _column_ids()
    n = len(ids)
    # One column per picker plus a trailing slim column for the ``+`` button
    # so it parks neatly to the right of the rightmost picker.
    layout = list(ids) + ["__add__"]
    cols = st.columns(len(layout))

    picked_products: list[dict[str, Any]] = []
    for cid, col in zip(ids, cols[:n]):
        with col:
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
            )
            if picked is not None:
                st.markdown(
                    _segment_line_html(picked["row"]),
                    unsafe_allow_html=True,
                )
                picked_products.append(picked["row"])

    with cols[-1]:
        if n < _MAX_COLUMNS:
            if st.button(
                "+",
                key="compare.add",
                help="Add another product to compare",
            ):
                _add_column()
                st.rerun()

    st.markdown(
        f'<div style="height:var(--cd-space-lg)"></div>',
        unsafe_allow_html=True,
    )

    if len(picked_products) < 2:
        st.info("Pick at least two products to compare.")
        return

    st.markdown(
        comparison_grid_html(picked_products),
        unsafe_allow_html=True,
    )
