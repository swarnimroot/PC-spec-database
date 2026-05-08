"""CPU / GPU catalog stub auto-add + vendor chip-spec seeding.

When a bridge emits a CPU or GPU model name we have not seen before, we:

1. INSERT a stub row into ``cpu_catalog`` / ``gpu_catalog`` with just
   ``{model, brand, catalog_status: 'needs-review'}``.
2. Enqueue a ``new_chip_unverified`` review row.

Vendor-published chip specs (Session 7 amendment to the Session 3
"stub-only" rule): when the laptop spec page surfaces chip-level data
(NPU TOPS, cores, clocks, architecture, process node), the bridge
attaches them to ``CandidateProduct.cpu_chip_specs``. This module
applies them per spec field with the following rule set:

* Existing cell ``NULL`` → write the new value (no queue).
* Existing ``catalog_status = 'needs-review'`` AND existing cell non-NULL
  AND new value matches → no-op.
* Existing ``catalog_status = 'needs-review'`` AND existing cell non-NULL
  AND new value differs → overwrite, AND queue a ``value_disagreement``
  ``review_queue`` row so the user sees the disagreement. Reasoning:
  needs-review hasn't been vouched, so the freshest extraction wins,
  but the user still sees the conflict.
* Existing ``catalog_status = 'vouched'`` → do NOT overwrite. Queue a
  ``value_disagreement`` row with both values noted.

Walking the candidate is the runner's job; this module exposes the
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


# CPU catalog spec columns the bridge layer can seed. Lifted into a
# constant so the cell-update walker doesn't accidentally touch
# ``model`` / ``catalog_status`` / ``brand``.
_CPU_CATALOG_SPEC_COLUMNS: frozenset[str] = frozenset({
    "architecture",
    "cores",
    "npu_tops",
    "base_clock",
    "boost_clock",
    "process_node",
    "nominal_tdp",
})


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
    """Stub-add unknown CPU/GPU models referenced by ``candidate`` and
    apply any vendor-published chip specs to ``cpu_catalog`` cells.

    Returns a small report ``{"new_cpus": [...], "new_gpus": [...]}`` so
    the runner can print a summary. Caller is responsible for the
    surrounding transaction.
    """
    new_cpus: list[str] = []
    new_gpus: list[str] = []
    pk = (candidate.model_code, candidate.year)

    # Track which CPU bundle goes with which model name so seeding can
    # reuse the bundle's provenance fields when queueing a conflict.
    cpu_bundle_by_model: dict[str, Bundle] = {}

    for model, bundle, field_path in _iter_cpu_models(candidate):
        cpu_bundle_by_model.setdefault(model, bundle)
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

    # Apply vendor-published chip specs (Session 7 amendment). Runs
    # after the stub-insert pass so a freshly-stubbed row gets its
    # specs in the same transaction.
    chip_specs = getattr(candidate, "cpu_chip_specs", None) or {}
    for model, specs in chip_specs.items():
        bundle = cpu_bundle_by_model.get(model)
        _apply_cpu_chip_specs(
            conn,
            model=model,
            specs=specs,
            bundle=bundle,
            product_pk=pk,
        )

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


# ---------------------------------------------------------------------------
# Vendor chip-spec seeding (Session 7 amendment)
# ---------------------------------------------------------------------------


def _read_cpu_catalog_row(
    conn: sqlite3.Connection, model: str
) -> Optional[sqlite3.Row]:
    cols = ", ".join(["catalog_status", *sorted(_CPU_CATALOG_SPEC_COLUMNS)])
    return conn.execute(
        f"SELECT {cols} FROM cpu_catalog WHERE model = ?", (model,)
    ).fetchone()


def _apply_cpu_chip_specs(
    conn: sqlite3.Connection,
    *,
    model: str,
    specs: dict[str, Optional[str]],
    bundle: Optional[Bundle],
    product_pk: tuple[str, int],
) -> None:
    """Apply per-cell seed/conflict rules to ``cpu_catalog`` for ``model``.

    Per Session 7 architecture call:

    * Existing cell NULL → write candidate (no queue).
    * Existing ``catalog_status = 'needs-review'`` and matches → no-op.
    * Existing ``catalog_status = 'needs-review'`` and differs →
      overwrite + queue ``value_disagreement``.
    * Existing ``catalog_status = 'vouched'`` → keep existing + queue
      ``value_disagreement``.

    Skips silently when the catalog row doesn't exist (it should — the
    stub-insert pass runs first; any missing row means the bundle was
    needs-review and got skipped, in which case we don't seed).
    """
    if not specs:
        return
    row = _read_cpu_catalog_row(conn, model)
    if row is None:
        return
    row_status = row["catalog_status"]
    detected_at = datetime.now(timezone.utc).isoformat()
    for col, new_value in specs.items():
        if col not in _CPU_CATALOG_SPEC_COLUMNS:
            # Bridge handed us a non-spec column name — ignore defensively.
            continue
        if new_value is None:
            # Vendor explicitly indicated "doesn't publish" for this chip
            # spec → never blow away an existing cell with NULL.
            continue
        existing = row[col]
        new_str = str(new_value)
        if existing is None:
            conn.execute(
                f"UPDATE cpu_catalog SET {col} = ? WHERE model = ?",
                (new_str, model),
            )
            continue
        if str(existing) == new_str:
            # No change needed.
            continue
        # Cells differ.
        if row_status == "vouched":
            _enqueue_catalog_disagreement(
                conn,
                model=model,
                column=col,
                existing_value=existing,
                candidate_value=new_str,
                bundle=bundle,
                product_pk=product_pk,
                detected_at=detected_at,
            )
            continue
        # row_status == 'needs-review' (or any other non-vouched state)
        # → freshest extraction wins, but still queue the disagreement.
        conn.execute(
            f"UPDATE cpu_catalog SET {col} = ? WHERE model = ?",
            (new_str, model),
        )
        _enqueue_catalog_disagreement(
            conn,
            model=model,
            column=col,
            existing_value=existing,
            candidate_value=new_str,
            bundle=bundle,
            product_pk=product_pk,
            detected_at=detected_at,
        )


def _enqueue_catalog_disagreement(
    conn: sqlite3.Connection,
    *,
    model: str,
    column: str,
    existing_value: str,
    candidate_value: str,
    bundle: Optional[Bundle],
    product_pk: tuple[str, int],
    detected_at: str,
) -> None:
    """Insert a ``value_disagreement`` row keyed against the catalog cell.

    ``existing_value`` / ``candidate_value`` carry both values so the
    user can see the disagreement at a glance. ``field_path`` reads
    ``cpu_catalog.<model>.<column>`` so review tooling can route by
    catalog vs product. ``existing_provenance`` is left NULL (the
    catalog cell isn't a bundle), ``candidate_provenance`` carries the
    bundle that surfaced the new value.
    """
    field_path = f"cpu_catalog.{model}.{column}"
    conn.execute(
        """
        INSERT INTO review_queue (
            product_model_code, product_year, field_path, conflict_type,
            existing_value, existing_provenance,
            candidate_value, candidate_provenance, detected_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_pk[0],
            product_pk[1],
            field_path,
            "value_disagreement",
            json.dumps({"value": existing_value}),
            None,
            json.dumps({"value": candidate_value}),
            json.dumps(bundle) if bundle is not None else None,
            detected_at,
        ),
    )
