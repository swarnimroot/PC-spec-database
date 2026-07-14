"""``backfill-dell-families`` CLI subcommand — one-time migration that
applies the Dell SKU-pair parser to pre-existing Dell rows.

The Dell Intel/AMD merge only stamps ``family_code``,
``source_model_codes``, and ``arch_marker`` on candidates produced *after*
the bridge derivation landed. Rows ingested before that exist in the DB
with ``family_code IS NULL`` and ``model_code`` set to the original Dell
SKU code (e.g. ``da15260``). This command walks those rows, re-derives
``(family_code, arch_marker)`` from the stored ``model_code`` alone (the
Dell rule needs no title/URL), and either:

  * single-row family → update in place (rename ``model_code`` to the
    derived family_code, stamp ``arch_marker`` on each board, write
    ``family_code`` and ``source_model_codes=[original_sku_code]``).
  * multi-row family → merge boards into one canonical row, union the
    other offerings columns, keep the canonical row's scalars (any
    disagreement enqueues a ``value_disagreement`` in the review queue),
    then delete the non-canonical rows.

Unlike the Lenovo backfill, UNRESOLVED ``review_queue`` rows keyed on a
renamed/merged SKU code are re-pointed at the new family_code so they
keep resolving against the surviving row (resolved rows are left as
historical record).

Rows whose code can't be parsed are left untouched (``family_code`` stays
NULL). Re-running the command is a no-op — only ``family_code IS NULL``
rows are considered.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Optional

from ..bridge.dell import _derive_dell_family_and_arch
from ..db.connection import connect, transaction
# Cross-module access to the Lenovo backfill's apply helpers: the
# single-row rename and multi-row merge are vendor-agnostic (they key on
# model_code/year/family_code/arch only), and we want identical semantics
# here. Importing keeps this backfill thin without a wider refactor.
from .backfill_lenovo_families import _apply_merge, _apply_single


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "backfill-dell-families",
        help=(
            "One-time backfill: derive family_code / source_model_codes / "
            "arch_marker for Dell rows ingested before the bridge merge."
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
    candidates = _select_unbackfilled_dell(conn)
    if not candidates:
        print("backfill-dell-families: no Dell rows without family_code.")
        return

    # Per-row derivation: (model_code, year, family_code, arch_marker).
    parsed: list[tuple[str, int, str, Optional[str]]] = []
    unparseable: list[tuple[str, int]] = []
    for model_code, year in candidates:
        family, arch = _derive_dell_family_and_arch(model_code)
        if family is None:
            unparseable.append((model_code, year))
        else:
            parsed.append((model_code, year, family, arch))

    print(
        f"Found {len(candidates)} Dell product(s) without family_code. "
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
    requeued = 0

    for (family, year), members in single_groups.items():
        model_code, family_code, arch = members[0]
        _apply_single(conn, model_code, year, family_code, arch)
        requeued += _remap_unresolved_queue_rows(
            conn, [model_code], year, family_code
        )
        updated += 1

    for (family, year), members in merge_groups.items():
        # Deterministic canonical pick: alphabetic by original model_code.
        members_sorted = sorted(members, key=lambda m: m[0])
        canonical = members_sorted[0]
        others = members_sorted[1:]
        _apply_merge(conn, year, family, canonical, others)
        requeued += _remap_unresolved_queue_rows(
            conn, [m[0] for m in members_sorted], year, family
        )
        updated += 1
        deleted += len(others)

    print()
    print(
        f"Done. {updated} product(s) updated, {deleted} row(s) deleted "
        f"(merged), {requeued} unresolved review_queue row(s) re-pointed, "
        f"{len(unparseable)} product(s) unchanged."
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _select_unbackfilled_dell(
    conn: sqlite3.Connection,
) -> list[tuple[str, int]]:
    """All Dell rows with no family_code yet, ordered for determinism.

    Vendor detection matches the existing convention: the ``brand`` bundle
    on a products row carries ``value: 'Dell'`` for Dell (set in
    ``bridge/dell.py``).
    """
    rows = conn.execute(
        "SELECT model_code, year FROM products "
        "WHERE family_code IS NULL "
        "AND json_extract(brand, '$.value') = 'Dell' "
        "ORDER BY model_code, year"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _remap_unresolved_queue_rows(
    conn: sqlite3.Connection,
    old_codes: list[str],
    year: int,
    family_code: str,
) -> int:
    """Re-point unresolved review_queue rows at the new family_code.

    Queue rows key on the vendor slug ``(product_model_code,
    product_year)``; after the rename/merge the products row answers to
    ``family_code``, so unresolved rows must follow or they orphan (the
    Review UI's identity lookup and the resolve CLI both join on
    ``products.model_code``). Resolved rows keep their original code as a
    historical record.
    """
    placeholders = ", ".join(["?"] * len(old_codes))
    cur = conn.execute(
        f"UPDATE review_queue SET product_model_code = ? "
        f"WHERE product_model_code IN ({placeholders}) "
        f"AND product_year = ? AND resolved_at IS NULL",
        [family_code, *old_codes, year],
    )
    return cur.rowcount
