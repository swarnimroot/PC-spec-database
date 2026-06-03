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


def _run(default_timeout: float = 10.0) -> AppTest:
    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=default_timeout)
    return at


def test_hub_renders_against_empty_db(empty_db):
    at = _run().run()
    assert not at.exception, [str(e) for e in at.exception]
    # Editorial Hub: hero copy + 3 metric tiles + 3 CTA cards with Open → buttons.
    markdown_blob = "\n".join(m.value for m in at.markdown)
    # Tagline removed in the rework.
    assert "The competitive gaming-laptop reference." not in markdown_blob
    for tile_label in ("products", "vendors", "since refresh"):
        assert tile_label in markdown_blob
    for card_title in ("Spec Roster", "Find"):
        assert card_title in markdown_blob
    button_labels = [b.label for b in at.button]
    assert button_labels.count("Open →") == 2


def test_spec_roster_view_renders_empty_state(empty_db):
    at = _run()
    at.session_state["view"] = "spec_roster"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    titles = [t.value for t in at.title]
    assert "Spec Roster" in titles
    info_messages = [i.value for i in at.info]
    assert any("No products" in msg for msg in info_messages)


def test_view_dispatcher_routes_to_find_screen(empty_db):
    at = _run()
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # Phase E: the editorial page title is the canonical sentinel that
    # the dispatcher picked ``find.render`` rather than falling back to hub.
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert "Find products" in markdown_blob
    assert "Build a query to surface laptops" in markdown_blob


def test_welcome_modal_renders_on_first_hub_visit(empty_db):
    at = _run().run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_blob = "\n".join(m.value for m in at.markdown)
    # Hero kicker + explanatory section headers. "Who it's for" is
    # asserted indirectly via the function row labels below — its
    # apostrophe gets HTML-escaped in the rendered output.
    for sentinel in (
        "The problem",
        "What this does",
        "Hand-normalized",
        "spec categories",
    ):
        assert sentinel in markdown_blob, sentinel
    # Per-function rows in the "Who it's for" section.
    for function_label in ("Product", "Marketing", "Competitive intel"):
        assert function_label in markdown_blob, function_label
    # Empty-DB fallback for the vendor list — the body should read
    # "from every major OEM" rather than a hardcoded brand list.
    assert "every major OEM" in markdown_blob
    # Flag is set immediately on open so an X-dismissal also sticks.
    assert at.session_state["welcome_seen"] is True


def test_welcome_modal_skipped_when_already_seen(empty_db):
    at = _run()
    at.session_state["welcome_seen"] = True
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_blob = "\n".join(m.value for m in at.markdown)
    # None of the modal's unique sentinels should appear.
    for sentinel in ("The problem", "Hand-normalized", "Competitive intel"):
        assert sentinel not in markdown_blob, sentinel
    # Hub still renders below where the modal would have been.
    assert "Spec Roster" in markdown_blob


def test_welcome_modal_dismisses_on_got_it_click(empty_db):
    """``Got it`` triggers a rerun that should not raise — guards against
    the dialog body accidentally reaching for the live DB connection,
    which Streamlit reruns on a worker thread distinct from the one that
    created it.
    """
    at = _run().run()
    assert not at.exception, [str(e) for e in at.exception]
    got_it = [b for b in at.button if b.label == "Got it"]
    assert len(got_it) == 1
    got_it[0].click().run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_blob = "\n".join(m.value for m in at.markdown)
    assert "The problem" not in markdown_blob
    assert "Hand-normalized" not in markdown_blob


def test_welcome_modal_lists_live_vendor_names(empty_db):
    """When products are seeded, the modal body lists the actual brand
    names from the DB (sorted, comma-joined, ``etc.`` appended).
    """
    import json as _json
    from competitive_database.db.connection import connect, transaction

    conn = connect(empty_db)
    try:
        with transaction(conn):
            for code, brand in (("dell_a", "Dell"), ("asus_a", "ASUS")):
                conn.execute(
                    "INSERT INTO products (product, model_code, year, brand) "
                    "VALUES (?, ?, ?, ?)",
                    (code, code, 2026, _json.dumps({"value": brand})),
                )
    finally:
        conn.close()

    at = _run().run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_blob = "\n".join(m.value for m in at.markdown)
    # Sorted alphabetically with ``etc.`` appended — future-proofs the
    # copy for Acer/MSI/etc. before they're seeded.
    assert "ASUS, Dell, etc." in markdown_blob
