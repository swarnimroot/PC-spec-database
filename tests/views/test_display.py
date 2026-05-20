"""Tests for the Display view's Stage 10b rollup.

Browse / Compare / Find collapse the Display section to one rolled-up
line per product: ``<size>" <res_label> <hz>Hz <panel>`` (single
offering) or ``<size>" tri_a · tri_b ...`` (multi, sizes hoisted when
shared). Per-SKU detail (nits, HDR, color gamuts, response, VRR,
anti-glare, tier) stays in the DB and on Edit but drops from the
rollup.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.display import field_paths, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def _offering(size=None, panel=None, res_label=None, hz=None, *, hz_status="verified"):
    out: dict = {}
    if size is not None:
        out["size_inches"] = _bundle(size)
    if panel is not None:
        out["panel_type"] = _bundle(panel)
    if res_label is not None:
        out["resolution_label"] = _bundle(res_label)
    if hz is not None:
        out["refresh_rate_hz"] = _bundle(hz, status=hz_status)
    return out


def test_empty_offerings_returns_empty():
    value, marker = rollup_value({"display_offerings": None})
    assert value == ""
    assert marker == "[empty]"
    value, marker = rollup_value({"display_offerings": []})
    assert value == ""
    assert marker == "[empty]"


def test_single_offering_size_size_then_res_hz_panel():
    product = {
        "display_offerings": [
            _offering(size=16, res_label="2.5K", hz=240, panel="IPS"),
        ]
    }
    value, marker = rollup_value(product)
    assert value == '16" 2.5K 240Hz IPS'
    assert marker == "[verified]"


def test_single_offering_size_trims_trailing_zero():
    product = {
        "display_offerings": [
            _offering(size=16.0, res_label="QHD", hz=165, panel="OLED"),
        ]
    }
    value, _marker = rollup_value(product)
    assert value == '16" QHD 165Hz OLED'


def test_multi_offering_same_size_hoists_size():
    product = {
        "display_offerings": [
            _offering(size=16, res_label="2.5K", hz=240, panel="IPS"),
            _offering(size=16, res_label="2.5K", hz=165, panel="OLED"),
            _offering(size=16, res_label="3.2K", hz=240, panel="IPS"),
        ]
    }
    value, _marker = rollup_value(product)
    assert value == '16" 2.5K 240Hz IPS · 2.5K 165Hz OLED · 3.2K 240Hz IPS'


def test_multi_offering_different_sizes_keep_size_per_triple():
    product = {
        "display_offerings": [
            _offering(size=16, res_label="2.5K", hz=240, panel="IPS"),
            _offering(size=18, res_label="QHD", hz=165, panel="OLED"),
        ]
    }
    value, _marker = rollup_value(product)
    assert value == '16" 2.5K 240Hz IPS · 18" QHD 165Hz OLED'


def test_multi_offering_dedupe_first_occurrence_ordered():
    product = {
        "display_offerings": [
            _offering(size=16, res_label="2.5K", hz=240, panel="IPS"),
            _offering(size=16, res_label="2.5K", hz=240, panel="IPS"),
        ]
    }
    value, _marker = rollup_value(product)
    assert value == '16" 2.5K 240Hz IPS'


def test_null_panel_drops_token():
    product = {
        "display_offerings": [
            _offering(size=16, res_label="2.5K", hz=240),  # no panel
        ]
    }
    value, _marker = rollup_value(product)
    assert value == '16" 2.5K 240Hz'


def test_all_rollup_leaves_null_returns_empty_string():
    # One empty offering: every rollup-source bundle is None → value is
    # blank. Marker falls back to needs-review per worst_marker's
    # behavior for a list of bundles that all returned MARKER_EMPTY
    # (empty isn't in the precedence ladder, so the fallback fires).
    product = {"display_offerings": [{}]}
    value, marker = rollup_value(product)
    assert value == ""
    assert marker == "[?]"


def test_worst_marker_propagates_needs_review():
    product = {
        "display_offerings": [
            _offering(size=16, res_label="2.5K", hz=240, panel="IPS"),
            _offering(
                size=16,
                res_label="QHD",
                hz=165,
                panel="OLED",
                hz_status="needs-review",
            ),
        ]
    }
    _value, marker = rollup_value(product)
    assert marker == "[?]"


def test_field_paths_enumerates_all_per_offering_leaves():
    # Edit / find-empty contract: every per-offering bundle stays
    # surfaced via field_paths even though most leaves drop from the rollup.
    product = {
        "display_offerings": [
            _offering(size=16, res_label="2.5K", hz=240, panel="IPS"),
        ]
    }
    paths = field_paths(product)
    keys = {p for p, _l in paths}
    expected = {
        "display_offerings.0.size_inches",
        "display_offerings.0.panel_type",
        "display_offerings.0.resolution_label",
        "display_offerings.0.resolution_pixels",
        "display_offerings.0.refresh_rate_hz",
        "display_offerings.0.nits_peak",
        "display_offerings.0.hdr_certification",
        "display_offerings.0.dci_p3_pct",
        "display_offerings.0.srgb_pct",
        "display_offerings.0.response_time_ms",
        "display_offerings.0.vrr",
        "display_offerings.0.anti_glare",
        "display_offerings.0.tier",
    }
    assert expected.issubset(keys)
