"""Edit one product — bulk per-field editor with pending-change buffer.

Phase F (Stage 10a) rewrite. The previous single-field form is replaced
with a bulk editor: pick a product (Company / Product / Year), see every
spec field listed vertically grouped by section, click the pencil on any
row to expand an inline form (new value / status pills / source URL /
note), accumulate changes across as many rows as the user wants, then
save them all in one go via :func:`competitive_database.cli.manual_edit.manual_edit_cell`.

No JSON-literal toggle, no field-path strings visible — type coercion
runs behind the scenes via :func:`competitive_database.views.formatting.coerce_to_field_type`.
"""

from __future__ import annotations

import html
import sqlite3
from typing import Any

import streamlit as st

from competitive_database.cli.manual_edit import manual_edit_cell
from competitive_database.ui._components import (
    cascading_picker,
    dot_marker,
    friendly_leaf_label,
)
from competitive_database.ui._markers import resolve_path
from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_VENDOR_NO_PUB,
    MARKER_VERIFIED,
    coerce_to_field_type,
    display_value,
    marker_for_bundle,
)
from competitive_database.views.orchestrator import _SECTION_REGISTRY


# Pill labels surfaced in the inline form; mapped to the canonical
# ``manual_edit_cell`` status strings on save. ``manual`` is a real
# third status (Stage 10a) — no longer aliased to ``vouched``.
_STATUS_PILLS: list[str] = ["verified", "needs review", "manual"]
_STATUS_TO_BUNDLE: dict[str, str] = {
    "verified": "vouched",
    "needs review": "needs-review",
    "manual": "manual",
}
_DEFAULT_PILL = "verified"


def _edit_css() -> str:
    """Return the scoped <style> block for the Edit screen."""
    return """
<style>
.cd-edit__title {
    font-size: var(--cd-size-xl);
    font-weight: 600;
    color: var(--cd-text);
    margin-bottom: var(--cd-space-xs);
}
.cd-edit__subtitle {
    font-size: var(--cd-size-sm);
    color: var(--cd-text-muted);
    margin-bottom: var(--cd-space-lg);
}
.cd-edit__section-header {
    display: flex;
    align-items: center;
    gap: var(--cd-space-md);
    color: var(--cd-text-faint);
    font-size: var(--cd-size-xs);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 500;
    margin: var(--cd-space-lg) 0 var(--cd-space-xs) 0;
}
.cd-edit__section-header::before,
.cd-edit__section-header::after {
    content: "";
    flex: 1;
    border-top: 1px dashed var(--cd-border);
}
.cd-edit__row {
    border-left: 3px solid transparent;
    padding: var(--cd-space-xs) var(--cd-space-sm);
    border-bottom: 1px solid var(--cd-border);
}
.cd-edit__row--active {
    border-left: 3px solid var(--cd-accent);
    background: var(--cd-bg-accent-soft);
}
.cd-edit__feature {
    color: var(--cd-text-muted);
    font-size: var(--cd-size-sm);
    padding-top: 6px;
}
.cd-edit__value {
    color: var(--cd-text);
    font-size: var(--cd-size-sm);
    padding-top: 6px;
}
.cd-edit__value--placeholder {
    color: var(--cd-text-faint);
    font-style: italic;
}
.cd-edit__form {
    padding: var(--cd-space-sm) 0 var(--cd-space-sm) var(--cd-space-lg);
}
.cd-edit__pill-active {
    color: var(--cd-text);
    font-weight: 600;
}
.cd-edit__savebar {
    margin-top: var(--cd-space-xl);
    padding-top: var(--cd-space-md);
    border-top: 1px solid var(--cd-border);
}
</style>
"""


def _bundle_value_str(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return None
    v = raw.get("value")
    if isinstance(v, str) and v:
        return v
    return None


def _offering_identity(
    product: dict[str, Any], path: str
) -> str | None:
    """Return a short ``(offering N: cpu name)``-style suffix for offering rows."""
    parts = path.split(".")
    if len(parts) != 3:
        return None
    col, idx_s, _leaf = parts
    try:
        idx = int(idx_s)
    except ValueError:
        return None
    offerings = product.get(col)
    if not isinstance(offerings, list) or idx >= len(offerings):
        return None
    offering = offerings[idx]
    if not isinstance(offering, dict):
        return None
    # Surface the CPU model / board label / display ordinal — whatever
    # disambiguates this row from its siblings. Falls back to the bare
    # ordinal when the offering carries no name leaf.
    for name_leaf in ("model", "label"):
        name = _bundle_value_str(offering.get(name_leaf))
        if name:
            return f"{name} (#{idx + 1})"
    return f"#{idx + 1}"


def _row_label(product: dict[str, Any], section: str, path: str, label: str) -> str:
    """Friendly row label combining the leaf label with offering identity."""
    parts = path.split(".")
    if len(parts) == 3:
        leaf = parts[-1]
        leaf_label = friendly_leaf_label(leaf, section)
        ident = _offering_identity(product, path)
        if ident:
            return f"{leaf_label} — {ident}"
        return leaf_label
    return friendly_leaf_label(parts[-1], section)


def _current_value_str(product: dict[str, Any], path: str) -> tuple[str, str]:
    """Return ``(display_value, marker_token)`` for the current cell."""
    bundle, plain = resolve_path(product, path)
    if plain is not None:
        return plain, MARKER_VERIFIED
    marker = marker_for_bundle(bundle)
    if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB):
        return "—", marker
    value = display_value(bundle, field_path=path) or "—"
    return value, marker


