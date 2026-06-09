"""Pure spec-query engine — no Streamlit, no UI dependencies.

This module is the importable core that powers the Find-products screen
and (in future) a FastAPI backend. It operates on already-loaded product
dicts (the shape returned by ``views.load.load_product``) and knows
nothing about widgets or session state.

Operator semantics are addressed by canonical string constants (see
``Op``) so a caller can pass an operator without knowing any UI label:

  - ``Op.EQ`` ("eq")            — equals (case-insensitive; numeric-aware)
  - ``Op.GTE`` ("gte")          — numeric ≥
  - ``Op.LTE`` ("lte")          — numeric ≤
  - ``Op.CONTAINS`` ("contains")— case-insensitive substring
  - ``Op.IS_SET`` ("is_set")    — has any value (excludes vendor-no-publish)
  - ``Op.IS_EMPTY`` ("is_empty")— empty/unset (excludes vendor-no-publish)
  - ``Op.VENDOR_UNAVAILABLE`` ("vendor_unavailable")
        — status == "vendor-doesn't-publish"

The matching semantics are byte-for-byte identical to the original
``ui.find`` implementation.
"""

from __future__ import annotations

from typing import Any, Optional

from competitive_database.views import orchestrator
from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_VENDOR_NO_PUB,
    MARKER_VERIFIED,
    canonicalize_display,
    display_value,
    marker_for_bundle,
)


class Op:
    """Canonical operator names usable by any caller (UI or API)."""

    EQ = "eq"
    GTE = "gte"
    LTE = "lte"
    CONTAINS = "contains"
    IS_SET = "is_set"
    IS_EMPTY = "is_empty"
    VENDOR_UNAVAILABLE = "vendor_unavailable"


#: Operators that require a comparison value to be supplied.
OPS_NEED_VALUE: frozenset[str] = frozenset(
    {Op.EQ, Op.GTE, Op.LTE, Op.CONTAINS}
)

#: All canonical operators, in canonical display order.
OPS_ALL: tuple[str, ...] = (
    Op.EQ,
    Op.GTE,
    Op.LTE,
    Op.CONTAINS,
    Op.IS_SET,
    Op.IS_EMPTY,
    Op.VENDOR_UNAVAILABLE,
)

_VENDOR_NO_PUB_STATUS = "vendor-doesn't-publish"


# ---------------------------------------------------------------------------
# Path resolution (re-implemented here so query/ stays Streamlit-free; the
# ui._markers copy transitively imports streamlit via theme).
# ---------------------------------------------------------------------------


def resolve_path(
    product: dict[str, Any],
    path: str,
) -> tuple[Optional[dict], Optional[str]]:
    """Return ``(bundle, plain)`` for one dotted path on a loaded product.

    Exactly one of the two is non-None when the cell is present, else
    ``(None, None)``. Plain-string leaves take the second slot;
    everything else is bundle-shaped.
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


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


def template_of(path: str) -> str:
    """Collapse offering index in a 3-part path to ``*``."""
    parts = path.split(".")
    if len(parts) == 3:
        return f"{parts[0]}.*.{parts[2]}"
    return path


def union_templates(
    products: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Union of (section, template) across products, render order preserved."""
    seen: set[tuple[str, str]] = set()
    section_order: list[str] = []
    section_templates: dict[str, list[str]] = {}
    for prod in products:
        for section, path, _label in orchestrator.all_field_paths(prod):
            template = template_of(path)
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


def expand_template(prod: dict[str, Any], template: str) -> list[str]:
    """All concrete paths on ``prod`` that match ``template``."""
    parts = template.split(".")
    if "*" not in parts:
        return [template]
    col, _, leaf = parts
    offerings = prod.get(col)
    if not isinstance(offerings, list):
        return []
    return [f"{col}.{i}.{leaf}" for i in range(len(offerings))]


def coerce_number(s: Any) -> float | None:
    """Best-effort float coercion; ``None`` when not numeric."""
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Operator matching core
# ---------------------------------------------------------------------------


def cell_matches(
    bundle: dict | None,
    plain: str | None,
    op: str,
    value: str,
    field_path: str,
) -> bool:
    """Return whether one resolved cell satisfies ``op``/``value``.

    Semantics are identical to the original ``ui.find._cell_matches``:
    ``IS_EMPTY`` excludes vendor-no-publish cells, ``VENDOR_UNAVAILABLE``
    matches status == "vendor-doesn't-publish", and ``EQ``/``GTE``/``LTE``
    fall back to float coercion.
    """
    if op == Op.IS_EMPTY:
        if plain is not None:
            return False
        if bundle is None:
            return True
        if bundle.get("status") == _VENDOR_NO_PUB_STATUS:
            return False
        return bundle.get("value") is None
    if op == Op.VENDOR_UNAVAILABLE:
        return (
            bundle is not None
            and bundle.get("status") == _VENDOR_NO_PUB_STATUS
        )
    if op == Op.IS_SET:
        if plain is not None:
            return True
        if bundle is None:
            return False
        if bundle.get("status") == _VENDOR_NO_PUB_STATUS:
            return False
        return bundle.get("value") is not None

    if plain is not None:
        rendered = canonicalize_display(field_path, plain)
    elif bundle is not None and bundle.get("status") != _VENDOR_NO_PUB_STATUS:
        if bundle.get("value") is None:
            return False
        rendered = display_value(bundle, field_path=field_path)
    else:
        return False

    if op == Op.CONTAINS:
        return value.casefold() in rendered.casefold()
    if op == Op.EQ:
        if rendered.casefold() == value.casefold():
            return True
        a, b = coerce_number(rendered), coerce_number(value)
        return a is not None and b is not None and a == b
    if op == Op.GTE:
        a, b = coerce_number(rendered), coerce_number(value)
        return a is not None and b is not None and a >= b
    if op == Op.LTE:
        a, b = coerce_number(rendered), coerce_number(value)
        return a is not None and b is not None and a <= b
    return False


