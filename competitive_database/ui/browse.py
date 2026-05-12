"""Browse one product — picker + full inspect-product view.

T8.1 scope: select a (model_code, year) and render the full view-layer
dump (same text ``inspect-product`` prints) as colored HTML, with the
six provenance markers wrapped in spans for at-a-glance scanning. No
new write paths; reuses ``views.orchestrator.render_product`` verbatim.

Marker palette + colorizer extracted to ``ui/_markers.py`` in T8.4.
"""

from __future__ import annotations

import html
import sqlite3

import streamlit as st

from competitive_database.ui._markers import colorize_text
from competitive_database.views import load, orchestrator


def _list_products(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT model_code, year FROM products ORDER BY model_code, year"
    ).fetchall()
    return [(mc, yr) for mc, yr in rows]


def _render_html(text: str) -> str:
    colored = colorize_text(html.escape(text))
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
