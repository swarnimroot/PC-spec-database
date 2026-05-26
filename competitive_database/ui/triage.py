"""Review queue triage — sidebar list + main panel detail.

Lists every unresolved ``review_queue`` row in a left-rail list;
selecting a row loads its existing-vs-candidate diff into the right-hand
panel with action buttons matching the ``resolve`` CLI verbs
(``accept_candidate`` / ``kept_existing`` / ``manual_override`` /
``dropped``).

Writes route through :func:`competitive_database.cli.resolve.resolve_row`
— the same handler the CLI uses, re-callable as a library function.
``new_chip_unverified`` rows get the catalog vouching dispatch (only
``accept_candidate`` / ``dropped`` are valid); the UI hides the
inapplicable buttons.
"""

from __future__ import annotations

import html
import json
import sqlite3
from typing import Any

import streamlit as st

from competitive_database.cli.resolve import coerce_value_string, resolve_row
from competitive_database.ui import theme
from competitive_database.ui._components import _bundle_value, _product_name
from competitive_database.ui._markers import MARKER_COLORS
from competitive_database.views.formatting import marker_for_bundle

_QUEUE_COLS = (
    "rq.id, rq.product_model_code, rq.product_year, rq.field_path, "
    "rq.conflict_type, rq.existing_value, rq.existing_provenance, "
    "rq.candidate_value, rq.candidate_provenance, rq.detected_at, "
    "p.vendor_full_name AS _product_vfn"
)

# Friendly labels for the 4 ``review_queue.conflict_type`` enum values.
# Surfaced on sidebar headers + detail-pane caption; the raw enum stays
# as the DB-internal identifier (used by resolve / ingest paths).
_CONFLICT_LABELS: dict[str, str] = {
    "value_disagreement": "Value mismatch",
    "low_confidence_extraction": "Low confidence",
    "new_chip_unverified": "Catalog vouch",
    "year_inferred": "Year guess",
}
_CONFLICT_LABELS_PLURAL: dict[str, str] = {
    "value_disagreement": "Value mismatches",
    "low_confidence_extraction": "Low confidence",
    "new_chip_unverified": "Catalog vouches",
    "year_inferred": "Year guesses",
}
# Canonical order for conflict-type sub-folders within a product folder.
_CT_ORDER: tuple[str, ...] = tuple(_CONFLICT_LABELS.keys())


def _list_unresolved(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {_QUEUE_COLS} FROM review_queue rq "
        "LEFT JOIN products p ON p.model_code = rq.product_model_code "
        "  AND p.year = rq.product_year "
        "WHERE rq.resolved_at IS NULL ORDER BY rq.id"
    ).fetchall()
    return [dict(r) for r in rows]


def _pkey(row: dict[str, Any]) -> str:
    """Stable string key for a (model_code, year) pair."""
    return f"{row['product_model_code']}:{row['product_year']}"


def _ckey(row: dict[str, Any]) -> str:
    """Stable string key for a (product, conflict_type) pair."""
    return f"{_pkey(row)}|{row['conflict_type']}"


def _friendly_product_name(row: dict[str, Any]) -> str:
    """Friendly product name for a queue row's product, or model_code fallback."""
    vfn = _bundle_value(row.get("_product_vfn"))
    return _product_name(vfn, row["product_model_code"], int(row["product_year"]))


