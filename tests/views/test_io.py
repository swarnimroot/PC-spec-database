"""Tests for the I/O view's Stage 10b multi-row rollup.

I/O is the only multi-row rollup: ``rollup_rows`` returns four sub-rows
(USB / HDMI / SD card / Audio jack) under one section header. Each
sub-row's marker tracks only that sub-row's source bundles. Zero-count
USB tokens drop from the USB sub-row.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.io import field_paths, rollup_rows


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def test_empty_product_renders_four_dash_rows():
    rows = rollup_rows({})
    assert len(rows) == 4
    labels = [r[0] for r in rows]
    assert labels == ["USB", "HDMI", "SD card", "Audio jack"]
    for _label, value, marker in rows:
        assert value == "—"
        assert marker == "[empty]"


def test_usb_row_counts_three_types():
    product = {
        "usbc_thunderbolt_count": _bundle(2),
        "usbc_thunderbolt_version": _bundle("4"),
        "usbc_non_thunderbolt_count": _bundle(1),
        "usbc_non_thunderbolt_version": _bundle("3.2"),
        "usba_count": _bundle(2),
        "usba_version": _bundle("3.2"),
    }
    rows = rollup_rows(product)
    label, value, marker = rows[0]
    assert label == "USB"
    # No versions in the USB sub-row — just counts × type tokens.
    assert value == "2× TB · 1× USB-C · 2× USB-A"
    assert marker == "[verified]"


def test_usb_zero_count_tokens_dropped():
    product = {
        "usbc_thunderbolt_count": _bundle(0),  # dropped
        "usbc_non_thunderbolt_count": _bundle(2),
        "usba_count": _bundle(0),  # dropped
    }
    rows = rollup_rows(product)
    _label, value, _marker = rows[0]
    assert value == "2× USB-C"


def test_hdmi_row():
    product = {"hdmi_count": _bundle(1), "hdmi_version": _bundle("2.1")}
    rows = rollup_rows(product)
    label, value, marker = rows[1]
    assert label == "HDMI"
    assert value == "1× 2.1"
    assert marker == "[verified]"


def test_sd_card_row_uses_literal_value():
    product = {"sd_card": _bundle("microSD")}
    rows = rollup_rows(product)
    label, value, marker = rows[2]
    assert label == "SD card"
    assert value == "microSD"
    assert marker == "[verified]"


def test_audio_jack_row_uses_literal_value():
    product = {"audio_jack": _bundle("3.5mm combo")}
    rows = rollup_rows(product)
    label, value, marker = rows[3]
    assert label == "Audio jack"
    assert value == "3.5mm combo"
    assert marker == "[verified]"


def test_per_sub_row_marker_independence():
    # USB sub-row should be needs-review, HDMI should stay verified.
    product = {
        "usbc_thunderbolt_count": _bundle(2, status="needs-review"),
        "hdmi_count": _bundle(1),
        "hdmi_version": _bundle("2.1"),
    }
    rows = rollup_rows(product)
    _usb_label, _usb_value, usb_marker = rows[0]
    _hdmi_label, _hdmi_value, hdmi_marker = rows[1]
    assert usb_marker == "[?]"
    assert hdmi_marker == "[verified]"


def test_per_sub_row_null_handling_isolated():
    # SD card NULL → that row dashes; other rows reflect their own data.
    product = {"hdmi_count": _bundle(1), "hdmi_version": _bundle("2.1")}
    rows = rollup_rows(product)
    _label, value, marker = rows[2]
    assert value == "—"
    assert marker == "[empty]"


def test_field_paths_unchanged():
    paths = field_paths({})
    keys = {p for p, _l in paths}
    expected = {
        "usbc_thunderbolt_count",
        "usbc_thunderbolt_version",
        "usbc_non_thunderbolt_count",
        "usbc_non_thunderbolt_version",
        "usba_count",
        "usba_version",
        "hdmi_count",
        "hdmi_version",
        "sd_card",
        "sd_card_speed",
        "audio_jack",
    }
    assert expected == keys
