"""Browse one product — picker + full inspect-product view.

T8.1 scope: select a (model_code, year) and render the full view-layer
dump (same text ``inspect-product`` prints) as colored HTML, with the
six provenance markers wrapped in spans for at-a-glance scanning. No
new write paths; reuses ``views.orchestrator.render_product`` verbatim.
"""

from __future__ import annotations

import html
import re
import sqlite3

import streamlit as st

from competitive_database.views import load, orchestrator
from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_MANUAL,
    MARKER_NEEDS_REVIEW,
    MARKER_PARTIAL,
    MARKER_VENDOR_NO_PUB,
    MARKER_VERIFIED,
)

_MARKER_COLORS: dict[str, str] = {
    MARKER_VERIFIED: "#3fb950",       # green
    MARKER_NEEDS_REVIEW: "#d29922",   # amber
    MARKER_VENDOR_NO_PUB: "#8b949e",  # gray
    MARKER_MANUAL: "#58a6ff",         # blue
    MARKER_EMPTY: "#6e7681",          # dim
    MARKER_PARTIAL: "#d29922",        # amber
}

_MARKER_RE = re.compile(
    "(" + "|".join(re.escape(m) for m in _MARKER_COLORS) + ")"
)


def _list_products(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT model_code, year FROM products ORDER BY model_code, year"
    ).fetchall()
    return [(mc, yr) for mc, yr in rows]


def _render_html(text: str) -> str:
    escaped = html.escape(text)

    def _color(match: re.Match[str]) -> str:
        marker = match.group(1)
        return f'<span style="color:{_MARKER_COLORS[marker]}">{marker}</span>'

    colored = _MARKER_RE.sub(_color, escaped)
    return (
        '<pre style="font-family:ui-monospace,Consolas,Menlo,monospace;'
        'font-size:0.85rem;line-height:1.45;white-space:pre;'
        'overflow-x:auto">'
        f"{colored}"
        "</pre>"
    )


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Browse one product")
    if st.button("← Hub"):
        st.session_state["view"] = "hub"
        st.rerun()

    products = _list_products(conn)
    if not products:
        st.info("No products in the database yet.")
        return

    options = [f"{mc} · {yr}" for mc, yr in products]
    selected = st.selectbox("Product", options, index=0)
    idx = options.index(selected)
    model_code, year = products[idx]

    product = load.load_product(conn, model_code, year=year)
    cpu_catalog = load.load_cpu_catalog(conn)
    gpu_catalog = load.load_gpu_catalog(conn)
    text = orchestrator.render_product(product, cpu_catalog, gpu_catalog)

    st.markdown(_render_html(text), unsafe_allow_html=True)
    st.caption(f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.1")
