"""Compare side-by-side - placeholder stub ahead of T8.3."""

from __future__ import annotations

import sqlite3

import streamlit as st


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Compare side-by-side")
    if st.button("← Hub"):
        st.session_state["view"] = "hub"
        st.rerun()
    st.info("Coming in T8.3 — placeholder while the hub destinations get wired through.")
