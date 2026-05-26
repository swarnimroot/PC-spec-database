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
from competitive_database.views import (
    adapter as adapter_view,
    audio as audio_view,
    battery as battery_view,
    boards as boards_view,
    camera as camera_view,
    cpu as cpu_view,
    design as design_view,
    dimensions as dimensions_view,
    display as display_view,
    io as io_view,
    load,
    memory as memory_view,
    network as network_view,
    storage as storage_view,
    weight as weight_view,
)
from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_MANUAL,
    MARKER_NEEDS_REVIEW,
    MARKER_PARTIAL,
    MARKER_VENDOR_NO_PUB,
    MARKER_VERIFIED,
    display_value,
    marker_for_bundle,
    worst_marker,
)
from competitive_database.views.orchestrator import (
    _SECTION_REGISTRY,
    _VISUAL_SECTIONS,
)

# Stage 10b: per-section row label for the rollup cells. Section names
# are matched verbatim against ``_SECTION_REGISTRY`` so they stay in
# sync. Sections whose label matches the section heading itself (most of
# the batch-2 rollups) inherit the section name as the feature label.
_ROLLUP_FEATURE_LABEL: dict[str, str] = {
    "Processor": "Architecture",
    "Graphics": "Boards",
    "Display": "Panel",
    "Memory": "RAM",
    "Storage": "Slots",
    "Camera": "Webcam",
    "Audio": "Speakers",
    "Network": "Wi-Fi",
    "Battery": "Battery",
    "Adapter": "Adapter",
    "Dimensions": "Size",
    "Weight": "Weight",
    "Design": "Covers",
}

# Per-section feature labels for the multi-row I/O rollup. Each sub-row
# carries its own (label, value, marker) tuple — see ``io.rollup_rows``.
_IO_SECTION = "I/O"


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
        if section == "Processor":
            return "Processor"
        if section == "Graphics":
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
        "SELECT model_code, year, brand, vendor_full_name, sub_brand, series "
        "FROM products ORDER BY model_code, year"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for mc, yr, brand_raw, vfn_raw, sub_raw, series_raw in rows:
        brand = _bundle_value(brand_raw) or "Unknown"
        vfn = _bundle_value(vfn_raw)
        sub = _bundle_value(sub_raw)
        series = _bundle_value(series_raw)
        out.append(
            {
                "model_code": mc,
                "year": int(yr),
                "brand": brand,
                "sub_brand": sub,
                "series": series,
                "product_name": _product_name(vfn, mc, int(yr)),
            }
        )
    return out


_PLACEHOLDER = "—"


def cascading_picker(
    conn: sqlite3.Connection,
    key_prefix: str,
    want_year: bool = True,
    vertical: bool = False,
    strict_cascade: bool = False,
    rung_mode: str = "product",
) -> Optional[dict]:
    """Render the cascading product picker; return the picked row.

    Two rung modes:
      * ``"product"`` (default, legacy) — Company → Product → Year.
      * ``"series"`` — Company → Sub-brand → Series → Year. Each tuple
        ``(brand, sub_brand, series, year)`` resolves to one product.

    ``strict_cascade=False`` (default) preserves the existing auto-default
    behavior — every selectbox renders at first paint with its first
    option pre-selected. ``strict_cascade=True`` hides downstream
    selectboxes until the upstream rung has been explicitly picked by
    the user; a placeholder ``"—"`` is prepended to every rung so first
    paint carries no auto-selection.

    Returns ``{"company", "product", "year", "row", ...}`` with
    ``"sub_brand"`` and ``"series"`` populated when ``rung_mode='series'``,
    or ``None`` when the DB has no products / the cascade isn't complete.
    Session keys are namespaced under ``key_prefix`` so multiple pickers
    can coexist on one page. Set ``vertical=True`` to render the rungs
    stacked (used by Compare's per-column pickers).
    """
    products = _list_products(conn)
    if not products:
        return None

    if rung_mode == "series":
        return _series_cascade(
            products, conn, key_prefix, want_year, vertical, strict_cascade
        )
    return _product_cascade(
        products, conn, key_prefix, want_year, vertical, strict_cascade
    )


def _is_picked(value: Any) -> bool:
    return value is not None and value != _PLACEHOLDER


def _selectbox(
    label: str,
    options: list,
    key: str,
    on_change=None,
    *,
    strict: bool,
) -> Any:
    """Render one rung; when strict, prepend a placeholder + return-None gate."""
    if strict:
        opts = [_PLACEHOLDER] + list(options)
        chosen = st.selectbox(label, opts, key=key, on_change=on_change)
        return chosen
    chosen = st.selectbox(label, options, key=key, on_change=on_change)
    return chosen


