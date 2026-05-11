"""Tests for the boards view's per-product ordinal renumbering (T7.0c).

Bridge stores tier labels (MB1/MB2/MB3) for cross-tile merge logic; the
view layer renames them to per-product ordinals at render time, sorted
tier-ascending with unmapped (label.value=None) entries last.
"""

from __future__ import annotations

from competitive_database.db.helpers import make_scraped_bundle
from competitive_database.views.boards import field_paths, render


SOURCE_URL = "https://example.com/spec"
CAPTURED_AT = "2026-05-08T00:00:00Z"
SCRAPER_ID = "test"


def _label_bundle(value, status="verified"):
    return make_scraped_bundle(value, SOURCE_URL, CAPTURED_AT, SCRAPER_ID, status=status)


def _board(label_value, gpus=None, label_status="verified"):
    return {
        "label": _label_bundle(label_value, status=label_status),
        "tgp_max": None,
        "tpp_max": None,
        "gpus": gpus or [],
    }


def test_empty_boards_renders_empty_marker():
    out = render({"boards": None}, {})
    assert out == "Boards: [empty]"
    out = render({"boards": []}, {})
    assert out == "Boards: [empty]"


def test_single_board_renders_mb1():
    product = {"boards": [_board("MB1")]}
    out = render(product, {})
    assert "label: MB1 [verified]" in out
    # No "Board N" header for a single offering.
    assert "Board 1" not in out


def test_three_boards_identity_renumber():
    product = {
        "boards": [
            _board("MB1"),
            _board("MB2"),
            _board("MB3"),
        ]
    }
    out = render(product, {})
    lines = out.splitlines()
    label_lines = [ln.strip() for ln in lines if ln.strip().startswith("label:")]
    assert label_lines == [
        "label: MB1 [verified]",
        "label: MB2 [verified]",
        "label: MB3 [verified]",
    ]


def test_gap_in_tiers_renumbers_to_mb1_mb2():
    # The ac16251 case from Session 13: vendor only ships MB2 + MB3 SKUs.
    # Render should display them as MB1 + MB2.
    product = {
        "boards": [
            _board("MB2"),
            _board("MB3"),
        ]
    }
    out = render(product, {})
    label_lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("label:")]
    assert label_lines == [
        "label: MB1 [verified]",
        "label: MB2 [verified]",
    ]


def test_bridge_emission_out_of_tier_order_is_sorted():
    # _merge_boards preserves tile-iteration order, which can land
    # higher-tier boards after lower-tier ones. The view sorts before
    # renumbering, so the lowest-numbered MB always renders first.
    product = {
        "boards": [
            _board("MB3"),
            _board("MB1"),
            _board("MB2"),
        ]
    }
    out = render(product, {})
    label_lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("label:")]
    assert label_lines == [
        "label: MB1 [verified]",
        "label: MB2 [verified]",
        "label: MB3 [verified]",
    ]


def test_field_paths_excludes_label():
    # T7.0e: label is synthesized per-product at render time (MB{ordinal}),
    # so manual-edit must not expose it as an editable cell — any edit
    # would be silently masked by the view.
    product = {
        "boards": [
            _board("MB1"),
            _board("MB2"),
        ]
    }
    paths = field_paths(product)
    keys = [path for path, _label in paths]
    assert "boards.0.label" not in keys
    assert "boards.1.label" not in keys
    # Other scalar leaves still editable.
    assert "boards.0.tgp_max" in keys
    assert "boards.0.tpp_max" in keys
    assert "boards.1.tgp_max" in keys


def test_field_paths_includes_arch_marker():
    # User Decision 2: arch_marker is hand-editable via manual-edit, so
    # field_paths() must expose it. (Complement of the label exclusion.)
    product = {
        "boards": [
            _board("MB1"),
            _board("MB2"),
        ]
    }
    paths = field_paths(product)
    keys = [path for path, _label in paths]
    assert "boards.0.arch_marker" in keys
    assert "boards.1.arch_marker" in keys


def test_render_surfaces_arch_marker():
    # M3 stamps arch_marker on each board so users can tell Intel and AMD
    # variants apart when they inspect-product. The render must surface
    # it. Boards without arch_marker (non-Lenovo / unparseable) skip the
    # line entirely instead of printing None.
    intel_board = _board("MB1")
    intel_board["arch_marker"] = "intel-rtx"
    amd_board = _board("MB2")
    amd_board["arch_marker"] = "amd-radeon"
    product = {"boards": [intel_board, amd_board]}
    out = render(product, {})
    assert "intel-rtx" in out
    assert "amd-radeon" in out
    # And a non-Lenovo board (no arch_marker key) doesn't print a stray
    # arch line.
    product_no_arch = {"boards": [_board("MB1")]}
    out_no_arch = render(product_no_arch, {})
    assert "arch:" not in out_no_arch
    assert "None" not in out_no_arch


def test_unmapped_board_does_not_consume_ordinal():
    # An unmapped GPU emits a board with label.value=None and
    # status=needs-review. It sorts last and keeps the default leaf
    # rendering; mapped boards renumber as MB1, MB2 around it.
    product = {
        "boards": [
            _board("MB2"),
            _board(None, label_status="needs-review"),
            _board("MB1"),
        ]
    }
    out = render(product, {})
    label_lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("label:")]
    assert label_lines == [
        "label: MB1 [verified]",
        "label: MB2 [verified]",
        "label:  [?]",
    ]
