"""Find products where... - placeholder stub ahead of T8.4."""

from __future__ import annotations

import sqlite3

import streamlit as st


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Find products where…")
    if st.button("← Hub"):
        st.session_state["view"] = "hub"
        st.rerun()
    st.info("Coming in T8.4 — placeholder while the hub destinations get wired through.")
