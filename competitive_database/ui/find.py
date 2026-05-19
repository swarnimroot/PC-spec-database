"""Find products — single-spec query bar + result cards.

Phase E (Stage 10a) rewrite of the Find screen. The behavioral core —
``_cell_matches``, ``_expand_template``, ``_distinct_values_for_template``,
``_union_templates`` — is preserved unchanged; the presentation layer
moves from a 4-selectbox row + monospace grep dump to a labelled query
bar (Spec field / Match / Value) plus optional Company/Year narrow-by
chips plus result cards with dot markers and an ``Open →`` jump to
Browse.
"""

from __future__ import annotations

import html
import sqlite3
from typing import Any

import streamlit as st

from competitive_database.ui._components import (
    _product_name,
    dot_marker,
    friendly_field_label as _friendly_field_label,
    friendly_leaf_label as _friendly_leaf_label,
)
from competitive_database.ui._markers import resolve_path
from competitive_database.views import load, orchestrator
from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_VENDOR_NO_PUB,
    MARKER_VERIFIED,
    canonicalize_display,
    display_value,
    marker_for_bundle,
)


_OP_EQ = "="
_OP_CONTAINS = "contains"
_OP_GE = "≥"
_OP_LE = "≤"
_OP_IS_SET = "is set"
_OP_IS_EMPTY = "is empty"
_OP_NO_PUB = "vendor doesn't publish"
_OPS_NEED_VALUE = {_OP_EQ, _OP_CONTAINS, _OP_GE, _OP_LE}
_OPS_ALL = [_OP_EQ, _OP_GE, _OP_LE, _OP_CONTAINS, _OP_IS_SET, _OP_IS_EMPTY, _OP_NO_PUB]

# Plain-English op labels shown in the Match dropdown.
_OP_LABEL: dict[str, str] = {
    _OP_EQ: "equals",
    _OP_GE: "is at least",
    _OP_LE: "is at most",
    _OP_CONTAINS: "contains",
    _OP_IS_SET: "has any value",
    _OP_IS_EMPTY: "is empty",
    _OP_NO_PUB: "marked unavailable",
}
_LABEL_TO_OP: dict[str, str] = {label: op for op, label in _OP_LABEL.items()}
_OP_LABELS_ORDERED: list[str] = [_OP_LABEL[op] for op in _OPS_ALL]

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
    """Union of (section, template) across products, render order preserved."""
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
    field_path: str,
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

    if plain is not None:
        rendered = canonicalize_display(field_path, plain)
    elif bundle is not None and bundle.get("status") != "vendor-doesn't-publish":
        if bundle.get("value") is None:
            return False
        rendered = display_value(bundle, field_path=field_path)
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
    """Sorted distinct rendered values across products for this template."""
    seen: set[str] = set()
    for prod in products:
        for concrete_path in _expand_template(prod, template):
            bundle, plain = resolve_path(prod, concrete_path)
            if plain is not None:
                seen.add(canonicalize_display(template, plain))
                continue
            if bundle is None:
                continue
            if bundle.get("status") == "vendor-doesn't-publish":
                continue
            if bundle.get("value") is None:
                continue
            seen.add(display_value(bundle, field_path=template))

    def _sort_key(s: str) -> tuple[int, float | str]:
        n = _coerce_number(s)
        return (0, n) if n is not None else (1, s.casefold())

    return sorted(seen, key=_sort_key)


def _label_for_product(prod: dict[str, Any]) -> str:
    """Friendly ``Product Name · Year`` line for the result card header."""
    mc = str(prod.get("model_code") or "")
    yr_raw = prod.get("year")
    try:
        yr = int(yr_raw) if yr_raw is not None else 0
    except (TypeError, ValueError):
        yr = 0
    vfn_bundle = prod.get("vendor_full_name")
    vfn = None
    if isinstance(vfn_bundle, dict):
        v = vfn_bundle.get("value")
        if isinstance(v, str):
            vfn = v
    name = _product_name(vfn, mc, yr)
    return f"{name} · {yr}" if yr else name