def _group_by_product_and_type(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """{pkey: {conflict_type: [rows...]}} preserving row order from the query."""
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in rows:
        groups.setdefault(_pkey(r), {}).setdefault(r["conflict_type"] or "?", []).append(r)
    return groups


def _decode_json(raw: Any) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _marker_html(marker: str) -> str:
    color = MARKER_COLORS.get(marker, theme.PALETTE["text_muted"])
    return f'<span style="color:{color}">{html.escape(marker)}</span>'


def _value_display(value_json: Any, provenance: Any) -> str:
    """Render the value bit of a side-panel — value + provenance marker.

    ``value_json`` may be ``{"value": …}`` (the bundle skeleton stored on
    ``review_queue.existing_value`` / ``candidate_value``), a plain scalar
    (manual_override stores ``json.dumps(value)`` directly), an offerings
    list (column-level disagreements), or ``None``.
    """
    if isinstance(value_json, dict) and "value" in value_json:
        v: Any = value_json["value"]
    else:
        v = value_json
    marker = marker_for_bundle(provenance) if isinstance(provenance, dict) else None
    marker_html = f" {_marker_html(marker)}" if marker else ""
    if isinstance(v, (dict, list)):
        body = f"<code>{html.escape(json.dumps(v, indent=2)[:400])}</code>"
    elif v is None:
        body = f'<span style="color:{theme.PALETTE["text_faint"]}">—</span>'
    elif isinstance(v, bool):
        body = "yes" if v else "no"
    else:
        body = html.escape(str(v))
    return (
        f'<div style="font-family:ui-monospace,Consolas,Menlo,monospace;'
        f'font-size:1.05rem;line-height:1.5">{body}{marker_html}</div>'
    )


def _render_side_panel(label: str, value_json: Any, provenance: Any) -> None:
    st.markdown(f"**{label}**")
    if value_json is None and provenance is None:
        st.markdown(
            f'<div style="color:{theme.PALETTE["text_faint"]};font-style:italic">(no value)</div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown(_value_display(value_json, provenance), unsafe_allow_html=True)
    if isinstance(provenance, dict):
        for key, label_str in (
            ("source_url", "source"),
            ("captured_at", "captured"),
            ("scraper_id", "scraper"),
            ("entered_by", "entered by"),
            ("entered_at", "entered"),
            ("source_note", "note"),
            ("status", "status"),
        ):
            val = provenance.get(key)
            if val:
                st.caption(f"{label_str}: {val}")


def _render_new_chip_panel(value_json: Any, provenance: Any) -> None:
    st.markdown("**Candidate (new chip)**")
    if isinstance(value_json, dict):
        table = value_json.get("table")
        model = value_json.get("model")
        st.markdown(
            f'<div style="font-family:ui-monospace,Consolas,Menlo,monospace;'
            f'font-size:1.05rem">catalog target: '
            f'<code>{html.escape(str(table))}</code> · '
            f'<code>{html.escape(str(model))}</code></div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Stub catalog row created at ingest; accept_candidate flips "
            "its `catalog_status` to `vouched`."
        )
    if isinstance(provenance, dict):
        for key, label_str in (
            ("source_url", "first seen at"),
            ("captured_at", "captured"),
            ("scraper_id", "scraper"),
        ):
            val = provenance.get(key)
            if val:
                st.caption(f"{label_str}: {val}")


def _resolve_and_advance(
    conn: sqlite3.Connection,
    row_id: int,
    action: str,
    *,
    value: Any = None,
    note: str | None = None,
    has_value: bool = False,
) -> None:
    """Call the library resolve handler; toast on success, error on failure."""
    kwargs: dict[str, Any] = {"row_id": row_id, "action": action, "note": note}
    if has_value:
        kwargs["value"] = value
    try:
        summary = resolve_row(conn, **kwargs)
    except ValueError as exc:
        st.session_state["queue_last_error"] = f"#{row_id}: {exc}"
        return
    st.session_state["queue_last_resolved"] = (summary["id"], summary["action"])
    # Drop the selection so the next render auto-selects the first remaining
    # row; otherwise the now-resolved id lingers in session_state.
    st.session_state.pop("queue_selected_id", None)


def _render_actions(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    is_new_chip: bool,
) -> None:
    rid = row["id"]
    st.markdown("**Actions**")
    if is_new_chip:
        c1, c2 = st.columns(2)
        if c1.button(
            "Accept (vouch catalog row)",
            key=f"act-accept-{rid}",
            use_container_width=True,
            type="primary",
        ):
            _resolve_and_advance(conn, rid, "accept_candidate")
            st.rerun()
        if c2.button(
            "Drop (discard)",
            key=f"act-drop-{rid}",
            use_container_width=True,
        ):
            _resolve_and_advance(conn, rid, "dropped")
            st.rerun()
        st.caption(
            "Catalog-vouch rows only support Accept or Drop — there's no "
            "existing value to keep, and manual override doesn't apply."
        )
        return

    c1, c2, c3 = st.columns(3)
    if c1.button(
        "Accept candidate",
        key=f"act-accept-{rid}",
        use_container_width=True,
        type="primary",
    ):
        _resolve_and_advance(conn, rid, "accept_candidate")
        st.rerun()
    if c2.button(
        "Keep existing",
        key=f"act-keep-{rid}",
        use_container_width=True,
    ):
        _resolve_and_advance(conn, rid, "kept_existing")
        st.rerun()
    if c3.button(
        "Drop",
        key=f"act-drop-{rid}",
        use_container_width=True,
    ):
        _resolve_and_advance(conn, rid, "dropped")
        st.rerun()

    with st.expander("Manual override"):
        with st.form(key=f"manual-override-{rid}", clear_on_submit=False):
            value_str = st.text_input(
                "Value",
                key=f"mo-val-{rid}",
                placeholder="e.g. 240, OLED, Wi-Fi 7",
            )
            use_json = st.checkbox(
                "Treat value as JSON literal",
                key=f"mo-json-{rid}",
                help="Required for booleans (true/false), null, or lists.",
            )
            note = st.text_input(
                "Note (source / rationale)",
                key=f"mo-note-{rid}",
                placeholder="Optional — stored on the queue row + the cell's source_note.",
            )
            submitted = st.form_submit_button("Apply manual override")
            if submitted:
                if not value_str and not use_json:
                    st.error("Enter a value (or check 'Treat as JSON' to pass null / lists).")
                    return
                try:
                    if use_json:
                        decoded = json.loads(value_str) if value_str else None
                    else:
                        decoded = coerce_value_string(value_str)
                except json.JSONDecodeError as exc:
                    st.error(f"Value is not valid JSON: {exc}")
                    return
                _resolve_and_advance(
                    conn,
                    rid,
                    "manual_override",
                    value=decoded,
                    note=note or None,
                    has_value=True,
                )
                st.rerun()


def _render_detail(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> None:
    rid = row["id"]
    mc = row["product_model_code"]
    yr = row["product_year"]
    ct = row["conflict_type"]
    fp = row["field_path"]
    is_new_chip = ct == "new_chip_unverified"

    st.markdown(f"### Row #{rid} · `{mc}` · {yr}")
    detected = row.get("detected_at") or "?"
    ct_label = _CONFLICT_LABELS.get(ct, ct)
    st.caption(
        f"{ct_label} · field: `{fp}` · detected: {detected}"
    )

    existing_v = _decode_json(row["existing_value"])
    existing_p = _decode_json(row["existing_provenance"])
    candidate_v = _decode_json(row["candidate_value"])
    candidate_p = _decode_json(row["candidate_provenance"])

    left, right = st.columns(2)
    with left:
        _render_side_panel("Existing", existing_v, existing_p)
    with right:
        if is_new_chip:
            _render_new_chip_panel(candidate_v, candidate_p)
        else:
            _render_side_panel("Candidate", candidate_v, candidate_p)

    st.divider()
    _render_actions(conn, row, is_new_chip)


def _render_sidebar(
    rows: list[dict[str, Any]],
    selected_id: int,
) -> None:
    """Two-level collapsible tree: product folder → conflict-type sub-folder → row leaf.

    State held in `queue_expanded_products` + `queue_expanded_cts` (sets
    of pkey / ckey strings). The path to the selected row auto-expands
    on selection change (tracked via `queue_last_auto_expanded_for`)
    but does not re-expand if the user explicitly collapses a folder
    that already contains the current selection.
    """
    st.markdown(f"**Queue ({len(rows)})**")

    expanded_products: set[str] = st.session_state.setdefault(
        "queue_expanded_products", set()
    )
    expanded_cts: set[str] = st.session_state.setdefault(
        "queue_expanded_cts", set()
    )

    # Auto-expand the path to the selected row, but only when the
    # selection changes — so an explicit collapse by the user sticks.
    last_auto = st.session_state.get("queue_last_auto_expanded_for")
    if last_auto != selected_id:
        sel_row = next((r for r in rows if r["id"] == selected_id), None)
        if sel_row is not None:
            expanded_products.add(_pkey(sel_row))
            expanded_cts.add(_ckey(sel_row))
        st.session_state["queue_last_auto_expanded_for"] = selected_id

    groups = _group_by_product_and_type(rows)
    # Build a friendly-name lookup for sort + label.
    name_for_pkey = {
        pkey: _friendly_product_name(next(iter(ct_rows.values()))[0])
        for pkey, ct_rows in groups.items()
    }

    def _ct_sort_key(ct: str) -> int:
        return _CT_ORDER.index(ct) if ct in _CT_ORDER else len(_CT_ORDER)

    for pkey in sorted(groups.keys(), key=lambda k: name_for_pkey[k].lower()):
        product_total = sum(len(rs) for rs in groups[pkey].values())
        friendly = name_for_pkey[pkey]
        is_open = pkey in expanded_products
        chevron = "▾" if is_open else "▸"
        if st.button(
            f"{chevron} {friendly}  ({product_total} open)",
            key=f"queue-prod-{pkey}",
            use_container_width=True,
        ):
            if is_open:
                expanded_products.discard(pkey)
            else:
                expanded_products.add(pkey)
            st.rerun()

        if not is_open:
            continue

        for ct in sorted(groups[pkey].keys(), key=_ct_sort_key):
            ct_rows = groups[pkey][ct]
            ct_label = _CONFLICT_LABELS_PLURAL.get(ct, ct)
            ct_key = f"{pkey}|{ct}"
            is_ct_open = ct_key in expanded_cts
            ct_chevron = "▾" if is_ct_open else "▸"
            if st.button(
                f" {ct_chevron} {ct_label}  ({len(ct_rows)})",
                key=f"queue-ct-{ct_key}",
                use_container_width=True,
            ):
                if is_ct_open:
                    expanded_cts.discard(ct_key)
                else:
                    expanded_cts.add(ct_key)
                st.rerun()

            if not is_ct_open:
                continue

            for r in ct_rows:
                is_sel = r["id"] == selected_id
                leaf_label = f"  #{r['id']} · {r['field_path']}"
                clicked = st.button(
                    leaf_label,
                    key=f"queue-pick-{r['id']}",
                    use_container_width=True,
                    type=("primary" if is_sel else "secondary"),
                )
                if clicked and not is_sel:
                    st.session_state["queue_selected_id"] = r["id"]
                    st.rerun()


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Review queue triage")

    # Surface the previous turn's resolve outcome (if any) at the top of
    # the page. Kept in session_state across the st.rerun() so the user
    # sees confirmation after the page refreshes.
    last = st.session_state.pop("queue_last_resolved", None)
    if last is not None:
        st.success(f"Row #{last[0]} resolved as `{last[1]}`.")
    err = st.session_state.pop("queue_last_error", None)
    if err is not None:
        st.error(f"Resolve failed — {err}")

    rows = _list_unresolved(conn)
    if not rows:
        st.success("Queue empty — no unresolved review rows.")
        return

    selected_id = st.session_state.get("queue_selected_id")
    valid_ids = {r["id"] for r in rows}
    if selected_id is None or selected_id not in valid_ids:
        selected_id = rows[0]["id"]
        st.session_state["queue_selected_id"] = selected_id

    sidebar_col, main_col = st.columns([1, 3])
    with sidebar_col:
        _render_sidebar(rows, selected_id)
    with main_col:
        row = next(r for r in rows if r["id"] == selected_id)
        _render_detail(conn, row)
