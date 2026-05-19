"""Refresh products — three-mode tabbed picker + slim progress card + result panel.

Phase G (Stage 10a) rewrite. The pre-Phase-G screen exposed a 2-mode
radio (one product / all products) with an inner URL-source toggle and
streamed an ``st.status`` event log during a run. This rewrite collapses
the modes into three editorial tabs (All products / By company /
Selected products), all sourcing URLs from the DB, and replaces the
event log with a slim in-progress card that transitions to a designed
post-run result panel.

The actual refresh batch lives in
:func:`competitive_database.cli.refresh.refresh_product` — we drive it
in a per-product loop here so the UI can rewrite the in-progress card
between products. ``refresh_all_products`` is not called directly; its
planning logic is mirrored locally so the UI surfaces per-target skip
reasons without re-fetching.
"""

from __future__ import annotations

import html
import json
import sqlite3
import time
from typing import Any, Optional

import streamlit as st

from competitive_database.cli.refresh import (
    VENDOR_TEMPLATES,
    collect_source_urls_from_product,
    refresh_product,
)
from competitive_database.ui._components import _product_name


_MODE_KEY = "refresh.mode"
_LAST_RESULT_KEY = "refresh.last_result"
_MODE_ALL = "all"
_MODE_COMPANY = "company"
_MODE_SELECTED = "selected"
_MODE_LABELS: dict[str, str] = {
    _MODE_ALL: "All products",
    _MODE_COMPANY: "By company",
    _MODE_SELECTED: "Selected products",
}
_MODES_ORDERED: list[str] = [_MODE_ALL, _MODE_COMPANY, _MODE_SELECTED]


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------


