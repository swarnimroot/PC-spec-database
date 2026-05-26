"""Find products — Section→Feature→Match→Value cascade + result cards.

Stage 10c rewrite of the Find screen. The behavioral core —
``_cell_matches``, ``_expand_template``, ``_distinct_values_for_template``,
``_union_templates`` — is preserved unchanged from Phase E. What
changes is the query shape (now a strict Section → Feature → Match →
Value cascade, with optional Company / Series / Year narrow-by chips)
and the result rendering (horizontal cards driven by the per-section
rollup dispatch, with a marker dot + ``Open →`` jump to Browse).
"""

from __future__ import annotations

import sqlite3
from typing import Any

import streamlit as st

from competitive_database.ui._components import (
    find_result_card_html,
    find_rollup_for_section,
    friendly_leaf_label as _friendly_leaf_label,
    inject_findcard_styles,
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

# Narrow-by ``"all of axis"`` sentinel — keeps the dropdowns truthy and
# distinguishes "user picked nothing" from "user picked some literal".
_ANY = "(any)"


# Sections that surface as a single rolled-up line in result cards. This
# tracks ``orchestrator._VISUAL_SECTIONS`` minus I/O — I/O renders as a
# multi-row rollup in the spec table, which doesn't compress neatly
# into the card layout. When the queried section is I/O the card falls
# back to a Section-name header without a rollup string.
_CARD_ROLLUP_SECTIONS: frozenset[str] = frozenset(
    orchestrator._VISUAL_SECTIONS
) - {"I/O"}


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
    section: str,
    cpu_catalog: dict[str, dict[str, Any]],
    gpu_catalog: dict[str, dict[str, Any]],
    fallback_value: str,
    fallback_marker: str,
) -> None:
    """Render one horizontal result card + ``Open →`` button."""
    company = _company_of(prod)
    sub = _sub_brand_of(prod)
    series = _series_of(prod)
    year = _year_of(prod)

    # For visual-section queries we use the per-section rollup as the
    # card's middle line. Outside that set (Identity, Keyboard, Thermals,
    # I/O) we fall back to the matched cell's own value + marker, so the
    # user still sees what the query hit.
    if section in _CARD_ROLLUP_SECTIONS:
        value_str, marker = find_rollup_for_section(
            section, prod, cpu_catalog, gpu_catalog
        )
        if not value_str:
            value_str, marker = fallback_value, fallback_marker
    else:
        value_str, marker = fallback_value, fallback_marker

    body_html = find_result_card_html(
        company=company,
        sub_brand=sub,
        series=series,
        year=year,
        section_name=section,
        rollup_value=value_str,
        marker=marker,
    )

    container = st.container()
    with container:
        cols = st.columns([6, 1])
        with cols[0]:
            st.markdown(body_html, unsafe_allow_html=True)
        with cols[1]:
            mc = prod.get("model_code")
            yr = year
            key = f"find.open.{mc}.{yr}"
            if st.button("Open →", key=key, use_container_width=True):
                _open_in_browse(prod)


