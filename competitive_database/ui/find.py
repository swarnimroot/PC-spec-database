"""Find products where… — single-field filter playground.

T8.4 scope: pick one path from the union of
``views.orchestrator.all_field_paths`` (offering indices collapsed to a
wildcard so the filter sweeps every instantiated offering), pick a
comparator, pick a value when the op needs one. Every product is
scanned; matches are grouped per-product with each matching cell
rendered as ``value [marker]`` inline.

T9.1 (Session 36): value input is a dropdown of distinct values present
in the DB for the chosen (section, field), not free text. The dropdown
is computed by ``_distinct_values_for_template`` over the same product
loop ``_render_matches`` uses; values are sorted numerically when
``_coerce_number`` succeeds, alphabetically (casefold) otherwise.

Read-only; reuses ``ui/_markers.resolve_path`` + ``render_cell``.

Catalog spec columns (e.g. ``cpu_catalog.npu_tops``) are not in the
``all_field_paths`` registry yet, so they're out of scope for this
filter. ``cpu_offerings.*.model`` with ``contains`` is the closest hook
for "CPU with NPU X" today; a registry extension would lift that
limitation later (no schema work needed — the catalog rows are already
loaded by ``views.load.load_cpu_catalog``).
"""

from __future__ import annotations

import html
import sqlite3
from typing import Any

import streamlit as st

from competitive_database.ui._markers import render_cell, resolve_path
from competitive_database.views import load, orchestrator
from competitive_database.views.formatting import display_value

_OP_EQ = "="
_OP_CONTAINS = "contains"
_OP_GE = "≥"
_OP_LE = "≤"
_OP_IS_SET = "is set"
_OP_IS_EMPTY = "is empty"
_OP_NO_PUB = "vendor doesn't publish"
_OPS_NEED_VALUE = {_OP_EQ, _OP_CONTAINS, _OP_GE, _OP_LE}
_OPS_ALL = [_OP_EQ, _OP_CONTAINS, _OP_GE, _OP_LE, _OP_IS_SET, _OP_IS_EMPTY, _OP_NO_PUB]


def _list_product_pks(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT model_code, year FROM products ORDER BY model_code, year"
    ).fetchall()
    return [(mc, yr) for mc, yr in rows]


def _load_all(
    conn: sqlite3.Connection, pks: list[tuple[str, int]]
) -> list[dict[str, Any]]:
    return [load.load_product(conn, mc, year=yr) for mc, yr in pks]


def _template_of(path: str) -> str:
    """Collapse offering index in a 3-part path to ``*``."""
    parts = path.split(".")
    if len(parts) == 3:
        return f"{parts[0]}.*.{parts[2]}"
    return path


