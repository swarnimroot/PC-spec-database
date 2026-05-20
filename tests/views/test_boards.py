"""Tests for the Graphics view's Stage 10b rollup.

Browse / Compare / Find collapse the GPU section to a single line: per
GPU, NVIDIA contributes the catalog ``board`` value (MB1 / MB2 / MB3);
AMD / Intel contribute the brand name. The cell shows deduped,
comma-joined values plus a single worst-status marker across the
per-GPU offering bundles.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.boards import field_paths, render, rollup_value


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-08T00:00:00Z"
SCRAPER_ID = "test"


def _bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def _board(label_value, gpu_models, *, gpu_status="verified", label_status="verified"):
    return {
        "label": _bundle(label_value, status=label_status),
        "tgp_max": None,
        "tpp_max": None,
        "gpus": [_bundle(m, status=gpu_status) for m in gpu_models],
    }


def _catalog_row(brand=None, board=None, gpu_class=None):
    rec: dict = {"catalog_status": "vouched"}
    if brand is not None:
        rec["brand"] = _bundle(brand)
    if board is not None:
        rec["board"] = _bundle(board)
    if gpu_class is not None:
        rec["gpu_class"] = _bundle(gpu_class)
    return rec


def test_empty_boards_renders_empty_marker():
    out = render({"boards": None}, {})
    assert out == "Graphics: [empty]"
    out = render({"boards": []}, {})
    assert out == "Graphics: [empty]"


def test_single_nvidia_gpu_rollup():
    product = {"boards": [_board("MB1", ["RTX 5080"])]}
    catalog = {"RTX 5080": _catalog_row(brand="NVIDIA", board="MB1")}
    value, marker = rollup_value(product, catalog)
    assert value == "MB1"
    assert marker == "[verified]"


def test_two_nvidia_boards_dedupe_to_same_tier():
    # Two SKUs on one board, both MB1-tier GPUs.
    product = {"boards": [_board("MB1", ["RTX 5070 Ti", "RTX 5090"])]}
    catalog = {
        "RTX 5070 Ti": _catalog_row(brand="NVIDIA", board="MB1"),
        "RTX 5090": _catalog_row(brand="NVIDIA", board="MB1"),
    }
    value, _marker = rollup_value(product, catalog)
    assert value == "MB1"


def test_mixed_tiers_show_both():
    product = {
        "boards": [
            _board("MB1", ["RTX 5080"]),
            _board("MB2", ["RTX 5070"]),
        ]
    }
    catalog = {
        "RTX 5080": _catalog_row(brand="NVIDIA", board="MB1"),
        "RTX 5070": _catalog_row(brand="NVIDIA", board="MB2"),
    }
    value, _marker = rollup_value(product, catalog)
    assert value == "MB1, MB2"


def test_amd_gpu_shows_brand_not_board():
    product = {"boards": [_board("MB1", ["Radeon RX 7700S"])]}
    catalog = {"Radeon RX 7700S": _catalog_row(brand="AMD", board=None)}
    value, _marker = rollup_value(product, catalog)
    assert value == "AMD"


def test_intel_gpu_shows_brand():
    product = {"boards": [_board("MB1", ["Arc A370M"])]}
    catalog = {"Arc A370M": _catalog_row(brand="Intel")}
    value, _marker = rollup_value(product, catalog)
    assert value == "Intel"


def test_nvidia_plus_amd_combine():
    product = {
        "boards": [
            _board("MB1", ["RTX 5080", "Radeon RX 7900M"]),
        ]
    }
    catalog = {
        "RTX 5080": _catalog_row(brand="NVIDIA", board="MB1"),
        "Radeon RX 7900M": _catalog_row(brand="AMD"),
    }
    value, _marker = rollup_value(product, catalog)
    assert value == "MB1, AMD"


def test_uncurated_nvidia_drops_from_rollup():
    # Catalog row exists but ``board`` is unpopulated (curation not yet
    # filled). Stage 10b: render is not gated on curation — value omits
    # that GPU, marker still reflects the offering status.
    product = {"boards": [_board("MB1", ["RTX 5080", "RTX 5070"])]}
    catalog = {
        "RTX 5080": _catalog_row(brand="NVIDIA", board="MB1"),
        "RTX 5070": _catalog_row(brand="NVIDIA", board=None),
    }
    value, marker = rollup_value(product, catalog)
    assert value == "MB1"
    assert marker == "[verified]"


def test_worst_marker_propagates_needs_review():
    # One verified GPU, one needs-review GPU → cell marker is worst (needs-review).
    product = {
        "boards": [
            {
                "label": _bundle("MB1"),
                "tgp_max": None,
                "tpp_max": None,
                "gpus": [
                    _bundle("RTX 5080", status="verified"),
                    _bundle("RTX 5090", status="needs-review"),
                ],
            }
        ]
    }
    catalog = {
        "RTX 5080": _catalog_row(brand="NVIDIA", board="MB1"),
        "RTX 5090": _catalog_row(brand="NVIDIA", board="MB1"),
    }
    _value, marker = rollup_value(product, catalog)
    assert marker == "[?]"


def test_missing_catalog_row_falls_through_to_blank():
    product = {"boards": [_board("MB1", ["RTX 5080"])]}
    value, _marker = rollup_value(product, {})  # empty catalog
    assert value == ""


def test_render_emits_graphics_heading():
    product = {"boards": [_board("MB1", ["RTX 5080"])]}
    catalog = {"RTX 5080": _catalog_row(brand="NVIDIA", board="MB1")}
    out = render(product, catalog)
    assert out.startswith("Graphics:")
    assert "MB1" in out


def test_integrated_gpu_dropped_from_rollup():
    # AMD Radeon 8050S Graphics curated as integrated → rollup omits it
    # (would otherwise contribute "AMD"). Marker still tracks the
    # per-GPU offering status.
    product = {"boards": [_board("MB1", ["AMD Radeon 8050S Graphics"])]}
    catalog = {
        "AMD Radeon 8050S Graphics": _catalog_row(
            brand="AMD", gpu_class="integrated"
        ),
    }
    value, marker = rollup_value(product, catalog)
    assert value == ""
    assert marker == "[verified]"


def test_integrated_alongside_discrete_only_shows_discrete():
    product = {
        "boards": [
            _board(
                "MB1",
                ["AMD Radeon 8050S Graphics", "RTX 5080"],
            ),
        ]
    }
    catalog = {
        "AMD Radeon 8050S Graphics": _catalog_row(
            brand="AMD", gpu_class="integrated"
        ),
        "RTX 5080": _catalog_row(
            brand="NVIDIA", board="MB1", gpu_class="discrete"
        ),
    }
    value, _marker = rollup_value(product, catalog)
    assert value == "MB1"


def test_null_gpu_class_treated_as_discrete():
    # No gpu_class on the catalog row (uncurated) → existing behavior
    # preserved: AMD/Intel surface as the brand name, NVIDIA surfaces
    # as the board value.
    product = {"boards": [_board("MB1", ["Radeon RX 7900M"])]}
    catalog = {"Radeon RX 7900M": _catalog_row(brand="AMD")}
    value, _marker = rollup_value(product, catalog)
    assert value == "AMD"


def test_field_paths_excludes_label_and_includes_arch_marker():
    # Edit / find-empty contract unchanged in Stage 10b.
    product = {"boards": [_board("MB1", ["RTX 5080"]), _board("MB2", ["RTX 5070"])]}
    paths = field_paths(product)
    keys = [p for p, _l in paths]
    assert "boards.0.label" not in keys
    assert "boards.0.tgp_max" in keys
    assert "boards.0.tpp_max" in keys
    assert "boards.0.arch_marker" in keys
    assert "boards.1.arch_marker" in keys
