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


# ---------------------------------------------------------------------------
# Stage 11 Phase 6 — Echo-parent display rule
# ---------------------------------------------------------------------------


def _echo_row(
    *,
    brand: str | None = "ASUS",
    sub_brand: str | None = "ROG",
    series: str | None = "Strix",
    status: str = "active",
    segment: str = "gaming",
) -> dict:
    """Minimal product shape for echo-parent tests.

    Each identity leaf is either a real ``_bundle(value)`` or ``None``
    so the helper sees the same shape it would on a row loaded from the
    DB with NULL identity columns.
    """
    return {
        "brand": _bundle(brand) if brand is not None else None,
        "sub_brand": _bundle(sub_brand) if sub_brand is not None else None,
        "series": _bundle(series) if series is not None else None,
        "status": _bundle(status),
        "segment": _bundle(segment),
    }


def test_echo_parent_helper_sub_brand_null_returns_brand_italic():
    from competitive_database.ui._components import _echo_parent_for_leaf

    row = _echo_row(sub_brand=None)
    value, is_echo = _echo_parent_for_leaf("sub_brand", row)
    assert value == "ASUS"
    assert is_echo is True


def test_echo_parent_helper_series_null_with_sub_brand_returns_sub_brand():
    from competitive_database.ui._components import _echo_parent_for_leaf

    row = _echo_row(series=None)
    value, is_echo = _echo_parent_for_leaf("series", row)
    assert value == "ROG"
    assert is_echo is True


def test_echo_parent_helper_series_null_no_sub_brand_returns_brand():
    from competitive_database.ui._components import _echo_parent_for_leaf

    # Defensive: current DB has zero rows with sub_brand null + series
    # null, but the chain must still walk to brand if it ever happens.
    row = _echo_row(sub_brand=None, series=None)
    value, is_echo = _echo_parent_for_leaf("series", row)
    assert value == "ASUS"
    assert is_echo is True


def test_echo_parent_helper_populated_returns_own_value_no_echo():
    from competitive_database.ui._components import _echo_parent_for_leaf

    row = _echo_row()
    value, is_echo = _echo_parent_for_leaf("series", row)
    assert value == "Strix"
    assert is_echo is False


def test_echo_parent_helper_empty_chain_returns_none():
    from competitive_database.ui._components import _echo_parent_for_leaf

    row = _echo_row(brand=None, sub_brand=None, series=None)
    value, is_echo = _echo_parent_for_leaf("series", row)
    assert value is None
    assert is_echo is False


def test_picker_placeholder_sentinel_never_routes_through_echo_helper():
    # The "—" picker sentinel (from list_series_options) maps back to
    # None via _series_sentinel_to_none BEFORE any echo logic runs.
    # _echo_parent_for_leaf operates on bundle dicts, not raw strings,
    # so passing the sentinel cannot accidentally be interpreted as a
    # bundle value. This test locks that boundary.
    from competitive_database.ui._components import (
        _PLACEHOLDER,
        _echo_parent_for_leaf,
        _series_sentinel_to_none,
    )

    assert _series_sentinel_to_none(_PLACEHOLDER) is None
    # If a caller ever did pass {"value": "—"} as a bundle, the helper
    # would treat it as a real string — but the contract is that the
    # sentinel is stripped upstream. Confirm the helper signature reads
    # bundle["value"], not raw strings, by passing a non-dict and
    # getting the "no own value" path.
    row = {"sub_brand": _PLACEHOLDER, "brand": _bundle("ASUS")}
    value, is_echo = _echo_parent_for_leaf("sub_brand", row)
    # The string "—" is not a dict, so own resolves to None and the
    # helper echoes the brand.
    assert value == "ASUS"
    assert is_echo is True


def test_identity_strip_renders_echo_class_for_null_sub_brand():
    row = _echo_row(sub_brand=None)
    out = identity_strip_html(row)
    # The --echo class lives in the CSS block too, so anchor on the
    # full cell element to verify the class is actually applied.
    assert '<div class="cd-identity__value cd-identity__value--echo">' in out
    # The brand's value should appear as the echo content in the
    # sub-brand cell.
    assert "ASUS" in out


