"""CPU / GPU catalog stub auto-add.

When a bridge emits a CPU or GPU model name we have not seen before, we:

1. INSERT a stub row into ``cpu_catalog`` / ``gpu_catalog`` with just
   ``{model, brand, catalog_status: 'needs-review'}``.
2. Enqueue a ``new_chip_unverified`` review row.

Chip specs (cores, NPU TOPS, etc.) are NOT auto-fetched — that is a
deferred backfill (see ARCHITECTURE.md §"Locked decisions"). Existing
rows are left alone.

Walking the candidate is the runner's job; this module exposes two
focused helpers it calls per chip name.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from ..bridge.helpers import infer_cpu_brand, infer_gpu_brand
from ..bridge.types import Bundle, CandidateProduct
from ..db.helpers import make_scraped_bundle


def _exists(
    conn: sqlite3.Connection, table: str, model: str
) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE model = ? LIMIT 1", (model,)
    ).fetchone()
    return row is not None


def _insert_stub(
    conn: sqlite3.Connection,
    table: str,
    model: str,
    brand: Optional[str],
    source_url: str,
    captured_at: str,
    scraper_id: str,
) -> None:
    """INSERT a stub row with model + brand bundle + needs-review status."""
    brand_bundle = (
        json.dumps(
            make_scraped_bundle(
                value=brand,
                source_url=source_url,
                captured_at=captured_at,
                scraper_id=scraper_id,
                status="needs-review" if brand is None else "needs-review",
            )
        )
        if brand is not None
        else None
    )
    conn.execute(
        f"INSERT INTO {table} (model, catalog_status, brand) VALUES (?, ?, ?)",
        (model, "needs-review", brand_bundle),
    )


def _enqueue_new_chip(
    conn: sqlite3.Connection,
    *,
    table: str,
    model: str,
    candidate_value: str,
    candidate_provenance: Bundle,
    product_pk: tuple[str, int],
    field_path: str,
) -> None:
    detected_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO review_queue (
            product_model_code, product_year, field_path, conflict_type,
            existing_value, existing_provenance,
            candidate_value, candidate_provenance, detected_at
        )
        VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?)
        """,
        (
            product_pk[0],
            product_pk[1],
            field_path,
            "new_chip_unverified",
            json.dumps({"table": table, "model": model, "value": candidate_value}),
            json.dumps(candidate_provenance),
            detected_at,
        ),
    )


def _iter_cpu_models(candidate: CandidateProduct) -> Iterable[tuple[str, Bundle, str]]:
    """Yield ``(model_string, bundle, field_path)`` for each CPU offering."""
    if candidate.cpu_offerings is None:
        return
    for idx, offering in enumerate(candidate.cpu_offerings):
        model_bundle = offering.get("model")
        if not model_bundle:
            continue
        model = model_bundle.get("value")
        if not model:
            continue
        yield str(model), model_bundle, f"cpu_offerings.{idx}.model"


def _iter_gpu_models(
    candidate: CandidateProduct,
) -> Iterable[tuple[str, Bundle, str]]:
    """Yield ``(model_string, bundle, field_path)`` for each board GPU."""
    if candidate.boards is None:
        return
    for b_idx, board in enumerate(candidate.boards):
        gpus = board.get("gpus") or []
        for g_idx, gpu_bundle in enumerate(gpus):
            if not isinstance(gpu_bundle, dict):
                continue
            model = gpu_bundle.get("value")
            if not model:
                continue
            yield str(model), gpu_bundle, f"boards.{b_idx}.gpus.{g_idx}"


def resolve_catalog(
    conn: sqlite3.Connection, candidate: CandidateProduct
) -> dict[str, list[str]]:
    """Stub-add unknown CPU/GPU models referenced by ``candidate``.

    Returns a small report ``{"new_cpus": [...], "new_gpus": [...]}`` so
    the runner can print a summary. Caller is responsible for the
    surrounding transaction.
    """
    new_cpus: list[str] = []
    new_gpus: list[str] = []
    pk = (candidate.model_code, candidate.year)

    for model, bundle, field_path in _iter_cpu_models(candidate):
        if _exists(conn, "cpu_catalog", model):
            continue
        # Skip catalog-add when the bundle itself is needs-review — we
        # don't want to pollute the catalog with extraction misses.
        if bundle.get("status") == "needs-review":
            continue
        brand = infer_cpu_brand(model)
        _insert_stub(
            conn,
            "cpu_catalog",
            model,
            brand,
            source_url=bundle.get("source_url", ""),
            captured_at=bundle.get("captured_at", ""),
            scraper_id=bundle.get("scraper_id", ""),
        )
        _enqueue_new_chip(
            conn,
            table="cpu_catalog",
            model=model,
            candidate_value=model,
            candidate_provenance=bundle,
            product_pk=pk,
            field_path=field_path,
        )
        new_cpus.append(model)

    for model, bundle, field_path in _iter_gpu_models(candidate):
        if _exists(conn, "gpu_catalog", model):
            continue
        if bundle.get("status") == "needs-review":
            continue
        brand = infer_gpu_brand(model)
        _insert_stub(
            conn,
            "gpu_catalog",
            model,
            brand,
            source_url=bundle.get("source_url", ""),
            captured_at=bundle.get("captured_at", ""),
            scraper_id=bundle.get("scraper_id", ""),
        )
        _enqueue_new_chip(
            conn,
            table="gpu_catalog",
            model=model,
            candidate_value=model,
            candidate_provenance=bundle,
            product_pk=pk,
            field_path=field_path,
        )
        new_gpus.append(model)

    return {"new_cpus": new_cpus, "new_gpus": new_gpus}
