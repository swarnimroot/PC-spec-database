"""Tests for the Memory view's Stage 10b rollup.

``<type> <speed>MT/s · <slots> slots ; up to <max>GB`` with the
soldered-RAM (``slots == 0``) special case.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.memory import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def test_empty_returns_empty_marker():
    value, marker = rollup_value({})
    assert value == ""
    assert marker == "[empty]"


def test_full_quad_renders_canonical_shape():
    product = {
        "memory_type": _bundle("DDR5"),
        "memory_speed_mts": _bundle(5600),
        "memory_slots": _bundle(2),
        "memory_max_gb": _bundle(64),
        "memory_overclocking": _bundle(True),
    }
    value, marker = rollup_value(product)
    assert value == "DDR5 5600MT/s · 2 slots ; up to 64GB"
    assert marker == "[verified]"


def test_zero_slots_renders_soldered():
    product = {
        "memory_type": _bundle("LPDDR5X"),
        "memory_speed_mts": _bundle(7500),
        "memory_slots": _bundle(0),
        "memory_max_gb": _bundle(32),
    }
    value, _marker = rollup_value(product)
    assert value == "LPDDR5X 7500MT/s · soldered ; up to 32GB"


def test_missing_type_drops_token():
    product = {
        "memory_speed_mts": _bundle(5600),
        "memory_slots": _bundle(2),
        "memory_max_gb": _bundle(64),
    }
    value, _marker = rollup_value(product)
    assert value == "5600MT/s · 2 slots ; up to 64GB"


def test_only_max_renders_clause():
    product = {"memory_max_gb": _bundle(64)}
    value, _marker = rollup_value(product)
    assert value == "up to 64GB"


def test_worst_marker_propagates_needs_review():
    product = {
        "memory_type": _bundle("DDR5"),
        "memory_speed_mts": _bundle(5600, status="needs-review"),
        "memory_slots": _bundle(2),
        "memory_max_gb": _bundle(64),
    }
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_unchanged():
    paths = field_paths({})
    keys = {p for p, _l in paths}
    assert "memory_type" in keys
    assert "memory_max_gb" in keys
    assert "memory_speed_mts" in keys
    assert "memory_slots" in keys
    assert "memory_overclocking" in keys
