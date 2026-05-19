"""Shared UI components: dot marker, cascading picker, identity strip, spec table."""

from __future__ import annotations

import html
import json
import re
import sqlite3
from typing import Any, Optional

import streamlit as st

from competitive_database.ui._markers import MARKER_COLORS, resolve_path
from competitive_database.ui.theme import PALETTE
from competitive_database.views import load
from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_MANUAL,
    MARKER_NEEDS_REVIEW,
    MARKER_PARTIAL,
    MARKER_VENDOR_NO_PUB,
    MARKER_VERIFIED,
    display_value,
    marker_for_bundle,
)
from competitive_database.views.orchestrator import _SECTION_REGISTRY


_MARKERS = PALETTE["markers"]  # type: ignore[index]

# Token → palette concept; aliases (legacy bracket forms + plain "—") map
# the same way so any cell that already carries a bracket marker still
# resolves to a colored dot.
_DOT_COLOR: dict[str, str] = {
    MARKER_VERIFIED: _MARKERS["verified"],
    MARKER_NEEDS_REVIEW: _MARKERS["needs_review"],
    MARKER_MANUAL: _MARKERS["manual"],
    MARKER_VENDOR_NO_PUB: _MARKERS["vendor_no_publish"],
    MARKER_EMPTY: _MARKERS["empty"],
    MARKER_PARTIAL: _MARKERS["needs_review"],
    "[verified]": _MARKERS["verified"],
    "[review]": _MARKERS["needs_review"],
    "[manual]": _MARKERS["manual"],
    "[—]": _MARKERS["vendor_no_publish"],
    "—": _MARKERS["empty"],
    "[low_conf]": _MARKERS["low_confidence"],
}

# Human-readable label per marker token. Used by the inline legend and by
# downstream screens (Compare, Edit) that surface marker meaning.
MARKER_LABELS: dict[str, str] = {
    MARKER_VERIFIED: "verified",
    MARKER_NEEDS_REVIEW: "needs review",
    MARKER_VENDOR_NO_PUB: "vendor n/p",
    MARKER_MANUAL: "manual",
    MARKER_EMPTY: "empty",
    MARKER_PARTIAL: "partial",
}

_HEADER_IDENTITY_LEAVES: list[tuple[str, str]] = [
    ("sub-brand", "sub_brand"),
    ("series", "series"),
    ("status", "status"),
    ("segment", "segment"),
]

_YEAR_TOKEN = re.compile(r"\s*[\(\[]?\s*\b(?P<year>20\d{2})\b\s*[\)\]]?\s*")


# Minimal override map: path-leaf → friendlier human noun. Anything not
# listed here falls back to title-case with underscores replaced by
# spaces. CPU/GPU ``model`` is special-cased so it reads "Processor" /
# "Chip" based on the section, not by leaf name alone. Surfaced by both
# Find (query bar / result cards) and Edit (per-field rows).
_LEAF_LABEL_OVERRIDES: dict[str, str] = {
    "refresh_rate_hz": "Refresh rate",
    "size_inches": "Size (in)",
    "resolution_label": "Resolution",
    "resolution_pixels": "Resolution (px)",
    "nits_peak": "Peak brightness (nits)",
    "hdr_certification": "HDR certification",
    "dci_p3_pct": "DCI-P3 (%)",
    "srgb_pct": "sRGB (%)",
    "response_time_ms": "Response time (ms)",
    "anti_glare": "Anti-glare",
    "panel_type": "Panel",
    "vrr": "VRR",
    "tier": "Tier",
    "memory_type": "Type",
    "memory_max_gb": "Max (GB)",
    "memory_speed_mts": "Speed (MT/s)",
    "memory_slots": "Slots",
    "memory_overclocking": "Overclocking",
    "storage_max_gb": "Max (GB)",
    "gen": "PCIe gen",
    "cpu_tdp_max": "TDP max (W)",
    "tgp_max": "TGP max (W)",
    "tpp_max": "TPP max (W)",
    "arch_marker": "Architecture marker",
    "wifi_standard": "Wi-Fi standard",
    "ethernet": "Ethernet",
    "bluetooth_version": "Bluetooth version",
    "wattage_wh": "Battery wattage (Wh)",
    "wattage_w": "Adapter wattage (W)",
    "cell_count": "Cell count",
    "adapter_connector": "Connector",
    "thermal_design": "Design",
    "thermal_material": "Material",
    "tim": "TIM",
    "fan_count": "Fan count",
    "width_mm": "Width (mm)",
    "depth_mm": "Depth (mm)",
    "height_mm_min": "Height min (mm)",
    "height_mm_max": "Height max (mm)",
    "weight_kg_min": "Weight min (kg)",
    "weight_kg_max": "Weight max (kg)",
    "a_cover_material": "A-cover material",
    "c_cover_material": "C-cover material",
    "d_cover_material": "D-cover material",
    "thermal_shelf": "Thermal shelf",
    "lighting": "Lighting",
    "speaker_count": "Speaker count",
    "tuning_brand": "Tuning brand",
    "has_subwoofer": "Subwoofer",
    "has_numpad": "Numpad",
    "ir_supported": "IR supported",
    "privacy_shutter": "Privacy shutter",
    "description": "Description",
    "resolution": "Resolution",
    "sub_brand": "Sub-brand",
    "series": "Series",
    "status": "Status",
    "segment": "Segment",
    "brand": "Brand",
    "vendor_full_name": "Vendor name",
    "usbc_thunderbolt_count": "USB-C Thunderbolt count",
    "usbc_thunderbolt_version": "USB-C Thunderbolt version",
    "usbc_non_thunderbolt_count": "USB-C non-Thunderbolt count",
    "usbc_non_thunderbolt_version": "USB-C non-Thunderbolt version",
    "usba_count": "USB-A count",
    "usba_version": "USB-A version",
    "hdmi_count": "HDMI count",
    "hdmi_version": "HDMI version",
}


