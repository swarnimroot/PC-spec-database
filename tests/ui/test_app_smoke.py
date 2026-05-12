"""T8.8 — first-cut Streamlit AppTest smoke layer.

Covers the entry-point boot, view dispatcher, and one read-only screen
end-to-end against an empty-DB fixture. Per-screen interaction tests
(write paths against seeded fixtures + monkeypatched ``refresh_product``)
are a follow-on once this layer is stable.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from tests.ui.conftest import APP_SCRIPT


_HUB_BUTTON_LABELS = {
    "Browse one product",
    "Compare side-by-side",
    "Find products where…",
    "Review queue triage",
    "Manual-edit a cell",
    "Refresh products",
}


def _run(default_timeout: float = 10.0) -> AppTest:
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=default_timeout)
    return at


def test_hub_renders_against_empty_db(empty_db):
    at = _run().run()
    assert not at.exception, [str(e) for e in at.exception]
    titles = [t.value for t in at.title]
    assert "Competitive Database" in titles
    # Four health metrics, six destinations.
    metric_labels = [m.label for m in at.metric]
    assert {"Products", "Vendors", "Review queue", "Days since refresh"} <= set(metric_labels)
    button_labels = {b.label for b in at.button}
    assert _HUB_BUTTON_LABELS <= button_labels


def test_browse_view_renders_empty_state(empty_db):
    at = _run()
    at.session_state["view"] = "browse"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    titles = [t.value for t in at.title]
    assert "Browse one product" in titles
    info_messages = [i.value for i in at.info]
    assert any("No products" in msg for msg in info_messages)


def test_view_dispatcher_routes_to_find_screen(empty_db):
    at = _run()
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # Find screen's "← Hub" button is the canonical sentinel that the
    # dispatcher picked ``find.render`` rather than falling back to hub.
    button_labels = {b.label for b in at.button}
    assert "← Hub" in button_labels
