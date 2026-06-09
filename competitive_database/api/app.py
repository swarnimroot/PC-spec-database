"""FastAPI app — read-only HTTP surface for the React Spec Finder.

Run locally:

    .venv\\Scripts\\python -m uvicorn competitive_database.api.app:app --reload --port 8000

DB path comes from the ``COMPETITIVE_DB_PATH`` env var (default
``competitive.db`` in the project root). A fresh connection is opened per
request because sqlite3 connections are not safe to share across threads.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from ..db.connection import connect
from ..db.helpers import list_all_product_identities
from ..query import OPS_ALL, OPS_NEED_VALUE, apply_narrow_by, find_matches, template_of
from . import serializers

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _db_path() -> str:
    """Resolve the DB path from env, falling back to ``competitive.db``."""
    env = os.environ.get("COMPETITIVE_DB_PATH")
    if env:
        return env
    return str(_PROJECT_ROOT / "competitive.db")


def _open_conn() -> sqlite3.Connection:
    """Open a fresh per-request connection (sqlite is per-thread)."""
    return connect(_db_path())


app = FastAPI(title="Competitive Spec DB API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/schema")
def get_schema() -> dict[str, Any]:
    return serializers.schema()


@app.get("/api/catalog")
def get_catalog() -> list[dict[str, Any]]:
    conn = _open_conn()
    try:
        return serializers.catalog(conn)
    finally:
        conn.close()


@app.get("/api/model/{model_id}")
def get_model(model_id: str, year: Optional[int] = Query(default=None)) -> dict[str, Any]:
    conn = _open_conn()
    try:
        model = serializers.model_object(conn, model_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()
    if year is None:
        return model
    # Year-resolved detail: merge base + that year's override.
    if year not in model["years"]:
        raise HTTPException(
            status_code=404,
            detail=f"model {model_id!r} has no year {year}",
        )
    resolved = dict(model["base"])
    override = model["byYear"].get(str(year), {})
    resolved.update(override)
    return {
        "id": model["id"],
        "brand": model["brand"],
        "series": model["series"],
        "model": model["model"],
        "segment": model["segment"],
        "year": year,
        "updated": model["updated"],
        "spec": resolved,
    }


@app.post("/api/find")
def post_find(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    field_path = payload.get("field_path")
    operator = payload.get("operator")
    value = payload.get("value") or ""
    narrow_by = payload.get("narrow_by") or {}

    if not field_path:
        raise HTTPException(status_code=422, detail="field_path is required")
    if operator not in OPS_ALL:
        raise HTTPException(
            status_code=422,
            detail=f"operator must be one of {list(OPS_ALL)}",
        )
    if operator in OPS_NEED_VALUE and not value:
        raise HTTPException(
            status_code=422,
            detail=f"operator {operator!r} requires a value",
        )

    conn = _open_conn()
    try:
        products = _load_all_products(conn)
    finally:
        conn.close()

    filtered = apply_narrow_by(
        products,
        brands=_single(narrow_by.get("brands")),
        series=_single(narrow_by.get("series")),
        products_names=_single(narrow_by.get("products")),
        years=_years(narrow_by.get("years")),
        statuses=narrow_by.get("statuses") or None,
    )

    template = template_of(field_path)
    matches = find_matches(filtered, template, operator, str(value))
    results = [
        {"id": prod.get("model_code"), "value": vstr, "marker": marker}
        for prod, vstr, marker in matches
    ]
    return {"matches": results, "count": len(results)}


def _load_all_products(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Load every (product, year) row across all identities."""
    out: list[dict[str, Any]] = []
    for ident in list_all_product_identities(conn):
        out.extend(
            serializers.load_identity_rows(
                conn, ident["brand"], ident["series"], ident["product"]
            )
        )
    return out


def _single(value: Any) -> Optional[str]:
    """Normalize a narrow-by axis to a single value (or None).

    Accepts a scalar or a single-element list; rejects multi-value lists by
    taking the first (apply_narrow_by filters on one exact value per axis).
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _years(value: Any) -> Optional[list[int]]:
    if not value:
        return None
    if isinstance(value, list):
        return [int(v) for v in value]
    return [int(value)]
