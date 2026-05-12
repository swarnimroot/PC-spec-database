"""Refresh trigger — pull fresh vendor data into one product or every product.

T8.7 scope: third UI write path (after T8.5 triage + T8.6 manual-edit).
Replaces the ``refresh`` CLI subcommand as the primary surface for
keeping the local DB current.

Mode toggle at the top:
  - One product — three URL-source options (URL template / custom URL /
    from-DB stored source_url), parallel to the CLI's three single-
    product modes.
  - All products — bulk-loops every product whose stored brand bundle
    resolves to a supported vendor and whose row carries at least one
    scraped source_url. Skipped products + per-product errors are
    surfaced in the post-run summary.

Progress streams live via ``st.status`` + an ``on_step`` callback the
library functions fire at every phase transition (URL resolution,
fetch start/done, dispatch, per-PK ingest, complete). One-product mode
shows the per-tile ingest line; all-products mode adds per-product
start / done / skip / error lines.

Writes route through
:func:`competitive_database.cli.refresh.refresh_product` /
:func:`...refresh_all_products` — the same library handlers the CLI
calls after the T8.7 refactor. The connection is the one open in
``ui/app.py``.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

import streamlit as st

from competitive_database.cli.refresh import (
    _VENDOR_TEMPLATES,
    _collect_source_urls_from_product,
    refresh_all_products,
    refresh_product,
)


_VENDORS = sorted(_VENDOR_TEMPLATES)


def _parse_brand_value(brand_json: Optional[str]) -> Optional[str]:
    if not isinstance(brand_json, str) or not brand_json:
        return None
    try:
        b = json.loads(brand_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(b, dict):
        return None
    raw = b.get("value")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    return None


def _enumerate_refresh_targets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Classify every product into eligible / skipped (with reason) so the
    UI can populate the From-DB picker and the All-products preview off
    one query. Mirrors the planning logic inside ``refresh_all_products``."""
    rows = conn.execute(
        "SELECT model_code, year, brand FROM products "
        "ORDER BY model_code, year"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        mc = row["model_code"]
        yr = row["year"]
        brand_value = _parse_brand_value(row["brand"])
        if brand_value is None:
            out.append({
                "model_code": mc, "year": yr, "brand": None,
                "skip_reason": "brand bundle is empty or missing",
                "url_count": 0,
            })
            continue
        if brand_value not in _VENDOR_TEMPLATES:
            out.append({
                "model_code": mc, "year": yr, "brand": brand_value,
                "skip_reason": f"brand {brand_value!r} not supported",
                "url_count": 0,
            })
            continue
        try:
            urls = _collect_source_urls_from_product(
                conn, model_code=mc, year=yr
            )
        except ValueError as exc:
            out.append({
                "model_code": mc, "year": yr, "brand": brand_value,
                "skip_reason": str(exc), "url_count": 0,
            })
            continue
        if not urls:
            out.append({
                "model_code": mc, "year": yr, "brand": brand_value,
                "skip_reason": "no scraped source_url on this row",
                "url_count": 0,
            })
            continue
        out.append({
            "model_code": mc, "year": yr, "brand": brand_value,
            "skip_reason": None, "url_count": len(urls),
        })
    return out


def _format_event(event: dict[str, Any]) -> Optional[str]:
    """Render one ``on_step`` event as a human-readable log line.

    Returns None for events we don't surface (``complete``, the inner
    ``dispatch start`` — too noisy when interleaved with ingest lines).
    """
    phase = event["phase"]
    if phase == "resolve_url":
        urls = event["urls"]
        if len(urls) == 1:
            return f"Resolved URL: {urls[0]}"
        return f"Resolved {len(urls)} URLs"
    if phase == "fetch" and event.get("status") == "start":
        return f"Fetching {event['url']}"
    if phase == "fetch" and event.get("status") == "done":
        return f"    got {event['snapshot_count']} snapshot(s)"
    if phase == "dispatch" and event.get("status") == "done":
        n = len(event["pks"])
        return f"Dispatched into {n} product PK(s)"
    if phase == "ingest" and event.get("status") == "start":
        pk = event["pk"]
        return f"Ingesting {pk[0]} · {pk[1]} ({len(event['tiles'])} tile(s))"
    if phase == "ingest" and event.get("status") == "done":
        return (
            f"    inserted={event['inserted_fields']} "
            f"refreshed={event['refreshed_fields']} "
            f"conflicts={event['conflicts']} "
            f"low_confidence={event['low_confidence']}"
        )
    if phase == "plan":
        ps = event["products"]
        n = len(ps)
        n_skip = sum(1 for p in ps if p["skip_reason"])
        return (
            f"Plan: {n} product(s); {n_skip} will be skipped, "
            f"{n - n_skip} will refresh"
        )
    if phase == "skip":
        return (
            f"[skip] {event['model_code']} · {event['year']} — "
            f"{event['reason']}"
        )
    if phase == "product_start":
        return (
            f"[refresh] {event['model_code']} · {event['year']} "
            f"({event['brand']})"
        )
    if phase == "product_done":
        return f"  done: {event['model_code']} · {event['year']}"
    if phase == "product_error":
        return (
            f"  ERROR: {event['model_code']} · {event['year']} — "
            f"{event['error']}"
        )
    return None


def _summary_banner_one(summary: dict[str, Any]) -> None:
    t = summary["totals"]
    st.success(
        f"Refresh complete — {summary['snapshot_count']} snapshot(s) "
        f"→ {len(summary['pks'])} product PK(s). "
        f"inserted={t['inserted_fields']}, "
        f"refreshed={t['refreshed_fields']}, "
        f"conflicts={t['conflicts']}, "
        f"low_confidence={t['low_confidence']}, "
        f"year_inferred={t['year_inferred']}, "
        f"new_cpus={t['new_cpus']}, new_gpus={t['new_gpus']}."
    )
    if summary["pks"]:
        st.markdown(
            "**Products updated:**\n"
            + "\n".join(f"- `{pk[0]}` · {pk[1]}" for pk in summary["pks"])
        )


def _summary_banner_all(summary: dict[str, Any]) -> None:
    t = summary["totals"]
    st.success(
        f"Refresh-all complete — refreshed={summary['refreshed_count']}, "
        f"skipped={summary['skipped_count']}, "
        f"errors={summary['error_count']}. "
        f"inserted={t['inserted_fields']}, "
        f"refreshed={t['refreshed_fields']}, "
        f"conflicts={t['conflicts']}, "
        f"low_confidence={t['low_confidence']}, "
        f"year_inferred={t['year_inferred']}."
    )
    if summary["errors"]:
        st.error(
            "**Per-product errors:**\n"
            + "\n".join(
                f"- `{e['model_code']}` · {e['year']} — {e['error']}"
                for e in summary["errors"]
            )
        )
    if summary["skipped"]:
        with st.expander(
            f"Skipped ({summary['skipped_count']}) — click to expand"
        ):
            for s in summary["skipped"]:
                st.markdown(
                    f"- `{s['model_code']}` · {s['year']} "
                    f"({s['brand'] or '—'}) — {s['reason']}"
                )


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Refresh products")
    if st.button("← Hub"):
        st.session_state["view"] = "hub"
        st.rerun()

    last_summary = st.session_state.pop("refresh_last_summary", None)
    last_error = st.session_state.pop("refresh_last_error", None)
    if last_error is not None:
        st.error(f"Refresh failed — {last_error}")
    if last_summary is not None:
        if last_summary["__mode"] == "all":
            _summary_banner_all(last_summary["__payload"])
        else:
            _summary_banner_one(last_summary["__payload"])

    mode = st.radio(
        "Mode",
        ["One product", "All products"],
        horizontal=True,
        key="refresh-mode",
    )

    if mode == "One product":
        _render_one_mode(conn)
    else:
        _render_all_mode(conn)

    st.caption(f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.7")


def _render_one_mode(conn: sqlite3.Connection) -> None:
    source = st.radio(
        "URL source",
        ["URL template", "Custom URL", "From DB stored source_url"],
        key="refresh-source",
    )

    if source == "URL template":
        c1, c2 = st.columns([1, 2])
        brand = c1.selectbox("Brand", _VENDORS, key="refresh-tmpl-brand")
        model = c2.text_input(
            "Model slug",
            placeholder=(
                "e.g. ac16251 (Dell) / 16t-ah100 (HP) / "
                "Legion_Pro_7_16AFR10H (Lenovo) / "
                "rog-zephyrus-g16-2026 (ASUS)"
            ),
            key="refresh-tmpl-model",
        )
        preview_slug = (model or "").strip() or "<model>"
        st.caption(
            f"URL preview: `{_VENDOR_TEMPLATES[brand].format(slug=preview_slug)}`"
        )
        if st.button("Refresh now", type="primary", key="refresh-tmpl-go"):
            if not (model or "").strip():
                st.error("Enter a model slug.")
                return
            _run_one(
                conn,
                brand=brand,
                model=model.strip(),
                url=None,
                from_db=False,
                year=None,
            )

    elif source == "Custom URL":
        c1, c2 = st.columns([1, 2])
        brand = c1.selectbox("Brand", _VENDORS, key="refresh-url-brand")
        url = c2.text_input(
            "Vendor URL",
            placeholder="Full URL — overrides the per-vendor template",
            key="refresh-url-url",
        )
        if st.button("Refresh now", type="primary", key="refresh-url-go"):
            if not (url or "").strip():
                st.error("Enter a vendor URL.")
                return
            _run_one(
                conn,
                brand=brand,
                model=None,
                url=url.strip(),
                from_db=False,
                year=None,
            )

    else:  # From DB stored source_url
        targets = _enumerate_refresh_targets(conn)
        eligible = [t for t in targets if t["skip_reason"] is None]
        if not eligible:
            st.info(
                "No products in the DB have a stored `source_url` yet. "
                "Use **URL template** or **Custom URL** to seed one first."
            )
            return
        labels = [
            f"{t['brand']} · {t['model_code']} · {t['year']} "
            f"({t['url_count']} URL{'s' if t['url_count'] != 1 else ''})"
            for t in eligible
        ]
        idx = st.selectbox(
            "Product",
            range(len(eligible)),
            format_func=lambda i: labels[i],
            key="refresh-fromdb-idx",
        )
        target = eligible[idx]
        if st.button("Refresh now", type="primary", key="refresh-fromdb-go"):
            _run_one(
                conn,
                brand=target["brand"],
                model=target["model_code"],
                url=None,
                from_db=True,
                year=target["year"],
            )


def _render_all_mode(conn: sqlite3.Connection) -> None:
    targets = _enumerate_refresh_targets(conn)
    eligible = [t for t in targets if t["skip_reason"] is None]
    skipped = [t for t in targets if t["skip_reason"] is not None]

    c1, c2, c3 = st.columns(3)
    c1.metric("Eligible", len(eligible))
    c2.metric("Skipped", len(skipped))
    c3.metric("Total in DB", len(targets))

    if eligible:
        st.markdown("**Will refresh:**")
        for t in eligible:
            st.markdown(
                f"- {t['brand']} · `{t['model_code']}` · {t['year']} "
                f"({t['url_count']} URL{'s' if t['url_count'] != 1 else ''})"
            )
    if skipped:
        with st.expander(f"Skipped ({len(skipped)}) — click to expand"):
            for t in skipped:
                st.markdown(
                    f"- `{t['model_code']}` · {t['year']} "
                    f"({t['brand'] or '—'}) — {t['skip_reason']}"
                )

    if not eligible:
        st.info(
            "No products are eligible for refresh. Add at least one with "
            "a stored `source_url` via **One product** mode first."
        )
        return

    if st.button(
        f"Refresh all {len(eligible)} product(s)",
        type="primary",
        key="refresh-all-go",
    ):
        _run_all(conn)


def _run_one(
    conn: sqlite3.Connection,
    *,
    brand: str,
    model: Optional[str],
    url: Optional[str],
    from_db: bool,
    year: Optional[int],
) -> None:
    with st.status("Refreshing…", expanded=True) as status:
        def on_step(event: dict[str, Any]) -> None:
            line = _format_event(event)
            if line is not None:
                st.write(line)
            phase = event["phase"]
            if phase == "fetch" and event.get("status") == "start":
                status.update(label="Fetching…")
            elif phase == "dispatch" and event.get("status") == "start":
                status.update(label="Dispatching to bridge…")
            elif phase == "ingest" and event.get("status") == "start":
                status.update(label="Ingesting…")

        try:
            summary = refresh_product(
                conn,
                brand=brand,
                model=model,
                url=url,
                from_db=from_db,
                year=year,
                on_step=on_step,
            )
        except ValueError as exc:
            status.update(label="Refresh failed (validation)", state="error")
            st.session_state["refresh_last_error"] = str(exc)
            st.rerun()
            return
        except Exception as exc:  # noqa: BLE001 — vendor / infra failure
            status.update(label="Refresh failed", state="error")
            st.session_state["refresh_last_error"] = (
                f"{type(exc).__name__}: {exc}"
            )
            st.rerun()
            return
        status.update(label="Refresh complete", state="complete")

    st.session_state["refresh_last_summary"] = {
        "__mode": "one", "__payload": summary,
    }
    st.rerun()


def _run_all(conn: sqlite3.Connection) -> None:
    with st.status("Refreshing all products…", expanded=True) as status:
        def on_step(event: dict[str, Any]) -> None:
            line = _format_event(event)
            if line is not None:
                st.write(line)
            phase = event["phase"]
            if phase == "product_start":
                status.update(
                    label=(
                        f"Refreshing {event['model_code']} · "
                        f"{event['year']}…"
                    )
                )

        try:
            summary = refresh_all_products(conn, on_step=on_step)
        except ValueError as exc:
            status.update(label="Refresh-all failed", state="error")
            st.session_state["refresh_last_error"] = str(exc)
            st.rerun()
            return
        except Exception as exc:  # noqa: BLE001
            status.update(label="Refresh-all failed", state="error")
            st.session_state["refresh_last_error"] = (
                f"{type(exc).__name__}: {exc}"
            )
            st.rerun()
            return
        status.update(label="Refresh-all complete", state="complete")

    st.session_state["refresh_last_summary"] = {
        "__mode": "all", "__payload": summary,
    }
    st.rerun()
