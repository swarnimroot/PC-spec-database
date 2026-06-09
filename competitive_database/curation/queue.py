"""Streamlit-free queue queries for the Curation Cockpit.

Two listings power the Cockpit's four tabs:

  - **conflicts** — unresolved ``review_queue`` rows. The pure SQL listing
    here is extracted from ``ui/triage.py``'s ``_list_unresolved`` (which
    lived in a Streamlit-importing module, so it could not be reused from
    the API or a CLI). The conflict-type → friendly-label / conflict-kind
    mapping mirrors ``ui/triage.py``'s ``_CONFLICT_LABELS``.

  - **review / missing / hand** — field-state cells, derived by walking
    :func:`competitive_database.views.orchestrator.all_field_paths` over
    every loaded product and reading each value's status, exactly the way
    ``cli/find_empty.py`` walks paths for empties. The stored-status →
    display-state mapping is reused from ``api/serializers`` so the Cockpit
    and the read endpoints agree on what "confirmed / review / hand / …"
    means.

No write logic lives here — writes go through ``cli/manual_edit`` and
``cli/resolve`` directly from the API layer.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from ..api import serializers
from ..views.load import load_product
from ..views.orchestrator import all_field_paths

# ---------------------------------------------------------------------------
# Conflict listing (extracted from ui/triage.py)
# ---------------------------------------------------------------------------

#: ``review_queue.conflict_type`` enum -> (friendly label, cockpit kind).
#: Friendly labels mirror ``ui/triage.py::_CONFLICT_LABELS``; the kind is the
#: short token the cockpit UI requested (value-mismatch / low-confidence /
#: catalog-vouch / year-guess).
CONFLICT_TYPE_META: dict[str, tuple[str, str]] = {
    "value_disagreement": ("Value mismatch", "value-mismatch"),
    "low_confidence_extraction": ("Low confidence", "low-confidence"),
    "new_chip_unverified": ("Catalog vouch", "catalog-vouch"),
    "year_inferred": ("Year guess", "year-guess"),
}

_QUEUE_SELECT = (
    "SELECT id, product_model_code, product_year, field_path, conflict_type, "
    "existing_value, existing_provenance, candidate_value, "
    "candidate_provenance, detected_at "
    "FROM review_queue WHERE resolved_at IS NULL ORDER BY id"
)


def _decode_json(raw: Any) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _unwrap_value(decoded: Any) -> Any:
    """Unwrap a stored value column to its bare value.

    ``existing_value`` / ``candidate_value`` may hold a ``{"value": …}``
    bundle skeleton, a plain scalar (manual_override stores ``json.dumps``
    of the value), an offerings list, or None. Mirrors
    ``ui/triage.py::_value_display``.
    """
    if isinstance(decoded, dict) and "value" in decoded:
        return decoded["value"]
    return decoded


def _identity_for(conn: sqlite3.Connection, model_code: str, year: Any) -> dict[str, Any]:
    """Brand/series/product identity for a (model_code, year), best-effort."""
    row = conn.execute(
        "SELECT json_extract(brand, '$.value') AS brand, "
        "json_extract(series, '$.value') AS series, product AS product "
        "FROM products WHERE model_code = ? AND year = ?",
        (model_code, year),
    ).fetchone()
    if row is None:
        return {"brand": None, "series": None, "model": model_code}
    return {"brand": row["brand"], "series": row["series"], "model": row["product"]}


def list_conflicts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Unresolved ``review_queue`` rows as cockpit queue items.

    Each item carries a stable ``id`` (the review_queue row id, prefixed so
    it never collides with field-state item ids), model identity, the field
    label, the existing value, the candidate value(s), and the conflict kind
    (value-mismatch / low-confidence / catalog-vouch / year-guess).
    """
    rows = conn.execute(_QUEUE_SELECT).fetchall()
    items: list[dict[str, Any]] = []
    for r in rows:
        ct = r["conflict_type"]
        label, kind = CONFLICT_TYPE_META.get(ct, (ct or "Conflict", ct or "conflict"))
        ident = _identity_for(conn, r["product_model_code"], r["product_year"])
        existing = _unwrap_value(_decode_json(r["existing_value"]))
        candidate = _unwrap_value(_decode_json(r["candidate_value"]))
        items.append(
            {
                "id": f"conflict:{r['id']}",
                "row_id": r["id"],
                "tab": "conflicts",
                "model_code": r["product_model_code"],
                "year": r["product_year"],
                "brand": ident["brand"],
                "series": ident["series"],
                "model": ident["model"],
                "field_path": r["field_path"],
                "label": r["field_path"],
                "conflict_type": ct,
                "conflict_type_label": label,
                "conflict_kind": kind,
                "existing": existing,
                "candidate": candidate,
                "detected_at": r["detected_at"],
            }
        )
    return items


def count_conflicts(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM review_queue WHERE resolved_at IS NULL"
    ).fetchone()
    return int(row[0])


# ---------------------------------------------------------------------------
# Field-state scan (review / missing / hand) — mirrors cli/find_empty.py
# ---------------------------------------------------------------------------

