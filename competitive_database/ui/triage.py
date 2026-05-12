"""Review queue triage — sidebar list + main panel detail.

T8.5 scope: first UI write path. Lists every unresolved ``review_queue``
row in a left-rail list; selecting a row loads its existing-vs-candidate
diff into the right-hand panel with four action buttons matching the
``resolve`` CLI verbs (``accept_candidate`` / ``kept_existing`` /
``manual_override`` / ``dropped``).

Writes route through :func:`competitive_database.cli.resolve.resolve_row`
— the same handler the CLI uses, re-callable as a library function after
the Session 31 refactor. ``new_chip_unverified`` rows get the catalog
vouching dispatch (only ``accept_candidate`` / ``dropped`` are valid);
the UI greys out the inapplicable buttons.
"""

from __future__ import annotations

import html
import json
import sqlite3
from typing import Any

import streamlit as st

from competitive_database.cli.resolve import coerce_value_string, resolve_row
from competitive_database.ui._markers import MARKER_COLORS
from competitive_database.views.formatting import marker_for_bundle

_QUEUE_COLS = (
    "id, product_model_code, product_year, field_path, conflict_type, "
    "existing_value, existing_provenance, candidate_value, "
    "candidate_provenance, detected_at"
)


def _list_unresolved(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {_QUEUE_COLS} FROM review_queue "
        "WHERE resolved_at IS NULL ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def _decode_json(raw: Any) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _marker_html(marker: str) -> str:
    color = MARKER_COLORS.get(marker, "#8b949e")
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
        body = '<span style="color:#6e7681">—</span>'
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
            '<div style="color:#6e7681;font-style:italic">(no value)</div>',
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


def _summarize_for_sidebar(row: dict[str, Any]) -> str:
    """One-line label for a queue row in the left rail."""
    mc = row["product_model_code"] or "?"
    short_mc = mc[:16] + "…" if len(mc) > 17 else mc
    ct = row["conflict_type"] or "?"
    ct_short = {
        "value_disagreement": "value_dis",
        "low_confidence_extraction": "low_conf",
        "new_chip_unverified": "new_chip",
        "year_inferred": "year_inf",
    }.get(ct, ct)
    return f"#{row['id']} · {short_mc} · {ct_short}"


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
            "`kept_existing` / `manual_override` aren't valid for "
            "`new_chip_unverified` rows — `existing_value` is always NULL."
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
    st.caption(
        f"conflict: `{ct}` · field: `{fp}` · detected: {detected}"
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
    st.markdown(f"**Queue ({len(rows)})**")
    for r in rows:
        is_sel = r["id"] == selected_id
        label = _summarize_for_sidebar(r)
        clicked = st.button(
            label,
            key=f"queue-pick-{r['id']}",
            use_container_width=True,
            type=("primary" if is_sel else "secondary"),
        )
        if clicked and not is_sel:
            st.session_state["queue_selected_id"] = r["id"]
            st.rerun()


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Review queue triage")
    if st.button("← Hub"):
        st.session_state["view"] = "hub"
        st.rerun()

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
        st.caption(
            f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.5"
        )
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

    st.caption(
        f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.5 · "
        f"first write path"
    )
