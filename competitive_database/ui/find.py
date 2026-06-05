"""Find products — searchable spec-field + Match + Value query → results table.

The behavioral core — ``_cell_matches``, ``_expand_template``,
``_distinct_values_for_template``, ``_union_templates`` — is unchanged.
The query is one searchable "Section · Feature" field + a Match operator
+ a Value; narrow-by uses the single-search product combobox + Year +
Status toggles. Results render as a table; per-row ``Open →`` loads one
product into Spec Roster, and "Compare selected (N) →" loads the ticked
rows (1–4) as Spec Roster compare columns.
"""

from __future__ import annotations

import html
import sqlite3
from typing import Any

import streamlit as st

from competitive_database.ui._components import (
    _value_cell_html,
    friendly_field_label,
    product_search_picker,
    status_toggle_block,
    year_toggle_block,
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

# Spec Roster's compare grid caps at four columns.
_MAX_COMPARE = 4

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


def _scalar_bundle_str(bundle: Any) -> str | None:
    if not isinstance(bundle, dict):
        return None
    v = bundle.get("value")
    if isinstance(v, str) and v:
        return v
    return None


def _company_of(prod: dict[str, Any]) -> str:
    return _scalar_bundle_str(prod.get("brand")) or "Unknown"


def _sub_brand_of(prod: dict[str, Any]) -> str | None:
    return _scalar_bundle_str(prod.get("sub_brand"))


def _series_of(prod: dict[str, Any]) -> str | None:
    return _scalar_bundle_str(prod.get("series"))


def _year_of(prod: dict[str, Any]) -> int | None:
    yr_raw = prod.get("year")
    try:
        return int(yr_raw) if yr_raw is not None else None
    except (TypeError, ValueError):
        return None


def _status_of(prod: dict[str, Any]) -> str | None:
    return _scalar_bundle_str(prod.get("status"))


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


def _open_in_spec_roster(prods: list[dict[str, Any]]) -> None:
    """Load up to four matched products into Spec Roster as columns.

    Sets the Spec Roster column ids + each column's combobox search key
    (the ``Brand · Series · Product`` label, matching the picker's option
    labels) and switches the view. One product → single-column roomy
    view; several → the comparison grid.
    """
    prods = prods[:4]
    ids = list(range(1, len(prods) + 1))
    st.session_state["spec_roster.column_ids"] = ids
    for cid, prod in zip(ids, prods):
        brand = _company_of(prod)
        series = _series_of(prod)
        product = prod.get("product")
        label = " · ".join(p for p in [brand, series, product] if p)
        st.session_state[f"spec_roster.col{cid}.search"] = label
    # Spec Roster lives inline on the hub.
    st.session_state["view"] = "hub"
    st.session_state["hub.section"] = "spec_roster"
    st.rerun()


_FIND_CHROME_CSS = """
<style>
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

    st.markdown(_FIND_CHROME_CSS, unsafe_allow_html=True)
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

    # ---- Filter: searchable spec-field + Match + Value ----
    field_options: list[str] = []
    label_to_entry: dict[str, tuple[str, str]] = {}
    for sec, tmpl in paths:
        lbl = friendly_field_label(sec, tmpl)
        label_to_entry[lbl] = (sec, tmpl)
        field_options.append(lbl)

    c_field, c_op, c_value = st.columns([3, 2, 2])
    with c_field:
        st.markdown('<div class="cd-find__label">Find</div>', unsafe_allow_html=True)
        field_label = st.selectbox(
            "Spec field",
            field_options,
            index=None,
            placeholder="Search a spec field…",
            key="find.field",
            label_visibility="collapsed",
        )
    if field_label is None:
        st.info("Pick a spec field to search on.")
        return
    section, template = label_to_entry[field_label]

    with c_op:
        st.markdown('<div class="cd-find__label">Match</div>', unsafe_allow_html=True)
        op_label = st.selectbox(
            "Match",
            _OP_LABELS_ORDERED,
            key="find.op_label",
            label_visibility="collapsed",
        )
    op = _LABEL_TO_OP[op_label]

    value = ""
    inline_empty = False
    if op in _OPS_NEED_VALUE:
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
                inline_empty = True
                st.markdown(
                    '<div style="font-size:var(--cd-size-sm);'
                    'color:var(--cd-text-muted);'
                    'padding-top:var(--cd-space-xs);">'
                    "No values to filter on for this field."
                    "</div>",
                    unsafe_allow_html=True,
                )
                value = ""

    if inline_empty:
        _render_narrow_by(conn, [])
        st.markdown(
            '<div class="cd-find__count cd-find__count--empty">'
            "No products match this query.</div>",
            unsafe_allow_html=True,
        )
        return

    # ---- Narrow-by, scoped to products consistent with the query ----
    # Year/status pill options are scoped to ``base_matches`` (products
    # matching the Section/Feature/Match/Value query) so each axis only
    # surfaces values that would actually narrow the result set.
    matches = _find_matches(products, template, op, value)
    brand_pick, series_pick, product_pick, active_years, active_statuses = (
        _render_narrow_by(conn, [m[0] for m in matches])
    )

    if brand_pick is not None:
        matches = [m for m in matches if _company_of(m[0]) == brand_pick]
    if series_pick is not None:
        matches = [m for m in matches if _series_of(m[0]) == series_pick]
    if product_pick is not None:
        matches = [m for m in matches if m[0].get("product") == product_pick]
    if active_years:
        year_set = set(active_years)
        matches = [m for m in matches if _year_of(m[0]) in year_set]
    if active_statuses:
        status_set = set(active_statuses)
        matches = [
            m for m in matches
            if (_status_of(m[0]) or "Active") in status_set
        ]

    n = len(matches)
    if n == 0:
        st.markdown(
            '<div class="cd-find__count cd-find__count--empty">'
            "No products match this query.</div>",
            unsafe_allow_html=True,
        )
        return

    # Which rows are currently ticked (stable per-product checkbox keys).
    selected: list[dict[str, Any]] = []
    for prod, _vstr, _marker in matches:
        mc = prod.get("model_code")
        yr = _year_of(prod)
        if st.session_state.get(f"find.pick.{mc}.{yr}"):
            selected.append(prod)
    sel_n = len(selected)
    over_cap = sel_n > _MAX_COMPARE

    bar_l, bar_r = st.columns([3, 2])
    with bar_l:
        st.markdown(
            f'<div class="cd-find__count">{n} product{"s" if n != 1 else ""} match</div>',
            unsafe_allow_html=True,
        )
    with bar_r:
        if over_cap:
            st.button(
                f"Compare selected ({sel_n}) → · max 4 — untick one",
                key="find.compare_selected",
                use_container_width=True,
                disabled=True,
            )
        elif st.button(
            f"Compare selected ({sel_n}) →",
            key="find.compare_selected",
            use_container_width=True,
            disabled=sel_n == 0,
        ):
            _open_in_spec_roster(selected)

    value_header = field_label.split(" · ")[-1]
    weights = [0.6, 3, 1, 1.4, 2.6, 1.2]
    _th = (
        '<div style="font-size:var(--cd-size-xs);color:var(--cd-text-faint);'
        "font-weight:600;text-transform:uppercase;letter-spacing:0.05em;"
        'border-bottom:1px solid var(--cd-border-strong);padding-bottom:4px;">{}</div>'
    )
    hdr = st.columns(weights)
    for col, text in zip(hdr, ("", "Product", "Year", "Status", value_header, "")):
        col.markdown(_th.format(html.escape(text)), unsafe_allow_html=True)

    for prod, vstr, marker in matches:
        brand = _company_of(prod)
        series = _series_of(prod)
        product = prod.get("product") or ""
        yr = _year_of(prod)
        status = _status_of(prod) or "Active"
        crumb = " · ".join(p for p in [brand, series] if p)
        display_v = "" if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB) else vstr
        mc = prod.get("model_code")
        row = st.columns(weights)
        row[0].checkbox(
            "Pick for compare",
            key=f"find.pick.{mc}.{yr}",
            label_visibility="collapsed",
        )
        row[1].markdown(
            f'<span style="color:var(--cd-text-faint)">{html.escape(crumb)} ·</span> '
            f"<strong>{html.escape(product)}</strong>",
            unsafe_allow_html=True,
        )
        row[2].markdown(str(yr) if yr is not None else "")
        row[3].markdown(html.escape(status))
        row[4].markdown(
            _value_cell_html(display_v, marker), unsafe_allow_html=True
        )
        if row[5].button(
            "Open →", key=f"find.open.{mc}.{yr}", use_container_width=True
        ):
            _open_in_spec_roster([prod])


def _render_narrow_by(
    conn: sqlite3.Connection,
    base_prods: list[dict[str, Any]],
) -> tuple[str | None, str | None, str | None, list[int], list[str]]:
    """Render the Stage 11 Phase 7 narrow-by block.

    Renders the strict 3-rung Brand → Series → Product picker plus Year
    + Status pill toggles. Partial picks narrow: e.g. Brand="Razer" with
    Series/Product unset narrows to all Razer products. Year/Status
    default to empty (no filter). The Year pill row is scoped to
    ``base_prods`` (products matching the Section/Feature/Match/Value
    query) so only useful years surface.

    Returns ``(brand, series, product, active_years, active_statuses)``.
    Each picker rung is ``None`` until actively chosen; the ``"—"``
    placeholder (and NULL-series sentinel emitted by the picker — the
    two are not distinguishable here) is treated as not-picked, matching
    the picker's own ``_is_picked`` contract.
    """
    st.markdown(
        '<div class="cd-find__narrow-label">Narrow by</div>',
        unsafe_allow_html=True,
    )
    picked = product_search_picker(
        conn, key_prefix="find.narrow", label="Product"
    )
    if picked is not None:
        brand_pick = picked["brand"]
        series_pick = picked["series"]
        product_pick = picked["product"]
    else:
        brand_pick = series_pick = product_pick = None

    years_int = sorted(
        {_year_of(p) for p in base_prods if _year_of(p) is not None},
        reverse=True,
    )
    active_years = year_toggle_block(
        years_int, key_prefix="find", default_latest=False
    )
    active_statuses = status_toggle_block(key_prefix="find", default=())
    return brand_pick, series_pick, product_pick, active_years, active_statuses
