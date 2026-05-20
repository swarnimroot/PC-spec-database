"""Tests for the Camera view's Stage 10b rollup (resolution-only)."""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.camera import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def _offering(res=None, *, res_status="verified"):
    out: dict = {}
    if res is not None:
        out["resolution"] = _bundle(res, status=res_status)
    return out


def test_empty_offerings_returns_empty():
    value, marker = rollup_value({})
    assert value == ""
    assert marker == "[empty]"


def test_single_offering():
    product = {"camera_offerings": [_offering(res="1080p")]}
    value, marker = rollup_value(product)
    assert value == "1080p"
    assert marker == "[verified]"


def test_multi_offering_dedupes_first_occurrence():
    product = {
        "camera_offerings": [
            _offering(res="1080p"),
            _offering(res="720p"),
            _offering(res="1080p"),  # dropped
        ]
    }
    value, _marker = rollup_value(product)
    assert value == "1080p · 720p"


def test_null_resolution_drops_from_value_but_other_marker_dominates():
    # Per worst_marker precedence, an empty bundle alongside a verified
    # bundle leaves the cell marker at the verified level (empty isn't in
    # the precedence ladder — it sorts above only the truly-blank case).
    product = {
        "camera_offerings": [
            _offering(res="1080p"),
            _offering(),  # NULL resolution
        ]
    }
    value, marker = rollup_value(product)
    assert value == "1080p"
    assert marker == "[verified]"


def test_worst_marker_propagates_needs_review():
    product = {
        "camera_offerings": [
            _offering(res="1080p"),
            _offering(res="720p", res_status="needs-review"),
        ]
    }
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_includes_all_per_offering_leaves():
    product = {"camera_offerings": [_offering(res="1080p")]}
    paths = field_paths(product)
    keys = {p for p, _l in paths}
    expected = {
        "camera_offerings.0.resolution",
        "camera_offerings.0.ir_supported",
        "camera_offerings.0.privacy_shutter",
        "camera_offerings.0.tier",
    }
    assert expected.issubset(keys)
