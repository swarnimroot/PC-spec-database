"""Tests for the CPU view's Stage 10b architecture-code rollup.

Browse / Compare / Find collapse the CPU section to a single line: each
offering's ``model`` keys into ``cpu_catalog``; the curated
``architecture_code`` value is extracted; values are deduped first-
occurrence-ordered and comma-joined. The cell carries a single worst-
status marker across the per-SKU offering bundles.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.cpu import field_paths, render, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-08T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def _offering(model_value, status="verified"):
    return {"model": _bundle(model_value, status=status)}


def _catalog_row(arch_code=None):
    rec: dict = {"catalog_status": "vouched"}
    if arch_code is not None:
        rec["architecture_code"] = _bundle(arch_code)
    return rec


def test_empty_offerings_renders_empty():
    out = render({"cpu_offerings": None}, {})
    assert out == "CPU: [empty]"
    out = render({"cpu_offerings": []}, {})
    assert out == "CPU: [empty]"
    value, marker = rollup_value({"cpu_offerings": []}, {})
    assert value == ""
    assert marker == "[empty]"


def test_single_sku_rollup():
    product = {"cpu_offerings": [_offering("Core Ultra 9 285H")]}
    catalog = {"Core Ultra 9 285H": _catalog_row(arch_code="ARL-H")}
    value, marker = rollup_value(product, catalog)
    assert value == "ARL-H"
    assert marker == "[verified]"


def test_two_skus_same_arch_dedupe():
    product = {
        "cpu_offerings": [
            _offering("Core Ultra 9 290HX Plus"),
            _offering("Core Ultra 9 275HX"),
        ]
    }
    catalog = {
        "Core Ultra 9 290HX Plus": _catalog_row(arch_code="ARL-HX"),
        "Core Ultra 9 275HX": _catalog_row(arch_code="ARL-HX"),
    }
    value, _marker = rollup_value(product, catalog)
    assert value == "ARL-HX"


def test_two_skus_different_arch_both_appear():
    product = {
        "cpu_offerings": [
            _offering("Core Ultra 9 285H"),
            _offering("Ryzen 9 9955HX"),
        ]
    }
    catalog = {
        "Core Ultra 9 285H": _catalog_row(arch_code="ARL-H"),
        "Ryzen 9 9955HX": _catalog_row(arch_code="FRP"),
    }
    value, _marker = rollup_value(product, catalog)
    assert value == "ARL-H, FRP"


def test_all_uncurated_renders_blank():
    # Catalog rows exist but architecture_code is unpopulated yet.
    product = {
        "cpu_offerings": [
            _offering("Core Ultra 9 285H"),
            _offering("Ryzen 9 9955HX"),
        ]
    }
    catalog = {
        "Core Ultra 9 285H": _catalog_row(arch_code=None),
        "Ryzen 9 9955HX": _catalog_row(arch_code=None),
    }
    value, marker = rollup_value(product, catalog)
    assert value == ""
    # Marker still reflects the offering status, not the catalog status.
    assert marker == "[verified]"


def test_worst_marker_propagates():
    # One verified offering, one needs-review offering → worst (needs-review).
    product = {
        "cpu_offerings": [
            _offering("Core Ultra 9 285H", status="verified"),
            _offering("Ryzen 9 9955HX", status="needs-review"),
        ]
    }
    catalog = {
        "Core Ultra 9 285H": _catalog_row(arch_code="ARL-H"),
        "Ryzen 9 9955HX": _catalog_row(arch_code="FRP"),
    }
    _value, marker = rollup_value(product, catalog)
    assert marker == "[?]"


def test_missing_catalog_row_falls_through():
    product = {"cpu_offerings": [_offering("Unknown CPU")]}
    value, _marker = rollup_value(product, {})
    assert value == ""


def test_render_emits_cpu_heading():
    product = {"cpu_offerings": [_offering("Core Ultra 9 285H")]}
    catalog = {"Core Ultra 9 285H": _catalog_row(arch_code="ARL-H")}
    out = render(product, catalog)
    assert out == "CPU: ARL-H [verified]"


def test_field_paths_still_per_sku():
    # Edit / find-empty contract unchanged in Stage 10b.
    product = {
        "cpu_offerings": [
            _offering("Core Ultra 9 285H"),
            _offering("Ryzen 9 9955HX"),
        ]
    }
    paths = field_paths(product)
    keys = [p for p, _l in paths]
    assert "cpu_offerings.0.model" in keys
    assert "cpu_offerings.1.model" in keys
    assert "cpu_tdp_max" in keys
