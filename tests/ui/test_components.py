"""Unit tests for UI helper components added in Phase C / Phase D."""

from __future__ import annotations

from competitive_database.ui._components import (
    MARKER_LABELS,
    comparison_grid_html,
    dot_marker,
    marker_legend_inline_html,
)
from competitive_database.ui.theme import PALETTE
from competitive_database.views.formatting import MARKER_VERIFIED


def _bundle(value: str) -> dict:
    return {
        "value": value,
        "source_url": "https://example.test/",
        "captured_at": "2026-05-19T00:00:00+00:00",
        "scraper_id": "test",
        "status": "verified",
    }


def _stub_product(model_code: str, year: int, name: str, refresh: str) -> dict:
    """Minimal loaded-product shape covering the comparison grid's needs.

    Carries ``vendor_full_name`` for the friendly header and one display
    offering with a ``refresh_rate_hz`` bundle so divergence checks can
    target a known section/path combo.
    """
    return {
        "model_code": model_code,
        "year": year,
        "vendor_full_name": _bundle(name),
        "cpu_offerings": [{"model": _bundle("Core Ultra 9 285HX")}],
        "boards": None,
        "memory": None,
        "storage": None,
        "display_offerings": [{"refresh_rate_hz": _bundle(refresh)}],
        "keyboard": None,
        "camera": None,
        "audio": None,
        "network": None,
        "io": None,
        "battery": None,
        "adapter": None,
        "thermals": None,
        "dimensions": None,
        "weight": None,
        "design": None,
    }


def test_dot_marker_uses_verified_color():
    html_out = dot_marker(MARKER_VERIFIED)
    verified_color = PALETTE["markers"]["verified"]  # type: ignore[index]
    assert verified_color in html_out
    assert "cd-dot" in html_out
    assert "●" in html_out


def test_marker_legend_inline_has_expected_labels():
    html_out = marker_legend_inline_html()
    assert "verified" in html_out
    assert "needs rev." in html_out
    assert "manual" in html_out
    assert "vendor n/p" in html_out


def test_marker_labels_covers_canonical_tokens():
    assert MARKER_LABELS[MARKER_VERIFIED] == "verified"


def test_comparison_grid_renders_with_two_products():
    a = _stub_product("AAA", 2026, "ROG Strix G16", "240")
    b = _stub_product("BBB", 2026, "Legion Pro 7", "240")
    html_out = comparison_grid_html([a, b])
    assert "ROG Strix G16 · 2026" in html_out
    assert "Legion Pro 7 · 2026" in html_out
    assert 'class="cd-cmp"' in html_out


def test_comparison_grid_divergence_majority_rule():
    # Three products: two match on refresh rate, one differs. Strict
    # majority kicks in (count=2 > 3/2), so only the odd-one-out should
    # carry the divergence class.
    a = _stub_product("AAA", 2026, "ROG Strix G16", "240")
    b = _stub_product("BBB", 2026, "Legion Pro 7", "240")
    c = _stub_product("CCC", 2026, "Alienware m18", "165")
    html_out = comparison_grid_html([a, b, c])
    # The class string appears once in the CSS selector definition. With
    # only refresh-rate diverging across the three products, exactly one
    # cell carries the class, so total occurrences = 2 (CSS + cell).
    assert html_out.count("cd-cmp__value--diverges") == 2
    # The diverging cell carries "165"; locate the cell occurrence (not
    # the CSS selector) and confirm "165" appears within its tag window.
    cell_idx = html_out.rfind('class="cd-cmp__value cd-cmp__value--diverges"')
    assert cell_idx != -1
    assert "165" in html_out[cell_idx : cell_idx + 200]
    # The two consensus cells must NOT carry the diverges class — verify
    # by checking that "240" appears in plain-class cells.
    assert 'class="cd-cmp__value">' in html_out