def test_identity_strip_no_echo_when_sub_brand_populated():
    row = _echo_row()
    out = identity_strip_html(row)
    # The --echo class always appears in the <style> block. What must
    # NOT appear is a cell that uses it. Anchor on the full element
    # signature so a CSS hit doesn't false-positive.
    assert '<div class="cd-identity__value cd-identity__value--echo">' not in out


def test_union_identity_strip_all_echo_rows_render_echo_class():
    a = _union_stub_row(year=2025, panel_hz="240", panel_type="IPS")
    b = _union_stub_row(year=2026, panel_hz="240", panel_type="OLED")
    # Both rows null their sub_brand → all-echo cell, must render with
    # the echo class.
    a["sub_brand"] = None
    a["brand"] = _bundle("ASUS")
    b["sub_brand"] = None
    b["brand"] = _bundle("ASUS")
    out = union_identity_strip_html([a, b])
    # Anchor on the full cell element so a CSS-block hit doesn't
    # false-positive.
    assert '<div class="cd-identity__value cd-identity__value--echo">' in out
    assert "ASUS" in out


def test_union_identity_strip_mixed_echo_and_real_renders_plain():
    # Locked product decision: mixed cells render PLAIN — only the
    # populated value(s), no echo styling. Mixing italic+real in one
    # cell would mislead which row(s) own the data.
    a = _union_stub_row(year=2025, panel_hz="240", panel_type="IPS")
    b = _union_stub_row(year=2026, panel_hz="240", panel_type="OLED")
    a["sub_brand"] = _bundle("ROG")
    a["brand"] = _bundle("ASUS")
    b["sub_brand"] = None
    b["brand"] = _bundle("ASUS")
    out = union_identity_strip_html([a, b])
    # The sub-brand cell carries only "ROG" — no echo styling on it
    # even though row b's sub_brand is null.
    assert "ROG" in out
    # We can't simply assert no --echo anywhere on the strip (other
    # leaves may legitimately echo). Instead: confirm the sub-brand
    # cell's joined value does NOT include "ASUS" echoed alongside ROG.
    assert "ROG · ASUS" not in out
    assert "ASUS · ROG" not in out


def test_find_result_card_renders_echo_crumb_for_null_sub_brand():
    from competitive_database.ui._components import find_result_card_html

    out = find_result_card_html(
        company="ASUS",
        sub_brand=None,
        series="Strix",
        year=2026,
        section_name="Display",
        rollup_value="QHD+ 240Hz",
        marker=MARKER_VERIFIED,
    )
    assert "cd-findcard__crumb--echo" in out
    # The echoed crumb wraps the brand ("ASUS") since sub_brand is null.
    assert "ASUS" in out
    # Series populated → plain crumb, no echo wrapper around "Strix".
    assert '<span class="cd-findcard__crumb--echo">Strix</span>' not in out


def test_find_result_card_renders_echo_crumb_for_null_series():
    from competitive_database.ui._components import find_result_card_html

    out = find_result_card_html(
        company="ASUS",
        sub_brand="ROG",
        series=None,
        year=2026,
        section_name="Display",
        rollup_value="QHD+ 240Hz",
        marker=MARKER_VERIFIED,
    )
    # Series null → echoes sub_brand ("ROG") in italic-faint.
    assert "cd-findcard__crumb--echo" in out
    assert "ROG" in out


def test_find_result_card_no_echo_when_both_populated():
    from competitive_database.ui._components import find_result_card_html

    out = find_result_card_html(
        company="ASUS",
        sub_brand="ROG",
        series="Strix",
        year=2026,
        section_name="Display",
        rollup_value="QHD+ 240Hz",
        marker=MARKER_VERIFIED,
    )
    # All identity leaves populated → no echo wrapper in the card.
    assert "cd-findcard__crumb--echo" not in out
