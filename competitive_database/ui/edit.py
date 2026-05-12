"""Manual-edit a cell — product + field + value + status + note form.

T8.6 scope: second UI write path. Replaces the ``manual-edit`` CLI as
the primary surface for filling empties and overriding bad cells.

Layout:
  1. Product selectbox over every ``(model_code, year)`` pair.
  2. Section → Field cascade over the union of
     ``views.orchestrator.all_field_paths`` across the DB. Offering
     indices collapse to ``*`` in the template; when the user picks a
     templated field, a third "Offering index" selectbox appears
     (mirrors the T8.4 find.py wildcard pattern).
  3. Current-value preview line with provenance marker.
  4. Submit form: new value (text + optional JSON-literal toggle) +
     status (vouched / needs-review) + optional note + optional
     entered-by override.
  5. After save: success banner with the before / after rendered
     side-by-side (same marker palette as the rest of the UI).

Writes route through
:func:`competitive_database.cli.manual_edit.manual_edit_cell` — the same
library handler the CLI calls after the T8.6 refactor. The connection
is the one open in ``ui/app.py``.
"""

from __future__ import annotations

import html
import json
import sqlite3
from typing import Any

import streamlit as st

from competitive_database.cli.manual_edit import manual_edit_cell
from competitive_database.cli.resolve import coerce_value_string
from competitive_database.ui._markers import render_cell, resolve_path
from competitive_database.views import load, orchestrator


def _list_pks(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT model_code, year FROM products ORDER BY model_code, year"
    ).fetchall()
    return [(mc, yr) for mc, yr in rows]


def _template_of(path: str) -> str:
    parts = path.split(".")
    if len(parts) == 3:
        return f"{parts[0]}.*.{parts[2]}"
    return path


