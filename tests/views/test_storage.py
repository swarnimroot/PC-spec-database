"""Tests for the Storage view's Stage 10b rollup.

``N× GenX [+ M× GenY] ; up to <max>TB`` — slot counts bucketed by gen
descending, max always rendered in TB (converted from GB).
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.storage import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def _slot(gen):
    return {"gen": _bundle(gen)} if gen is not None else {"gen": None}


def test_empty_returns_empty_marker():
    value, marker = rollup_value({})
    assert value == ""
    assert marker == "[empty]"


def test_single_gen_two_slots():
    product = {
        "storage_slots": [_slot(5), _slot(5)],
        "storage_max_gb": _bundle(4000),
    }
    value, marker = rollup_value(product)
    assert value == "2× Gen5 ; up to 4TB"
    assert marker == "[verified]"


def test_mixed_gens_sort_descending():
    product = {
        "storage_slots": [_slot(4), _slot(5), _slot(5), _slot(4)],
        "storage_max_gb": _bundle(8000),
    }
    value, _marker = rollup_value(product)
    assert value == "2× Gen5 + 2× Gen4 ; up to 8TB"


def test_no_max_renders_only_slot_clause():
    product = {"storage_slots": [_slot(5)]}
    value, _marker = rollup_value(product)
    assert value == "1× Gen5"


def test_only_max_renders_only_max_clause():
    product = {"storage_max_gb": _bundle(2000)}
    value, _marker = rollup_value(product)
    assert value == "up to 2TB"


def test_max_in_decimal_tb_keeps_decimal():
    product = {"storage_max_gb": _bundle(1500)}
    value, _marker = rollup_value(product)
    assert value == "up to 1.5TB"


def test_null_slot_gen_drops_from_count():
    product = {
        "storage_slots": [_slot(5), _slot(None)],
        "storage_max_gb": _bundle(4000),
    }
    value, _marker = rollup_value(product)
    # Slot with NULL gen contributes nothing to the per-gen counts.
    assert value == "1× Gen5 ; up to 4TB"


def test_worst_marker_propagates_needs_review():
    product = {
        "storage_slots": [_slot(5)],
        "storage_max_gb": _bundle(4000, status="needs-review"),
    }
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_includes_slot_and_max():
    product = {"storage_slots": [_slot(5), _slot(5)]}
    paths = field_paths(product)
    keys = {p for p, _l in paths}
    assert "storage_slots.0.gen" in keys
    assert "storage_slots.1.gen" in keys
    assert "storage_max_gb" in keys
