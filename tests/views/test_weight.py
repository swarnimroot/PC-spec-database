"""Tests for the Weight view's Stage 10b rollup.

``<min>-<max> kg`` (both), ``<v> kg min`` / ``<v> kg max`` (one-sided),
empty when both are NULL.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.weight import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def test_empty_returns_empty_marker():
    value, marker = rollup_value({})
    assert value == ""
    assert marker == "[empty]"


def test_both_present_renders_range():
    product = {
        "weight_kg_min": _bundle(2.4),
        "weight_kg_max": _bundle(2.7),
    }
    value, marker = rollup_value(product)
    assert value == "2.4-2.7 kg"
    assert marker == "[verified]"


def test_only_min_renders_min_label():
    product = {"weight_kg_min": _bundle(2.4)}
    value, _marker = rollup_value(product)
    assert value == "2.4 kg min"


def test_only_max_renders_max_label():
    product = {"weight_kg_max": _bundle(2.7)}
    value, _marker = rollup_value(product)
    assert value == "2.7 kg max"


def test_integer_value_trims_decimal():
    product = {"weight_kg_min": _bundle(3.0), "weight_kg_max": _bundle(3.0)}
    value, _marker = rollup_value(product)
    assert value == "3-3 kg"


def test_worst_marker_propagates_needs_review():
    product = {
        "weight_kg_min": _bundle(2.4),
        "weight_kg_max": _bundle(2.7, status="needs-review"),
    }
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_unchanged():
    paths = field_paths({})
    keys = {p for p, _l in paths}
    assert keys == {"weight_kg_min", "weight_kg_max"}