def _product_cascade(
    products: list[dict[str, Any]],
    conn: sqlite3.Connection,
    key_prefix: str,
    want_year: bool,
    vertical: bool,
    strict: bool,
) -> Optional[dict]:
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
        company = _selectbox(
            "Company", companies, k_company, _reset_product_year, strict=strict
        )
        if strict and not _is_picked(company):
            return None
        company_products = [p for p in products if p["brand"] == company]
        product_names = sorted(
            {p["product_name"] for p in company_products}, key=str.lower
        )
        if strict and not product_names:
            return None
        product_name = _selectbox(
            "Product", product_names, k_product, _reset_year, strict=strict
        )
        if strict and not _is_picked(product_name):
            return None
        matches = [
            p for p in company_products if p["product_name"] == product_name
        ]
        years = sorted({p["year"] for p in matches}, reverse=True)
        if want_year:
            if strict and not years:
                return None
            year = _selectbox("Year", years, k_year, None, strict=strict)
            if strict and not _is_picked(year):
                return None
        else:
            year = years[0] if years else None
    else:
        cols = st.columns([1, 2, 1] if want_year else [1, 2])
        with cols[0]:
            company = _selectbox(
                "Company", companies, k_company, _reset_product_year, strict=strict
            )
        if strict and not _is_picked(company):
            return None
        company_products = [p for p in products if p["brand"] == company]
        product_names = sorted(
            {p["product_name"] for p in company_products}, key=str.lower
        )
        if strict and not product_names:
            return None
        with cols[1]:
            product_name = _selectbox(
                "Product", product_names, k_product, _reset_year, strict=strict
            )
        if strict and not _is_picked(product_name):
            return None
        matches = [
            p for p in company_products if p["product_name"] == product_name
        ]
        years = sorted({p["year"] for p in matches}, reverse=True)
        if want_year:
            if strict and not years:
                return None
            with cols[2]:
                year = _selectbox("Year", years, k_year, None, strict=strict)
            if strict and not _is_picked(year):
                return None
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