def distinct_values_for_template(
    products: list[dict[str, Any]], template: str
) -> list[str]:
    """Sorted distinct rendered values across products for this template."""
    seen: set[str] = set()
    for prod in products:
        for concrete_path in expand_template(prod, template):
            bundle, plain = resolve_path(prod, concrete_path)
            if plain is not None:
                seen.add(canonicalize_display(template, plain))
                continue
            if bundle is None:
                continue
            if bundle.get("status") == _VENDOR_NO_PUB_STATUS:
                continue
            if bundle.get("value") is None:
                continue
            seen.add(display_value(bundle, field_path=template))

    def _sort_key(s: str) -> tuple[int, float | str]:
        n = coerce_number(s)
        return (0, n) if n is not None else (1, s.casefold())

    return sorted(seen, key=_sort_key)


def format_match(
    bundle: dict | None, plain: str | None, field_path: str
) -> tuple[str, str]:
    """Return ``(value_str, marker_token)`` for a matched cell."""
    if plain is not None:
        return plain, MARKER_VERIFIED
    marker = marker_for_bundle(bundle)
    if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB):
        return (
            "vendor doesn't publish"
            if marker == MARKER_VENDOR_NO_PUB
            else "—"
        ), marker
    value = display_value(bundle, field_path=field_path) or "—"
    return value, marker


def find_matches(
    products: list[dict[str, Any]],
    template: str,
    op: str,
    value: str,
) -> list[tuple[dict[str, Any], str, str]]:
    """Return matched products with one representative ``(value, marker)``.

    A product matches if at least one concrete path on it satisfies the
    op. The representative is taken from the first matching cell so each
    row shows one line, not a sub-list. Marker tokens are the
    ``views.formatting`` constants, unchanged from the original UI core.
    """
    out: list[tuple[dict[str, Any], str, str]] = []
    for prod in products:
        for concrete_path in expand_template(prod, template):
            bundle, plain = resolve_path(prod, concrete_path)
            if cell_matches(bundle, plain, op, value, concrete_path):
                vstr, marker = format_match(bundle, plain, concrete_path)
                out.append((prod, vstr, marker))
                break
    return out


# ---------------------------------------------------------------------------
# Identity accessors
# ---------------------------------------------------------------------------


def _scalar_bundle_str(bundle: Any) -> str | None:
    if not isinstance(bundle, dict):
        return None
    v = bundle.get("value")
    if isinstance(v, str) and v:
        return v
    return None


def company_of(prod: dict[str, Any]) -> str:
    """Brand string, or ``"Unknown"`` when absent."""
    return _scalar_bundle_str(prod.get("brand")) or "Unknown"


def sub_brand_of(prod: dict[str, Any]) -> str | None:
    return _scalar_bundle_str(prod.get("sub_brand"))


def series_of(prod: dict[str, Any]) -> str | None:
    return _scalar_bundle_str(prod.get("series"))


def year_of(prod: dict[str, Any]) -> int | None:
    yr_raw = prod.get("year")
    try:
        return int(yr_raw) if yr_raw is not None else None
    except (TypeError, ValueError):
        return None


def status_of(prod: dict[str, Any]) -> str | None:
    return _scalar_bundle_str(prod.get("status"))


# ---------------------------------------------------------------------------
# Narrow-by filter
# ---------------------------------------------------------------------------


def apply_narrow_by(
    products: list[dict[str, Any]],
    *,
    brands: str | None = None,
    series: str | None = None,
    products_names: str | None = None,
    years: list[int] | set[int] | None = None,
    statuses: list[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter loaded products by the Find narrow-by axes.

    Mirrors the inline filtering originally performed in
    ``ui.find.render``. Each axis is independent and additive:

      - ``brands`` / ``series`` / ``products_names`` — exact-match a single
        value; ``None`` means "don't filter on this axis".
      - ``years`` — keep products whose year is in the set (empty/None →
        no year filter).
      - ``statuses`` — keep products whose status is in the set, with a
        NULL/empty status treated as ``"Active"`` (empty/None → no filter).
    """
    out = list(products)
    if brands is not None:
        out = [p for p in out if company_of(p) == brands]
    if series is not None:
        out = [p for p in out if series_of(p) == series]
    if products_names is not None:
        out = [p for p in out if p.get("product") == products_names]
    if years:
        year_set = set(years)
        out = [p for p in out if year_of(p) in year_set]
    if statuses:
        status_set = set(statuses)
        out = [p for p in out if (status_of(p) or "Active") in status_set]
    return out
