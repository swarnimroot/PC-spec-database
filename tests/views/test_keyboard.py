"""Tests for the Keyboard view (Stage 10b: HIDDEN from visual rollup).

Keyboard surfaces nothing on Browse / Compare / Find but still
enumerates its per-offering paths via ``field_paths`` so the Edit screen
and ``find-empty`` keep working.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views import keyboard
from competitive_database.views.orchestrator import _VISUAL_SECTIONS


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def test_keyboard_not_in_visible_rollup_registry():
    # The visual table loop in _components.spec_table_html / comparison_grid_html
    # iterates _VISUAL_SECTIONS — Keyboard must NOT appear there.
    assert "Keyboard" not in _VISUAL_SECTIONS


def test_keyboard_module_does_not_expose_rollup_value():
    # Stage 10b batch 2: hidden sections don't define rollup_value /
    # rollup_rows. _components.py dispatch falls back to ("", MARKER_EMPTY)
    # for anything outside _VISUAL_SECTIONS.
    assert not hasattr(keyboard, "rollup_value")
    assert not hasattr(keyboard, "rollup_rows")


def test_field_paths_enumerates_all_per_offering_leaves():
    # Edit contract: every per-offering bundle stays surfaced via
    # field_paths even though the section is rollup-hidden.
    product = {
        "keyboard_offerings": [
            {
                "description": _bundle("Per-key RGB"),
                "has_numpad": _bundle(True),
                "tier": _bundle("gaming"),
            },
            {
                "description": _bundle("Single-zone"),
                "has_numpad": _bundle(False),
                "tier": _bundle("entry"),
            },
        ]
    }
    paths = keyboard.field_paths(product)
    keys = {p for p, _l in paths}
    expected = {
        "keyboard_offerings.0.description",
        "keyboard_offerings.0.has_numpad",
        "keyboard_offerings.0.tier",
        "keyboard_offerings.1.description",
        "keyboard_offerings.1.has_numpad",
        "keyboard_offerings.1.tier",
    }
    assert expected.issubset(keys)


def test_render_still_emits_section_heading():
    # inspect-product CLI still surfaces the per-SKU detail.
    out = keyboard.render({"keyboard_offerings": [{"description": _bundle("Per-key RGB")}]})
    assert "Keyboard:" in out
