"""Tests for the Dimensions view's Stage 10b rollup.

``<w> × <d> × <h_min>-<h_max> mm`` with graceful fallbacks for missing
heights, and trailing-``.0`` trimming on numeric values.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.dimensions import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def test_empty_returns_empty_marker():
    value, marker = rollup_value({})
    assert value == ""
    assert marker == "[empty]"


def test_full_quad_renders_min_max_height():
    product = {
        "width_mm": _bundle(354),
        "depth_mm": _bundle(246),
        "height_mm_min": _bundle(20),
        "height_mm_max": _bundle(28),
    }
    value, marker = rollup_value(product)
    assert value == "354 × 246 × 20-28 mm"
    assert marker == "[verified]"


def test_only_max_height_drops_dash():
    product = {
        "width_mm": _bundle(354),
        "depth_mm": _bundle(246),
        "height_mm_max": _bundle(28),
    }
    value, _marker = rollup_value(product)
    assert value == "354 × 246 × 28 mm"


def test_both_heights_null_drops_height_clause():
    product = {"width_mm": _bundle(354), "depth_mm": _bundle(246)}
    value, _marker = rollup_value(product)
    assert value == "354 × 246 mm"


def test_trailing_zero_trimmed():
    product = {
        "width_mm": _bundle(354.0),
        "depth_mm": _bundle(246.0),
        "height_mm_min": _bundle(20.0),
        "height_mm_max": _bundle(28.0),
    }
    value, _marker = rollup_value(product)
    assert value == "354 × 246 × 20-28 mm"


def test_non_integer_value_keeps_decimal():
    product = {
        "width_mm": _bundle(354.5),
        "depth_mm": _bundle(246),
    }
    value, _marker = rollup_value(product)
    assert value == "354.5 × 246 mm"


def test_missing_width_renders_empty_string():
    # Without width/depth the rollup is unprintable; marker still tracks the
    # surviving bundles so the cell dot reflects what's known.
    product = {"depth_mm": _bundle(246), "height_mm_max": _bundle(28)}
    value, marker = rollup_value(product)
    assert value == ""
    assert marker == "[verified]"


def test_worst_marker_propagates_needs_review():
    product = {
        "width_mm": _bundle(354),
        "depth_mm": _bundle(246, status="needs-review"),
        "height_mm_min": _bundle(20),
        "height_mm_max": _bundle(28),
    }
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_unchanged():
    paths = field_paths({})
    keys = {p for p, _l in paths}
    assert keys == {"width_mm", "depth_mm", "height_mm_min", "height_mm_max"}