def _brand_subbrand(prod: dict[str, Any]) -> str:
    """Right-aligned brand / sub-brand text for the card header."""
    brand = _scalar_bundle_str(prod.get("brand"))
    sub = _scalar_bundle_str(prod.get("sub_brand"))
    if brand and sub:
        return f"{brand} / {sub}"
    if brand:
        return brand
    if sub:
        return sub
    return ""


def _scalar_bundle_str(bundle: Any) -> str | None:
    if not isinstance(bundle, dict):
        return None
    v = bundle.get("value")
    if isinstance(v, str) and v:
        return v
    return None


def _company_of(prod: dict[str, Any]) -> str:
    return _scalar_bundle_str(prod.get("brand")) or "Unknown"


def _year_of(prod: dict[str, Any]) -> int | None:
    yr_raw = prod.get("year")
    try:
        return int(yr_raw) if yr_raw is not None else None
    except (TypeError, ValueError):
        return None


def _context_specs(prod: dict[str, Any]) -> str:
    """First CPU model + first board GPU model, joined with ``·``."""
    parts: list[str] = []
    cpus = prod.get("cpu_offerings") or []
    if cpus:
        cpu_bundle = cpus[0].get("model") if isinstance(cpus[0], dict) else None
        if isinstance(cpu_bundle, dict):
            v = display_value(cpu_bundle)
            if v:
                parts.append(v)
    boards = prod.get("boards") or []
    if boards:
        gpus = boards[0].get("gpus") if isinstance(boards[0], dict) else None
        if isinstance(gpus, list) and gpus:
            gpu_bundle = gpus[0]
            if isinstance(gpu_bundle, dict):
                v = display_value(gpu_bundle)
                if v:
                    parts.append(v)
    return " · ".join(parts)


def _format_match(
    bundle: dict | None, plain: str | None, field_path: str
) -> tuple[str, str]:
    """Return ``(value_str, marker_token)`` for a matched cell."""
    if plain is not None:
        return plain, MARKER_VERIFIED
    marker = marker_for_bundle(bundle)
    if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB):
        return ("vendor doesn't publish" if marker == MARKER_VENDOR_NO_PUB else "—"), marker
    value = display_value(bundle, field_path=field_path) or "—"
    return value, marker


def _find_matches(
    products: list[dict[str, Any]],
    template: str,
    op: str,
    value: str,
) -> list[tuple[dict[str, Any], str, str]]:
    """Return matched products with one representative ``(value, marker)`` each.

    A product matches if at least one concrete path on it satisfies the
    op. The representative is taken from the first matching cell so each
    card shows one line, not a sub-list.
    """
    out: list[tuple[dict[str, Any], str, str]] = []
    for prod in products:
        for concrete_path in _expand_template(prod, template):
            bundle, plain = resolve_path(prod, concrete_path)
            if _cell_matches(bundle, plain, op, value, concrete_path):
                vstr, marker = _format_match(bundle, plain, concrete_path)
                out.append((prod, vstr, marker))
                break
    return out


def _render_card(
    prod: dict[str, Any],
    spec_label: str,
    value_str: str,
    marker: str,
) -> None:
    """Render one result card; wire the ``Open →`` button to jump to Browse."""
    name_year = _label_for_product(prod)
    brand_sub = _brand_subbrand(prod)
    context = _context_specs(prod)

    body_lines: list[str] = []
    body_lines.append(
        '<div class="cd-find__card-header">'
        f'<div class="cd-find__card-title">{html.escape(name_year)}</div>'
        f'<div class="cd-find__card-brand">{html.escape(brand_sub)}</div>'
        "</div>"
    )
    body_lines.append(
        '<div class="cd-find__card-match">'
        f'<span class="cd-find__card-feature">{html.escape(spec_label)}</span>'
        '<span class="cd-find__card-sep"></span>'
        f"{dot_marker(marker)}"
        f'<span class="cd-find__card-value">{html.escape(value_str)}</span>'
        "</div>"
    )
    if context:
        body_lines.append(
            f'<div class="cd-find__card-context">{html.escape(context)}</div>'
        )

    body_html = (
        '<div class="cd-find__card">' + "".join(body_lines) + "</div>"
    )

    container = st.container()
    with container:
        cols = st.columns([5, 1])
        with cols[0]:
            st.markdown(body_html, unsafe_allow_html=True)
        with cols[1]:
            mc = prod.get("model_code")
            yr = _year_of(prod)
            key = f"find.open.{mc}.{yr}"
            if st.button("Open →", key=key, use_container_width=True):
                _open_in_browse(prod)


