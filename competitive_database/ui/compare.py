"""Compare side-by-side — multi-product grid with filter bar.

T8.3 scope: multiselect over ``(model_code, year)`` -> HTML grid (products
as columns, fields as rows) using ``views.orchestrator.all_field_paths``
for the row registry (unioned across selected products, section order +
first-appearance preserved). Vendor / segment / status selectboxes
narrow the multiselect pool. Read-only; reuses ``views.load.load_product``
and the six provenance markers from ``views.formatting``.

Marker color map is duplicated from ``ui/browse.py``; converge into a
shared helper once a third screen needs it (T8.4 / T8.5).
"""

from __future__ import annotations

import html
import json
import sqlite3
from typing import Any, Optional

import streamlit as st

from competitive_database.views import load, orchestrator
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

_MARKER_COLORS: dict[str, str] = {
    MARKER_VERIFIED: "#3fb950",
    MARKER_NEEDS_REVIEW: "#d29922",
    MARKER_VENDOR_NO_PUB: "#8b949e",
    MARKER_MANUAL: "#58a6ff",
    MARKER_EMPTY: "#6e7681",
    MARKER_PARTIAL: "#d29922",
}

_ALL = "(All)"


def _bundle_value(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    try:
        b = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(b, dict) and b.get("value") is not None:
        return str(b["value"])
    return None


def _list_products_with_facets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    # Vendor filter reads ``brand`` (the OEM: Dell / ASUS / Lenovo / HP),
    # not ``vendor_full_name`` (which stores the per-product marketing
    # title, e.g. "Alienware 18 Area-51 Gaming Laptop"). The PRD line
    # 136 phrasing "filter bar (vendor / ...)" maps to the OEM in the
    # user mental model; ``vendor_full_name`` would offer per-row strings
    # that each match exactly one product, defeating the filter.
    rows = conn.execute(
        "SELECT model_code, year, brand, segment, status "
        "FROM products ORDER BY model_code, year"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for mc, yr, brand, segment, status_ in rows:
        out.append(
            {
                "model_code": mc,
                "year": yr,
                "vendor": _bundle_value(brand),
                "segment": _bundle_value(segment),
                "status": _bundle_value(status_),
            }
        )
    return out


def _facet_values(rows: list[dict[str, Any]], key: str) -> list[str]:
    return sorted({r[key] for r in rows if r[key] is not None})


def _apply_filters(
    rows: list[dict[str, Any]],
    vendor: str,
    segment: str,
    status: str,
) -> list[dict[str, Any]]:
    def keep(r: dict[str, Any]) -> bool:
        if vendor != _ALL and r["vendor"] != vendor:
            return False
        if segment != _ALL and r["segment"] != segment:
            return False
        if status != _ALL and r["status"] != status:
            return False
        return True

    return [r for r in rows if keep(r)]


def _union_field_paths(
    products: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """Union of ``all_field_paths`` across products.

    Preserves section order (from the orchestrator registry, fixed by the
    first product) and within-section first-appearance order. Lets the
    grid grow rows as products with deeper offerings are added without
    breaking the inspect-product section spine.
    """
    section_order: list[str] = []
    section_paths: dict[str, list[tuple[str, str]]] = {}
    section_seen: dict[str, set[str]] = {}
    for prod in products:
        for section, path, label in orchestrator.all_field_paths(prod):
            if section not in section_seen:
                section_order.append(section)
                section_seen[section] = set()
                section_paths[section] = []
            if path in section_seen[section]:
                continue
            section_seen[section].add(path)
            section_paths[section].append((path, label))
    out: list[tuple[str, str, str]] = []
    for section in section_order:
        for path, label in section_paths[section]:
            out.append((section, path, label))
    return out


def _resolve_path(
    product: dict[str, Any],
    path: str,
) -> tuple[Optional[dict], Optional[str]]:
    """Return ``(bundle, plain)`` for one path on a loaded product.

    Exactly one of the two is non-None when the cell is present, else
    ``(None, None)``. Plain-string leaves (e.g. ``boards.N.arch_marker``)
    take the second slot; everything else is bundle-shaped.
    """
    parts = path.split(".")
    if len(parts) == 1:
        val = product.get(parts[0])
        if isinstance(val, dict):
            return val, None
        return None, None
    if len(parts) == 3:
        col, idx_s, leaf = parts
        offerings = product.get(col)
        if not isinstance(offerings, list):
            return None, None
        try:
            idx = int(idx_s)
        except ValueError:
            return None, None
        if idx >= len(offerings):
            return None, None
        leaf_val = offerings[idx].get(leaf)
        if isinstance(leaf_val, dict):
            return leaf_val, None
        if isinstance(leaf_val, str) and leaf_val:
            return None, leaf_val
        return None, None
    return None, None


def _render_cell(bundle: Optional[dict], plain: Optional[str]) -> str:
    if plain is not None:
        return html.escape(plain)
    marker = marker_for_bundle(bundle)
    color = _MARKER_COLORS[marker]
    marker_html = f'<span style="color:{color}">{html.escape(marker)}</span>'
    value = display_value(bundle)
    if not value:
        return marker_html
    return f"{html.escape(value)} {marker_html}"


_TABLE_CSS = (
    "border-collapse:collapse;"
    "font-family:ui-monospace,Consolas,Menlo,monospace;"
    "font-size:0.85rem;line-height:1.45;width:100%"
)
_BASE_CELL_CSS = (
    "border:1px solid #30363d;padding:0.25rem 0.5rem;vertical-align:top;"
    "white-space:pre-wrap;word-break:break-word"
)
_HEAD_CELL_CSS = _BASE_CELL_CSS + ";background:#161b22;font-weight:600;text-align:left"
_FIELD_CELL_CSS = _BASE_CELL_CSS + ";color:#8b949e;white-space:nowrap"
_SECTION_HEADER_CSS = (
    _BASE_CELL_CSS
    + ";background:#0d1117;font-weight:700;color:#c9d1d9;"
    "letter-spacing:0.04em;text-transform:uppercase;font-size:0.8rem"
)


def _render_grid_html(
    products: list[dict[str, Any]],
    columns: list[tuple[str, int]],
    rows: list[tuple[str, str, str]],
) -> str:
    head_cells = [f'<th style="{_HEAD_CELL_CSS}">Field</th>']
    for mc, yr in columns:
        head_cells.append(
            f'<th style="{_HEAD_CELL_CSS}">{html.escape(mc)}'
            f'<br><span style="color:#8b949e;font-weight:400">{yr}</span></th>'
        )

    ncols = 1 + len(columns)
    body_rows: list[str] = []
    last_section: Optional[str] = None
    for section, path, label in rows:
        if section != last_section:
            body_rows.append(
                f'<tr><td colspan="{ncols}" style="{_SECTION_HEADER_CSS}">'
                f'{html.escape(section)}</td></tr>'
            )
            last_section = section
        cells = [f'<td style="{_FIELD_CELL_CSS}">{html.escape(label)}</td>']
        for prod in products:
            bundle, plain = _resolve_path(prod, path)
            cells.append(
                f'<td style="{_BASE_CELL_CSS}">{_render_cell(bundle, plain)}</td>'
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    return (
        f'<div style="overflow-x:auto">'
        f'<table style="{_TABLE_CSS}">'
        f'<thead><tr>{"".join(head_cells)}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        f'</table></div>'
    )


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Compare side-by-side")
    if st.button("← Hub"):
        st.session_state["view"] = "hub"
        st.rerun()

    all_rows = _list_products_with_facets(conn)
    if not all_rows:
        st.info("No products in the database yet.")
        return

    c1, c2, c3 = st.columns(3)
    vendor = c1.selectbox("Vendor", [_ALL] + _facet_values(all_rows, "vendor"))
    segment = c2.selectbox("Segment", [_ALL] + _facet_values(all_rows, "segment"))
    status = c3.selectbox("Status", [_ALL] + _facet_values(all_rows, "status"))

    filtered = _apply_filters(all_rows, vendor, segment, status)
    options = [f"{r['model_code']} · {r['year']}" for r in filtered]
    option_to_row = {opt: r for opt, r in zip(options, filtered)}

    selected = st.multiselect(
        "Products to compare",
        options,
        default=[],
        help="Pick one or more products; rows are the union of fillable cells across them.",
    )

    if not selected:
        st.info("Pick at least one product to render the grid.")
        st.caption(f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.3")
        return

    products: list[dict[str, Any]] = []
    columns: list[tuple[str, int]] = []
    for label in selected:
        row = option_to_row[label]
        products.append(load.load_product(conn, row["model_code"], year=row["year"]))
        columns.append((row["model_code"], row["year"]))

    rows = _union_field_paths(products)
    grid_html = _render_grid_html(products, columns, rows)
    st.markdown(grid_html, unsafe_allow_html=True)
    st.caption(f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.3")