def friendly_leaf_label(leaf: str, section: str) -> str:
    """Map a path leaf segment to a human-friendly noun."""
    if leaf == "model":
        if section == "CPU":
            return "Processor"
        if section == "Boards":
            return "Chip"
        return "Model"
    override = _LEAF_LABEL_OVERRIDES.get(leaf)
    if override is not None:
        return override
    return leaf.replace("_", " ").strip().capitalize()


def friendly_field_label(section: str, template: str) -> str:
    """Build the ``Section · Feature`` label shown across Find / Edit."""
    parts = template.split(".")
    leaf = parts[-1]
    return f"{section} · {friendly_leaf_label(leaf, section)}"


def dot_marker(marker: str) -> str:
    """Return an HTML span with a colored ``●`` dot for the marker token."""
    color = _DOT_COLOR.get(marker, PALETTE["text_faint"])
    return (
        f'<span class="cd-dot" style="color:{color}" '
        f'title="{html.escape(MARKER_LABELS.get(marker, marker))}">●</span>'
    )


# ---------------------------------------------------------------------------
# Cascading picker (Company → Product → Year)
# ---------------------------------------------------------------------------


def _bundle_value(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict):
        v = parsed.get("value")
        if isinstance(v, str):
            return v
    return None


def _strip_year(name: str, year: int) -> str:
    yr = str(year)
    cleaned = _YEAR_TOKEN.sub(
        lambda m: " " if m.group("year") == yr else m.group(0),
        name,
    )
    cleaned = cleaned.replace(f"-{yr}", "").replace(f"_{yr}", "")
    return " ".join(cleaned.split())


def _product_name(vfn: str | None, model_code: str, year: int) -> str:
    raw = (vfn or model_code).strip()
    raw = raw.split(",", 1)[0].strip()
    return _strip_year(raw, year) or model_code


