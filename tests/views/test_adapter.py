"""Tests for the Adapter view's Stage 10b rollup.

``<wattages list> ; <connector>`` with the wattage list deduped
first-occurrence and the connector clause dropped when NULL.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.adapter import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def _offering(w=None, *, w_status="verified"):
    if w is None:
        return {}
    return {"wattage_w": _bundle(w, status=w_status)}


def test_empty_returns_empty_marker():
    value, marker = rollup_value({})
    assert value == ""
    assert marker == "[empty]"


def test_single_offering_with_connector():
    product = {
        "adapter_offerings": [_offering(w=330)],
        "adapter_connector": _bundle("barrel"),
    }
    value, marker = rollup_value(product)
    assert value == "330W ; barrel"
    assert marker == "[verified]"


def test_multi_offering_dedupes_first_occurrence():
    product = {
        "adapter_offerings": [
            _offering(w=330),
            _offering(w=240),
            _offering(w=330),  # dropped
        ],
        "adapter_connector": _bundle("barrel"),
    }
    value, _marker = rollup_value(product)
    assert value == "330W · 240W ; barrel"


def test_null_connector_drops_trailing_clause():
    product = {"adapter_offerings": [_offering(w=330)]}
    value, _marker = rollup_value(product)
    assert value == "330W"


def test_only_connector_renders_just_connector():
    product = {"adapter_connector": _bundle("USB-C")}
    value, _marker = rollup_value(product)
    assert value == "USB-C"


def test_worst_marker_propagates_needs_review():
    product = {
        "adapter_offerings": [
            _offering(w=330),
            _offering(w=240, w_status="needs-review"),
        ],
        "adapter_connector": _bundle("barrel"),
    }
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_unchanged():
    product = {"adapter_offerings": [_offering(w=330)]}
    paths = field_paths(product)
    keys = {p for p, _l in paths}
    assert "adapter_offerings.0.wattage_w" in keys
    assert "adapter_offerings.0.tier" in keys
    assert "adapter_connector" in keys
