"""Streamlit entry script.

Invoked indirectly by ``python -m competitive_database ui`` (see
``cli/ui_launch.py``), which shells out to ``python -m streamlit run``
against this file. The DB path is read from ``COMPETITIVE_DB_PATH``,
which the launcher sets before spawning Streamlit; falls back to
``competitive.db`` in the cwd for direct ``streamlit run`` invocations.
"""

from __future__ import annotations

import os

import streamlit as st

from competitive_database.db.connection import connect
from competitive_database.ui import browse, compare, edit, find, hub, triage


def _db_path() -> str:
    return os.environ.get("COMPETITIVE_DB_PATH", "competitive.db")


_VIEWS = {
    "hub": hub.render,
    "browse": browse.render,
    "compare": compare.render,
    "find": find.render,
    "queue": triage.render,
    "edit": edit.render,
}


def main() -> None:
    st.set_page_config(page_title="Competitive Database", layout="wide")
    db_path = _db_path()
    conn = connect(db_path)
    try:
        view = st.session_state.get("view", "hub")
        render = _VIEWS.get(view, hub.render)
        render(conn, db_path=db_path)
    finally:
        conn.close()


main()