def _list_products(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT model_code, year, brand, vendor_full_name FROM products "
        "ORDER BY model_code, year"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for mc, yr, brand_raw, vfn_raw in rows:
        brand = _bundle_value(brand_raw) or "Unknown"
        vfn = _bundle_value(vfn_raw)
        out.append(
            {
                "model_code": mc,
                "year": int(yr),
                "brand": brand,
                "product_name": _product_name(vfn, mc, int(yr)),
            }
        )
    return out


def cascading_picker(
    conn: sqlite3.Connection,
    key_prefix: str,
    want_year: bool = True,
    vertical: bool = False,
) -> Optional[dict]:
    """Render Company / Product / Year selectboxes; return the picked row.

    Returns ``{"company", "product", "year", "row"}`` (``row`` = full
    product dict loaded by ``views.load.load_product``), or ``None`` when
    the DB has no products. Session keys are namespaced under
    ``key_prefix`` so multiple pickers can coexist on one page. Set
    ``vertical=True`` to render the three selectboxes stacked (used by
    Compare's per-column pickers).
    """
    products = _list_products(conn)
    if not products:
        return None

    k_company = f"{key_prefix}.company"
    k_product = f"{key_prefix}.product"
    k_year = f"{key_prefix}.year"

    def _reset_product_year() -> None:
        for k in (k_product, k_year):
            st.session_state.pop(k, None)

    def _reset_year() -> None:
        st.session_state.pop(k_year, None)

    companies = sorted({p["brand"] for p in products}, key=str.lower)
    if vertical:
        company = st.selectbox(
            "Company",
            companies,
            key=k_company,
            on_change=_reset_product_year,
        )
        company_products = [p for p in products if p["brand"] == company]
        product_names = sorted(
            {p["product_name"] for p in company_products}, key=str.lower
        )
        product_name = st.selectbox(
            "Product",
            product_names,
            key=k_product,
            on_change=_reset_year,
        )
        matches = [
            p for p in company_products if p["product_name"] == product_name
        ]
        years = sorted({p["year"] for p in matches}, reverse=True)
        if want_year:
            year = st.selectbox("Year", years, key=k_year)
        else:
            year = years[0] if years else None
    else:
        cols = st.columns([1, 2, 1] if want_year else [1, 2])
        with cols[0]:
            company = st.selectbox(
                "Company",
                companies,
                key=k_company,
                on_change=_reset_product_year,
            )
        company_products = [p for p in products if p["brand"] == company]
        product_names = sorted(
            {p["product_name"] for p in company_products}, key=str.lower
        )
        with cols[1]:
            product_name = st.selectbox(
                "Product",
                product_names,
                key=k_product,
                on_change=_reset_year,
            )
        matches = [
            p for p in company_products if p["product_name"] == product_name
        ]
        years = sorted({p["year"] for p in matches}, reverse=True)
        if want_year:
            with cols[2]:
                year = st.selectbox("Year", years, key=k_year)
        else:
            year = years[0] if years else None

    if year is None:
        return None

    chosen = next((p for p in matches if p["year"] == year), None)
    if chosen is None:
        return None

    row = load.load_product(conn, chosen["model_code"], year=chosen["year"])
    return {
        "company": company,
        "product": product_name,
        "year": year,
        "row": row,
    }


# ---------------------------------------------------------------------------
# Identity strip + spec table
# ---------------------------------------------------------------------------


def _value_cell_html(value: str, marker: str) -> str:
    """Return ``<dot> value`` HTML for one cell. Value is escaped here."""
    return f"{dot_marker(marker)}{html.escape(value)}"


def _identity_cell_html(label: str, key: str, product: dict[str, Any]) -> str:
    bundle = product.get(key)
    if isinstance(bundle, dict):
        marker = marker_for_bundle(bundle)
        if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB):
            value_str = "—"
        else:
            value_str = display_value(bundle) or "—"
    else:
        marker = MARKER_EMPTY
        value_str = "—"
    value_color = (
        "var(--cd-text-muted)"
        if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB)
        else "var(--cd-text)"
    )
    return (
        '<div class="cd-identity__cell">'
        f'<div class="cd-identity__label">{html.escape(label.upper())}</div>'
        f'<div class="cd-identity__value" style="color:{value_color}">'
        f"{_value_cell_html(value_str, marker)}"
        "</div>"
        "</div>"
    )


def identity_strip_html(product: dict[str, Any]) -> str:
    """Return the 4-column identity context strip HTML."""
    cells = [
        _identity_cell_html(label, key, product)
        for label, key in _HEADER_IDENTITY_LEAVES
    ]
    return (
        "<style>"
        ".cd-identity {"
        "display:grid;grid-template-columns:repeat(4, minmax(0, 1fr));"
        "gap:var(--cd-space-lg);"
        "background:var(--cd-bg-card);"
        "border:1px solid var(--cd-border);"
        "border-radius:var(--cd-radius-md);"
        "padding:var(--cd-space-md) var(--cd-space-lg);"
        "margin:var(--cd-space-sm) 0 var(--cd-space-lg) 0;"
        "}"
        ".cd-identity__cell {display:flex;flex-direction:column;min-width:0;}"
        ".cd-identity__label {"
        "color:var(--cd-text-faint);"
        "font-size:var(--cd-size-xs);"
        "letter-spacing:0.08em;"
        "font-weight:500;"
        "margin-bottom:2px;"
        "}"
        ".cd-identity__value {"
        "color:var(--cd-text);"
        "font-size:var(--cd-size-sm);"
        "}"
        "</style>"
        f'<div class="cd-identity">{"".join(cells)}</div>'
    )