def _current_value_raw(product: dict[str, Any], path: str) -> str:
    """Return a plain string suitable for prefilling the New-value input."""
    bundle, plain = resolve_path(product, path)
    if plain is not None:
        return plain
    if isinstance(bundle, dict):
        v = bundle.get("value")
        if v is None:
            return ""
        if isinstance(v, bool):
            return "yes" if v else "no"
        return str(v)
    return ""


def _product_key(picked: dict | None) -> tuple[str, str, int] | None:
    if picked is None:
        return None
    return picked["company"], picked["product"], int(picked["year"])


def _reset_pending_state() -> None:
    st.session_state["edit.pending"] = {}
    st.session_state["edit.active_rows"] = set()


def _maybe_reset_on_product_change(picked: dict | None) -> None:
    """Clear pending + active state when the picked product changes."""
    new_key = _product_key(picked)
    prev_key = st.session_state.get("edit.product_key")
    if prev_key != new_key:
        st.session_state["edit.product_key"] = new_key
        _reset_pending_state()


def _ensure_state() -> None:
    if "edit.pending" not in st.session_state:
        st.session_state["edit.pending"] = {}
    if "edit.active_rows" not in st.session_state:
        st.session_state["edit.active_rows"] = set()


def _flush_flash() -> None:
    summary = st.session_state.pop("edit.last_save_summary", None)
    if summary:
        st.success(summary)
    err = st.session_state.pop("edit.last_save_error", None)
    if err:
        st.error(err)


def _save_pending(
    conn: sqlite3.Connection,
    product: dict[str, Any],
) -> None:
    """Apply every pending change to the DB; surface per-row errors."""
    pending: dict[str, dict[str, Any]] = st.session_state.get(
        "edit.pending", {}
    )
    if not pending:
        return
    model_code = product.get("model_code")
    year_raw = product.get("year")
    try:
        year = int(year_raw) if year_raw is not None else None
    except (TypeError, ValueError):
        year = None
    if not isinstance(model_code, str) or year is None:
        st.session_state["edit.last_save_error"] = (
            "Could not save — product has no resolvable (model_code, year)."
        )
        return

    errors: list[str] = []
    saved = 0
    for concrete_path, change in list(pending.items()):
        new_value_raw: str = change.get("new_value", "")
        status_pill: str = change.get("status", _DEFAULT_PILL)
        source_url = change.get("source_url") or None
        note = change.get("note") or None
        bundle_status = _STATUS_TO_BUNDLE.get(status_pill, "vouched")

        # Annotation-only edit: empty new value → write the current
        # rendered value as-is so only the metadata (status/note/source)
        # changes. Booleans need their original Python form preserved,
        # which we can't recover from a rendered display string — for
        # now, annotation-only edits on bool fields fall back to the
        # rendered "yes"/"no" coerced back to bool by the type rules.
        if new_value_raw == "":
            new_value_raw = _current_value_raw(product, concrete_path)
            if new_value_raw == "":
                errors.append(
                    f"Could not save {concrete_path}: nothing to write "
                    f"(empty new value and empty current value)."
                )
                continue

        try:
            value = coerce_to_field_type(concrete_path, new_value_raw)
        except ValueError as exc:
            errors.append(f"Could not save {concrete_path}: {exc}")
            continue

        try:
            manual_edit_cell(
                conn,
                model_code=model_code,
                year=year,
                field_path=concrete_path,
                value=value,
                status=bundle_status,
                note=note,
                entered_by=None,
                source_url=source_url,
            )
            saved += 1
        except ValueError as exc:
            errors.append(f"Could not save {concrete_path}: {exc}")
            continue

    if errors:
        st.session_state["edit.last_save_error"] = " · ".join(errors)
        return

    plural = "s" if saved != 1 else ""
    st.session_state["edit.last_save_summary"] = (
        f"Saved {saved} change{plural}."
    )
    _reset_pending_state()


