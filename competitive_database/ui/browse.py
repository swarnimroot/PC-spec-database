"""Browse one product — cascading picker + identity strip + spec table."""

from __future__ import annotations

import sqlite3

import streamlit as st

from competitive_database.ui._components import (
    cascading_picker,
    identity_strip_html,
    spec_table_html,
)


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the Browse-one-product screen."""
    st.title("Browse one product")

    picked = cascading_picker(conn, key_prefix="browse")
    if picked is None:
        st.info("No products in the database yet.")
        return

    product = picked["row"]
    st.markdown(identity_strip_html(product), unsafe_allow_html=True)
    st.markdown(spec_table_html(product), unsafe_allow_html=True)