#: Cockpit tab -> the set of display-states (see serializers.STATUS_TO_STATE)
#: that belong on that tab.
_TAB_STATES: dict[str, set[str]] = {
    "review": {"review"},
    "missing": {"blank", "not_published"},
    "hand": {"hand"},
}


def _lookup(product: dict[str, Any], field_path: str) -> Any:
    """Walk a dotted path within a loaded product dict (mirrors find_empty)."""
    parts = field_path.split(".")
    if len(parts) == 1:
        return product.get(parts[0])
    if len(parts) == 3:
        col, idx_s, leaf = parts
        offerings = product.get(col) or []
        try:
            idx = int(idx_s)
        except ValueError:
            return None
        if idx >= len(offerings):
            return None
        leaf_val = offerings[idx]
        if isinstance(leaf_val, dict):
            return leaf_val.get(leaf)
        return None
    return None


def _state_of(value: Any) -> str:
    """Display-state for a loaded cell value (bundle / scalar / None)."""
    if value is None:
        return "blank"
    if isinstance(value, dict):
        return serializers.state_for_status(value.get("status"))
    # Plain scalar leaf — scraped/verified by construction.
    return "confirmed"


def _all_product_pks(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT model_code, year FROM products ORDER BY model_code, year"
    ).fetchall()
    return [(r["model_code"], r["year"]) for r in rows]


def list_field_state(conn: sqlite3.Connection, tab: str) -> list[dict[str, Any]]:
    """Field-state cells for one of the ``review`` / ``missing`` / ``hand`` tabs.

    Walks ``all_field_paths`` over every product and keeps the cells whose
    display-state falls in the requested tab's state set. Each item carries a
    stable id, model identity, section·field label, the current value + state,
    and a ``byYear`` diff flag (whether the same cell differs across the
    product's yearly variants).
    """
    if tab not in _TAB_STATES:
        raise ValueError(f"unknown field-state tab {tab!r}")
    wanted = _TAB_STATES[tab]

    items: list[dict[str, Any]] = []
    # Cache loaded products per (mc, year) so the byYear diff can compare.
    by_model: dict[str, list[int]] = {}
    for mc, _yr in _all_product_pks(conn):
        by_model.setdefault(mc, [])
    for mc, yr in _all_product_pks(conn):
        by_model[mc].append(yr)

    for mc, yr in _all_product_pks(conn):
        product = load_product(conn, mc, year=yr)
        ident = _identity_for(conn, mc, yr)
        years = by_model.get(mc, [yr])
        for section, path, label in all_field_paths(product):
            value = _lookup(product, path)
            state = _state_of(value)
            if state not in wanted:
                continue
            cur = value.get("value") if isinstance(value, dict) else value
            items.append(
                {
                    "id": f"field:{mc}:{yr}:{path}",
                    "tab": tab,
                    "model_code": mc,
                    "year": yr,
                    "brand": ident["brand"],
                    "series": ident["series"],
                    "model": ident["model"],
                    "section": section,
                    "field_path": path,
                    "label": f"{section} · {label}",
                    "state": state,
                    "value": cur,
                    "byYearDiff": _byyear_diff(conn, mc, years, yr, path, cur),
                }
            )
    return items


def _byyear_diff(
    conn: sqlite3.Connection,
    model_code: str,
    years: list[int],
    this_year: int,
    field_path: str,
    this_value: Any,
) -> Optional[dict[str, Any]]:
    """If the cell differs across the model's other years, report the diff.

    Returns ``{otherYear: value, ...}`` for years whose value differs from
    ``this_value``, or None when the model has a single year / no difference.
    """
    others = [y for y in years if y != this_year]
    if not others:
        return None
    diff: dict[str, Any] = {}
    for y in others:
        try:
            other = load_product(conn, model_code, year=y)
        except LookupError:
            continue
        ov = _lookup(other, field_path)
        ov_value = ov.get("value") if isinstance(ov, dict) else ov
        if ov_value != this_value:
            diff[str(y)] = ov_value
    return diff or None


def count_field_state(conn: sqlite3.Connection, tab: str) -> int:
    return len(list_field_state(conn, tab))


# ---------------------------------------------------------------------------
# Provenance history (existing provenance only — no audit-log table)
# ---------------------------------------------------------------------------

_HISTORY_FIELDS = (
    "source_url",
    "captured_at",
    "scraper_id",
    "entered_by",
    "entered_at",
    "source_note",
    "note",
    "status",
)


def value_history(
    conn: sqlite3.Connection,
    *,
    model_code: str,
    year: int,
    field_path: str,
) -> dict[str, Any]:
    """Provenance fields for one cell (existing provenance only).

    History == the bundle's stored provenance; there is no separate audit
    log. Returns ``{model_code, year, field_path, value, provenance}`` where
    ``provenance`` holds the documented bundle fields (None for any absent).
    """
    product = load_product(conn, model_code, year=year)
    value = _lookup(product, field_path)
    if isinstance(value, dict):
        prov = {k: value.get(k) for k in _HISTORY_FIELDS}
        cur = value.get("value")
    else:
        prov = {k: None for k in _HISTORY_FIELDS}
        cur = value
    return {
        "model_code": model_code,
        "year": year,
        "field_path": field_path,
        "value": cur,
        "provenance": prov,
    }
