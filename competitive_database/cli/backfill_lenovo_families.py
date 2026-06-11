"""``backfill-lenovo-families`` CLI subcommand — one-time migration that
applies the M2+M3 Lenovo slug parser to pre-existing Lenovo rows.

The Lenovo Intel/AMD merge (Stage 7 T7.0a) only stamps ``family_code``,
``source_model_codes``, and ``arch_marker`` on candidates produced *after*
the M2+M3 bridge work landed. Rows ingested before that exist in the DB
with ``family_code IS NULL`` and ``model_code`` set to the original
Lenovo machine code (e.g. ``16IRX10``). This command walks those rows,
re-derives ``(family_code, arch_marker)`` from data already in the DB
(title + url + model_code), and either:

  * single-row family → update in place (rename ``model_code`` to the
    derived family_code, stamp ``arch_marker`` on each board, write
    ``family_code`` and ``source_model_codes=[original_machine_code]``).
  * multi-row family → merge boards into one canonical row, union the
    other offerings columns, keep the canonical row's scalars (any
    disagreement enqueues a ``value_disagreement`` in the review queue),
    then delete the non-canonical rows.

Rows whose slug can't be parsed are left untouched (``family_code`` stays
NULL). Re-running the command is a no-op — only ``family_code IS NULL``
rows are considered.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Any, Optional

from ..bridge.lenovo import _derive_lenovo_family_and_arch
from ..bridge.types import CandidateProduct, OFFERINGS_FIELDS, SCALAR_FIELDS
from ..db.connection import connect, transaction
from ..db.helpers import (
    read_offerings,
    read_scalar,
    resolve_products_pk,
    write_offerings,
    write_scalar,
)
# Cross-module access to runner internals: the M4 merge path already
# implements board union and the review-queue insert, and we want
# identical semantics here. Importing the underscored helpers keeps
# the backfill thin without a wider refactor.
from ..ingest.runner import (
    _enqueue,
    _merge_boards,
    _merge_offerings,
    _values_equal,
)


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "backfill-lenovo-families",
        help=(
            "One-time backfill: derive family_code / source_model_codes / "
            "arch_marker for Lenovo rows ingested before the M2+M3 bridge."
        ),
    )
    p.add_argument(
        "--db",
        default="competitive.db",
        help="Path to the SQLite DB file.",
    )
    p.set_defaults(func=main)


def main(args: argparse.Namespace) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    conn = connect(args.db)
    try:
        with transaction(conn):
            _run_backfill(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def _run_backfill(conn: sqlite3.Connection) -> None:
    """Scan, derive, group, and apply. Caller owns the transaction."""
    candidates = _select_unbackfilled_lenovo(conn)
    if not candidates:
        print("backfill-lenovo-families: no Lenovo rows without family_code.")
        return

    # Per-row derivation: (model_code, year, family_code, arch_marker).
    parsed: list[tuple[str, int, str, Optional[str]]] = []
    unparseable: list[tuple[str, int]] = []
    for model_code, year in candidates:
        title, url = _read_lenovo_title_and_url(conn, model_code, year)
        family, arch = _derive_lenovo_family_and_arch(title or "", url or "", model_code)
        if family is None:
            unparseable.append((model_code, year))
        else:
            parsed.append((model_code, year, family, arch))

    print(
        f"Found {len(candidates)} Lenovo product(s) without family_code. "
        f"Parseable: {len(parsed)}. Unparseable (left untouched): "
        f"{len(unparseable)}."
    )
    for model_code, year, family, arch in parsed:
        arch_str = arch if arch is not None else "(no arch)"
        print(f"  {model_code} -> family {family}, arch {arch_str}")
    for model_code, year in unparseable:
        print(f"  {model_code} -> unparseable, left as-is")

    # Group parseable rows by (family_code, year).
    groups: dict[tuple[str, int], list[tuple[str, str, Optional[str]]]] = {}
    for model_code, year, family, arch in parsed:
        groups.setdefault((family, year), []).append((model_code, family, arch))

    merge_groups = {k: v for k, v in groups.items() if len(v) > 1}
    single_groups = {k: v for k, v in groups.items() if len(v) == 1}

    if merge_groups:
        print()
        print(f"Found {len(merge_groups)} merge group(s):")
        for (family, year), members in sorted(merge_groups.items()):
            codes = sorted(m[0] for m in members)
            print(
                f"  {family} (year {year}): merging "
                f"{' + '.join(codes)}"
            )

    updated = 0
    deleted = 0

    for (family, year), members in single_groups.items():
        model_code, family_code, arch = members[0]
        _apply_single(conn, model_code, year, family_code, arch)
        updated += 1

    for (family, year), members in merge_groups.items():
        # Deterministic canonical pick: alphabetic by original model_code.
        members_sorted = sorted(members, key=lambda m: m[0])
        canonical = members_sorted[0]
        others = members_sorted[1:]
        _apply_merge(conn, year, family, canonical, others)
        updated += 1
        deleted += len(others)

    print()
    print(
        f"Done. {updated} product(s) updated, {deleted} row(s) deleted "
        f"(merged), {len(unparseable)} product(s) unchanged."
    )


# ---------------------------------------------------------------------------
# DB read helpers
# ---------------------------------------------------------------------------


def _select_unbackfilled_lenovo(
    conn: sqlite3.Connection,
) -> list[tuple[str, int]]:
    """All Lenovo rows with no family_code yet, ordered for determinism.

    Vendor detection matches the existing convention: the ``brand`` bundle
    on a products row carries ``value: 'Lenovo'`` for Lenovo (set in
    ``bridge/lenovo.py``). ``json_extract`` mirrors how the indexes on
    ``products.brand`` are built (see ``db/schema.sql``).
    """
    rows = conn.execute(
        "SELECT model_code, year FROM products "
        "WHERE family_code IS NULL "
        "AND json_extract(brand, '$.value') = 'Lenovo' "
        "ORDER BY model_code, year"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _read_lenovo_title_and_url(
    conn: sqlite3.Connection, model_code: str, year: int
) -> tuple[Optional[str], Optional[str]]:
    """Pull the title and source URL out of the provenance bundles so the
    M2+M3 derivation can run on data already in the DB.

    Priority order (the parser only needs the slug present in title OR URL):
      1. ``vendor_full_name`` (both title + source_url)
      2. ``brand`` (source_url only; the value is just "Lenovo" — not
         useful as a title, so we pass empty title alongside)
      3. Any remaining bundle in ``_FALLBACK_URL_FIELDS`` whose
         ``source_url`` is non-empty

    Real-DB rows with ``vendor_full_name IS NULL`` are common when the
    pre-M2 ingest path didn't populate the title cell; the slug still
    lives on ``brand.source_url`` and the other identity bundles.
    """
    pk = resolve_products_pk(conn, model_code, year)

    primary = read_scalar(conn, "products", pk, "vendor_full_name")
    title: Optional[str] = None
    url: Optional[str] = None
    if isinstance(primary, dict):
        if isinstance(primary.get("value"), str):
            title = primary.get("value")
        if isinstance(primary.get("source_url"), str) and primary.get("source_url"):
            url = primary.get("source_url")

    if url:
        return title, url

    # Fall back through bundles known to carry a usable source_url. We
    # don't grab provenance from arbitrary fields — only ones whose URL
    # is reliably the product page slug.
    for col in _FALLBACK_URL_FIELDS:
        bundle = read_scalar(conn, "products", pk, col)
        if not isinstance(bundle, dict):
            continue
        candidate_url = bundle.get("source_url")
        if isinstance(candidate_url, str) and candidate_url:
            # Title from these bundles isn't useful (brand="Lenovo",
            # status/segment are enums) — pass empty title so the parser
            # works off the URL slug alone.
            return title or "", candidate_url

    return title, url


# Bundles whose ``source_url`` reliably points at the per-product page
# slug. Order matches user-stated priority (brand first, then segment/
# status — both are scraped from the same vendor page).
_FALLBACK_URL_FIELDS: tuple[str, ...] = ("brand", "segment", "status")


# ---------------------------------------------------------------------------
# Apply: single-row case
# ---------------------------------------------------------------------------


def _apply_single(
    conn: sqlite3.Connection,
    model_code: str,
    year: int,
    family_code: str,
    arch_marker: Optional[str],
) -> None:
    """In-place update: rename model_code to family_code, stamp family_code
    + source_model_codes, and tag the row's boards with arch_marker."""
    # Stamp arch_marker on each board entry (if we derived one).
    if arch_marker is not None:
        pk = resolve_products_pk(conn, model_code, year)
        boards = read_offerings(conn, "products", pk, "boards")
        if boards:
            stamped = [_stamp_arch(b, arch_marker) for b in boards]
            write_offerings(conn, "products", pk, "boards", stamped)

    # Rename the (non-PK) model_code slug + set the two flat columns.
    codes_json = json.dumps([model_code])
    conn.execute(
        "UPDATE products SET model_code = ?, family_code = ?, "
        "source_model_codes = ? WHERE model_code = ? AND year = ?",
        (family_code, family_code, codes_json, model_code, year),
    )