def marker_legend_inline_html() -> str:
    """Return the small inline legend HTML (verified / needs rev. / manual / vendor n/p)."""
    entries = [
        (MARKER_VERIFIED, "verified"),
        (MARKER_NEEDS_REVIEW, "needs rev."),
        (MARKER_MANUAL, "manual"),
        (MARKER_VENDOR_NO_PUB, "vendor n/p"),
    ]
    parts: list[str] = []
    for marker, descr in entries:
        parts.append(
            '<span class="cd-legend__entry">'
            f"{dot_marker(marker)}{html.escape(descr)}"
            "</span>"
        )
    return f'<span class="cd-legend">{"".join(parts)}</span>'


def _format_cell(
    product: dict[str, Any], path: str
) -> tuple[str, str]:
    """Return ``(display_value_str, marker_token)`` for one path."""
    bundle, plain = resolve_path(product, path)
    if plain is not None:
        return plain, MARKER_VERIFIED
    marker = marker_for_bundle(bundle)
    if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB):
        return "—", marker
    value = display_value(bundle, field_path=path) or "—"
    return value, marker


def _section_rows_html(
    section_name: str,
    paths: list[tuple[str, str]],
    product: dict[str, Any],
) -> list[str]:
    """Build the ``<tr>`` strings for one section. Empty sections get a placeholder row."""
    rows: list[str] = []
    if not paths:
        rows.append(
            '<tr class="cd-spec__row cd-spec__row--last">'
            f'<td class="cd-spec__section" rowspan="1">{html.escape(section_name)}</td>'
            '<td class="cd-spec__feature">(no data scraped)</td>'
            f'<td class="cd-spec__value">{_value_cell_html("—", MARKER_EMPTY)}</td>'
            "</tr>"
        )
        return rows
    n = len(paths)
    for i, (path, feature_label) in enumerate(paths):
        value, marker = _format_cell(product, path)
        is_last = i == n - 1
        row_cls = "cd-spec__row cd-spec__row--last" if is_last else "cd-spec__row"
        section_cell = (
            f'<td class="cd-spec__section" rowspan="{n}">'
            f"{html.escape(section_name)}</td>"
            if i == 0
            else ""
        )
        rows.append(
            f'<tr class="{row_cls}">'
            f"{section_cell}"
            f'<td class="cd-spec__feature">{html.escape(feature_label)}</td>'
            f'<td class="cd-spec__value">{_value_cell_html(value, marker)}</td>'
            "</tr>"
        )
    return rows


def spec_table_html(
    product: dict[str, Any],
    sections: list[tuple[str, Any]] | None = None,
) -> str:
    """Return the full Section / Feature / Value spec table HTML with inline legend."""
    if sections is None:
        sections = _SECTION_REGISTRY
    body: list[str] = []
    for section_name, fn in sections:
        if section_name == "Identity":
            continue
        paths = fn(product)
        body.extend(_section_rows_html(section_name, paths, product))
    legend = marker_legend_inline_html()
    return (
        "<style>"
        ".cd-spec {"
        "border-collapse:collapse;width:100%;"
        "font-family:var(--cd-font-family);"
        "font-size:var(--cd-size-sm);line-height:1.5;"
        "margin-top:var(--cd-space-sm);"
        "}"
        ".cd-spec thead th {"
        "text-align:left;"
        "padding:var(--cd-space-sm) var(--cd-space-md) var(--cd-space-sm) 0;"
        "border-bottom:1px solid var(--cd-border-strong);"
        "color:var(--cd-text-faint);"
        "font-weight:500;"
        "font-size:var(--cd-size-xs);"
        "letter-spacing:0.08em;"
        "text-transform:uppercase;"
        "}"
        ".cd-spec thead th.cd-spec__th-value {"
        "text-align:right;padding-right:0;"
        "}"
        ".cd-spec__row {border-bottom:1px solid var(--cd-border);}"
        ".cd-spec__row--last {border-bottom:1px solid var(--cd-border-strong);}"
        ".cd-spec__section {"
        "padding:var(--cd-space-sm) var(--cd-space-md) var(--cd-space-sm) 0;"
        "vertical-align:top;"
        "font-weight:600;"
        "color:var(--cd-text);"
        "border-right:1px solid var(--cd-border);"
        "width:14%;"
        "font-size:var(--cd-size-sm);"
        "}"
        ".cd-spec__feature {"
        "padding:var(--cd-space-sm) var(--cd-space-md);"
        "vertical-align:top;"
        "color:var(--cd-text-muted);"
        "width:28%;"
        "}"
        ".cd-spec__value {"
        "padding:var(--cd-space-sm) 0;"
        "vertical-align:top;"
        "color:var(--cd-text);"
        "}"
        ".cd-legend {"
        "display:inline-flex;gap:var(--cd-space-md);"
        "font-size:var(--cd-size-xs);"
        "color:var(--cd-text-muted);"
        "font-weight:400;"
        "letter-spacing:0;"
        "text-transform:none;"
        "}"
        ".cd-legend__entry {"
        "display:inline-flex;align-items:center;"
        "}"
        "</style>"
        '<table class="cd-spec">'
        "<thead><tr>"
        '<th>Section</th>'
        '<th>Feature</th>'
        f'<th class="cd-spec__th-value">{legend}</th>'
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table>"
    )