_REFRESH_CSS = """
<style>
.cd-refresh__title {
    font-size: var(--cd-size-xl);
    font-weight: 600;
    color: var(--cd-text);
    margin-bottom: var(--cd-space-lg);
}
.cd-refresh__tabs {
    display: flex;
    gap: var(--cd-space-md);
    margin-bottom: var(--cd-space-lg);
}
.cd-refresh__tab {
    color: var(--cd-text-muted);
    font-size: var(--cd-size-sm);
    padding: var(--cd-space-xs) var(--cd-space-md);
}
.cd-refresh__tab--active {
    background: var(--cd-bg-card);
    border: 1px solid var(--cd-border);
    border-radius: var(--cd-radius-md);
    color: var(--cd-text);
    font-weight: 600;
    border-bottom: 2px solid var(--cd-accent);
}
.cd-refresh__plan {
    color: var(--cd-text-muted);
    font-size: var(--cd-size-sm);
    margin: var(--cd-space-md) 0 var(--cd-space-sm) 0;
}
.cd-refresh__last-run {
    color: var(--cd-text-faint);
    font-size: var(--cd-size-xs);
    margin-top: var(--cd-space-xs);
}
.cd-refresh__divider {
    border: none;
    border-top: 1px dotted var(--cd-border);
    margin: var(--cd-space-xl) 0 var(--cd-space-lg) 0;
}
.cd-refresh__progress-card {
    background: var(--cd-bg-card);
    border: 1px solid var(--cd-border);
    border-radius: var(--cd-radius-md);
    padding: var(--cd-space-lg);
    margin: var(--cd-space-md) 0;
}
.cd-refresh__progress-headline {
    font-size: var(--cd-size-lg);
    font-weight: 600;
    color: var(--cd-text);
    margin-bottom: var(--cd-space-xs);
}
.cd-refresh__progress-sub {
    font-size: var(--cd-size-sm);
    color: var(--cd-text-muted);
    margin-bottom: var(--cd-space-md);
}
.cd-refresh__progress-counter {
    font-size: var(--cd-size-xs);
    color: var(--cd-text-faint);
    margin-top: var(--cd-space-xs);
}
.cd-refresh__result-headline {
    font-size: var(--cd-size-lg);
    font-weight: 600;
    color: var(--cd-text);
    margin-bottom: var(--cd-space-md);
}
.cd-refresh__tile {
    background: var(--cd-bg-card);
    border: 1px solid var(--cd-border);
    border-radius: var(--cd-radius-md);
    padding: var(--cd-space-md) var(--cd-space-lg);
}
.cd-refresh__tile-value {
    font-size: var(--cd-size-hero);
    font-weight: 600;
    color: var(--cd-text);
    line-height: 1.1;
}
.cd-refresh__tile-label {
    margin-top: var(--cd-space-xs);
    font-size: var(--cd-size-sm);
    color: var(--cd-text-muted);
}
.cd-refresh__attention-title {
    font-size: var(--cd-size-sm);
    font-weight: 600;
    color: var(--cd-text);
    margin: var(--cd-space-lg) 0 var(--cd-space-xs) 0;
}
.cd-refresh__attention-line {
    font-size: var(--cd-size-sm);
    color: var(--cd-text);
    margin: 2px 0;
}
.cd-refresh__attention-line--info {
    color: var(--cd-text-muted);
}
.cd-refresh__skipped-row {
    font-size: var(--cd-size-sm);
    color: var(--cd-text-muted);
    display: flex;
    gap: var(--cd-space-md);
    padding: 2px 0;
}
.cd-refresh__skipped-slug {
    color: var(--cd-text);
    min-width: 28ch;
}
.cd-refresh__error-row {
    font-size: var(--cd-size-sm);
    color: var(--cd-marker-needs-review);
    padding: 2px 0;
}
</style>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bundle_value(raw: Any) -> Optional[str]:
    if not isinstance(raw, str) or not raw:
        if isinstance(raw, dict):
            v = raw.get("value")
            return v.strip() if isinstance(v, str) and v.strip() else None
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict):
        v = parsed.get("value")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _enumerate_targets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Classify every DB product into eligible / skipped (with reason).

    Mirrors the planning logic in ``refresh_all_products`` but produces a
    UI-shaped dict per row carrying both the friendly product name and
    the raw skip reason, so the plan summary and the post-run skipped
    expander render off one query.
    """
    rows = conn.execute(
        "SELECT model_code, year, brand, vendor_full_name FROM products "
        "ORDER BY model_code, year"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        mc = row["model_code"]
        yr = row["year"]
        brand_value = _bundle_value(row["brand"])
        brand_lc = brand_value.lower() if brand_value else None
        vfn = _bundle_value(row["vendor_full_name"])
        friendly = _product_name(vfn, mc, int(yr))
        record: dict[str, Any] = {
            "model_code": mc,
            "year": int(yr),
            "brand": brand_lc,
            "brand_display": brand_value or "Unknown",
            "friendly_name": friendly,
            "slug": f"{mc}-{yr}",
            "skip_reason": None,
        }
        if brand_lc is None:
            record["skip_reason"] = "brand bundle is empty or missing"
            out.append(record)
            continue
        if brand_lc not in VENDOR_TEMPLATES:
            record["skip_reason"] = f"brand {brand_lc!r} not supported"
            out.append(record)
            continue
        try:
            urls = collect_source_urls_from_product(
                conn, model_code=mc, year=int(yr)
            )
        except ValueError as exc:
            record["skip_reason"] = str(exc)
            out.append(record)
            continue
        if not urls:
            record["skip_reason"] = "no scraped source_url on this row"
            out.append(record)
            continue
        record["url_count"] = len(urls)
        out.append(record)
    return out


def _plan_summary(targets: list[dict[str, Any]], scope_label: str) -> str:
    """Build the one-line ``N in catalog · M will refresh · K skipped`` text."""
    n = len(targets)
    skipped = sum(1 for t in targets if t["skip_reason"] is not None)
    will = n - skipped
    return (
        f"{n} {scope_label} · {will} will refresh "
        f"· {skipped} skipped (no URL template)"
    )


def _time_ago(seconds: float) -> str:
    """Return a coarse ``N minutes ago`` / ``N hours ago`` / ``N days ago`` string."""
    seconds = max(seconds, 0)
    if seconds < 90:
        return "just now"
    minutes = seconds / 60.0
    if minutes < 90:
        n = max(int(round(minutes)), 1)
        return f"{n} minute{'s' if n != 1 else ''} ago"
    hours = minutes / 60.0
    if hours < 36:
        n = max(int(round(hours)), 1)
        return f"{n} hour{'s' if n != 1 else ''} ago"
    days = hours / 24.0
    n = max(int(round(days)), 1)
    return f"{n} day{'s' if n != 1 else ''} ago"


def _format_duration(seconds: float) -> str:
    seconds = max(seconds, 0)
    if seconds < 60:
        return f"{int(round(seconds))} seconds"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.1f} minutes"
    hours = minutes / 60.0
    return f"{hours:.1f} hours"