def _open_in_browse(prod: dict[str, Any]) -> None:
    """Wire Browse's cascading-picker session keys and switch view."""
    company = _company_of(prod)
    mc = str(prod.get("model_code") or "")
    yr = _year_of(prod)
    vfn = _scalar_bundle_str(prod.get("vendor_full_name"))
    product_name = _product_name(vfn, mc, yr or 0)
    st.session_state["browse.company"] = company
    st.session_state["browse.product"] = product_name
    if yr is not None:
        st.session_state["browse.year"] = yr
    st.session_state["view"] = "browse"
    st.rerun()


_CARD_CSS = """
<style>
.cd-find__card {
    background: var(--cd-bg-card);
    border: 1px solid var(--cd-border);
    border-radius: var(--cd-radius-md);
    padding: var(--cd-space-md) var(--cd-space-lg);
    margin: var(--cd-space-sm) 0;
}
.cd-find__card-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--cd-space-md);
    margin-bottom: var(--cd-space-xs);
}
.cd-find__card-title {
    font-size: var(--cd-size-base);
    font-weight: 600;
    color: var(--cd-text);
}
.cd-find__card-brand {
    font-size: var(--cd-size-sm);
    color: var(--cd-text-muted);
}
.cd-find__card-match {
    display: flex;
    align-items: center;
    gap: var(--cd-space-xs);
    font-size: var(--cd-size-sm);
    color: var(--cd-text);
    margin-bottom: var(--cd-space-xs);
}
.cd-find__card-feature {
    color: var(--cd-text-muted);
    margin-right: var(--cd-space-sm);
}
.cd-find__card-sep {
    width: var(--cd-space-xs);
}
.cd-find__card-value {
    font-weight: 500;
}
.cd-find__card-context {
    font-size: var(--cd-size-sm);
    color: var(--cd-text-muted);
}
.cd-find__label {
    color: var(--cd-text-faint);
    font-size: var(--cd-size-xs);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 500;
    margin-bottom: var(--cd-space-xs);
}
.cd-find__title {
    font-size: var(--cd-size-xl);
    font-weight: 600;
    color: var(--cd-text);
    margin-bottom: var(--cd-space-xs);
}
.cd-find__subtitle {
    font-size: var(--cd-size-sm);
    color: var(--cd-text-muted);
    margin-bottom: var(--cd-space-lg);
}
.cd-find__count {
    font-size: var(--cd-size-lg);
    font-weight: 500;
    color: var(--cd-text);
    margin: var(--cd-space-lg) 0 var(--cd-space-sm) 0;
}
.cd-find__count--empty {
    color: var(--cd-text-muted);
}
.cd-find__narrow-label {
    color: var(--cd-text-faint);
    font-size: var(--cd-size-xs);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 500;
    margin-top: var(--cd-space-md);
}
</style>
"""


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the Find-products screen."""
    del db_path  # chrome handles attribution; no internal IDs leak here.

    st.markdown(_CARD_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="cd-find__title">Find products</div>'
        '<div class="cd-find__subtitle">'
        "Build a query to surface laptops matching a single spec."
        "</div>",
        unsafe_allow_html=True,
    )

    pks = _list_product_pks(conn)
    if not pks:
        st.info("No products in the database yet.")
        return

    products = _load_all(conn, pks)
    paths = _union_templates(products)
    if not paths:
        st.info("No filterable cells in this database.")
        return

    # Build the flat Spec-field options: ``"Section · Feature"`` labels in
    # render order, with a parallel map back to (section, template).
    spec_options: list[str] = []
    spec_lookup: dict[str, tuple[str, str]] = {}
    for section, template in paths:
        label = _friendly_field_label(section, template)
        # Disambiguate the (rare) duplicate-label case by appending the
        # raw leaf — keeps the dropdown stable when two sections happen
        # to share a friendly name.
        suffix = 1
        unique = label
        while unique in spec_lookup:
            suffix += 1
            unique = f"{label} ({suffix})"
        spec_options.append(unique)
        spec_lookup[unique] = (section, template)

    # Op label currently picked; default ``equals``.
    op_default_label = _OP_LABEL[_OP_EQ]
    op_state_key = "find.op_label"
    op_current = st.session_state.get(op_state_key, op_default_label)
    needs_value = _LABEL_TO_OP[op_current] in _OPS_NEED_VALUE

    # Query bar: Spec field / Match / Value (Value hidden when n/a).
    if needs_value:
        c_field, c_op, c_value = st.columns([2, 2, 2])
    else:
        c_field, c_op = st.columns([2, 2])
        c_value = None

    with c_field:
        st.markdown('<div class="cd-find__label">Spec field</div>', unsafe_allow_html=True)
        spec_label = st.selectbox(
            "Spec field",
            spec_options,
            key="find.spec_field",
            label_visibility="collapsed",
        )

    with c_op:
        st.markdown('<div class="cd-find__label">Match</div>', unsafe_allow_html=True)
        op_label = st.selectbox(
            "Match",
            _OP_LABELS_ORDERED,
            key=op_state_key,
            label_visibility="collapsed",
        )
    op = _LABEL_TO_OP[op_label]

    section, template = spec_lookup[spec_label]

    value = ""
    if op in _OPS_NEED_VALUE and c_value is not None:
        values = _distinct_values_for_template(products, template)
        with c_value:
            st.markdown('<div class="cd-find__label">Value</div>', unsafe_allow_html=True)
            if values:
                value = st.selectbox(
                    "Value",
                    values,
                    key="find.value_select",
                    label_visibility="collapsed",
                )
            else:
                st.markdown(
                    '<div style="font-size:var(--cd-size-sm);'
                    'color:var(--cd-text-muted);'
                    'padding-top:var(--cd-space-xs);">'
                    "No values to filter on for this field."
                    "</div>",
                    unsafe_allow_html=True,
                )
                value = ""
                # Render the narrow-by row + zero-result line anyway, so
                # the layout doesn't collapse on the user.
                _render_narrow_by(products)
                st.markdown(
                    '<div class="cd-find__count cd-find__count--empty">'
                    "No products match this query.</div>",
                    unsafe_allow_html=True,
                )
                return

    # Narrow-by chip row.
    company_filter, year_filter = _render_narrow_by(products)

    # Compute matches, then apply narrow-by filters.
    matches = _find_matches(products, template, op, value)
    if company_filter != "(any)":
        matches = [m for m in matches if _company_of(m[0]) == company_filter]
    if year_filter != "(any)":
        matches = [m for m in matches if _year_of(m[0]) == year_filter]

    n = len(matches)
    if n == 0:
        st.markdown(
            '<div class="cd-find__count cd-find__count--empty">'
            "No products match this query.</div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div class="cd-find__count">{n} product{"s" if n != 1 else ""} match</div>',
        unsafe_allow_html=True,
    )

    feature_label = _friendly_leaf_label(template.split(".")[-1], section)
    spec_card_label = f"{section} {feature_label.lower()}"

    for prod, vstr, marker in matches:
        _render_card(prod, spec_card_label, vstr, marker)


def _render_narrow_by(
    products: list[dict[str, Any]],
) -> tuple[str, int | str]:
    """Render the optional Company/Year filter chips; return current picks."""
    st.markdown(
        '<div class="cd-find__narrow-label">Narrow by</div>',
        unsafe_allow_html=True,
    )
    companies = sorted({_company_of(p) for p in products}, key=str.lower)
    years_int = sorted({_year_of(p) for p in products if _year_of(p) is not None}, reverse=True)
    company_opts = ["(any)"] + companies
    year_opts: list[Any] = ["(any)"] + years_int

    c1, c2, _ = st.columns([1, 1, 2])
    with c1:
        company = st.selectbox(
            "Company",
            company_opts,
            key="find.narrow.company",
            label_visibility="visible",
        )
    with c2:
        year = st.selectbox(
            "Year",
            year_opts,
            key="find.narrow.year",
            label_visibility="visible",
        )
    return company, year