# ---------------------------------------------------------------------------
# Comparison grid (N-product side-by-side)
# ---------------------------------------------------------------------------


def _product_header(product: dict[str, Any]) -> str:
    """Derive the friendly ``Name · Year`` header for one loaded product."""
    mc = product.get("model_code") or ""
    yr = product.get("year")
    vfn_bundle = product.get("vendor_full_name")
    vfn = None
    if isinstance(vfn_bundle, dict):
        v = vfn_bundle.get("value")
        if isinstance(v, str):
            vfn = v
    try:
        yr_int = int(yr) if yr is not None else 0
    except (TypeError, ValueError):
        yr_int = 0
    name = _product_name(vfn, str(mc), yr_int)
    return f"{name} · {yr_int}" if yr_int else name


def _cmp_value_cell_html(value: str, marker: str, diverges: bool) -> str:
    cls = "cd-cmp__value"
    if diverges:
        cls += " cd-cmp__value--diverges"
    return (
        f'<td class="{cls}">{dot_marker(marker)}{html.escape(value)}</td>'
    )


def _cmp_section_rows_html(
    section_name: str,
    paths: list[tuple[str, str]],
    products: list[dict[str, Any]],
) -> list[str]:
    """Build ``<tr>`` strings for one section, with per-row divergence cues."""
    rows: list[str] = []
    n_prod = len(products)
    if not paths:
        empty_cells = "".join(
            _cmp_value_cell_html("—", MARKER_EMPTY, False)
            for _ in range(n_prod)
        )
        rows.append(
            '<tr class="cd-cmp__row cd-cmp__row--last">'
            f'<td class="cd-cmp__section" rowspan="1">{html.escape(section_name)}</td>'
            '<td class="cd-cmp__feature">(no data scraped)</td>'
            f"{empty_cells}"
            "</tr>"
        )
        return rows
    n = len(paths)
    for i, (path, feature_label) in enumerate(paths):
        cells: list[tuple[str, str]] = [
            _format_cell(prod, path) for prod in products
        ]
        values = [v for v, _m in cells]
        diverges_flags = _divergence_flags(values)
        is_last = i == n - 1
        row_cls = "cd-cmp__row cd-cmp__row--last" if is_last else "cd-cmp__row"
        section_cell = (
            f'<td class="cd-cmp__section" rowspan="{n}">'
            f"{html.escape(section_name)}</td>"
            if i == 0
            else ""
        )
        value_cells_html = "".join(
            _cmp_value_cell_html(value, marker, diverges_flags[idx])
            for idx, (value, marker) in enumerate(cells)
        )
        rows.append(
            f'<tr class="{row_cls}">'
            f"{section_cell}"
            f'<td class="cd-cmp__feature">{html.escape(feature_label)}</td>'
            f"{value_cells_html}"
            "</tr>"
        )
    return rows


