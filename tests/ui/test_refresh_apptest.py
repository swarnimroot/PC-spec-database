"""T8.8 — AppTest write-path coverage for the refresh screen.

Monkeypatches ``competitive_database.ui.refresh.refresh_product`` to a
stub (no real vendor fetch / parse), then drives the URL-template /
One-product flow. Asserts the stub was called with the form's values
and that the success banner renders the returned summary.

The patch target is the UI-bound name (not the CLI module) — that is
the symbol the ``_run_one`` helper resolves at call time.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

import competitive_database.ui.refresh as ui_refresh
from tests.ui.conftest import APP_SCRIPT


_FAKE_SUMMARY = {
    "snapshot_count": 1,
    "pks": [("ac16251", 2026)],
    "totals": {
        "inserted_fields": 4,
        "refreshed_fields": 0,
        "conflicts": 0,
        "low_confidence": 0,
        "year_inferred": 0,
        "new_cpus": 0,
        "new_gpus": 0,
    },
}


def test_refresh_url_template_calls_lib_and_renders_summary(
    empty_db, monkeypatch
):
    calls: list[dict] = []

    def fake_refresh_product(conn, **kwargs):
        calls.append(kwargs)
        return _FAKE_SUMMARY

    monkeypatch.setattr(ui_refresh, "refresh_product", fake_refresh_product)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "refresh"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # Default mode = "One product", default source = "URL template",
    # default brand = first alpha (asus). Just need to fill the slug.
    mode = next(r for r in at.radio if r.key == "refresh-mode")
    assert mode.value == "One product"
    source = next(r for r in at.radio if r.key == "refresh-source")
    assert source.value == "URL template"

    slug_input = next(t for t in at.text_input if t.key == "refresh-tmpl-model")
    slug_input.set_value("test-model-slug")

    go = next(b for b in at.button if b.key == "refresh-tmpl-go")
    go.click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    assert len(calls) == 1, f"expected exactly one refresh_product call; got {len(calls)}"
    kwargs = calls[0]
    brand_box = next(s for s in at.selectbox if s.key == "refresh-tmpl-brand")
    assert kwargs["brand"] == brand_box.value
    assert kwargs["model"] == "test-model-slug"
    assert kwargs["url"] is None
    assert kwargs["from_db"] is False
    assert kwargs["year"] is None
    assert callable(kwargs.get("on_step"))

    success_msgs = [s.value for s in at.success]
    assert any("Refresh complete" in m for m in success_msgs), (
        f"missing 'Refresh complete' banner; saw {success_msgs}"
    )
    assert any("inserted=4" in m for m in success_msgs), (
        f"summary totals not rendered; saw {success_msgs}"
    )


def test_refresh_url_template_surfaces_lib_error(empty_db, monkeypatch):
    def boom(conn, **kwargs):
        raise ValueError("vendor returned an empty page")

    monkeypatch.setattr(ui_refresh, "refresh_product", boom)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "refresh"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    next(t for t in at.text_input if t.key == "refresh-tmpl-model").set_value("x")
    next(b for b in at.button if b.key == "refresh-tmpl-go").click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    error_msgs = [e.value for e in at.error]
    assert any("vendor returned an empty page" in m for m in error_msgs), (
        f"expected lib ValueError surfaced as st.error; saw {error_msgs}"
    )