def _render_tabs() -> str:
    """Render the three-tab mode picker via columns + primary-on-active buttons.

    Returns the current mode value. Active cue is delivered through the
    ``type="primary"`` styling already wired in ``theme.inject_global_css``;
    inactive tabs are plain (text-only-looking) Streamlit buttons.
    """
    current = st.session_state.get(_MODE_KEY, _MODE_ALL)
    if current not in _MODES_ORDERED:
        current = _MODE_ALL
    st.session_state[_MODE_KEY] = current
    cols = st.columns(len(_MODES_ORDERED))
    for col, mode in zip(cols, _MODES_ORDERED):
        with col:
            is_active = mode == current
            btn_type = "primary" if is_active else "secondary"
            if st.button(
                _MODE_LABELS[mode],
                key=f"refresh.tab.{mode}",
                type=btn_type,
                use_container_width=True,
            ):
                if not is_active:
                    st.session_state[_MODE_KEY] = mode
                    st.rerun()
    return current


def _render_last_run_caption() -> None:
    last = st.session_state.get(_LAST_RESULT_KEY)
    if not isinstance(last, dict):
        return
    started = last.get("started_at")
    if not isinstance(started, (int, float)):
        return
    ago = _time_ago(time.time() - started)
    st.markdown(
        f'<div class="cd-refresh__last-run">Last run {html.escape(ago)}</div>',
        unsafe_allow_html=True,
    )


