"""Find products — searchable spec-field + Match + Value query → results table.

The behavioral core now lives in ``competitive_database.query`` (a pure,
Streamlit-free module a future API can call); this screen maps its
plain-English Match labels onto the canonical operators and delegates.
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

from competitive_database.query import (
    Op,
    OPS_NEED_VALUE,
    company_of,
    distinct_values_for_template,
    find_matches,
    series_of,
    status_of,
    union_templates,
    year_of,
)
from competitive_database.query.engine import apply_narrow_by
from competitive_database.ui._components import (
    _value_cell_html,
    friendly_field_label,
    product_search_picker,
    status_toggle_block,
    year_toggle_block,
)
from competitive_database.views import load
from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_VENDOR_NO_PUB,
)


# Plain-English op labels shown in the Match dropdown, mapped to the
# canonical query operators. Order here is the dropdown order.
_OP_LABEL: dict[str, str] = {
    Op.EQ: "equals",
    Op.GTE: "is at least",
    Op.LTE: "is at most",
    Op.CONTAINS: "contains",
    Op.IS_SET: "has any value",
    Op.IS_EMPTY: "is empty",
    Op.VENDOR_UNAVAILABLE: "marked unavailable",
}
_LABEL_TO_OP: dict[str, str] = {label: op for op, label in _OP_LABEL.items()}
_OP_LABELS_ORDERED: list[str] = list(_OP_LABEL.values())

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
        brand = company_of(prod)
        series = series_of(prod)
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
    paths = union_templates(products)
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
    if op in OPS_NEED_VALUE:
        values = distinct_values_for_template(products, template)
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
    matches = find_matches(products, template, op, value)
    brand_pick, series_pick, product_pick, active_years, active_statuses = (
        _render_narrow_by(conn, [m[0] for m in matches])
    )

    # apply_narrow_by works on products; map the kept products (by object
    # identity, preserved across the filter) back onto the match tuples so
    # each row keeps its representative (value, marker).
    kept = {
        id(p): None
        for p in apply_narrow_by(
            [m[0] for m in matches],
            brands=brand_pick,
            series=series_pick,
            products_names=product_pick,
            years=active_years,
            statuses=active_statuses,
        )
    }
    matches = [m for m in matches if id(m[0]) in kept]

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
        yr = year_of(prod)
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
        brand = company_of(prod)
        series = series_of(prod)
        product = prod.get("product") or ""
        yr = year_of(prod)
        status = status_of(prod) or "Active"
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
        {year_of(p) for p in base_prods if year_of(p) is not None},
        reverse=True,
    )
    active_years = year_toggle_block(
        years_int, key_prefix="find", default_latest=False
    )
    active_statuses = status_toggle_block(key_prefix="find", default=())
    return brand_pick, series_pick, product_pick, active_years, active_statuses
