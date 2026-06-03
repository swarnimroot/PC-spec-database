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
from competitive_database.ui import _chrome, edit, hub, refresh, triage


def _db_path() -> str:
    return os.environ.get("COMPETITIVE_DB_PATH", "competitive.db")


# Top-level views. Spec Roster + Find are NOT here: they render inline on
# the hub via ``hub.section`` (the hub owns the Spec Roster / Find pills).
_VIEWS = {
    "hub": hub.render,
    "queue": triage.render,
    "edit": edit.render,
    "refresh": refresh.render,
}

# Legacy / deep-link views that now resolve to an inline hub section.
_HUB_SECTION_REDIRECTS = {
    "browse": "spec_roster",
    "compare": "spec_roster",
    "spec_roster": "spec_roster",
    "find": "find",
}


def main() -> None:
    st.set_page_config(
        page_title="Spec Compass",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    db_path = _db_path()
    conn = connect(db_path)
    try:
        view = st.session_state.get("view", "hub")
        if view in _HUB_SECTION_REDIRECTS:
            st.session_state["hub.section"] = _HUB_SECTION_REDIRECTS[view]
            st.session_state["view"] = view = "hub"
        _chrome.render_header(active=view)
        render = _VIEWS.get(view, hub.render)
        render(conn, db_path=db_path)
        _chrome.render_footer()
    finally:
        conn.close()


main()