def _render_plan_line(text: str) -> None:
    st.markdown(
        f'<div class="cd-refresh__plan">{html.escape(text)}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Run driver
# ---------------------------------------------------------------------------


def _run_batch(
    conn: sqlite3.Connection,
    eligible: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    mode: str,
    panel: "st.delta_generator.DeltaGenerator",
) -> dict[str, Any]:
    """Refresh each eligible target sequentially, rewriting the panel as we go.

    ``panel`` is a ``st.empty()`` placeholder owned by the caller — we
    rewrite it between products so the slim in-progress card stays put
    (no page churn). After the loop the caller transitions the same slot
    to the result panel.
    """
    n = len(eligible)
    started_at = time.time()

    totals = {
        "inserted_fields": 0,
        "refreshed_fields": 0,
        "conflicts": 0,
        "low_confidence": 0,
        "year_inferred": 0,
        "new_cpus": 0,
        "new_gpus": 0,
    }
    refreshed_count = 0
    errors: list[dict[str, Any]] = []

    for idx, target in enumerate(eligible, start=1):
        with panel.container():
            st.markdown(
                '<div class="cd-refresh__progress-card">'
                f'<div class="cd-refresh__progress-headline">'
                f'Refreshing {idx} of {n}…</div>'
                f'<div class="cd-refresh__progress-sub">'
                f'{html.escape(target["friendly_name"])} · {target["year"]}'
                "</div>"
                "</div>",
                unsafe_allow_html=True,
            )
            st.progress(idx / max(n, 1))
            st.markdown(
                f'<div class="cd-refresh__progress-counter">'
                f'{idx} of {n}</div>',
                unsafe_allow_html=True,
            )

        try:
            sub = refresh_product(
                conn,
                brand=target["brand"],
                model=target["model_code"],
                from_db=True,
                year=target["year"],
            )
        except Exception as exc:  # noqa: BLE001 — vendor / infra failure surfaced per-row
            errors.append({
                "model_code": target["model_code"],
                "year": target["year"],
                "friendly_name": target["friendly_name"],
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        refreshed_count += 1
        t = sub["totals"]
        for k in totals:
            totals[k] += t[k]

    duration_s = time.time() - started_at

    attention_lines: list[dict[str, str]] = []
    if totals["conflicts"]:
        attention_lines.append({
            "marker": "●",
            "kind": "priority",
            "text": (
                f"{totals['conflicts']} cells flagged as conflicts "
                "→ sent to the review queue."
            ),
        })
    catalog_additions = totals["new_cpus"] + totals["new_gpus"]
    if catalog_additions:
        attention_lines.append({
            "marker": "●",
            "kind": "priority",
            "text": (
                f"{catalog_additions} new CPU / GPU chips added to the catalog."
            ),
        })
    if totals["low_confidence"]:
        attention_lines.append({
            "marker": "·",
            "kind": "info",
            "text": f"{totals['low_confidence']} cells with low confidence in this batch.",
        })
    if totals["year_inferred"]:
        attention_lines.append({
            "marker": "·",
            "kind": "info",
            "text": (
                f"{totals['year_inferred']} products had year inferred from URL "
                "(no year in payload)."
            ),
        })

    skipped_records = [
        {
            "slug": s["slug"],
            "friendly_name": s["friendly_name"],
            "reason": s["skip_reason"],
        }
        for s in skipped
    ]

    return {
        "mode": mode,
        "headline_count": refreshed_count,
        "started_at": started_at,
        "duration_s": duration_s,
        "refreshed": refreshed_count,
        "inserted": totals["inserted_fields"],
        "conflicts": totals["conflicts"],
        "catalog_additions": catalog_additions,
        "low_confidence": totals["low_confidence"],
        "year_inferred": totals["year_inferred"],
        "attention_lines": attention_lines,
        "skipped": skipped_records,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Post-run result panel
# ---------------------------------------------------------------------------


def _tile_html(value: str, label: str) -> str:
    return (
        '<div class="cd-refresh__tile">'
        f'<div class="cd-refresh__tile-value">{html.escape(value)}</div>'
        f'<div class="cd-refresh__tile-label">{html.escape(label)}</div>'
        "</div>"
    )


def _render_result_panel(result: dict[str, Any]) -> None:
    """Render the post-run result panel (4 tiles + attention + skipped)."""
    st.markdown(
        '<hr class="cd-refresh__divider" />',
        unsafe_allow_html=True,
    )
    ago = _time_ago(time.time() - result["started_at"])
    duration = _format_duration(result["duration_s"])
    n = result["headline_count"]
    plural = "s" if n != 1 else ""
    st.markdown(
        '<div class="cd-refresh__result-headline">'
        f'{n} product{plural} refreshed   ·   {html.escape(ago)}   '
        f'·   {html.escape(duration)}'
        "</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(4)
    tiles = [
        (str(result["refreshed"]), "Refreshed"),
        (str(result["inserted"]), "New products inserted"),
        (str(result["conflicts"]), "Conflicts (in queue)"),
        (str(result["catalog_additions"]), "Catalog additions"),
    ]
    for col, (val, label) in zip(cols, tiles):
        with col:
            st.markdown(_tile_html(val, label), unsafe_allow_html=True)

    attention = result.get("attention_lines") or []
    if attention:
        st.markdown(
            '<div class="cd-refresh__attention-title">What needs attention</div>',
            unsafe_allow_html=True,
        )
        for line in attention[:4]:
            cls = "cd-refresh__attention-line"
            if line.get("kind") == "info":
                cls += " cd-refresh__attention-line--info"
            st.markdown(
                f'<div class="{cls}">{html.escape(line["marker"])} '
                f'{html.escape(line["text"])}</div>',
                unsafe_allow_html=True,
            )

    errors = result.get("errors") or []
    if errors:
        st.markdown(
            '<div class="cd-refresh__attention-title">Errors</div>',
            unsafe_allow_html=True,
        )
        for err in errors:
            st.markdown(
                '<div class="cd-refresh__error-row">'
                f'● {html.escape(err["friendly_name"])} · '
                f'{err["year"]} — {html.escape(err["error"])}'
                "</div>",
                unsafe_allow_html=True,
            )

    skipped = result.get("skipped") or []
    if skipped:
        with st.expander(f"Skipped ({len(skipped)})", expanded=True):
            for s in skipped:
                st.markdown(
                    '<div class="cd-refresh__skipped-row">'
                    f'<span class="cd-refresh__skipped-slug">'
                    f'{html.escape(s["slug"])}</span>'
                    f'<span>{html.escape(s["reason"])}</span>'
                    "</div>",
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Per-mode bodies
# ---------------------------------------------------------------------------


def _resolve_run(
    conn: sqlite3.Connection,
    eligible: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    mode: str,
) -> None:
    """Drive a batch run: in-progress card → result panel; persist + rerun."""
    placeholder = st.empty()
    with placeholder.container():
        result = _run_batch(conn, eligible, skipped, mode, placeholder)
    placeholder.empty()
    st.session_state[_LAST_RESULT_KEY] = result
    st.rerun()


def _render_all_body(
    conn: sqlite3.Connection, targets: list[dict[str, Any]]
) -> None:
    eligible = [t for t in targets if t["skip_reason"] is None]
    skipped = [t for t in targets if t["skip_reason"] is not None]
    _render_plan_line(_plan_summary(targets, "products in catalog"))
    _render_last_run_caption()
    if st.button(
        "Run refresh",
        type="primary",
        key="refresh.run.all",
        disabled=not eligible,
    ):
        _resolve_run(conn, eligible, skipped, _MODE_ALL)


def _render_company_body(
    conn: sqlite3.Connection, targets: list[dict[str, Any]]
) -> None:
    companies = sorted(
        {t["brand_display"] for t in targets if t["brand"] is not None},
        key=str.lower,
    )
    if not companies:
        st.info("No companies with refresh-capable products in the DB yet.")
        return
    company = st.selectbox("Company", companies, key="refresh.company")
    company_lc = company.lower() if isinstance(company, str) else None
    company_targets = [
        t for t in targets if t["brand"] == company_lc
    ]
    eligible = [t for t in company_targets if t["skip_reason"] is None]
    skipped = [t for t in company_targets if t["skip_reason"] is not None]
    _render_plan_line(_plan_summary(company_targets, f"{company} products in catalog"))
    _render_last_run_caption()
    if st.button(
        "Run refresh",
        type="primary",
        key="refresh.run.company",
        disabled=not eligible,
    ):
        _resolve_run(conn, eligible, skipped, _MODE_COMPANY)


def _render_selected_body(
    conn: sqlite3.Connection, targets: list[dict[str, Any]]
) -> None:
    if not targets:
        st.info("No products in the database yet.")
        return
    # Build a stable label map keyed by ``slug`` so multiselect chips show
    # the friendly product name + year while we keep the underlying
    # primary key available for the run loop.
    label_map: dict[str, dict[str, Any]] = {}
    options: list[str] = []
    for t in targets:
        label = f"{t['friendly_name']} · {t['year']}"
        # Disambiguate the rare collision where two products share the
        # same friendly name + year.
        suffix = 1
        unique = label
        while unique in label_map:
            suffix += 1
            unique = f"{label} ({suffix})"
        label_map[unique] = t
        options.append(unique)
    chosen = st.multiselect(
        "Products",
        options,
        key="refresh.selected",
    )
    chosen_targets = [label_map[lbl] for lbl in chosen if lbl in label_map]
    eligible = [t for t in chosen_targets if t["skip_reason"] is None]
    skipped = [t for t in chosen_targets if t["skip_reason"] is not None]
    n_sel = len(chosen_targets)
    n_will = len(eligible)
    n_skip = len(skipped)
    _render_plan_line(
        f"Selected {n_sel} product{'s' if n_sel != 1 else ''} "
        f"· {n_will} will refresh · {n_skip} skipped"
    )
    _render_last_run_caption()
    button_label = (
        f"Run refresh on {n_will} product{'s' if n_will != 1 else ''}"
    )
    if st.button(
        button_label,
        type="primary",
        key="refresh.run.selected",
        disabled=n_will == 0,
    ):
        _resolve_run(conn, eligible, skipped, _MODE_SELECTED)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the three-mode Refresh screen."""
    del db_path  # chrome handles attribution; no internal IDs leak here.
    st.markdown(_REFRESH_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="cd-refresh__title">Refresh</div>',
        unsafe_allow_html=True,
    )

    mode = _render_tabs()
    targets = _enumerate_targets(conn)

    if mode == _MODE_ALL:
        _render_all_body(conn, targets)
    elif mode == _MODE_COMPANY:
        _render_company_body(conn, targets)
    else:
        _render_selected_body(conn, targets)

    last_result = st.session_state.get(_LAST_RESULT_KEY)
    if isinstance(last_result, dict):
        _render_result_panel(last_result)
