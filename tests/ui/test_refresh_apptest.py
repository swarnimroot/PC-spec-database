"""Phase G (Stage 10a) AppTest smoke coverage for the Refresh screen.

The pre-Phase-G screen had a 2-mode radio + URL-template / Custom-URL /
From-DB inner toggle; Phase G replaces all of that with three tabs
backed by the ``refresh.mode`` session key. The pre-Phase-G AppTest
suite asserted on the dropped widgets (``refresh-tmpl-model``,
``refresh-tmpl-go``, etc.) and is replaced here by two minimal cases:
empty-DB renders without error, and clicking a mode tab switches the
session-state value.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from tests.ui.conftest import APP_SCRIPT


def test_refresh_empty_db_renders_without_error(empty_db):
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "refresh"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # Title sentinel — the Phase G screen uses an editorial markdown
    # heading rather than st.title, so we scan the markdown blob.
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert "Refresh" in markdown_blob
    # Three mode tabs render as buttons; default mode is ``all``.
    button_keys = {b.key for b in at.button}
    assert "refresh.tab.all" in button_keys
    assert "refresh.tab.company" in button_keys
    assert "refresh.tab.selected" in button_keys
    assert at.session_state["refresh.mode"] == "all"


def test_refresh_tab_click_switches_mode(empty_db):
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "refresh"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    company_tab = next(b for b in at.button if b.key == "refresh.tab.company")
    company_tab.click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["refresh.mode"] == "company"
