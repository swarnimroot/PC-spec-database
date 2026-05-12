"""Dashboard hub — landing page render.

T8.0 scope: three live counts (products, vendors, review queue) read
straight from the open connection. T8.2 will add the four destination
buttons (browse / compare / find / queue) and any additional health
stats.
"""

from __future__ import annotations

import json
import sqlite3

import streamlit as st


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


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    st.title("Competitive Database")
    products, vendors, queue = _counts(conn)
    col1, col2, col3 = st.columns(3)
    col1.metric("Products", products)
    col2.metric("Vendors", vendors)
    col3.metric("Review queue", queue)
    st.caption(f"Reading from `{db_path}` — Stage 8 / Phase 2 UI · T8.0 skeleton")
