"""Tests for the Battery view's Stage 10b rollup.

Per-offering ``<Wh>Wh <cells>-cell`` joined by ``" · "``; cells optional.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.battery import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def _offering(wh=None, cells=None, *, wh_status="verified"):
    out: dict = {}
    if wh is not None:
        out["wattage_wh"] = _bundle(wh, status=wh_status)
    if cells is not None:
        out["cell_count"] = _bundle(cells)
    return out


def test_empty_offerings_returns_empty():
    value, marker = rollup_value({})
    assert value == ""
    assert marker == "[empty]"


def test_single_offering_full():
    product = {"battery_offerings": [_offering(wh=99, cells=6)]}
    value, marker = rollup_value(product)
    assert value == "99Wh 6-cell"
    assert marker == "[verified]"


def test_single_offering_null_cells_just_wh():
    product = {"battery_offerings": [_offering(wh=99)]}
    value, _marker = rollup_value(product)
    assert value == "99Wh"


def test_multi_offering_dot_join_deduped():
    product = {
        "battery_offerings": [
            _offering(wh=99, cells=6),
            _offering(wh=70, cells=4),
            _offering(wh=99, cells=6),  # duplicate dropped
        ]
    }
    value, _marker = rollup_value(product)
    assert value == "99Wh 6-cell · 70Wh 4-cell"


def test_wh_trims_trailing_zero():
    product = {"battery_offerings": [_offering(wh=99.0, cells=6)]}
    value, _marker = rollup_value(product)
    assert value == "99Wh 6-cell"


def test_worst_marker_propagates_needs_review():
    product = {
        "battery_offerings": [
            _offering(wh=99, cells=6),
            _offering(wh=70, cells=4, wh_status="needs-review"),
        ]
    }
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_unchanged():
    product = {"battery_offerings": [_offering(wh=99, cells=6)]}
    paths = field_paths(product)
    keys = {p for p, _l in paths}
    assert "battery_offerings.0.wattage_wh" in keys
    assert "battery_offerings.0.cell_count" in keys
    assert "battery_offerings.0.tier" in keys
