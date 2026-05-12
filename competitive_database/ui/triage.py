"""Review queue triage - placeholder stub ahead of T8.5."""

from __future__ import annotations

import sqlite3

import streamlit as st


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Review queue triage")
    if st.button("← Hub"):
        st.session_state["view"] = "hub"
        st.rerun()
    st.info("Coming in T8.5 — placeholder while the hub destinations get wired through.")
