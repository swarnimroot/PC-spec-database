"""FastAPI app — read-only HTTP surface for the React Spec Finder.

Run locally:

    .venv\\Scripts\\python -m uvicorn competitive_database.api.app:app --reload --port 8000

DB path comes from the ``COMPETITIVE_DB_PATH`` env var (default
``competitive.db`` in the project root). A fresh connection is opened per
request because sqlite3 connections are not safe to share across threads.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from ..cli.manual_edit import manual_edit_cell
from ..cli.refresh import (
    VENDOR_TEMPLATES,
    refresh_all_products,
    refresh_product,
    scrape_only,
)
from ..cli.resolve import resolve_row
from ..ingest.runner import ingest_product
from ..curation import queue as curation_queue
from ..db.connection import connect
from ..db.helpers import list_all_product_identities
from ..query import OPS_ALL, OPS_NEED_VALUE, apply_narrow_by, find_matches, template_of
from . import serializers

_FIELD_STATE_TABS = ("review", "missing", "hand")

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


# --- Add-product flow ----------------------------------------------------

#: Vendor navigation options for the Add-product UI. One entry per scrape
#: ``brand``; each carries one or more ``links`` (label + landing URL) the
#: user opens to find a product URL to paste. Links target the SAME host the
#: scraper reads — Dell ``/spd``, HP ``/pdp``, Lenovo PSREF (not the store),
#: ASUS ROG (rog.asus.com) and ASUS TUF/Vivobook (www.asus.com) — so the
#: pasted product URL is one the fetcher can handle. ASUS carries two links
#: (ROG and ASUS) because they live on different hosts; both scrape under
#: ``brand="asus"`` (the fetcher routes by hostname).
VENDOR_OPTIONS: list[dict[str, Any]] = [
    {
        "brand": "dell",
        "label": "Dell",
        "links": [
            {
                "label": "Dell",
                "url": "https://www.dell.com/en-us/shop/gaming-laptops/sf/alienware-laptops",
            }
        ],
    },
    {
        "brand": "hp",
        "label": "HP",
        "links": [
            {"label": "HP", "url": "https://www.hp.com/us-en/shop/slp/hp-gaming/laptops"}
        ],
    },
    {
        "brand": "lenovo",
        "label": "Lenovo",
        "links": [{"label": "Lenovo PSREF", "url": "https://psref.lenovo.com/"}],
    },
    {
        "brand": "asus",
        "label": "ASUS",
        "links": [
            {"label": "ROG", "url": "https://rog.asus.com/us/laptops-group/allmodels/"},
            {"label": "ASUS", "url": "https://www.asus.com/us/laptops/for-gaming/tuf-gaming/"},
        ],
    },
]

#: Token -> freshly scraped candidate groups (list[list[CandidateProduct]]),
#: stashed between POST /api/products/scrape (preview) and POST
#: /api/products/add (commit). Capped to the most recent entries so a long-
#: lived process doesn't accumulate stale scrapes unboundedly.
_PENDING_SCRAPES: "dict[str, list[list[Any]]]" = {}
_PENDING_SCRAPES_MAX = 10


def _stash_scrape(candidates: list[list[Any]]) -> str:
    """Stash candidate groups under a fresh token, evicting oldest over cap."""
    token = secrets.token_urlsafe(8)
    _PENDING_SCRAPES[token] = candidates
    while len(_PENDING_SCRAPES) > _PENDING_SCRAPES_MAX:
        # dicts preserve insertion order — drop the oldest entry.
        oldest = next(iter(_PENDING_SCRAPES))
        del _PENDING_SCRAPES[oldest]
    return token


def _pk_exists(conn: sqlite3.Connection, model_code: str, year: int) -> bool:
    """True if a ``products`` row already exists for this ``(model_code, year)``."""
    row = conn.execute(
        "SELECT 1 FROM products WHERE model_code = ? AND year = ? LIMIT 1",
        (model_code, year),
    ).fetchone()
    return row is not None


app = FastAPI(title="Competitive Spec DB API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8501",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8501",
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


@app.get("/api/model/{model_id}/detail")
def get_model_detail(
    model_id: str, year: Optional[int] = Query(default=None)
) -> dict[str, Any]:
    """Raw detail leaves (accordion expand) for one (model, year).

    ``year`` is REQUIRED here — a detail expand always targets a concrete
    year's row, not the identity's latest. Missing year → 422.
    """
    if year is None:
        raise HTTPException(status_code=422, detail="year is required")
    conn = _open_conn()
    try:
        return serializers.model_detail(conn, model_id, year)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/api/schema/detail")
def get_detail_schema() -> dict[str, Any]:
    """Union of every possible detail leaf per section (field-visibility panel)."""
    conn = _open_conn()
    try:
        return serializers.detail_schema(conn)
    finally:
        conn.close()


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


# ---------------------------------------------------------------------------
# Curation Cockpit — WRITE + QUEUE endpoints
# ---------------------------------------------------------------------------


@app.get("/api/queue/counts")
def queue_counts() -> dict[str, int]:
    """Counts for the Cockpit's four tabs: conflicts, review, missing, hand."""
    conn = _open_conn()
    try:
        return {
            "conflicts": curation_queue.count_conflicts(conn),
            "review": curation_queue.count_field_state(conn, "review"),
            "missing": curation_queue.count_field_state(conn, "missing"),
            "hand": curation_queue.count_field_state(conn, "hand"),
        }
    finally:
        conn.close()