def _union_section_templates(
    products: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Union of ``(section, template)`` across products, render order preserved.

    Same pattern as ``ui/find.py``: offering indices collapse to ``*`` so
    one row in the field dropdown represents the leaf shape across every
    offering on every product.
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


def _fmt_cell_html(value: Any) -> str:
    """Render a read_at_path return (bundle dict, plain scalar, or None) as
    one-line ``value [marker]`` HTML — same palette as ``render_cell``."""
    if value is None:
        return render_cell(None, None)
    if isinstance(value, dict):
        return render_cell(value, None)
    return render_cell(None, str(value))


def _format_template_for_dropdown(template: str) -> str:
    return template.replace(".*.", ".N.")


def _resolve_concrete_path(
    product: dict[str, Any],
    template: str,
) -> tuple[str | None, str | None]:
    """Return ``(concrete_path, warning)``. ``warning`` is set if the
    template has a ``*`` but the product has no offerings to write to."""
    if "*" not in template:
        return template, None
    parts = template.split(".")
    offerings_col = parts[0]
    offerings = product.get(offerings_col)
    if not isinstance(offerings, list) or not offerings:
        return None, (
            f"This product has 0 `{offerings_col}` offerings — there's "
            f"no offering to write to. Add one via `refresh` or pick a "
            f"different product."
        )
    return None, None  # placeholder; caller picks the index


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Manual-edit a cell")
    if st.button("← Hub"):
        st.session_state["view"] = "hub"
        st.rerun()

    # Surface the previous turn's edit summary (if any). Kept in
    # session_state so the user sees confirmation after the rerun.
    last = st.session_state.pop("edit_last_summary", None)
    err = st.session_state.pop("edit_last_error", None)
    if err is not None:
        st.error(f"Manual-edit failed — {err}")
    if last is not None:
        before_html = _fmt_cell_html(last["before"])
        after_html = _fmt_cell_html(last["after"])
        st.success(
            f"Wrote `{last['field_path']}` on "
            f"`{last['model_code']}` · {last['year']}."
        )
        st.markdown(
            f'<div style="font-family:ui-monospace,Consolas,Menlo,monospace;'
            f'font-size:0.9rem;padding-left:1.5rem">'
            f'before: {before_html}<br>after: {after_html}'
            f"</div>",
            unsafe_allow_html=True,
        )

    pks = _list_pks(conn)
    if not pks:
        st.info("No products in the database yet.")
        return

    pk_labels = [f"{mc} · {yr}" for mc, yr in pks]
    pk_idx = st.selectbox(
        "Product",
        range(len(pks)),
        format_func=lambda i: pk_labels[i],
        key="edit-product",
    )
    model_code, year = pks[pk_idx]

    # Build the field picker from the DB-wide union (covers fields filled
    # somewhere — sufficient for the common "fill empties on offerings"
    # workflow that motivates this screen). The fully-empty-everywhere
    # case (e.g. a scalar no product has set yet) falls through to the
    # custom-path escape hatch below.
    products = [load.load_product(conn, mc, year=yr) for mc, yr in pks]
    templates = _union_section_templates(products)

    sections: list[str] = []
    for s, _ in templates:
        if s not in sections:
            sections.append(s)

    c1, c2 = st.columns([1, 2])
    section = c1.selectbox("Section", sections, key="edit-section")
    in_section = [t for s, t in templates if s == section]
    template = c2.selectbox(
        "Field",
        in_section,
        format_func=_format_template_for_dropdown,
        key="edit-template",
    )

    product = next(
        p for p in products
        if p["model_code"] == model_code and p["year"] == year
    )

    # Resolve the wildcard template to a concrete path for THIS product.
    if "*" in template:
        offerings_col = template.split(".")[0]
        offerings = product.get(offerings_col) or []
        if not offerings:
            st.warning(
                f"This product has 0 `{offerings_col}` offerings — "
                f"there's no offering to write to. Pick a different field "
                f"or product."
            )
            return
        idx = st.selectbox(
            "Offering index",
            range(len(offerings)),
            key="edit-offering-idx",
        )
        concrete_path = template.replace(".*.", f".{idx}.")
    else:
        concrete_path = template

    bundle, plain = resolve_path(product, concrete_path)
    current_html = render_cell(bundle, plain)
    st.markdown(
        f'<div style="font-family:ui-monospace,Consolas,Menlo,monospace;'
        f'font-size:0.9rem;padding:0.5rem 0">'
        f'Current value at <code>{html.escape(concrete_path)}</code>: '
        f"{current_html}</div>",
        unsafe_allow_html=True,
    )

    with st.form(key=f"edit-form-{model_code}-{year}", clear_on_submit=False):
        value_str = st.text_input(
            "New value",
            placeholder="e.g. 600, OLED, true",
            key=f"edit-val-{model_code}-{year}",
        )
        use_json = st.checkbox(
            "Treat value as JSON literal",
            help="Required for booleans (true / false), null, or lists.",
            key=f"edit-json-{model_code}-{year}",
        )
        status = st.radio(
            "Status",
            ["vouched", "needs-review"],
            horizontal=True,
            help="`vouched` = confident manual entry; `needs-review` = "
            "self-flagged for follow-up.",
            key=f"edit-status-{model_code}-{year}",
        )
        note = st.text_input(
            "Note (source / rationale)",
            placeholder="Optional — stored as the bundle's source_note.",
            key=f"edit-note-{model_code}-{year}",
        )
        entered_by = st.text_input(
            "Entered by (override)",
            placeholder="Optional — defaults to $USER / $USERNAME env var.",
            key=f"edit-by-{model_code}-{year}",
        )
        submitted = st.form_submit_button("Save manual edit", type="primary")
        if not submitted:
            st.caption(
                f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.6"
            )
            return

        if not value_str and not use_json:
            st.error(
                "Enter a value (or check 'Treat as JSON' to pass null / lists)."
            )
            return
        try:
            if use_json:
                value: Any = json.loads(value_str) if value_str else None
            else:
                value = coerce_value_string(value_str)
        except json.JSONDecodeError as exc:
            st.error(f"Value is not valid JSON: {exc}")
            return
        try:
            summary = manual_edit_cell(
                conn,
                model_code=model_code,
                year=year,
                field_path=concrete_path,
                value=value,
                status=status,
                note=note or None,
                entered_by=entered_by or None,
            )
        except ValueError as exc:
            st.session_state["edit_last_error"] = str(exc)
            st.rerun()
            return
        st.session_state["edit_last_summary"] = summary
        st.rerun()