# ---------------------------------------------------------------------------
# Apply: merge case
# ---------------------------------------------------------------------------


def _apply_merge(
    conn: sqlite3.Connection,
    year: int,
    family_code: str,
    canonical: tuple[str, str, Optional[str]],
    others: list[tuple[str, str, Optional[str]]],
) -> None:
    """Collapse a multi-row family into the canonical row.

    Strategy:
      * Stamp ``arch_marker`` on every row's boards using its derived arch.
      * Union all rows' boards via ``_merge_boards`` (same code path the
        M4 ingest uses for cross-tile / cross-arch board merges).
      * For other offerings columns, union via ``_merge_offerings`` (so
        e.g. an Intel-only display_offerings entry and an AMD-only one
        end up coexisting in the merged row).
      * For scalar bundles, keep the canonical row's value; if another
        row holds a different ``value``, enqueue ``value_disagreement``
        with canonical-as-existing.
      * Set ``source_model_codes`` to the sorted list of all original
        machine codes for determinism.
      * Delete the non-canonical rows; rename the canonical row's
        model_code to ``family_code``.
    """
    canonical_code, _, canonical_arch = canonical
    other_codes = [o[0] for o in others]
    all_codes = sorted([canonical_code] + other_codes)
    canonical_pk = resolve_products_pk(conn, canonical_code, year)

    # Build CandidateProduct holders so we can reuse _merge_boards /
    # _merge_offerings, which both read offerings off CandidateProduct
    # attributes. The holder PKs don't matter for the merge logic.
    holders: list[CandidateProduct] = []
    for code, arch in [(canonical_code, canonical_arch)] + [
        (o[0], o[2]) for o in others
    ]:
        pk = resolve_products_pk(conn, code, year)
        holder = CandidateProduct(model_code=family_code, year=year)
        # Stamp arch_marker on this row's boards before union.
        boards = read_offerings(conn, "products", pk, "boards")
        if boards is not None and arch is not None:
            holder.boards = [_stamp_arch(b, arch) for b in boards]
        elif boards is not None:
            holder.boards = boards
        for col in OFFERINGS_FIELDS:
            if col == "boards":
                continue
            setattr(holder, col, read_offerings(conn, "products", pk, col))
        holders.append(holder)

    # boards: union via _merge_boards (handles (label, arch_marker) keying).
    merged_boards = _merge_boards(holders)
    if merged_boards is not None:
        write_offerings(conn, "products", canonical_pk, "boards", merged_boards)

    # Other offerings: union by their per-column identity key.
    for col in OFFERINGS_FIELDS:
        if col == "boards":
            continue
        merged = _merge_offerings(col, holders)
        if merged is not None:
            write_offerings(conn, "products", canonical_pk, col, merged)

    # Scalars: canonical wins; any other-row disagreement enqueues a
    # value_disagreement. We enqueue against the FINAL slug identity
    # (family_code, year) so the queue rows match the post-rename
    # product identity — the row itself hasn't been renamed yet.
    for col in SCALAR_FIELDS:
        canonical_bundle = read_scalar(conn, "products", canonical_pk, col)
        for o in others:
            other_pk = resolve_products_pk(conn, o[0], year)
            other_bundle = read_scalar(conn, "products", other_pk, col)
            if other_bundle is None:
                continue
            if canonical_bundle is None:
                # Canonical missing this scalar — adopt the other row's
                # bundle (no conflict).
                write_scalar(conn, "products", canonical_pk, col, other_bundle)
                canonical_bundle = other_bundle
                continue
            if _values_equal(canonical_bundle.get("value"), other_bundle.get("value")):
                continue
            # Disagreement — keep canonical, queue the conflict against
            # the final PK shape (family_code, year).
            _enqueue(
                conn,
                family_code,
                year,
                col,
                "value_disagreement",
                existing_bundle=canonical_bundle,
                candidate_bundle=other_bundle,
            )

    # Delete non-canonical rows BEFORE renaming canonical, so the PK
    # rename can't collide with an existing row.
    for code in other_codes:
        conn.execute(
            "DELETE FROM products WHERE model_code = ? AND year = ?",
            (code, year),
        )

    # Rename canonical row's PK to (family_code, year) and stamp the
    # merge columns.
    codes_json = json.dumps(all_codes)
    conn.execute(
        "UPDATE products SET model_code = ?, family_code = ?, "
        "source_model_codes = ? WHERE model_code = ? AND year = ?",
        (family_code, family_code, codes_json, canonical_code, year),
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _stamp_arch(board: dict[str, Any], arch_marker: str) -> dict[str, Any]:
    """Return a shallow copy of ``board`` with ``arch_marker`` set.

    Idempotent — re-stamping a board that already carries the same marker
    is a no-op; a board already carrying a *different* marker is left
    alone (defensive: we shouldn't overwrite richer per-board data, and
    the M4 path keys boards by (label, arch_marker) so a mismatched
    pre-existing marker would split the entry anyway).
    """
    if "arch_marker" in board:
        return board
    out = dict(board)
    out["arch_marker"] = arch_marker
    return out
