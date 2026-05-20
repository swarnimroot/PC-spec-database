"""Tests for the Audio view's Stage 10b rollup.

``<n>-speaker <tuning_brand>`` — either side optional. ``has_subwoofer``
drops from the rollup but stays on the Edit screen.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.audio import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def test_empty_returns_empty_marker():
    value, marker = rollup_value({})
    assert value == ""
    assert marker == "[empty]"


def test_full_renders_canonical_shape():
    product = {
        "speaker_count": _bundle(4),
        "tuning_brand": _bundle("Dolby Atmos"),
        "has_subwoofer": _bundle(True),  # dropped from rollup
    }
    value, marker = rollup_value(product)
    assert value == "4-speaker Dolby Atmos"
    assert marker == "[verified]"


def test_only_count():
    product = {"speaker_count": _bundle(2)}
    value, _marker = rollup_value(product)
    assert value == "2-speaker"


def test_only_tuning_brand():
    product = {"tuning_brand": _bundle("Bang & Olufsen")}
    value, _marker = rollup_value(product)
    assert value == "Bang & Olufsen"


def test_worst_marker_propagates_needs_review():
    product = {
        "speaker_count": _bundle(4),
        "tuning_brand": _bundle("Dolby", status="needs-review"),
    }
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_unchanged():
    paths = field_paths({})
    keys = {p for p, _l in paths}
    assert "speaker_count" in keys
    assert "tuning_brand" in keys
    assert "has_subwoofer" in keys