def _series_cascade(
    products: list[dict[str, Any]],
    conn: sqlite3.Connection,
    key_prefix: str,
    want_year: bool,
    vertical: bool,
    strict: bool,
) -> Optional[dict]:
    """Company → Sub-brand → Series → Year rung mode."""
    k_company = f"{key_prefix}.company"
    k_sub = f"{key_prefix}.sub_brand"
    k_series = f"{key_prefix}.series"
    k_year = f"{key_prefix}.year"

    def _reset_below_company() -> None:
        for k in (k_sub, k_series, k_year):
            st.session_state.pop(k, None)

    def _reset_below_sub() -> None:
        for k in (k_series, k_year):
            st.session_state.pop(k, None)

    def _reset_year() -> None:
        st.session_state.pop(k_year, None)

    companies = sorted({p["brand"] for p in products}, key=str.lower)

    def render_company() -> Any:
        return _selectbox(
            "Company", companies, k_company, _reset_below_company, strict=strict
        )

    def render_sub(opts: list[str]) -> Any:
        return _selectbox(
            "Sub-brand", opts, k_sub, _reset_below_sub, strict=strict
        )

    def render_series(opts: list[str]) -> Any:
        return _selectbox(
            "Series", opts, k_series, _reset_year, strict=strict
        )

    def render_year(opts: list[int]) -> Any:
        return _selectbox("Year", opts, k_year, None, strict=strict)

    if vertical:
        company = render_company()
        if strict and not _is_picked(company):
            return None
        co_prods = [p for p in products if p["brand"] == company]
        sub_opts = sorted(
            {p["sub_brand"] or "—" for p in co_prods}, key=str.lower
        )
        if strict and not sub_opts:
            return None
        sub = render_sub(sub_opts)
        if strict and not _is_picked(sub):
            return None
        sub_prods = [p for p in co_prods if (p["sub_brand"] or "—") == sub]
        series_opts = sorted(
            {p["series"] or "—" for p in sub_prods}, key=str.lower
        )
        if strict and not series_opts:
            return None
        series = render_series(series_opts)
        if strict and not _is_picked(series):
            return None
        series_prods = [p for p in sub_prods if (p["series"] or "—") == series]
        years = sorted({p["year"] for p in series_prods}, reverse=True)
        if want_year:
            if strict and not years:
                return None
            year = render_year(years)
            if strict and not _is_picked(year):
                return None
        else:
            year = years[0] if years else None
    else:
        cols = st.columns([1, 1, 1, 1] if want_year else [1, 1, 1])
        with cols[0]:
            company = render_company()
        if strict and not _is_picked(company):
            return None
        co_prods = [p for p in products if p["brand"] == company]
        sub_opts = sorted(
            {p["sub_brand"] or "—" for p in co_prods}, key=str.lower
        )
        if strict and not sub_opts:
            return None
        with cols[1]:
            sub = render_sub(sub_opts)
        if strict and not _is_picked(sub):
            return None
        sub_prods = [p for p in co_prods if (p["sub_brand"] or "—") == sub]
        series_opts = sorted(
            {p["series"] or "—" for p in sub_prods}, key=str.lower
        )
        if strict and not series_opts:
            return None
        with cols[2]:
            series = render_series(series_opts)
        if strict and not _is_picked(series):
            return None
        series_prods = [p for p in sub_prods if (p["series"] or "—") == series]
        years = sorted({p["year"] for p in series_prods}, reverse=True)
        if want_year:
            if strict and not years:
                return None
            with cols[3]:
                year = render_year(years)
            if strict and not _is_picked(year):
                return None
        else:
            year = years[0] if years else None

    if year is None:
        return None

    chosen = next((p for p in series_prods if p["year"] == year), None)
    if chosen is None:
        return None

    row = load.load_product(conn, chosen["model_code"], year=chosen["year"])
    return {
        "company": company,
        "sub_brand": sub,
        "series": series,
        "product": chosen["product_name"],
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


def _rollup_row_html(
    section_name: str,
    feature_label: str,
    value_str: str,
    marker: str,
) -> str:
    """One ``<tr>`` carrying a single-row rollup cell.

    Empty rollup renders ``—`` with the empty marker (consistent with
    the per-section "(no data scraped)" placeholder elsewhere).
    """
    if value_str:
        cell_value = value_str
        cell_marker = marker
    else:
        cell_value = "—"
        cell_marker = MARKER_EMPTY
    return (
        '<tr class="cd-spec__row cd-spec__row--last">'
        f'<td class="cd-spec__section" rowspan="1">{html.escape(section_name)}</td>'
        f'<td class="cd-spec__feature">{html.escape(feature_label)}</td>'
        f'<td class="cd-spec__value">{_value_cell_html(cell_value, cell_marker)}</td>'
        "</tr>"
    )


def _rollup_rows_html(
    section_name: str,
    rows: list[tuple[str, str, str]],
) -> list[str]:
    """``<tr>`` strings for a multi-row rollup (I/O).

    Renders N rows under one section header (section cell ``rowspan=N``
    on the first sub-row only). Each tuple is ``(label, value, marker)``;
    empty values render as ``—`` with ``MARKER_EMPTY``.
    """
    if not rows:
        return [
            _rollup_row_html(section_name, "(no data scraped)", "", MARKER_EMPTY)
        ]
    n = len(rows)
    out: list[str] = []
    for i, (label, value_str, marker) in enumerate(rows):
        cell_value = value_str if value_str else "—"
        cell_marker = marker if value_str else MARKER_EMPTY
        is_last = i == n - 1
        row_cls = "cd-spec__row cd-spec__row--last" if is_last else "cd-spec__row"
        section_cell = (
            f'<td class="cd-spec__section" rowspan="{n}">'
            f"{html.escape(section_name)}</td>"
            if i == 0
            else ""
        )
        out.append(
            f'<tr class="{row_cls}">'
            f"{section_cell}"
            f'<td class="cd-spec__feature">{html.escape(label)}</td>'
            f'<td class="cd-spec__value">{_value_cell_html(cell_value, cell_marker)}</td>'
            "</tr>"
        )
    return out


def _rollup_for_section(
    section_name: str,
    product: dict[str, Any],
    cpu_catalog: dict[str, dict[str, Any]],
    gpu_catalog: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    """Dispatch a section name to its ``rollup_value`` and return (value, marker).

    I/O uses ``rollup_rows`` instead (multi-row shape); callers branch
    on the section name before reaching this helper.
    """
    if section_name == "Processor":
        return cpu_view.rollup_value(product, cpu_catalog)
    if section_name == "Graphics":
        return boards_view.rollup_value(product, gpu_catalog)
    if section_name == "Display":
        return display_view.rollup_value(product)
    if section_name == "Memory":
        return memory_view.rollup_value(product)
    if section_name == "Storage":
        return storage_view.rollup_value(product)
    if section_name == "Camera":
        return camera_view.rollup_value(product)
    if section_name == "Audio":
        return audio_view.rollup_value(product)
    if section_name == "Network":
        return network_view.rollup_value(product)
    if section_name == "Battery":
        return battery_view.rollup_value(product)
    if section_name == "Adapter":
        return adapter_view.rollup_value(product)
    if section_name == "Dimensions":
        return dimensions_view.rollup_value(product)
    if section_name == "Weight":
        return weight_view.rollup_value(product)
    if section_name == "Design":
        return design_view.rollup_value(product)
    return "", MARKER_EMPTY


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
    *,
    cpu_catalog: dict[str, dict[str, Any]] | None = None,
    gpu_catalog: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Return the full Section / Feature / Value spec table HTML with inline legend.

    Stage 10b: every section in ``_VISUAL_SECTIONS`` collapses to a
    rollup row driven by that section's ``rollup_value`` (or
    ``rollup_rows`` for I/O — the multi-row outlier). Sections outside
    ``_VISUAL_SECTIONS`` (Keyboard, Thermals) and ``Identity`` are
    skipped from the visual table; their per-leaf bundles still surface
    on the Edit screen via ``field_paths``. When the catalogs are not
    supplied, the CPU + Graphics rollup cells render blank — render is
    not gated on curation per the user's Stage 10b call.
    """
    if sections is None:
        sections = _SECTION_REGISTRY
    cpu_catalog = cpu_catalog or {}
    gpu_catalog = gpu_catalog or {}
    body: list[str] = []
    for section_name, _fn in sections:
        if section_name not in _VISUAL_SECTIONS:
            continue
        if section_name == _IO_SECTION:
            body.extend(
                _rollup_rows_html(section_name, io_view.rollup_rows(product))
            )
            continue
        value, marker = _rollup_for_section(
            section_name, product, cpu_catalog, gpu_catalog
        )
        body.append(
            _rollup_row_html(
                section_name,
                _ROLLUP_FEATURE_LABEL.get(section_name, section_name),
                value,
                marker,
            )
        )
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
# Stage 11 Phase 3 — Union spec view (one logical product, N year rows)
# ---------------------------------------------------------------------------


def _union_marker(markers: list[str]) -> str:
    """Worst marker across N per-row markers, EMPTY-preserving.

    ``worst_marker`` falls back to ``MARKER_NEEDS_REVIEW`` when given
    only unknown tokens — but for the union path the all-EMPTY case
    should stay EMPTY so an N=1 union over a missing section renders
    the same gray dot as the per-row ``rollup_value`` would. Defers to
    ``worst_marker`` otherwise so the worst real status wins.
    """
    if not markers:
        return MARKER_EMPTY
    if all(m == MARKER_EMPTY for m in markers):
        return MARKER_EMPTY
    return worst_marker(markers)


def _union_rollup_for_section(
    section_name: str,
    rows: list[dict[str, Any]],
    *,
    cpu_catalog: dict[str, dict[str, Any]],
    gpu_catalog: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    """Union one section's rollup across N product rows.

    Calls ``_rollup_for_section`` once per row. Empty/None values are
    dropped before deduping so a year-row missing data doesn't pollute
    the union. Remaining values dedupe by exact-string equality with
    first-seen order preserved, then join with `` · ``. Marker is the
    worst across every per-row marker (including the rows whose values
    were skipped — their marker still counts toward confidence);
    all-empty markers stay empty.
    """
    per_row: list[tuple[str, str]] = [
        _rollup_for_section(section_name, row, cpu_catalog, gpu_catalog)
        for row in rows
    ]
    parts: list[str] = []
    for value_str, _marker in per_row:
        if not value_str:
            continue
        if value_str not in parts:
            parts.append(value_str)
    return " · ".join(parts), _union_marker([m for _v, m in per_row])


def _union_io_rollup_rows(
    rows: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """Union the I/O multi-row rollup across N product rows.

    ``io.rollup_rows`` always returns four sub-rows in a fixed order
    (USB / HDMI / SD card / Audio jack). For each sub-row index we
    dedupe values (first-seen order; the ``"—"`` placeholder counts
    as empty for dedupe purposes so a row missing a leaf doesn't
    pollute the union) and take the worst marker across every row,
    with all-empty staying empty so a fully-missing sub-row keeps its
    gray dot.
    """
    per_row_lists = [io_view.rollup_rows(row) for row in rows]
    n_sub = len(per_row_lists[0])
    out: list[tuple[str, str, str]] = []
    for sub_idx in range(n_sub):
        per_prod = [rows_list[sub_idx] for rows_list in per_row_lists]
        label = per_prod[0][0]
        parts: list[str] = []
        for _label, value_str, _marker in per_prod:
            if not value_str or value_str == "—":
                continue
            if value_str not in parts:
                parts.append(value_str)
        marker = _union_marker([m for _l, _v, m in per_prod])
        joined = " · ".join(parts) if parts else "—"
        out.append((label, joined, marker))
    return out


def union_spec_table_html(
    rows: list[dict[str, Any]],
    *,
    cpu_catalog: dict[str, dict[str, Any]] | None = None,
    gpu_catalog: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Return the Section / Feature / Value spec table HTML for N year-rows.

    Same HTML shell as ``spec_table_html``. Body iterates
    ``_VISUAL_SECTIONS`` and unions each section's rollup across all
    rows: deduped values (first-seen order, exact string equality)
    joined by `` · ``; marker = worst across rows. With ``len(rows) == 1``
    the dedupe collapses to the single per-row value, so the output is
    byte-identical to ``spec_table_html(rows[0])``. With ``len(rows) == 0``
    raises ``ValueError`` — callers handle the zero-row case before
    calling this.
    """
    if not rows:
        raise ValueError("union_spec_table_html requires at least one row")
    cpu_catalog = cpu_catalog or {}
    gpu_catalog = gpu_catalog or {}
    body: list[str] = []
    for section_name, _fn in _SECTION_REGISTRY:
        if section_name not in _VISUAL_SECTIONS:
            continue
        if section_name == _IO_SECTION:
            body.extend(
                _rollup_rows_html(section_name, _union_io_rollup_rows(rows))
            )
            continue
        value, marker = _union_rollup_for_section(
            section_name, rows, cpu_catalog=cpu_catalog, gpu_catalog=gpu_catalog
        )
        body.append(
            _rollup_row_html(
                section_name,
                _ROLLUP_FEATURE_LABEL.get(section_name, section_name),
                value,
                marker,
            )
        )
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


def _year_set_cell_html(rows: list[dict[str, Any]]) -> str:
    """Render the year-set identity cell for the union strip.

    Echoes the sorted-ascending year set joined by ``, `` (e.g.
    ``2025, 2026``). Carries no provenance dot — the year value is a PK
    column, not a bundle, so a verified marker would be misleading; the
    cell renders as a plain identity row consistent with the
    sub-brand / series / status / segment treatment when those carry
    real bundles.
    """
    years = sorted({row.get("year") for row in rows if row.get("year") is not None})
    value_str = ", ".join(str(y) for y in years) if years else "—"
    value_color = "var(--cd-text)" if years else "var(--cd-text-muted)"
    return (
        '<div class="cd-identity__cell">'
        f'<div class="cd-identity__label">{html.escape("YEAR")}</div>'
        f'<div class="cd-identity__value" style="color:{value_color}">'
        f"{html.escape(value_str)}"
        "</div>"
        "</div>"
    )


def union_identity_strip_html(rows: list[dict[str, Any]]) -> str:
    """Return the identity context strip HTML for N year-rows.

    With ``len(rows) == 1`` delegates to ``identity_strip_html(rows[0])``
    so the single-row case stays byte-identical to the existing strip
    (no year cell — the existing layout has none). With
    ``len(rows) > 1`` the four identity leaves (sub-brand / series /
    status / segment) union the same way the spec rollup cells do
    (deduped values joined by `` · ``, marker = worst) and a fifth
    ``year`` cell echoes the sorted-ascending year set joined with
    ``, ``. PK ``(product, year)`` guarantees product itself is
    constant across rows; product surfaces in the caller's title, not
    in this strip.
    """
    if not rows:
        raise ValueError("union_identity_strip_html requires at least one row")
    if len(rows) == 1:
        return identity_strip_html(rows[0])
    cells = [
        _union_identity_cell_html(label, key, rows)
        for label, key in _HEADER_IDENTITY_LEAVES
    ]
    cells.append(_year_set_cell_html(rows))
    return (
        "<style>"
        ".cd-identity {"
        "display:grid;grid-template-columns:repeat(5, minmax(0, 1fr));"
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


def _union_identity_cell_html(
    label: str, key: str, rows: list[dict[str, Any]]
) -> str:
    """Union one identity cell across N rows.

    Mirrors ``_identity_cell_html`` but dedupes per-row display values
    (skipping empty / vendor-n/p before deduping so a row missing data
    doesn't surface as ``—`` in the union) and joins with `` · ``.
    Marker = worst across every per-row bundle's marker (empty / n/p
    rows still count toward confidence, matching the rollup rule).
    """
    parts: list[str] = []
    markers: list[str] = []
    for row in rows:
        bundle = row.get(key)
        if isinstance(bundle, dict):
            marker = marker_for_bundle(bundle)
            value_str = (
                "" if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB)
                else (display_value(bundle) or "")
            )
        else:
            marker = MARKER_EMPTY
            value_str = ""
        markers.append(marker)
        if value_str and value_str not in parts:
            parts.append(value_str)
    final_marker = worst_marker(markers)
    if parts:
        joined = " · ".join(parts)
        value_color = "var(--cd-text)"
    else:
        joined = "—"
        value_color = "var(--cd-text-muted)"
    return (
        '<div class="cd-identity__cell">'
        f'<div class="cd-identity__label">{html.escape(label.upper())}</div>'
        f'<div class="cd-identity__value" style="color:{value_color}">'
        f"{_value_cell_html(joined, final_marker)}"
        "</div>"
        "</div>"
    )


def year_toggle_block(
    years: list[int],
    key_prefix: str,
    *,
    default_latest: bool = True,
) -> list[int]:
    """Render a row of year-toggle pill buttons and return active years.

    Active years are stored as a ``set[int]`` in
    ``st.session_state[f"{key_prefix}.years"]``. On first paint (key
    absent), seed ``{max(years)}`` if ``default_latest`` else the empty
    set. Clicking a pill toggles that year in/out. The returned list is
    sorted descending (newest first) so callers' downstream ordering
    matches the Browse year-dropdown convention.
    """
    state_key = f"{key_prefix}.years"
    if state_key not in st.session_state:
        st.session_state[state_key] = {max(years)} if (default_latest and years) else set()
    active: set[int] = set(st.session_state[state_key])
    if not years:
        return []
    cols = st.columns(len(years))
    for col, yr in zip(cols, years):
        with col:
            is_on = yr in active
            label = f"● {yr}" if is_on else f"○ {yr}"
            if st.button(label, key=f"{key_prefix}.year_btn.{yr}"):
                if yr in active:
                    active.discard(yr)
                else:
                    active.add(yr)
                st.session_state[state_key] = active
                st.rerun()
    return sorted(active, reverse=True)


def status_toggle_block(
    key_prefix: str,
    *,
    default: tuple[str, ...] = ("Active",),
) -> list[str]:
    """Render the two fixed status pills (Active / Discontinued).

    Active statuses are stored as a ``set[str]`` in
    ``st.session_state[f"{key_prefix}.status"]``. On first paint the
    set is seeded from ``default``. Returns the sorted list of
    currently-active statuses so callers can filter their row set
    deterministically.
    """
    state_key = f"{key_prefix}.status"
    if state_key not in st.session_state:
        st.session_state[state_key] = set(default)
    active: set[str] = set(st.session_state[state_key])
    options = ("Active", "Discontinued")
    cols = st.columns(len(options))
    for col, opt in zip(cols, options):
        with col:
            is_on = opt in active
            label = f"● {opt}" if is_on else f"○ {opt}"
            if st.button(label, key=f"{key_prefix}.status_btn.{opt}"):
                if opt in active:
                    active.discard(opt)
                else:
                    active.add(opt)
                st.session_state[state_key] = active
                st.rerun()
    return sorted(active)


# ---------------------------------------------------------------------------
# Stage 11 Phase 3: strict 3-rung Brand → Series → Product picker
# ---------------------------------------------------------------------------


def _series_sentinel_to_none(series: str) -> Optional[str]:
    """Convert the ``"—"`` series sentinel back to ``None``; pass-through otherwise."""
    return None if series == _PLACEHOLDER else series


def brand_series_product_picker(
    conn: sqlite3.Connection,
    key_prefix: str,
    *,
    strict: bool = True,
) -> Optional[dict]:
    """Strict 3-rung Brand → Series → Product cascade (Stage 11 PK identity).

    Renders three ``_selectbox``-style dropdowns inside
    ``st.columns([1, 1, 2])``. Strict cascade: Series only renders once
    Brand is picked, Product only renders once Series is picked. Changing
    Brand resets Series + Product session-state; changing Series resets
    Product (mirroring ``_reset_below_company`` in ``_series_cascade``).

    The ``"—"`` series sentinel emitted by ``list_series_options`` maps
    back to ``None`` in both the call to ``list_product_options`` and in
    the returned dict's ``"series"`` slot (so callers downstream can pass
    it straight into ``list_years_for_product`` / ``load_product_rows``).

    Returns ``None`` when the cascade isn't fully picked. Returns
    ``{"brand": str, "series": str | None, "product": str}`` once all
    three rungs are chosen.
    """
    # Local import: keep this module's top-level imports unchanged (the
    # existing cascading_picker doesn't pull from db.helpers either).
    from competitive_database.db.helpers import (
        list_brand_options,
        list_product_options,
        list_series_options,
    )

    k_brand = f"{key_prefix}.brand"
    k_series = f"{key_prefix}.series"
    k_product = f"{key_prefix}.product"

    def _reset_below_brand() -> None:
        for k in (k_series, k_product):
            st.session_state.pop(k, None)

    def _reset_below_series() -> None:
        st.session_state.pop(k_product, None)

    brands = list_brand_options(conn)
    cols = st.columns([1, 1, 2])
    with cols[0]:
        brand = _selectbox(
            "Brand", brands, k_brand, _reset_below_brand, strict=strict
        )
    if strict and not _is_picked(brand):
        return None

    series_opts = list_series_options(conn, brand)
    if strict and not series_opts:
        return None
    with cols[1]:
        series = _selectbox(
            "Series", series_opts, k_series, _reset_below_series, strict=strict
        )
    if strict and not _is_picked(series):
        return None

    series_value = _series_sentinel_to_none(series)
    product_opts = list_product_options(conn, brand, series_value)
    if strict and not product_opts:
        return None
    with cols[2]:
        product = _selectbox(
            "Product", product_opts, k_product, None, strict=strict
        )
    if strict and not _is_picked(product):
        return None

    return {
        "brand": brand,
        "series": series_value,
        "product": product,
    }


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


def _cmp_rollup_row_html(
    section_name: str,
    feature_label: str,
    rollups: list[tuple[str, str]],
) -> str:
    """Compare-grid ``<tr>`` carrying one rolled-up row across N products."""
    cells_data: list[tuple[str, str]] = []
    for value_str, marker in rollups:
        if value_str:
            cells_data.append((value_str, marker))
        else:
            cells_data.append(("—", MARKER_EMPTY))
    values = [c[0] for c in cells_data]
    diverges_flags = _divergence_flags(values)
    cells_html = "".join(
        _cmp_value_cell_html(value, marker, diverges_flags[idx])
        for idx, (value, marker) in enumerate(cells_data)
    )
    return (
        '<tr class="cd-cmp__row cd-cmp__row--last">'
        f'<td class="cd-cmp__section" rowspan="1">{html.escape(section_name)}</td>'
        f'<td class="cd-cmp__feature">{html.escape(feature_label)}</td>'
        f"{cells_html}"
        "</tr>"
    )


def _cmp_rollup_rows_html(
    section_name: str,
    per_product_rows: list[list[tuple[str, str, str]]],
) -> list[str]:
    """Compare-grid ``<tr>`` strings for a multi-row rollup (I/O).

    ``per_product_rows[i]`` is the row-list for product ``i``. Each
    product is assumed to emit the same number of sub-rows in the same
    order (true of ``io.rollup_rows`` which always returns 4 entries).
    Each sub-row carries its own divergence cue across products.
    """
    if not per_product_rows:
        return []
    n_sub = len(per_product_rows[0])
    if n_sub == 0:
        return []
    out: list[str] = []
    for sub_idx in range(n_sub):
        per_prod = [rows[sub_idx] for rows in per_product_rows]
        label = per_prod[0][0]
        cells_data: list[tuple[str, str]] = []
        for _label, value_str, marker in per_prod:
            if value_str:
                cells_data.append((value_str, marker))
            else:
                cells_data.append(("—", MARKER_EMPTY))
        values = [c[0] for c in cells_data]
        diverges_flags = _divergence_flags(values)
        cells_html = "".join(
            _cmp_value_cell_html(value, marker, diverges_flags[idx])
            for idx, (value, marker) in enumerate(cells_data)
        )
        is_last = sub_idx == n_sub - 1
        row_cls = "cd-cmp__row cd-cmp__row--last" if is_last else "cd-cmp__row"
        section_cell = (
            f'<td class="cd-cmp__section" rowspan="{n_sub}">'
            f"{html.escape(section_name)}</td>"
            if sub_idx == 0
            else ""
        )
        out.append(
            f'<tr class="{row_cls}">'
            f"{section_cell}"
            f'<td class="cd-cmp__feature">{html.escape(label)}</td>'
            f"{cells_html}"
            "</tr>"
        )
    return out


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
    *,
    cpu_catalog: dict[str, dict[str, Any]] | None = None,
    gpu_catalog: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Return the full N-product side-by-side comparison grid HTML.

    Stage 10b: ``CPU`` and ``Graphics`` sections collapse to one rollup
    row each, divergence-marked the same way as per-cell rows.
    """
    if sections is None:
        sections = _SECTION_REGISTRY
    cpu_catalog = cpu_catalog or {}
    gpu_catalog = gpu_catalog or {}
    headers = [_product_header(p) for p in products]
    n_prod = len(products)
    body: list[str] = []
    for section_name, _fn in sections:
        if section_name not in _VISUAL_SECTIONS:
            continue
        if section_name == _IO_SECTION:
            per_product_rows = [io_view.rollup_rows(prod) for prod in products]
            body.extend(_cmp_rollup_rows_html(section_name, per_product_rows))
            continue
        rollups = [
            _rollup_for_section(section_name, prod, cpu_catalog, gpu_catalog)
            for prod in products
        ]
        body.append(
            _cmp_rollup_row_html(
                section_name,
                _ROLLUP_FEATURE_LABEL.get(section_name, section_name),
                rollups,
            )
        )
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


# ---------------------------------------------------------------------------
# Stage 10c additions: Compare ``+`` button styling + Find result cards
# ---------------------------------------------------------------------------


_COMPARE_STYLES_INJECTED_KEY = "__cd_compare_css_injected__"


def inject_compare_styles() -> None:
    """One-shot injection of Compare-screen scoped styles.

    Owns the ``+`` button restyle (faint accent fill, vertically centered)
    plus the faint horizontal connector line that runs behind the button
    across the picker stack. The button gets ``z-index: 2`` and a solid
    fill so the line visually passes behind it.
    """
    if st.session_state.get(_COMPARE_STYLES_INJECTED_KEY):
        return
    st.session_state[_COMPARE_STYLES_INJECTED_KEY] = True
    css = """
<style>
.cd-cmp-rail {
    position: relative;
    height: 1px;
    background: var(--cd-border);
    margin: var(--cd-space-md) 0;
}
.cd-cmp-add-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 120px;
    position: relative;
    z-index: 2;
}
.cd-cmp-add-wrap [data-testid="stButton"] > button {
    background: var(--cd-bg-accent-soft) !important;
    color: var(--cd-accent) !important;
    border: 1px solid var(--cd-border-strong) !important;
    border-radius: var(--cd-radius-pill) !important;
    width: 36px;
    height: 36px;
    padding: 0 !important;
    font-size: var(--cd-size-lg);
    font-weight: 600;
    line-height: 1;
    box-shadow: 0 0 0 4px var(--cd-bg-page);
}
.cd-cmp-add-wrap [data-testid="stButton"] > button:hover {
    background: var(--cd-bg-accent-soft-hover) !important;
}
</style>
"""
    st.markdown(css, unsafe_allow_html=True)


def find_rollup_for_section(
    section_name: str,
    product: dict[str, Any],
    cpu_catalog: dict[str, dict[str, Any]],
    gpu_catalog: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    """Public re-export of the per-section rollup dispatch.

    Find uses this to render the queried section's rolled-up value + marker
    inside each result card. I/O still routes through ``io.rollup_rows``
    upstream; callers decide whether to dispatch here or to that.
    """
    return _rollup_for_section(section_name, product, cpu_catalog, gpu_catalog)


def find_result_card_html(
    *,
    company: str,
    sub_brand: str | None,
    series: str | None,
    year: int | None,
    section_name: str,
    rollup_value: str,
    marker: str,
) -> str:
    """Render one horizontal Find result card.

    Layout: left identity strip · middle rolled-up section value · right
    marker dot. The ``Open →`` button is rendered separately by the
    caller in a Streamlit column so the click can hand back control to
    Python.
    """
    crumbs: list[str] = [html.escape(company)]
    if sub_brand:
        crumbs.append(html.escape(sub_brand))
    if series:
        crumbs.append(html.escape(series))
    if year is not None:
        crumbs.append(html.escape(str(year)))
    identity_html = (
        '<span class="cd-findcard__crumbs">'
        + (
            '<span class="cd-findcard__sep"> · </span>'.join(crumbs)
        )
        + "</span>"
    )
    value_str = rollup_value if rollup_value else "—"
    return (
        '<div class="cd-findcard">'
        '<div class="cd-findcard__identity">'
        f"{identity_html}"
        "</div>"
        '<div class="cd-findcard__rollup">'
        f'<span class="cd-findcard__section">{html.escape(section_name)}</span>'
        f'<span class="cd-findcard__value">{html.escape(value_str)}</span>'
        "</div>"
        f'<div class="cd-findcard__marker">{dot_marker(marker)}</div>'
        "</div>"
    )


_FIND_CARD_STYLES_INJECTED_KEY = "__cd_findcard_css_injected__"


def inject_findcard_styles() -> None:
    """One-shot injection of Find result-card layout styles."""
    if st.session_state.get(_FIND_CARD_STYLES_INJECTED_KEY):
        return
    st.session_state[_FIND_CARD_STYLES_INJECTED_KEY] = True
    css = """
<style>
.cd-findcard {
    display: grid;
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 2fr) auto;
    align-items: center;
    gap: var(--cd-space-lg);
    background: var(--cd-bg-card);
    border: 1px solid var(--cd-border);
    border-radius: var(--cd-radius-md);
    padding: var(--cd-space-md) var(--cd-space-lg);
    margin: var(--cd-space-sm) 0;
    font-size: var(--cd-size-sm);
}
.cd-findcard__identity {
    color: var(--cd-text);
    font-weight: 500;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.cd-findcard__sep {
    color: var(--cd-text-faint);
    font-weight: 400;
    margin: 0 var(--cd-space-xs);
}
.cd-findcard__rollup {
    display: flex;
    align-items: baseline;
    gap: var(--cd-space-md);
    min-width: 0;
    overflow: hidden;
}
.cd-findcard__section {
    color: var(--cd-text-faint);
    font-size: var(--cd-size-xs);
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.cd-findcard__value {
    color: var(--cd-text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.cd-findcard__marker {
    display: inline-flex;
    align-items: center;
    justify-content: center;
}
</style>
"""
    st.markdown(css, unsafe_allow_html=True)
