"""Tests for the Design view's Stage 10b rollup (cover materials only).

A and D cover materials are surfaced. C-cover, thermal_shelf, and
lighting drop from the rollup but stay on the Edit screen.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.design import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def test_empty_returns_empty_marker():
    value, marker = rollup_value({})
    assert value == ""
    assert marker == "[empty]"


def test_a_and_d_same_material_collapsed():
    product = {
        "a_cover_material": _bundle("aluminium"),
        "d_cover_material": _bundle("aluminium"),
    }
    value, marker = rollup_value(product)
    assert value == "aluminium (A + D)"
    assert marker == "[verified]"


def test_a_and_d_different_materials_show_both():
    product = {
        "a_cover_material": _bundle("aluminium"),
        "d_cover_material": _bundle("magnesium"),
    }
    value, _marker = rollup_value(product)
    assert value == "aluminium (A) · magnesium (D)"


def test_only_a_cover():
    product = {"a_cover_material": _bundle("aluminium")}
    value, _marker = rollup_value(product)
    assert value == "aluminium (A)"


def test_only_d_cover():
    product = {"d_cover_material": _bundle("plastic")}
    value, _marker = rollup_value(product)
    assert value == "plastic (D)"


def test_c_cover_drops_from_rollup():
    # C-cover should not contribute to the rollup output.
    product = {"c_cover_material": _bundle("aluminium")}
    value, marker = rollup_value(product)
    assert value == ""
    # c_cover_material is not a rollup source, so the marker doesn't pick
    # it up — the cell carries the all-empty marker.
    assert marker == "[empty]"


def test_worst_marker_propagates_needs_review():
    product = {
        "a_cover_material": _bundle("aluminium"),
        "d_cover_material": _bundle("magnesium", status="needs-review"),
    }
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_unchanged():
    paths = field_paths({})
    keys = {p for p, _l in paths}
    expected = {
        "a_cover_material",
        "c_cover_material",
        "d_cover_material",
        "thermal_shelf",
        "lighting",
    }
    assert expected == keys
