"""Editorial Hub landing screen (Stage 10 Phase B)."""

from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timezone

import streamlit as st

from competitive_database.ui import theme


# Card definitions: (title, description, route).
_CTA_CARDS: tuple[tuple[str, str, str], ...] = (
    ("Browse", "The full catalog, one row per laptop.", "browse"),
    ("Compare", "Place any two or more laptops side by side.", "compare"),
    ("Find", "Filter by the spec that matters to you.", "find"),
)


def _counts(conn: sqlite3.Connection) -> tuple[int, int]:
    """Return (product_count, distinct_brand_count) from the live DB."""
    products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    brand_rows = conn.execute(
        "SELECT brand FROM products WHERE brand IS NOT NULL"
    ).fetchall()
    brands: set[str] = set()
    for row in brand_rows:
        bundle = json.loads(row[0])
        if isinstance(bundle, dict) and bundle.get("value") is not None:
            brands.add(bundle["value"])
    return products, len(brands)


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
    """Days since the most recent ``captured_at`` across all products."""
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


def _tile(value: str, label: str) -> str:
    """Render a rounded box with a large value on top and a small label below."""
    p = theme.PALETTE
    return (
        f'<div style="'
        f'background:{p["bg_card"]};'
        f'border:1px solid {p["border"]};'
        f'border-radius:{theme.RADIUS["lg"]}px;'
        f'padding:{theme.SPACE["lg"]}px;'
        f'">'
        f'<div style="'
        f'font-size:{theme.TYPE["size_hero"]}px;'
        f'font-weight:{theme.TYPE["weight_semibold"]};'
        f'color:{p["text"]};'
        f'line-height:1.1;'
        f'">{html.escape(value)}</div>'
        f'<div style="'
        f'margin-top:{theme.SPACE["xs"]}px;'
        f'font-size:{theme.TYPE["size_sm"]}px;'
        f'color:{p["text_muted"]};'
        f'">{html.escape(label)}</div>'
        f'</div>'
    )


def _card_shell(title: str, description: str) -> str:
    """Render the top half of a CTA card (title + sub-copy)."""
    p = theme.PALETTE
    return (
        f'<div style="'
        f'background:{p["bg_card"]};'
        f'border:1px solid {p["border"]};'
        f'border-radius:{theme.RADIUS["lg"]}px;'
        f'padding:{theme.SPACE["lg"]}px;'
        f'">'
        f'<div style="'
        f'font-size:{theme.TYPE["size_lg"]}px;'
        f'font-weight:{theme.TYPE["weight_semibold"]};'
        f'color:{p["text"]};'
        f'">{html.escape(title)}</div>'
        f'<div style="'
        f'margin-top:{theme.SPACE["sm"]}px;'
        f'font-size:{theme.TYPE["size_sm"]}px;'
        f'color:{p["text_muted"]};'
        f'line-height:1.5;'
        f'">{html.escape(description)}</div>'
        f'</div>'
    )


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the Hub landing screen."""
    del db_path  # chrome handles attribution; no internal IDs leak here.
    p = theme.PALETTE

    # Hero line.
    st.markdown(
        f'<div style="'
        f'margin-top:{theme.SPACE["xxl"]}px;'
        f'margin-bottom:{theme.SPACE["xxl"]}px;'
        f'font-size:{theme.TYPE["size_xl"]}px;'
        f'font-weight:{theme.TYPE["weight_normal"]};'
        f'color:{p["text_muted"]};'
        f'">The competitive gaming-laptop reference.</div>',
        unsafe_allow_html=True,
    )

    # Metric tiles.
    products, vendors = _counts(conn)
    days = _days_since_last_refresh(conn)
    if products == 0 or days is None:
        days_value = "—"
    else:
        days_value = f"{days} days"
    metric_cols = st.columns(3)
    with metric_cols[0]:
        st.markdown(_tile(str(products), "products"), unsafe_allow_html=True)
    with metric_cols[1]:
        st.markdown(_tile(str(vendors), "vendors"), unsafe_allow_html=True)
    with metric_cols[2]:
        st.markdown(_tile(days_value, "since refresh"), unsafe_allow_html=True)

    # Spacer between metric row and CTA row.
    st.markdown(
        f'<div style="height:{theme.SPACE["xxl"]}px"></div>',
        unsafe_allow_html=True,
    )

    # CTA cards.
    card_cols = st.columns(3)
    for col, (title, description, route) in zip(card_cols, _CTA_CARDS):
        with col:
            st.markdown(_card_shell(title, description), unsafe_allow_html=True)
            if st.button(
                "Open →",
                key=f"hub_cta_{route}",
                use_container_width=True,
                type="primary",
            ):
                st.session_state["view"] = route
                st.rerun()