def _divergence_flags(values: list[str]) -> list[bool]:
    """Return per-cell divergence flags per the strict-majority rule.

    Strict majority: a value's count must exceed N/2. Cells holding the
    majority value are consensus (False). Everything else diverges (True).
    With no strict majority, every cell diverges.
    """
    n = len(values)
    if n <= 1:
        return [False] * n
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    max_count = max(counts.values())
    if max_count * 2 > n:
        majority_value = next(v for v, c in counts.items() if c == max_count)
        return [v != majority_value for v in values]
    return [True] * n


def comparison_grid_html(
    products: list[dict[str, Any]],
    sections: list[tuple[str, Any]] | None = None,
) -> str:
    """Return the full N-product side-by-side comparison grid HTML."""
    if sections is None:
        sections = _SECTION_REGISTRY
    headers = [_product_header(p) for p in products]
    n_prod = len(products)
    body: list[str] = []
    for section_name, fn in sections:
        if section_name == "Identity":
            continue
        # Union of paths across all products preserves first-appearance
        # order so deeper offerings on later columns still surface rows.
        seen: set[str] = set()
        paths: list[tuple[str, str]] = []
        for prod in products:
            for path, label in fn(prod):
                if path in seen:
                    continue
                seen.add(path)
                paths.append((path, label))
        body.extend(_cmp_section_rows_html(section_name, paths, products))
    legend = marker_legend_inline_html()
    value_col_pct = max(8, int(58 / max(n_prod, 1)))
    header_cells = "".join(
        f'<th class="cd-cmp__th-value" style="width:{value_col_pct}%">'
        f"{html.escape(h)}</th>"
        for h in headers
    )
    # Final value-column header carries the inline legend in its top-right
    # so the cue rides with the table rather than floating above it.
    return (
        "<style>"
        ".cd-cmp {"
        "border-collapse:collapse;width:100%;"
        "font-family:var(--cd-font-family);"
        "font-size:var(--cd-size-sm);line-height:1.5;"
        "margin-top:var(--cd-space-sm);"
        "}"
        ".cd-cmp thead th {"
        "text-align:left;"
        "padding:var(--cd-space-sm) var(--cd-space-md) var(--cd-space-sm) 0;"
        "border-bottom:1px solid var(--cd-border-strong);"
        "color:var(--cd-text-faint);"
        "font-weight:500;"
        "font-size:var(--cd-size-xs);"
        "letter-spacing:0.08em;"
        "text-transform:uppercase;"
        "vertical-align:bottom;"
        "}"
        ".cd-cmp thead th.cd-cmp__th-value {"
        "color:var(--cd-text);"
        "text-transform:none;"
        "letter-spacing:0;"
        "font-size:var(--cd-size-sm);"
        "font-weight:600;"
        "padding-right:var(--cd-space-md);"
        "}"
        ".cd-cmp thead th.cd-cmp__th-legend {"
        "text-align:right;padding-right:0;"
        "font-size:var(--cd-size-xs);"
        "}"
        ".cd-cmp__row {border-bottom:1px solid var(--cd-border);}"
        ".cd-cmp__row--last {border-bottom:1px solid var(--cd-border-strong);}"
        ".cd-cmp__section {"
        "padding:var(--cd-space-sm) var(--cd-space-md) var(--cd-space-sm) 0;"
        "vertical-align:top;"
        "font-weight:600;"
        "color:var(--cd-text);"
        "border-right:1px solid var(--cd-border);"
        "width:12%;"
        "font-size:var(--cd-size-sm);"
        "}"
        ".cd-cmp__feature {"
        "padding:var(--cd-space-sm) var(--cd-space-md);"
        "vertical-align:top;"
        "color:var(--cd-text-muted);"
        "width:18%;"
        "}"
        ".cd-cmp__value {"
        "padding:var(--cd-space-sm) var(--cd-space-md);"
        "vertical-align:top;"
        "color:var(--cd-text);"
        "border-left:3px solid transparent;"
        "}"
        ".cd-cmp__value--diverges {"
        "border-left:3px solid var(--cd-accent);"
        "background:var(--cd-bg-accent-soft);"
        "}"
        "</style>"
        '<table class="cd-cmp">'
        "<thead><tr>"
        '<th>Section</th>'
        '<th>Feature</th>'
        f"{header_cells}"
        "</tr>"
        "<tr>"
        '<th></th>'
        '<th></th>'
        f'<th class="cd-cmp__th-legend" colspan="{n_prod}">{legend}</th>'
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table>"
    )
