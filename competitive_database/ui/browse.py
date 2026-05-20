"""Browse one product — cascading picker + identity strip + spec table."""

from __future__ import annotations

import sqlite3

import streamlit as st

from competitive_database.ui._components import (
    cascading_picker,
    identity_strip_html,
    spec_table_html,
)
from competitive_database.views import load as views_load


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the Browse-one-product screen.

    Stage 10c: strict cascade across Company → Sub-brand → Series → Year.
    The spec table only renders once all four rungs are picked; identity
    strip + table are separated by an ``xl`` vertical gap so the band
    reads with breathing room.
    """
    st.title("Browse one product")

    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        st.info("No products in the database yet.")
        return

    picked = cascading_picker(
        conn,
        key_prefix="browse",
        strict_cascade=True,
        rung_mode="series",
    )
    if picked is None:
        # Cascade not yet complete; the picker has rendered whatever rungs
        # are unlocked, and nothing follows until the user picks all four.
        return

    product = picked["row"]
    cpu_catalog = views_load.load_cpu_catalog(conn)
    gpu_catalog = views_load.load_gpu_catalog(conn)
    st.markdown(identity_strip_html(product), unsafe_allow_html=True)
    # Visual breathing room between identity band and the spec data.
    st.markdown(
        '<div style="height:var(--cd-space-xl)"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        spec_table_html(
            product, cpu_catalog=cpu_catalog, gpu_catalog=gpu_catalog
        ),
        unsafe_allow_html=True,
    )
