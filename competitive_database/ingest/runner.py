"""Orchestrator: candidate → catalog-resolve → diff → write/queue.

One :func:`ingest` call per ``CandidateProduct``, all inside one
transaction. Diff semantics (per ARCHITECTURE.md §Ingestion runner):

* No existing row → insert candidate cells (modulo ``needs-review`` skip).
* Field empty in DB → write candidate cell.
* Field matches candidate (compare ``value`` only, ignore provenance) →
  refresh ``captured_at`` only; everything else stays.
* Field differs from candidate → enqueue ``value_disagreement``;
  existing untouched.
* Candidate cell ``status: needs-review`` → enqueue
  ``low_confidence_extraction``; do not write.
* Candidate ``vendor_full_name`` is ``needs-review`` AND the candidate
  has ``year_was_inferred=True`` → enqueue ``year_inferred`` instead of
  ``low_confidence_extraction`` (Decision 1).

Cross-tile merge (Decision 3): :func:`ingest_product` accepts a list of
candidates that share a PK (typically one per scraper tile) and unions
the list-of-offerings fields by an appropriate identity key before
running the per-cell diff. Scalar disagreements between tiles are
preserved as the existing ``value_disagreement`` path on the first
write — same logic as before, just on the merged candidate.

All DB writes go through :mod:`competitive_database.db.helpers`. The only
direct ``INSERT`` lives on the ``review_queue`` table here and in
:mod:`catalog_resolve`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..bridge.types import (
    Bundle,
    CandidateProduct,
    OFFERINGS_FIELDS,
    OfferingsList,
    SCALAR_FIELDS,
)
from ..db.connection import transaction
from ..db.helpers import (
    read_offerings,
    read_scalar,
    write_offerings,
    write_scalar,
)
from .catalog_resolve import resolve_catalog


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class IngestReport:
    """Summary of one ``ingest`` call."""

    inserted_fields: int = 0
    refreshed_fields: int = 0
    conflicts: int = 0
    low_confidence: int = 0
    year_inferred: int = 0
    new_cpus: list[str] = field(default_factory=list)
    new_gpus: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, other: "IngestReport") -> None:
        self.inserted_fields += other.inserted_fields
        self.refreshed_fields += other.refreshed_fields
        self.conflicts += other.conflicts
        self.low_confidence += other.low_confidence
        self.year_inferred += other.year_inferred
        self.new_cpus.extend(other.new_cpus)
        self.new_gpus.extend(other.new_gpus)
        self.notes.extend(other.notes)


# ---------------------------------------------------------------------------
# Public entry — single candidate
# ---------------------------------------------------------------------------


def ingest(
    conn: sqlite3.Connection, candidate: CandidateProduct
) -> IngestReport:
    """Apply ``candidate`` to ``conn`` inside a single transaction.

    Returns a :class:`IngestReport`. On exception the transaction is
    rolled back and the exception re-raised.
    """
    report = IngestReport(notes=list(candidate.notes))
    pk = {"model_code": candidate.model_code, "year": candidate.year}

    with transaction(conn):
        # Catalog stubs first so the cpu_offerings reference is valid
        # immediately. (We don't enforce FKs on the JSON values, but
        # consistency is still preferable.) ``resolve_catalog`` also
        # applies any vendor-published chip specs from
        # ``candidate.cpu_chip_specs`` to the corresponding ``cpu_catalog``
        # cells per the Session 7 seed/conflict rules:
        #   * empty cell → write
        #   * needs-review row + match → no-op
        #   * needs-review row + diff → overwrite + queue value_disagreement
        #   * vouched row + diff → keep + queue value_disagreement
        cat_report = resolve_catalog(conn, candidate)
        report.new_cpus = cat_report["new_cpus"]
        report.new_gpus = cat_report["new_gpus"]

        # Lenovo Intel/AMD merge (Stage 7 T7.0a M4): when the row may
        # already exist with sibling-arch data (e.g. Intel ingested last
        # week, AMD arrives today), pre-union the candidate's
        # ``boards`` and ``source_model_codes`` with whatever the DB row
        # already has. Without this, the diff path would enqueue a
        # value_disagreement on the partial AMD-only boards list. The
        # union only runs when ``family_code`` is set on the candidate.
        if candidate.family_code is not None:
            _premerge_lenovo_existing_row(conn, pk, candidate)

        # PK row guarantee: if no row yet, write the vendor_full_name
        # bundle first (it's the only column we always emit) so the row
        # exists before the per-cell diffs run.
        if candidate.vendor_full_name is not None:
            _diff_scalar(
                conn,
                pk,
                "vendor_full_name",
                candidate.vendor_full_name,
                report,
                year_was_inferred=candidate.year_was_inferred,
            )

        for col in SCALAR_FIELDS:
            if col == "vendor_full_name":
                continue
            cand_bundle: Optional[Bundle] = getattr(candidate, col)
            if cand_bundle is None:
                continue
            _diff_scalar(conn, pk, col, cand_bundle, report)

        for col in OFFERINGS_FIELDS:
            cand_offerings: Optional[OfferingsList] = getattr(candidate, col)
            if cand_offerings is None:
                continue
            _diff_offerings(conn, pk, col, cand_offerings, report)

        # Write the two plain-text Lenovo merge columns last, after the
        # row is guaranteed to exist. These are NOT provenance bundles;
        # they live as flat scalars per the M1 schema.
        if candidate.family_code is not None:
            _write_lenovo_merge_columns(
                conn,
                pk,
                family_code=candidate.family_code,
                source_model_codes=candidate.source_model_codes,
            )

    return report


# ---------------------------------------------------------------------------
# Public entry — multi-tile (cross-tile merge per Decision 3)
# ---------------------------------------------------------------------------


def ingest_product(
    conn: sqlite3.Connection, candidates: list[CandidateProduct]
) -> IngestReport:
    """Merge ``candidates`` (all sharing a PK) and ingest atomically.

    Per Decision 3, the eight list-of-offerings columns are *additive*
    across tiles — multiple tiles for the same product simply union
    their offerings. Scalars stay one-per-snapshot; the first candidate
    wins, and any later candidate whose scalar disagrees still queues a
    ``value_disagreement`` against the first (handled by re-running the
    diff for each later candidate against the in-progress DB row).

    Single-tile callers can keep using :func:`ingest`; this function is
    the right entry point whenever a refresh produces multiple
    snapshots for one PK.
    """
    if not candidates:
        return IngestReport()
    if len(candidates) == 1:
        return ingest(conn, candidates[0])

    pk0 = (candidates[0].model_code, candidates[0].year)
    for c in candidates[1:]:
        if (c.model_code, c.year) != pk0:
            raise ValueError(
                f"ingest_product: candidates must share a PK; got "
                f"{(c.model_code, c.year)} vs {pk0}"
            )

    merged = _merge_candidates(candidates)
    return ingest(conn, merged)


# ---------------------------------------------------------------------------
# Cross-tile merge
# ---------------------------------------------------------------------------


# Identity-key extractors per offerings column. Each function takes one
# offering dict and returns a hashable identity key. Two offerings with
# the same key (and the same review status) are unioned into one entry;
# the first instance wins for the bundle metadata. ``needs-review``
# offerings stay separate from ``verified`` offerings (Decision 3 rule).
def _cpu_id(off: dict[str, Any]) -> Any:
    bundle = off.get("model")
    return _value(bundle)


def _gpu_id(off: dict[str, Any]) -> Any:
    # boards entries: identity = (label, arch_marker, frozenset of GPU model
    # names). ``arch_marker`` (Lenovo Intel/AMD merge, Stage 7 T7.0a) keeps
    # boards from different arches separate even when the vendor happens to
    # reuse the same label across them. Absent for non-Lenovo bridges and
    # for Lenovo bridges that couldn't derive a family.
    label = _value(off.get("label"))
    gpus = off.get("gpus") or []
    gpu_names = tuple(sorted(_value(g) for g in gpus if isinstance(g, dict)))
    arch = off.get("arch_marker")
    return (label, arch, gpu_names)


def _display_id(off: dict[str, Any]) -> Any:
    return (
        _value(off.get("resolution_pixels")),
        _value(off.get("panel_type")),
        _value(off.get("refresh_rate_hz")),
        _value(off.get("size_inches")),
    )


def _battery_id(off: dict[str, Any]) -> Any:
    return (_value(off.get("wattage_wh")), _value(off.get("cell_count")))


def _keyboard_id(off: dict[str, Any]) -> Any:
    return _value(off.get("description"))


def _storage_id(off: dict[str, Any]) -> Any:
    return _value(off.get("gen"))


def _adapter_id(off: dict[str, Any]) -> Any:
    return _value(off.get("wattage_w"))


def _camera_id(off: dict[str, Any]) -> Any:
    return (
        _value(off.get("resolution")),
        _value(off.get("ir_supported")),
        _value(off.get("privacy_shutter")),
    )


# Identity keys per offerings column. Tunable per field; documented here
# so the rule is in one place. Cross-tile equality is by these tuples.
_OFFERING_IDENTITY: dict[str, Any] = {
    "cpu_offerings": _cpu_id,
    "boards": _gpu_id,
    "display_offerings": _display_id,
    "battery_offerings": _battery_id,
    "keyboard_offerings": _keyboard_id,
    "storage_slots": _storage_id,
    "adapter_offerings": _adapter_id,
    "camera_offerings": _camera_id,
}


def _value(bundle: Any) -> Any:
    """Best-effort ``value`` extraction from a leaf bundle (or fallthrough)."""
    if isinstance(bundle, dict) and "value" in bundle:
        return bundle.get("value")
    return bundle


def _offering_review_status(offering: dict[str, Any]) -> str:
    """Returns ``"needs-review"`` if any leaf is needs-review, else ``"ok"``.

    Used to keep needs-review offerings separate from verified offerings
    when unioning across tiles (Decision 3 rule: do not silently merge a
    needs-review offering with a verified one).
    """
    for leaf in offering.values():
        if isinstance(leaf, dict) and leaf.get("status") == "needs-review":
            return "needs-review"
        if isinstance(leaf, list):
            for item in leaf:
                if isinstance(item, dict) and item.get("status") == "needs-review":
                    return "needs-review"
    return "ok"


def _merge_offerings(
    column: str, candidates: list[CandidateProduct]
) -> Optional[OfferingsList]:
    """Union one offerings column across ``candidates`` by identity key.

    First-seen wins for the bundle metadata. ``needs-review`` and
    ``verified`` versions of the same logical offering stay as two
    distinct entries in the output (Decision 3 rule).

    For ``boards`` specifically: when the same label appears in two
    tiles with different GPUs, the GPU lists are unioned (deduped by
    GPU model name). That's the static-board union the user asked for —
    one MB1 entry across tiles, ``gpus = [RTX 5070 Ti, RTX 5090]``.
    """
    id_fn = _OFFERING_IDENTITY.get(column)
    if id_fn is None:
        # Unknown offerings column — fall through to the first non-None.
        for c in candidates:
            v = getattr(c, column)
            if v is not None:
                return v
        return None

    if column == "boards":
        return _merge_boards(candidates)

    out: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for c in candidates:
        offerings = getattr(c, column)
        if offerings is None:
            continue
        for off in offerings:
            review = _offering_review_status(off)
            key = (id_fn(off), review)
            if key in seen:
                continue
            seen.add(key)
            out.append(off)
    return out or None


def _merge_boards(candidates: list[CandidateProduct]) -> Optional[OfferingsList]:
    """Special-case boards merge: union GPUs within the same (label, arch).

    Each candidate's boards entries already group GPUs by label (via the
    bridge's static-map lookup). Cross-tile, we collapse same-label
    entries and dedupe their GPU lists by model name, preserving the
    first-seen GPU bundle (which carries provenance).

    Lenovo Intel/AMD merge (Stage 7 T7.0a M4): the collapse key is
    ``(label, arch_marker)`` so the Intel ``MB1`` and the AMD ``MB1`` of
    the same family stay as distinct entries with their own GPU lists
    and arch tag. ``arch_marker`` is absent for non-Lenovo bridges and
    for unparseable Lenovo slugs — those collapse on label alone (the
    arch component is ``None`` and matches across entries).
    """
    # (label_value, arch_marker) -> {"label", "tpp_max", "tgp_max",
    #                                "arch_marker", "gpus_by_name"}
    by_key: dict[Any, dict[str, Any]] = {}
    key_order: list[Any] = []
    for c in candidates:
        boards = c.boards
        if boards is None:
            continue
        for entry in boards:
            label_val = _value(entry.get("label"))
            arch = entry.get("arch_marker")
            key = (label_val, arch)
            if key not in by_key:
                slot: dict[str, Any] = {
                    "label": entry.get("label"),
                    "tpp_max": entry.get("tpp_max"),
                    "tgp_max": entry.get("tgp_max"),
                    "gpus_by_name": {},
                }
                if arch is not None:
                    slot["arch_marker"] = arch
                by_key[key] = slot
                key_order.append(key)
            slot = by_key[key]
            for gpu in entry.get("gpus") or []:
                if not isinstance(gpu, dict):
                    continue
                name = gpu.get("value")
                if name in slot["gpus_by_name"]:
                    continue
                slot["gpus_by_name"][name] = gpu
    if not by_key:
        return None
    out: OfferingsList = []
    for key in key_order:
        slot = by_key[key]
        entry: dict[str, Any] = {
            "label": slot["label"],
            "tpp_max": slot["tpp_max"],
            "tgp_max": slot["tgp_max"],
            "gpus": list(slot["gpus_by_name"].values()),
        }
        if "arch_marker" in slot:
            entry["arch_marker"] = slot["arch_marker"]
        out.append(entry)
    return out


# Ceiling-style scalar fields that merge across tiles via ``max()`` instead
# of last-writer-wins. These represent a *platform ceiling* (the highest
# config the product line supports), so the right cross-tile semantic is
# "take the greatest ceiling published anywhere on this product."
#
# Stage 6 candidates for the same ``max()``-style merge (NOT yet
# implemented — Stage 6 will revisit the full scalar-merge path):
#     - ``memory_max_gb``        (platform max RAM ceiling)
#     - ``storage_max_gb``       (platform max storage ceiling)  [active]
#     - ``memory_speed_mts``     (top published memory speed)
#
# Today only ``storage_max_gb`` uses the ceiling-merge path; the other two
# stay last-writer-wins to keep the change scoped. Add to this set when
# Stage 6 lands the broader refactor.
_CEILING_MERGE_SCALARS: frozenset[str] = frozenset({"storage_max_gb"})


def _merge_ceiling_scalar(
    candidates: list[CandidateProduct], col: str
) -> Optional[Bundle]:
    """Pick the bundle with the largest numeric ``value`` across tiles.

    Skips ``None``-valued bundles and bundles with non-numeric values (the
    extractor uses ``vendor-doesn't-publish`` with ``value: None`` when no
    number could be parsed). Falls back to the first non-None bundle if no
    bundle has a numeric value (preserves the ``vendor-doesn't-publish``
    provenance in that case).
    """
    best: Optional[Bundle] = None
    best_val: Optional[float] = None
    fallback: Optional[Bundle] = None
    for c in candidates:
        bundle = getattr(c, col)
        if bundle is None:
            continue
        if fallback is None:
            fallback = bundle
        v = bundle.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v_num = float(v)
            if best_val is None or v_num > best_val:
                best_val = v_num
                best = bundle
    return best if best is not None else fallback


def _merge_candidates(candidates: list[CandidateProduct]) -> CandidateProduct:
    """Combine N candidates with the same PK into one merged candidate.

    * Scalars: first candidate's bundle wins by default. Ceiling-style
      scalars listed in ``_CEILING_MERGE_SCALARS`` (currently just
      ``storage_max_gb``) pick the bundle with the largest numeric value
      across tiles instead — same logic that should eventually apply to
      ``memory_max_gb`` and ``memory_speed_mts`` under the Stage 6
      scalar-merge refactor (left as a forward-compat hook above).
      Non-ceiling scalar disagreements between tiles are real conflicts;
      they fall through to the existing ``value_disagreement`` path when
      the second candidate would have written but the first already did.
      To preserve that signal we re-run the diff inside ``ingest`` for
      each tile in turn — but doing it in one pass via a merged candidate
      already captures the first-write semantics. Tile-2 disagreements
      are intentionally lost in the simpler model; if any prove
      load-bearing later, swap to per-tile re-diff. For Stage 2 the
      tradeoff is fine — Dell tiles never disagree on scalars in practice.
    * Offerings: unioned by identity key per column.
    * ``year_was_inferred``: ORed across candidates (any inferred year
      means the merged identity is suspect).
    * ``notes``: concatenated (de-duped by string).
    """
    base = candidates[0]
    merged = CandidateProduct(model_code=base.model_code, year=base.year)
    merged.year_was_inferred = any(c.year_was_inferred for c in candidates)

    # Lenovo merge (Stage 7 T7.0a M4): family_code is shared by all
    # candidates in this group (the grouping layer keyed on it). Union
    # source_model_codes across the group, preserving first-seen order.
    family_codes = {c.family_code for c in candidates if c.family_code is not None}
    if family_codes:
        # All non-None family_codes must agree — guaranteed by grouping
        # in cli/refresh.py, but assert defensively.
        if len(family_codes) > 1:
            raise ValueError(
                f"_merge_candidates: candidates disagree on family_code: "
                f"{sorted(family_codes)}"
            )
        merged.family_code = next(iter(family_codes))
        seen_codes: list[str] = []
        seen_set: set[str] = set()
        for c in candidates:
            for code in c.source_model_codes or ():
                if code in seen_set:
                    continue
                seen_set.add(code)
                seen_codes.append(code)
        merged.source_model_codes = seen_codes or None

    seen_notes: set[str] = set()
    for c in candidates:
        for n in c.notes:
            if n in seen_notes:
                continue
            seen_notes.add(n)
            merged.notes.append(n)

    # Scalars: ceiling-style fields take max() across tiles; everything
    # else is first-non-None-wins.
    for col in SCALAR_FIELDS:
        if col in _CEILING_MERGE_SCALARS:
            picked = _merge_ceiling_scalar(candidates, col)
            if picked is not None:
                setattr(merged, col, picked)
            continue
        for c in candidates:
            val = getattr(c, col)
            if val is not None:
                setattr(merged, col, val)
                break

    # Offerings: union per column.
    for col in OFFERINGS_FIELDS:
        merged_value = _merge_offerings(col, candidates)
        if merged_value is not None:
            setattr(merged, col, merged_value)

    return merged


# ---------------------------------------------------------------------------
# Lenovo Intel/AMD merge — pre-union with existing DB row + flat-column write
# ---------------------------------------------------------------------------


def _premerge_lenovo_existing_row(
    conn: sqlite3.Connection,
    pk: dict[str, Any],
    candidate: CandidateProduct,
) -> None:
    """Union the candidate's ``boards`` and ``source_model_codes`` with the
    existing DB row, then write the merged ``boards`` directly and clear
    the candidate's copy so the per-cell diff doesn't re-run on it.

    Without this short-circuit, an AMD-arch refresh arriving after the
    Intel-arch row was already stored would present a *unioned* boards
    list (its own AMD entries plus the existing Intel ones), and the
    diff path would see "existing differs from candidate" — because the
    candidate is now strictly larger — and enqueue a
    ``value_disagreement``. Writing directly here bypasses that.

    Idempotent: re-running the same arch refresh produces the same
    union (the dedup key on ``_merge_boards`` is set-based).
    """
    existing_boards = read_offerings(conn, "products", pk, "boards")
    if existing_boards is not None:
        # Wrap the existing row as a synthetic CandidateProduct so we
        # can reuse the cross-tile merge code path verbatim.
        existing_holder = CandidateProduct(
            model_code=str(pk["model_code"]), year=int(pk["year"])
        )
        existing_holder.boards = existing_boards
        cand_holder = CandidateProduct(
            model_code=str(pk["model_code"]), year=int(pk["year"])
        )
        cand_holder.boards = candidate.boards
        merged_boards = _merge_boards([existing_holder, cand_holder])
        if merged_boards is not None:
            write_offerings(conn, "products", pk, "boards", merged_boards)
            # Clear the candidate's boards so the diff path doesn't
            # re-process them and enqueue a false conflict.
            candidate.boards = None

    # Union source_model_codes (existing row's JSON-array column with
    # the candidate's list). Preserve first-seen order. Direct UPDATE
    # of source_model_codes runs later via _write_lenovo_merge_columns.
    existing_codes_raw = _read_flat_column(conn, pk, "source_model_codes")
    if existing_codes_raw:
        try:
            existing_codes = json.loads(existing_codes_raw)
        except (json.JSONDecodeError, TypeError):
            existing_codes = []
        if isinstance(existing_codes, list):
            seen: list[str] = []
            seen_set: set[str] = set()
            for code in existing_codes:
                if isinstance(code, str) and code not in seen_set:
                    seen_set.add(code)
                    seen.append(code)
            for code in candidate.source_model_codes or ():
                if code not in seen_set:
                    seen_set.add(code)
                    seen.append(code)
            candidate.source_model_codes = seen


def _read_flat_column(
    conn: sqlite3.Connection, pk: dict[str, Any], column: str
) -> Optional[str]:
    """Read one plain-text column from the products row at ``pk``.

    Returns ``None`` if the row is missing or the column is NULL. Used
    for the two flat Lenovo merge columns (``family_code``,
    ``source_model_codes``) which are NOT provenance bundles.
    """
    row = conn.execute(
        "SELECT {col} FROM products WHERE model_code = ? AND year = ?".format(
            col=column
        ),
        (pk["model_code"], pk["year"]),
    ).fetchone()
    if row is None:
        return None
    return row[0]


def _write_lenovo_merge_columns(
    conn: sqlite3.Connection,
    pk: dict[str, Any],
    *,
    family_code: str,
    source_model_codes: Optional[list[str]],
) -> None:
    """Write the flat ``family_code`` and ``source_model_codes`` columns.

    ``source_model_codes`` is JSON-encoded as an array of strings; the
    schema declares the column as plain TEXT (Stage 7 T7.0a M1). The
    row is guaranteed to already exist by the time this runs — every
    Lenovo ingest path writes ``vendor_full_name`` (or some other
    column) first, so we always UPDATE, never INSERT, here.
    """
    codes_json = (
        json.dumps(list(source_model_codes)) if source_model_codes else None
    )
    conn.execute(
        "UPDATE products SET family_code = ?, source_model_codes = ? "
        "WHERE model_code = ? AND year = ?",
        (family_code, codes_json, pk["model_code"], pk["year"]),
    )


# ---------------------------------------------------------------------------
# Scalar diff
# ---------------------------------------------------------------------------


def _diff_scalar(
    conn: sqlite3.Connection,
    pk: dict[str, Any],
    field_path: str,
    candidate: Bundle,
    report: IngestReport,
    *,
    year_was_inferred: bool = False,
) -> None:
    if candidate.get("status") == "needs-review":
        existing = read_scalar(conn, "products", pk, field_path)
        # Decision 1: route year-inferred vendor_full_name to its own
        # queue type.
        if field_path == "vendor_full_name" and year_was_inferred:
            conflict_type = "year_inferred"
            report.year_inferred += 1
        else:
            conflict_type = "low_confidence_extraction"
            report.low_confidence += 1
        _enqueue(
            conn,
            pk,
            field_path,
            conflict_type,
            existing_bundle=existing,
            candidate_bundle=candidate,
        )
        return

    existing = read_scalar(conn, "products", pk, field_path)
    if existing is None:
        write_scalar(conn, "products", pk, field_path, candidate)
        report.inserted_fields += 1
        return

    if _values_equal(existing.get("value"), candidate.get("value")):
        # Refresh captured_at only.
        refreshed = dict(existing)
        if "captured_at" in candidate:
            refreshed["captured_at"] = candidate["captured_at"]
        write_scalar(conn, "products", pk, field_path, refreshed)
        report.refreshed_fields += 1
        return

    # Genuine disagreement.
    _enqueue(
        conn,
        pk,
        field_path,
        "value_disagreement",
        existing_bundle=existing,
        candidate_bundle=candidate,
    )
    report.conflicts += 1


# ---------------------------------------------------------------------------
# Offerings diff (list-of-dicts-of-bundles)
# ---------------------------------------------------------------------------


def _diff_offerings(
    conn: sqlite3.Connection,
    pk: dict[str, Any],
    field_path: str,
    candidate: OfferingsList,
    report: IngestReport,
) -> None:
    """List-level diff: index-aligned per-offering, per-leaf comparison.

    Strategy: if any leaf of any offering is ``needs-review``, the entire
    list is enqueued as ``low_confidence_extraction`` and not written.
    Otherwise:

    * No existing list → insert the list as-is.
    * Lists "value-equal" (every leaf value matches at the same index/key)
      → refresh ``captured_at`` on every leaf bundle.
    * Lists differ → enqueue ``value_disagreement``; existing untouched.

    The collapse-to-list-level diff is intentional for Stage 2: per-leaf
    diff inside an offering is finicky and can be tightened later without
    touching the bridge.
    """
    if _any_offering_needs_review(candidate):
        existing = read_offerings(conn, "products", pk, field_path)
        _enqueue(
            conn,
            pk,
            field_path,
            "low_confidence_extraction",
            existing_value_raw=existing,
            candidate_value_raw=candidate,
        )
        report.low_confidence += 1
        return

    existing = read_offerings(conn, "products", pk, field_path)
    if existing is None:
        write_offerings(conn, "products", pk, field_path, candidate)
        report.inserted_fields += 1
        return

    if _offerings_value_equal(existing, candidate):
        refreshed = _refresh_offerings_captured_at(existing, candidate)
        write_offerings(conn, "products", pk, field_path, refreshed)
        report.refreshed_fields += 1
        return

    _enqueue(
        conn,
        pk,
        field_path,
        "value_disagreement",
        existing_value_raw=existing,
        candidate_value_raw=candidate,
    )
    report.conflicts += 1


def _any_offering_needs_review(offerings: OfferingsList) -> bool:
    for offering in offerings:
        for leaf in offering.values():
            if isinstance(leaf, dict) and leaf.get("status") == "needs-review":
                return True
            if isinstance(leaf, list):
                # gpus / similar list-of-bundles
                for item in leaf:
                    if (
                        isinstance(item, dict)
                        and item.get("status") == "needs-review"
                    ):
                        return True
    return False


def _offerings_value_equal(a: OfferingsList, b: OfferingsList) -> bool:
    """Compare ``value`` of every leaf bundle, ignoring provenance fields."""
    return _strip_provenance(a) == _strip_provenance(b)


def _strip_provenance(offerings: OfferingsList) -> list[Any]:
    out: list[Any] = []
    for offering in offerings:
        cleaned: dict[str, Any] = {}
        for k, v in offering.items():
            if isinstance(v, dict) and "value" in v:
                cleaned[k] = {"value": v.get("value")}
            elif isinstance(v, list):
                cleaned[k] = [
                    {"value": x.get("value") if isinstance(x, dict) else x}
                    for x in v
                ]
            else:
                cleaned[k] = v
        out.append(cleaned)
    return out


def _refresh_offerings_captured_at(
    existing: OfferingsList, candidate: OfferingsList
) -> OfferingsList:
    """Walk ``existing`` and replace each leaf's ``captured_at`` with the
    candidate's matching leaf timestamp where present."""
    out: OfferingsList = []
    for e_off, c_off in zip(existing, candidate):
        merged: dict[str, Bundle] = {}
        for k, e_leaf in e_off.items():
            if isinstance(e_leaf, dict) and "value" in e_leaf:
                ref = dict(e_leaf)
                c_leaf = c_off.get(k) if isinstance(c_off, dict) else None
                if isinstance(c_leaf, dict) and "captured_at" in c_leaf:
                    ref["captured_at"] = c_leaf["captured_at"]
                merged[k] = ref
            else:
                merged[k] = e_leaf  # type: ignore[assignment]
        out.append(merged)
    return out