def _union_templates(
    products: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Union of (section, template) across products, render order preserved.

    Templates collapse offering indices so the user picks one slot and the
    filter sweeps every instantiated offering on every product.
    """
    seen: set[tuple[str, str]] = set()
    section_order: list[str] = []
    section_templates: dict[str, list[str]] = {}
    for prod in products:
        for section, path, _label in orchestrator.all_field_paths(prod):
            template = _template_of(path)
            key = (section, template)
            if key in seen:
                continue
            seen.add(key)
            if section not in section_templates:
                section_order.append(section)
                section_templates[section] = []
            section_templates[section].append(template)
    out: list[tuple[str, str]] = []
    for section in section_order:
        for template in section_templates[section]:
            out.append((section, template))
    return out


def _expand_template(
    prod: dict[str, Any], template: str
) -> list[str]:
    """All concrete paths on ``prod`` that match ``template``."""
    parts = template.split(".")
    if "*" not in parts:
        return [template]
    col, _, leaf = parts
    offerings = prod.get(col)
    if not isinstance(offerings, list):
        return []
    return [f"{col}.{i}.{leaf}" for i in range(len(offerings))]


def _coerce_number(s: Any) -> float | None:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def _cell_matches(
    bundle: dict | None,
    plain: str | None,
    op: str,
    value: str,
) -> bool:
    if op == _OP_IS_EMPTY:
        if plain is not None:
            return False
        if bundle is None:
            return True
        if bundle.get("status") == "vendor-doesn't-publish":
            return False
        return bundle.get("value") is None
    if op == _OP_NO_PUB:
        return (
            bundle is not None
            and bundle.get("status") == "vendor-doesn't-publish"
        )
    if op == _OP_IS_SET:
        if plain is not None:
            return True
        if bundle is None:
            return False
        if bundle.get("status") == "vendor-doesn't-publish":
            return False
        return bundle.get("value") is not None

    # Value-comparing ops: need a concrete rendered value.
    if plain is not None:
        rendered = plain
    elif bundle is not None and bundle.get("status") != "vendor-doesn't-publish":
        if bundle.get("value") is None:
            return False
        rendered = display_value(bundle)
    else:
        return False

    if op == _OP_CONTAINS:
        return value.casefold() in rendered.casefold()
    if op == _OP_EQ:
        if rendered.casefold() == value.casefold():
            return True
        a, b = _coerce_number(rendered), _coerce_number(value)
        return a is not None and b is not None and a == b
    if op == _OP_GE:
        a, b = _coerce_number(rendered), _coerce_number(value)
        return a is not None and b is not None and a >= b
    if op == _OP_LE:
        a, b = _coerce_number(rendered), _coerce_number(value)
        return a is not None and b is not None and a <= b
    return False


def _distinct_values_for_template(
    products: list[dict[str, Any]], template: str
) -> list[str]:
    """Sorted distinct rendered values across products for this template.

    Mirrors the path-expansion loop in ``_render_matches`` but collects
    ``display_value(bundle)`` (or the ``plain`` string for plain-string
    leaves) instead of running an op against each cell. Skips empty
    cells, ``vendor doesn't publish`` placeholders, and bundles whose
    ``value`` is None so the dropdown only offers picks you could
    actually filter on.

    Sort order: numeric values first (by numeric value), then string
    values (alphabetically, case-insensitive).
    """
    seen: set[str] = set()
    for prod in products:
        for concrete_path in _expand_template(prod, template):
            bundle, plain = resolve_path(prod, concrete_path)
            if plain is not None:
                seen.add(plain)
                continue
            if bundle is None:
                continue
            if bundle.get("status") == "vendor-doesn't-publish":
                continue
            if bundle.get("value") is None:
                continue
            seen.add(display_value(bundle))

    def _sort_key(s: str) -> tuple[int, float | str]:
        n = _coerce_number(s)
        return (0, n) if n is not None else (1, s.casefold())

    return sorted(seen, key=_sort_key)


def _vendor_label(prod: dict[str, Any]) -> str | None:
    brand = prod.get("brand")
    if isinstance(brand, dict) and brand.get("value"):
        return str(brand["value"])
    return None


_RESULT_FONT = (
    "font-family:ui-monospace,Consolas,Menlo,monospace;"
    "font-size:0.85rem;line-height:1.55"
)


def _render_matches(
    products: list[dict[str, Any]],
    template: str,
    op: str,
    value: str,
) -> tuple[str, int, int]:
    """Render the result list HTML; also return (n_products, n_cells)."""
    blocks: list[str] = []
    n_products = 0
    n_cells = 0
    for prod in products:
        prod_matches: list[tuple[str, str]] = []
        for concrete_path in _expand_template(prod, template):
            bundle, plain = resolve_path(prod, concrete_path)
            if _cell_matches(bundle, plain, op, value):
                prod_matches.append((concrete_path, render_cell(bundle, plain)))
                n_cells += 1
        if not prod_matches:
            continue
        n_products += 1
        mc = html.escape(str(prod.get("model_code")))
        yr = html.escape(str(prod.get("year")))
        vendor = _vendor_label(prod)
        vendor_html = (
            f' <span style="color:#8b949e">({html.escape(vendor)})</span>'
            if vendor
            else ""
        )
        header = f"<div><strong>{mc} · {yr}</strong>{vendor_html}</div>"
        match_lines = "".join(
            f'<div style="padding-left:1.5rem">'
            f'<span style="color:#8b949e">{html.escape(p)}</span>: {c}</div>'
            for p, c in prod_matches
        )
        blocks.append(
            f'<div style="margin-bottom:0.75rem">{header}{match_lines}</div>'
        )
    body = "".join(blocks)
    return body, n_products, n_cells


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Find products where…")
    if st.button("← Hub"):
        st.session_state["view"] = "hub"
        st.rerun()

    pks = _list_product_pks(conn)
    if not pks:
        st.info("No products in the database yet.")
        return

    products = _load_all(conn, pks)
    paths = _union_templates(products)
    if not paths:
        st.info("No filterable cells in this database.")
        return

    sections: list[str] = []
    for section, _ in paths:
        if section not in sections:
            sections.append(section)

    c1, c2, c3 = st.columns([1, 2, 1])
    section = c1.selectbox("Section", sections)
    in_section = [t for s, t in paths if s == section]
    template = c2.selectbox(
        "Field",
        in_section,
        format_func=lambda t: t.replace(".*.", ".N."),
    )
    op = c3.selectbox("Op", _OPS_ALL)

    if op in _OPS_NEED_VALUE:
        values = _distinct_values_for_template(products, template)
        if not values:
            st.info(
                "No values to filter on for this field — no product has a "
                "filled, non-publish-skipped cell at this path."
            )
            st.caption(f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.4")
            return
        value = st.selectbox("Value", values, key="find-value-select")
    else:
        value = ""

    st.caption(
        "Tip: `is set` returns every product where this cell is populated "
        "(non-empty, non-publish-skipped) — covers \"which vendors publish "
        "this field\" use-case queries."
    )

    body, n_products, n_cells = _render_matches(products, template, op, value)
    if n_products == 0:
        st.info("0 products match.")
        st.caption(f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.4")
        return

    summary = f"{n_products} product{'s' if n_products != 1 else ''} match"
    if n_cells != n_products:
        summary += f" · {n_cells} matching cells"
    st.markdown(
        f'<div style="{_RESULT_FONT}">'
        f'<div style="margin-bottom:0.5rem"><strong>{html.escape(summary)}</strong></div>'
        f"{body}"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.caption(f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.4")