def _render_compact_row(
    product: dict[str, Any],
    section: str,
    path: str,
    label: str,
) -> None:
    """Render one collapsed row: feature + current value + pencil button."""
    pending: dict[str, dict[str, Any]] = st.session_state["edit.pending"]
    active: set[str] = st.session_state["edit.active_rows"]
    row_label = _row_label(product, section, path, label)
    value_str, marker = _current_value_str(product, path)

    is_active = path in active
    row_cls = "cd-edit__row cd-edit__row--active" if is_active else "cd-edit__row"

    with st.container():
        st.markdown(
            f'<div class="{row_cls}">',
            unsafe_allow_html=True,
        )
        cols = st.columns([3, 5, 1])
        with cols[0]:
            st.markdown(
                f'<div class="cd-edit__feature">{html.escape(row_label)}</div>',
                unsafe_allow_html=True,
            )
        with cols[1]:
            placeholder_cls = (
                " cd-edit__value--placeholder"
                if marker in (MARKER_EMPTY, MARKER_VENDOR_NO_PUB)
                else ""
            )
            st.markdown(
                f'<div class="cd-edit__value{placeholder_cls}">'
                f'{dot_marker(marker)}{html.escape(value_str)}'
                "</div>",
                unsafe_allow_html=True,
            )
        with cols[2]:
            btn_key = f"edit.pencil.{path}"
            if not is_active:
                if st.button("Edit", key=btn_key, help="Edit this field"):
                    active.add(path)
                    st.rerun()
            else:
                if st.button("Cancel", key=btn_key, help="Collapse this row"):
                    active.discard(path)
                    pending.pop(path, None)
                    st.rerun()
        if is_active:
            _render_active_form(product, path)
        st.markdown("</div>", unsafe_allow_html=True)


def _render_active_form(product: dict[str, Any], path: str) -> None:
    """Render the inline form below the compact line for an active row."""
    pending: dict[str, dict[str, Any]] = st.session_state["edit.pending"]
    existing = pending.get(path) or {}
    default_new = existing.get("new_value")
    if default_new is None:
        default_new = _current_value_raw(product, path)
    default_status = existing.get("status", _DEFAULT_PILL)
    default_source = existing.get("source_url") or ""
    default_note = existing.get("note") or ""

    with st.container():
        st.markdown('<div class="cd-edit__form">', unsafe_allow_html=True)
        new_value = st.text_input(
            "New value",
            value=default_new,
            key=f"edit.newval.{path}",
            help="Leave empty to change only status / source / note.",
        )
        status = st.radio(
            "Status",
            _STATUS_PILLS,
            index=_STATUS_PILLS.index(default_status)
            if default_status in _STATUS_PILLS
            else 0,
            horizontal=True,
            key=f"edit.status.{path}",
        )
        source_url = st.text_input(
            "Source URL",
            value=default_source,
            key=f"edit.source.{path}",
        )
        note = st.text_area(
            "Note (optional)",
            value=default_note,
            key=f"edit.note.{path}",
            height=68,
        )
        pending[path] = {
            "new_value": new_value,
            "status": status,
            "source_url": source_url or None,
            "note": note or None,
        }
        remove_key = f"edit.remove.{path}"
        if st.button("Remove change", key=remove_key):
            pending.pop(path, None)
            st.session_state["edit.active_rows"].discard(path)
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


def _render_section(
    product: dict[str, Any],
    section_name: str,
    paths: list[tuple[str, str]],
) -> None:
    """Render one section: dotted header + per-field compact rows."""
    st.markdown(
        f'<div class="cd-edit__section-header">{html.escape(section_name)}</div>',
        unsafe_allow_html=True,
    )
    if not paths:
        st.markdown(
            '<div class="cd-edit__row">'
            '<div class="cd-edit__value cd-edit__value--placeholder">'
            "(no data scraped)</div></div>",
            unsafe_allow_html=True,
        )
        return
    for path, label in paths:
        _render_compact_row(product, section_name, path, label)


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the bulk-edit screen."""
    del db_path  # chrome handles attribution; no internal IDs leak here.

    _ensure_state()
    st.markdown(_edit_css(), unsafe_allow_html=True)
    st.markdown(
        '<div class="cd-edit__title">Edit a product</div>'
        '<div class="cd-edit__subtitle">'
        "Make changes across any number of fields. All edits are saved together."
        "</div>",
        unsafe_allow_html=True,
    )
    _flush_flash()

    picked = cascading_picker(conn, key_prefix="edit", vertical=False)
    if picked is None:
        st.info("No products in the database yet.")
        return

    _maybe_reset_on_product_change(picked)

    if (
        st.session_state.get("edit.company") is None
        or st.session_state.get("edit.product") is None
        or st.session_state.get("edit.year") is None
    ):
        # The picker handles its own selectbox defaults; this branch is
        # a belt-and-braces guard for the early-render case.
        st.info("Pick a product to start editing.")
        return

    product = picked["row"]

    # Field list, grouped by section.
    for section_name, fn in _SECTION_REGISTRY:
        if section_name == "Identity":
            # Identity leaves are surfaced by the orchestrator's identity
            # helper; we still render them under an "Identity" header so
            # the user can edit vendor name / brand / segment / status.
            paths = fn(product)
        else:
            paths = fn(product)
        _render_section(product, section_name, paths)

    # Save bar.
    st.markdown('<div class="cd-edit__savebar"></div>', unsafe_allow_html=True)
    n_pending = len(st.session_state["edit.pending"])
    plural = "s" if n_pending != 1 else ""
    save_label = f"Save {n_pending} change{plural}"
    save_cols = st.columns([1, 2, 1])
    with save_cols[0]:
        if st.button("Cancel", key="edit.cancel"):
            _reset_pending_state()
            st.rerun()
    with save_cols[2]:
        if st.button(
            save_label,
            key="edit.save",
            type="primary",
            disabled=n_pending == 0,
        ):
            _save_pending(conn, product)
            st.rerun()