# ---------------------------------------------------------------------------
# Comparison helper
# ---------------------------------------------------------------------------


def _values_equal(a: Any, b: Any) -> bool:
    """Loose equality used for diff: ``None == None``, ``int == float``, etc."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return a == b


# ---------------------------------------------------------------------------
# review_queue insert
# ---------------------------------------------------------------------------


def _enqueue(
    conn: sqlite3.Connection,
    pk: dict[str, Any],
    field_path: str,
    conflict_type: str,
    *,
    existing_bundle: Optional[Bundle] = None,
    candidate_bundle: Optional[Bundle] = None,
    existing_value_raw: Any = None,
    candidate_value_raw: Any = None,
) -> None:
    """Insert one row into ``review_queue``."""
    detected_at = datetime.now(timezone.utc).isoformat()

    if existing_bundle is not None:
        existing_value = json.dumps(
            {"value": existing_bundle.get("value")}
        )
        existing_prov = json.dumps(existing_bundle)
    else:
        existing_value = (
            json.dumps(existing_value_raw) if existing_value_raw is not None else None
        )
        existing_prov = None

    if candidate_bundle is not None:
        cand_value = json.dumps({"value": candidate_bundle.get("value")})
        cand_prov = json.dumps(candidate_bundle)
    else:
        cand_value = (
            json.dumps(candidate_value_raw)
            if candidate_value_raw is not None
            else None
        )
        cand_prov = None

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
            pk["model_code"],
            pk["year"],
            field_path,
            conflict_type,
            existing_value,
            existing_prov,
            cand_value,
            cand_prov,
            detected_at,
        ),
    )