def _open_in_browse(prod: dict[str, Any]) -> None:
    """Wire Browse's 3-rung picker session keys and switch view.

    Browse (Stage 11 Phase 3) reads its picker from
    ``browse.brand / browse.series / browse.product`` and its year
    toggles from ``browse.years`` (a ``set[int]``). NULL series uses
    the ``"—"`` sentinel to match ``list_series_options``.
    """
    brand = _company_of(prod)
    series = _series_of(prod) or "—"
    product = prod.get("product")
    yr = _year_of(prod)
    st.session_state["browse.brand"] = brand
    st.session_state["browse.series"] = series
    st.session_state["browse.product"] = product
    if yr is not None:
        st.session_state["browse.years"] = {yr}
    st.session_state["view"] = "browse"
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
    inject_findcard_styles()
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

    # Section → list of (template, friendly_leaf_label). Sections render in
    # the order they first appear in ``all_field_paths`` (i.e. orchestrator
    # render order).
    sections_in_order: list[str] = []
    by_section: dict[str, list[tuple[str, str]]] = {}
    for section, template in paths:
        if section not in by_section:
            sections_in_order.append(section)
            by_section[section] = []
        leaf = template.split(".")[-1]
        feature_label = _friendly_leaf_label(leaf, section)
        by_section[section].append((template, feature_label))

    # ---- Section / Feature row ----
    c_section, c_feature = st.columns([2, 2])
    with c_section:
        st.markdown('<div class="cd-find__label">Section</div>', unsafe_allow_html=True)
        section = st.selectbox(
            "Section",
            sections_in_order,
            key="find.section",
            label_visibility="collapsed",
        )
    feature_entries = by_section.get(section, [])
    feature_labels = [lbl for _, lbl in feature_entries]
    label_to_template: dict[str, str] = {
        lbl: tmpl for tmpl, lbl in feature_entries
    }
    with c_feature:
        st.markdown('<div class="cd-find__label">Feature</div>', unsafe_allow_html=True)
        feature_label = st.selectbox(
            "Feature",
            feature_labels,
            key="find.feature",
            label_visibility="collapsed",
        )
    template = label_to_template.get(feature_label, "")
    if not template:
        st.info("No features available in this section.")
        return

    # ---- Match / Value row ----
    op_default_label = _OP_LABEL[_OP_EQ]
    op_state_key = "find.op_label"
    op_current = st.session_state.get(op_state_key, op_default_label)
    needs_value = _LABEL_TO_OP[op_current] in _OPS_NEED_VALUE

    if needs_value:
        c_op, c_value = st.columns([2, 2])
    else:
        c_op, c_value = st.columns([2, 2])

    with c_op:
        st.markdown('<div class="cd-find__label">Match</div>', unsafe_allow_html=True)
        op_label = st.selectbox(
            "Match",
            _OP_LABELS_ORDERED,
            key=op_state_key,
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
        _render_narrow_by(products, template, op, value)
        st.markdown(
            '<div class="cd-find__count cd-find__count--empty">'
            "No products match this query.</div>",
            unsafe_allow_html=True,
        )
        return

    # ---- Narrow-by chips, scoped to products consistent with the query ----
    # Match-eligible product universe (before narrow-by) is what the
    # narrow-by dropdowns expose, so each axis only lists values that
    # would actually narrow the matches.
    matches = _find_matches(products, template, op, value)
    company_filter, series_filter, year_filter = _render_narrow_by(
        products, template, op, value, base_matches=matches
    )

    if company_filter != _ANY:
        matches = [m for m in matches if _company_of(m[0]) == company_filter]
    if series_filter != _ANY:
        matches = [m for m in matches if (_series_of(m[0]) or "—") == series_filter]
    if year_filter != _ANY:
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

    cpu_catalog = load.load_cpu_catalog(conn)
    gpu_catalog = load.load_gpu_catalog(conn)
    for prod, vstr, marker in matches:
        _render_card(prod, section, cpu_catalog, gpu_catalog, vstr, marker)


def _render_narrow_by(
    products: list[dict[str, Any]],
    template: str,
    op: str,
    value: str,
    *,
    base_matches: list[tuple[dict[str, Any], str, str]] | None = None,
) -> tuple[str, str, Any]:
    """Render the optional Company / Series / Year narrow-by chips.

    The dropdown options are scoped to ``base_matches`` (the products
    consistent with the Section/Feature/Match/Value query) so each
    narrow-by axis lists only values that would actually filter the
    result set. Returns ``(company, series, year)`` — ``_ANY`` for
    untouched axes.
    """
    st.markdown(
        '<div class="cd-find__narrow-label">Narrow by</div>',
        unsafe_allow_html=True,
    )
    if base_matches is None:
        base_matches = _find_matches(products, template, op, value)
    base_prods = [m[0] for m in base_matches]
    if not base_prods:
        base_prods = products  # nothing to narrow to; show full axes
    companies = sorted({_company_of(p) for p in base_prods}, key=str.lower)
    series_vals = sorted(
        {(_series_of(p) or "—") for p in base_prods}, key=str.lower
    )
    years_int = sorted(
        {_year_of(p) for p in base_prods if _year_of(p) is not None},
        reverse=True,
    )
    company_opts = [_ANY] + companies
    series_opts = [_ANY] + series_vals
    year_opts: list[Any] = [_ANY] + years_int

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        company = st.selectbox(
            "Company",
            company_opts,
            key="find.narrow.company",
            label_visibility="visible",
        )
    with c2:
        series_pick = st.selectbox(
            "Series",
            series_opts,
            key="find.narrow.series",
            label_visibility="visible",
        )
    with c3:
        year = st.selectbox(
            "Year",
            year_opts,
            key="find.narrow.year",
            label_visibility="visible",
        )
    return company, series_pick, year