@app.get("/api/queue")
def queue(tab: str = Query(default="conflicts")) -> dict[str, Any]:
    """List queue items for one tab.

    ``tab=conflicts`` returns unresolved review_queue items (with candidate
    values + conflict kind); ``tab=review|missing|hand`` returns field-state
    items (with state + byYear diff).
    """
    conn = _open_conn()
    try:
        if tab == "conflicts":
            items = curation_queue.list_conflicts(conn)
        elif tab in _FIELD_STATE_TABS:
            items = curation_queue.list_field_state(conn, tab)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"tab must be one of conflicts/{'/'.join(_FIELD_STATE_TABS)}",
            )
    finally:
        conn.close()
    return {"tab": tab, "items": items, "count": len(items)}


@app.post("/api/value")
def post_value(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Write a manual cell value (wraps ``manual_edit_cell``).

    Body: ``{model_code, year?, field_path, value, status?, note?,
    entered_by?, source_url?}``. Returns the before/after summary.
    """
    model_code = payload.get("model_code")
    field_path = payload.get("field_path")
    if not model_code:
        raise HTTPException(status_code=422, detail="model_code is required")
    if not field_path:
        raise HTTPException(status_code=422, detail="field_path is required")
    if "value" not in payload:
        raise HTTPException(status_code=422, detail="value is required")

    year = payload.get("year")
    conn = _open_conn()
    try:
        summary = manual_edit_cell(
            conn,
            model_code=model_code,
            year=int(year) if year is not None else None,
            field_path=field_path,
            value=payload.get("value"),
            status=payload.get("status") or "vouched",
            note=payload.get("note"),
            entered_by=payload.get("entered_by"),
            source_url=payload.get("source_url"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()
    return summary


@app.post("/api/resolve")
def post_resolve(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Resolve one scrape conflict (wraps ``resolve_row``).

    Body: ``{id|row_id, action, value?, note?, entered_by?}``. ``id`` accepts
    either a bare review_queue id or the ``conflict:<id>`` item id the queue
    listing emits. Returns the resolve summary.
    """
    raw_id = payload.get("row_id", payload.get("id"))
    if raw_id is None:
        raise HTTPException(status_code=422, detail="id (row_id) is required")
    row_id = _parse_row_id(raw_id)
    action = payload.get("action")
    if not action:
        raise HTTPException(status_code=422, detail="action is required")

    kwargs: dict[str, Any] = {
        "row_id": row_id,
        "action": action,
        "note": payload.get("note"),
        "entered_by": payload.get("entered_by"),
    }
    if "value" in payload:
        kwargs["value"] = payload["value"]

    conn = _open_conn()
    try:
        summary = resolve_row(conn, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()
    return summary


@app.get("/api/value/history")
def value_history(
    model_code: str = Query(...),
    field_path: str = Query(...),
    year: Optional[int] = Query(default=None),
) -> dict[str, Any]:
    """Provenance for one cell (existing provenance only — no audit log)."""
    conn = _open_conn()
    try:
        resolved_year = year if year is not None else _resolve_year(conn, model_code)
        return curation_queue.value_history(
            conn,
            model_code=model_code,
            year=resolved_year,
            field_path=field_path,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


@app.post("/api/refresh")
def post_refresh(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Re-scrape a vendor product and re-ingest it (HEAVY / EXTERNAL op).

    WARNING: this is the heavy, external operation. A real call hits the
    vendor's website over the network (Playwright / httpx) and then writes
    every changed cell + any new conflicts into the DB. It is NOT safe to run
    in unit tests — tests should only assert input validation / reachability,
    never actually invoke a live scrape.

    Body: ``{all: true}`` to refresh every eligible product, or
    ``{brand, model|url, from_db?, year?}`` for a single product (mirrors the
    ``refresh`` CLI). Returns the refresh summary.
    """
    conn = _open_conn()
    try:
        if payload.get("all"):
            return refresh_all_products(
                conn, profiles_dir=payload.get("profiles_dir", ".profiles")
            )
        brand = payload.get("brand")
        if not brand:
            raise HTTPException(
                status_code=422,
                detail="brand is required (unless all=true)",
            )
        return refresh_product(
            conn,
            brand=brand,
            model=payload.get("model"),
            url=payload.get("url"),
            from_db=bool(payload.get("from_db", False)),
            year=payload.get("year"),
            profiles_dir=payload.get("profiles_dir", ".profiles"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/api/vendors")
def get_vendors() -> list[dict[str, Any]]:
    """List the Add-product vendor options, each with one or more landing links.

    Each entry is ``{brand, label, links}`` where ``links`` is a list of
    ``{label, url}`` navigation hints the Add-product UI links to so the user
    can find a product page to paste into the scrape form; the URLs point at
    the same host the scraper reads. ASUS carries two links (ROG vs
    TUF/Vivobook, different hosts) but both submit ``brand="asus"``.
    """
    return list(VENDOR_OPTIONS)


@app.post("/api/products/scrape")
def post_products_scrape(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Scrape a vendor product URL and return a PREVIEW (no DB writes).

    WARNING: heavy / external — hits the vendor site over the network
    (Playwright / httpx), ~1 min, same as ``/api/refresh``. NOT safe to run
    in unit tests against the live stack.

    Body: ``{brand, url}``. Validates ``brand`` against the supported set
    (422). Scrapes via :func:`scrape_only` (pure, no writes), groups by PK,
    and flags each group whose ``(model_code, year)`` already exists in
    ``products``. The raw candidate groups are stashed under ``token`` for a
    follow-up POST /api/products/add. Scrape / parse failures raise 422 with
    the real error message (no silent swallow).

    Returns ``{token, products: [{...preview, already_exists}, ...]}``.
    """
    brand = payload.get("brand")
    brand_l = (brand or "").lower()
    if brand_l not in VENDOR_TEMPLATES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"brand {brand!r} is not supported; "
                f"known: {sorted(VENDOR_TEMPLATES)}"
            ),
        )
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=422, detail="url is required")

    try:
        candidates = scrape_only(brand=brand_l, url=url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # vendor / parser failure — surface, don't swallow
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    conn = _open_conn()
    try:
        products = []
        for group in candidates:
            head = group[0]
            preview = serializers.serialize_scrape_preview(head)
            preview["already_exists"] = _pk_exists(
                conn, head.model_code, head.year
            )
            products.append(preview)
    finally:
        conn.close()

    token = _stash_scrape(candidates)
    return {"token": token, "products": products}


@app.post("/api/products/add")
def post_products_add(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Commit a previously scraped product preview into the DB.

    Body: ``{token, names?}`` from a prior POST /api/products/scrape (404 if
    unknown / expired). ``names`` is an OPTIONAL dict keyed by the string
    ``"<model_code>|<year>"`` -> the desired ``products.product`` name; when
    absent / empty, behavior is unchanged (new rows keep ``product =
    model_code`` from ``_normalize_products_pk``). For each grouped candidate:
    if its ``(model_code, year)`` PK already exists it is SKIPPED (ingesting an
    existing PK would queue ``value_disagreement`` conflicts — the Add flow
    must not); otherwise it is a clean insert via :func:`ingest_product`, and a
    non-empty ``names`` entry for that PK is written to ``products.product``.
    Names are NOT applied to skipped (already-existing) PKs. The token is
    consumed (popped) after use.

    Returns ``{items: [{model_code, year, already_existed, inserted, product,
    inserted_fields?}, ...]}`` where ``product`` is the applied name (or the
    model_code when none was given).
    """
    token = payload.get("token")
    if not token or token not in _PENDING_SCRAPES:
        raise HTTPException(
            status_code=404, detail=f"unknown or expired token {token!r}"
        )
    names = payload.get("names") or {}
    if not isinstance(names, dict):
        raise HTTPException(
            status_code=422, detail="names must be an object keyed by '<mc>|<year>'"
        )
    candidates = _PENDING_SCRAPES.pop(token)

    conn = _open_conn()
    try:
        items = []
        for group in candidates:
            head = group[0]
            model_code = head.model_code
            year = head.year
            if _pk_exists(conn, model_code, year):
                items.append(
                    {
                        "model_code": model_code,
                        "year": year,
                        "already_existed": True,
                        "inserted": False,
                    }
                )
                continue
            report = ingest_product(conn, group)
            # Default name is the model_code (what _normalize_products_pk
            # writes); override with the user-supplied name if non-empty.
            product_name = model_code
            override = names.get(f"{model_code}|{year}")
            if isinstance(override, str) and override.strip():
                product_name = override.strip()
                conn.execute(
                    "UPDATE products SET product = ? "
                    "WHERE model_code = ? AND year = ?",
                    (product_name, model_code, year),
                )
                conn.commit()
            items.append(
                {
                    "model_code": model_code,
                    "year": year,
                    "already_existed": False,
                    "inserted": True,
                    "product": product_name,
                    "inserted_fields": report.inserted_fields,
                }
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"items": items}


def _parse_row_id(raw: Any) -> int:
    """Accept a bare int id or the ``conflict:<id>`` queue item id."""
    if isinstance(raw, int):
        return raw
    s = str(raw)
    if s.startswith("conflict:"):
        s = s.split(":", 1)[1]
    try:
        return int(s)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid conflict id {raw!r}"
        ) from exc


def _resolve_year(conn: sqlite3.Connection, model_code: str) -> int:
    from ..views.load import resolve_year

    return resolve_year(conn, model_code)


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
