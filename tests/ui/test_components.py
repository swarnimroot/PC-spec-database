"""Unit tests for UI helper components added in Phase C / Phase D."""

from __future__ import annotations

import pytest

from competitive_database.ui._components import (
    MARKER_LABELS,
    _union_rollup_for_section,
    comparison_grid_html,
    dot_marker,
    identity_strip_html,
    marker_legend_inline_html,
    spec_table_html,
    union_identity_strip_html,
    union_spec_table_html,
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


# ---------------------------------------------------------------------------
# Stage 11 Phase 3 — Union spec view
# ---------------------------------------------------------------------------


def _union_stub_row(
    *,
    year: int,
    panel_hz: str,
    panel_type: str,
    sub_brand: str = "ROG",
    series: str = "Strix",
    status: str = "active",
    segment: str = "gaming",
) -> dict:
    """Minimal loaded-product shape covering the union spec table's needs.

    Carries one display offering whose four rollup-source bundles are
    populated (size / resolution_label / refresh_rate_hz / panel_type)
    plus the four identity-strip leaves. All other offerings/sections
    are None so the rest of the union table fans out to empty rows
    consistently across rows.
    """
    return {
        "product": "Strix G16",
        "year": year,
        "sub_brand": _bundle(sub_brand),
        "series": _bundle(series),
        "status": _bundle(status),
        "segment": _bundle(segment),
        "vendor_full_name": _bundle("ROG Strix G16"),
        "model_code": f"G16-{year}",
        "cpu_offerings": None,
        "boards": None,
        "display_offerings": [
            {
                "size_inches": _bundle("16"),
                "resolution_label": _bundle("QHD+"),
                "refresh_rate_hz": _bundle(panel_hz),
                "panel_type": _bundle(panel_type),
            }
        ],
        "camera_offerings": None,
        "battery_offerings": None,
        "adapter_offerings": None,
        "storage_slots": None,
        "memory": None,
        "storage": None,
        "audio": None,
        "network": None,
        "io": None,
        "thermals": None,
        "dimensions": None,
        "weight": None,
        "design": None,
    }


def test_union_spec_table_n1_byte_identical_to_spec_table():
    row = _union_stub_row(year=2025, panel_hz="240", panel_type="IPS")
    expected = spec_table_html(row)
    actual = union_spec_table_html([row])
    assert actual == expected


def test_union_spec_table_n2_differing_rows_join_with_middle_dot():
    a = _union_stub_row(year=2025, panel_hz="240", panel_type="IPS")
    b = _union_stub_row(year=2026, panel_hz="240", panel_type="OLED")
    out = union_spec_table_html([a, b])
    # Each row's Display rollup is "16" QHD+ 240Hz <panel>"; the union
    # should dedupe-join the two distinct values with " · ". The literal
    # double-quote is HTML-escaped to &quot; in the cell.
    assert "16&quot; QHD+ 240Hz IPS · 16&quot; QHD+ 240Hz OLED" in out


def test_union_spec_table_n2_identical_rows_collapse_via_dedup():
    a = _union_stub_row(year=2025, panel_hz="240", panel_type="IPS")
    b = _union_stub_row(year=2026, panel_hz="240", panel_type="IPS")
    out = union_spec_table_html([a, b])
    # Dedup collapses the two identical rollup strings to one entry —
    # no " · " separator should appear in the Display cell.
    assert "16&quot; QHD+ 240Hz IPS" in out
    assert "16&quot; QHD+ 240Hz IPS · 16&quot; QHD+ 240Hz IPS" not in out


def test_union_rollup_for_section_skips_empty_values_before_dedup():
    # Row A has a real Display rollup; row B has no display offerings,
    # so its rollup_value returns ("", MARKER_EMPTY). The union helper
    # must skip the empty value before deduping rather than letting it
    # surface as a stray empty token. This helper operates on raw
    # display strings (pre-HTML-escape), so the literal `"` stays.
    a = _union_stub_row(year=2025, panel_hz="240", panel_type="IPS")
    b = _union_stub_row(year=2026, panel_hz="240", panel_type="IPS")
    b["display_offerings"] = None
    value, _marker = _union_rollup_for_section(
        "Display", [a, b], cpu_catalog={}, gpu_catalog={}
    )
    assert value == '16" QHD+ 240Hz IPS'
    assert " ·  ·" not in value
    assert not value.startswith(" · ")
    assert not value.endswith(" · ")


def test_union_spec_table_empty_rows_raises_value_error():
    with pytest.raises(ValueError):
        union_spec_table_html([])


def test_union_identity_strip_n1_matches_identity_strip():
    row = _union_stub_row(year=2025, panel_hz="240", panel_type="IPS")
    assert union_identity_strip_html([row]) == identity_strip_html(row)


def test_union_identity_strip_n2_year_cell_lists_ascending_years():
    a = _union_stub_row(year=2026, panel_hz="240", panel_type="OLED")
    b = _union_stub_row(year=2025, panel_hz="240", panel_type="IPS")
    out = union_identity_strip_html([a, b])
    # Sorted ascending, comma-space joined.
    assert "2025, 2026" in out
    assert "YEAR" in out


# ---------------------------------------------------------------------------
# Stage 11 Phase 3 Step 4: brand_series_product_picker helper
# ---------------------------------------------------------------------------


def test_series_sentinel_to_none_converts_em_dash():
    from competitive_database.ui._components import _series_sentinel_to_none

    assert _series_sentinel_to_none("—") is None


def test_series_sentinel_to_none_passes_through_real_series():
    from competitive_database.ui._components import _series_sentinel_to_none

    assert _series_sentinel_to_none("Legion Pro") == "Legion Pro"
    assert _series_sentinel_to_none("ROG Strix") == "ROG Strix"
