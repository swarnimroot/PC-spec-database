"""Tests for the Network view's Stage 10b rollup (Wi-Fi standard only).

Ethernet + Bluetooth drop from the rollup but stay on the Edit screen.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.network import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def test_empty_returns_empty_marker():
    value, marker = rollup_value({})
    assert value == ""
    assert marker == "[empty]"


def test_wifi_standard_only():
    product = {
        "wifi_standard": _bundle("Wi-Fi 7"),
        "ethernet": _bundle("2.5GbE"),  # dropped
        "bluetooth_version": _bundle("5.4"),  # dropped
    }
    value, marker = rollup_value(product)
    assert value == "Wi-Fi 7"
    assert marker == "[verified]"


def test_wifi_needs_review_propagates():
    product = {"wifi_standard": _bundle("Wi-Fi 6E", status="needs-review")}
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_unchanged():
    paths = field_paths({})
    keys = {p for p, _l in paths}
    assert "wifi_standard" in keys
    assert "ethernet" in keys
    assert "bluetooth_version" in keys
