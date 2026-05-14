"""Browse one product — Company → Product → Year picker + spec table.

Session 40 refresh: replaced the inline wall-of-text dump with a three-level
cascading picker (brand → year-stripped product name → year) and a
Section / Feature / Value HTML table with rowspan-merged section cells.
Identity rows moved out of the table into a context strip above it
(sub-brand / series / status / segment); vendor + brand + year are folded
into the dropdowns themselves.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
from typing import Any

import streamlit as st

from competitive_database.ui._markers import MARKER_COLORS, resolve_path
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


_HEADER_IDENTITY_LEAVES: list[tuple[str, str]] = [
    ("sub-brand", "sub_brand"),
    ("series", "series"),
    ("status", "status"),
    ("segment", "segment"),
]

_MARKER_LABEL: dict[str, str] = {
    MARKER_VERIFIED: "verified",
    MARKER_NEEDS_REVIEW: "needs review",
    MARKER_VENDOR_NO_PUB: "vendor n/p",
    MARKER_MANUAL: "manual",
    MARKER_EMPTY: "empty",
    MARKER_PARTIAL: "partial",
}

_YEAR_TOKEN = re.compile(r"\s*[\(\[]?\s*\b(?P<year>20\d{2})\b\s*[\)\]]?\s*")


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


def _marker_view(marker: str) -> tuple[str, str]:
    return _MARKER_LABEL.get(marker, marker), MARKER_COLORS.get(marker, "#8b949e")


def _format_cell(product: dict[str, Any], path: str) -> tuple[str, str, str]:
    bundle, plain = resolve_path(product, path)
    if plain is not None:
        return plain, "", ""
    marker = marker_for_bundle(bundle)
    label, color = _marker_view(marker)
    if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB):
        return "—", label, color
    value = display_value(bundle, field_path=path) or "—"
    return value, label, color


def _row_html(
    section_label: str,
    rowspan: int,
    feature: str,
    value: str,
    marker_label: str,
    marker_color: str,
    last_in_section: bool,
) -> str:
    border_b = "2px solid #30363d" if last_in_section else "1px solid #21262d"
    section_cell = ""
    if section_label:
        section_cell = (
            f'<td rowspan="{rowspan}" style="padding:0.6rem 1rem 0.6rem 0;'
            "vertical-align:top;font-weight:600;color:#e6edf3;"
            "border-right:1px solid #30363d;width:13%;font-size:0.92rem;"
            'letter-spacing:0.01em">'
            f"{html.escape(section_label)}</td>"
        )
    marker_html = ""
    if marker_label:
        marker_html = (
            f'<span style="color:{marker_color};margin-left:0.85rem;'
            'font-size:0.74rem;letter-spacing:0.04em;font-weight:500">'
            f"{html.escape(marker_label)}</span>"
        )
    return (
        f'<tr style="border-bottom:{border_b}">'
        f"{section_cell}"
        f'<td style="padding:0.5rem 1rem;vertical-align:top;color:#8b949e;'
        'width:26%">'
        f"{html.escape(feature)}</td>"
        f'<td style="padding:0.5rem 0;vertical-align:top;color:#c9d1d9">'
        f"{html.escape(value)}{marker_html}</td>"
        "</tr>"
    )


def _build_table_html(product: dict[str, Any]) -> str:
    body: list[str] = []
    for section_name, fn in _SECTION_REGISTRY:
        if section_name == "Identity":
            continue
        paths = fn(product)
        if not paths:
            empty_label, empty_color = _marker_view(MARKER_EMPTY)
            body.append(
                _row_html(
                    section_name,
                    1,
                    "(no data scraped)",
                    "—",
                    empty_label,
                    empty_color,
                    True,
                )
            )
            continue
        n = len(paths)
        for i, (path, feature_label) in enumerate(paths):
            value, marker_label, marker_color = _format_cell(product, path)
            body.append(
                _row_html(
                    section_name if i == 0 else "",
                    n,
                    feature_label,
                    value,
                    marker_label,
                    marker_color,
                    i == n - 1,
                )
            )
    table_css = (
        "border-collapse:collapse;width:100%;"
        "font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"
        "system-ui,sans-serif;font-size:0.9rem;line-height:1.5;"
        "margin-top:0.5rem"
    )
    head_th = (
        "text-align:left;padding:0.55rem 1rem 0.55rem 0;"
        "border-bottom:1px solid #30363d;color:#8b949e;font-weight:600;"
        "font-size:0.72rem;letter-spacing:0.07em;text-transform:uppercase"
    )
    return (
        f'<table style="{table_css}">'
        "<thead><tr>"
        f'<th style="{head_th}">Section</th>'
        f'<th style="{head_th};padding-left:1rem">Feature</th>'
        f'<th style="{head_th};padding-right:0">Value</th>'
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table>"
    )


def _identity_header_html(product: dict[str, Any]) -> str:
    items: list[str] = []
    for label, key in _HEADER_IDENTITY_LEAVES:
        bundle = product.get(key)
        if isinstance(bundle, dict):
            marker = marker_for_bundle(bundle)
            marker_label, color = _marker_view(marker)
            if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB):
                value_str = "—"
            else:
                value_str = display_value(bundle) or "—"
        else:
            marker_label, color = _marker_view(MARKER_EMPTY)
            value_str = "—"
        items.append(
            '<div style="display:flex;flex-direction:column;min-width:9rem">'
            '<div style="color:#6e7681;font-size:0.7rem;letter-spacing:0.06em;'
            'text-transform:uppercase;margin-bottom:0.2rem">'
            f"{html.escape(label)}</div>"
            '<div style="color:#e6edf3;font-size:0.95rem">'
            f"{html.escape(value_str)}"
            f'<span style="color:{color};font-size:0.72rem;margin-left:0.45rem;'
            'font-weight:500">'
            f"{html.escape(marker_label)}</span></div>"
            "</div>"
        )
    return (
        '<div style="display:flex;gap:2rem;flex-wrap:wrap;padding:0.95rem 1.1rem;'
        "background:#0d1117;border:1px solid #21262d;border-radius:6px;"
        'margin:0.75rem 0 1.25rem 0">'
        f"{''.join(items)}"
        "</div>"
    )


def _marker_legend_html() -> str:
    entries = [
        (MARKER_VERIFIED, "verified"),
        (MARKER_NEEDS_REVIEW, "needs review"),
        (MARKER_VENDOR_NO_PUB, "vendor doesn't publish"),
        (MARKER_MANUAL, "manual entry"),
        (MARKER_EMPTY, "empty"),
        (MARKER_PARTIAL, "partial"),
    ]
    parts: list[str] = []
    for marker, descr in entries:
        color = MARKER_COLORS[marker]
        parts.append(
            '<span style="display:inline-flex;align-items:center;'
            'margin-right:1.4rem;margin-top:0.25rem">'
            f'<span style="width:0.5rem;height:0.5rem;background:{color};'
            'border-radius:50%;margin-right:0.45rem"></span>'
            f'<span style="color:#8b949e">{html.escape(descr)}</span>'
            "</span>"
        )
    return (
        '<div style="font-size:0.75rem;margin-top:1.25rem;'
        'padding-top:0.75rem;border-top:1px solid #21262d">'
        f"{''.join(parts)}"
        "</div>"
    )


def _reset_product_year() -> None:
    for k in ("browse_product", "browse_year"):
        st.session_state.pop(k, None)


def _reset_year() -> None:
    st.session_state.pop("browse_year", None)


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Browse one product")
    if st.button("← Hub"):
        st.session_state["view"] = "hub"
        st.rerun()

    products = _list_products(conn)
    if not products:
        st.info("No products in the database yet.")
        return

    companies = sorted({p["brand"] for p in products}, key=str.lower)
    c1, c2, c3 = st.columns([1, 2, 1])

    with c1:
        company = st.selectbox(
            "Company",
            companies,
            key="browse_company",
            on_change=_reset_product_year,
        )

    company_products = [p for p in products if p["brand"] == company]
    product_names = sorted(
        {p["product_name"] for p in company_products}, key=str.lower
    )

    with c2:
        product_name = st.selectbox(
            "Product",
            product_names,
            key="browse_product",
            on_change=_reset_year,
        )

    matches = [p for p in company_products if p["product_name"] == product_name]
    years = sorted({p["year"] for p in matches}, reverse=True)

    with c3:
        year = st.selectbox("Year", years, key="browse_year")

    chosen = next((p for p in matches if p["year"] == year), None)
    if chosen is None:
        st.info("No products matched the picker selection.")
        return

    product = load.load_product(conn, chosen["model_code"], year=chosen["year"])

    st.markdown(_identity_header_html(product), unsafe_allow_html=True)
    st.markdown(_build_table_html(product), unsafe_allow_html=True)
    st.markdown(_marker_legend_html(), unsafe_allow_html=True)
    st.caption(f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.1")
