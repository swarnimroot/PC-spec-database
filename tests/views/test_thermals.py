"""Tests for the Thermals view (Stage 10b: HIDDEN from visual rollup).

Same shape as Keyboard: ``field_paths`` continues to surface every
scalar so the Edit screen and ``find-empty`` keep working, but the
section is excluded from ``_VISUAL_SECTIONS`` so Browse / Compare /
Find never render a Thermals row.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views import thermals
from competitive_database.views.orchestrator import _VISUAL_SECTIONS


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-20T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def test_thermals_not_in_visible_rollup_registry():
    assert "Thermals" not in _VISUAL_SECTIONS


def test_thermals_module_does_not_expose_rollup_value():
    assert not hasattr(thermals, "rollup_value")
    assert not hasattr(thermals, "rollup_rows")


def test_field_paths_enumerates_all_scalars():
    paths = thermals.field_paths({})
    keys = {p for p, _l in paths}
    expected = {"thermal_design", "thermal_material", "tim", "fan_count"}
    assert expected == keys


def test_render_still_emits_section_heading():
    out = thermals.render({"thermal_design": _bundle("vapor chamber")})
    assert "Thermals:" in out
