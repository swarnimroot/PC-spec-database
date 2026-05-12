"""Dashboard hub - landing page render.

T8.0 shipped three live counts (products, vendors, review queue). T8.1
added a single "Browse one product" entry-point that navigates to
``ui/browse.py`` via ``st.session_state["view"]``. T8.2 replaced the
single button with the four-destination grid (browse / compare / find /
queue) and added the fourth health stat: days since the most recent
``captured_at`` across every scraped bundle in ``products``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import streamlit as st


_DESTINATIONS: tuple[tuple[str, str], ...] = (
    ("Browse one product", "browse"),
    ("Compare side-by-side", "compare"),
    ("Find products where…", "find"),
    ("Review queue triage", "queue"),
)


def _counts(conn: sqlite3.Connection) -> tuple[int, int, int]:
    products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    brand_rows = conn.execute(
        "SELECT brand FROM products WHERE brand IS NOT NULL"
    ).fetchall()
    brands: set[str] = set()
    for row in brand_rows:
        bundle = json.loads(row[0])
        if isinstance(bundle, dict) and bundle.get("value") is not None:
            brands.add(bundle["value"])
    queue = conn.execute(
        "SELECT COUNT(*) FROM review_queue WHERE resolved_at IS NULL"
    ).fetchone()[0]
    return products, len(brands), queue


def _walk_captured_at(node: object, out: list[str]) -> None:
    if isinstance(node, dict):
        cap = node.get("captured_at")
        if isinstance(cap, str):
            out.append(cap)
        for v in node.values():
            _walk_captured_at(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_captured_at(item, out)


def _days_since_last_refresh(conn: sqlite3.Connection) -> int | None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(products)")]
    bundled = [c for c in cols if c not in {"model_code", "year", "family_code", "source_model_codes"}]
    if not bundled:
        return None
    select = ", ".join(bundled)
    captured: list[str] = []
    for row in conn.execute(f"SELECT {select} FROM products").fetchall():
        for raw in row:
            if raw is None:
                continue
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError):
                continue
            _walk_captured_at(decoded, captured)
    if not captured:
        return None
    latest: datetime | None = None
    for ts in captured:
        try:
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if latest is None or parsed > latest:
            latest = parsed
    if latest is None:
        return None
    delta = datetime.now(timezone.utc) - latest
    return max(delta.days, 0)


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Competitive Database")
    products, vendors, queue = _counts(conn)
    days = _days_since_last_refresh(conn)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Products", products)
    col2.metric("Vendors", vendors)
    col3.metric("Review queue", queue)
    col4.metric("Days since refresh", "—" if days is None else days)
    st.divider()
    cols = st.columns(4)
    for col, (label, route) in zip(cols, _DESTINATIONS):
        if col.button(label, key=f"hub_{route}", use_container_width=True):
            st.session_state["view"] = route
            st.rerun()
    st.caption(f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.2")
