"""``backfill-asus-families`` CLI subcommand — one-time migration that
applies the ASUS TUF F/A slug parser to pre-existing ASUS rows.

The ASUS TUF Intel/AMD merge (T9.3, Session 42) only stamps
``family_code``, ``source_model_codes``, and ``arch_marker`` on candidates
produced *after* the bridge derivation landed. The TUF rows scraped before
that exist with ``family_code IS NULL`` and ``model_code`` still set to an
arch-specific slug (e.g. ``asus-tuf-gaming-f16-2024``) — so the first TUF
refresh would re-derive ``asus-tuf-gaming-16-2024``, miss the row, and
orphan into a NEW duplicate row. This command walks those rows, re-derives
``(family_code, arch_marker)`` from the stored ``model_code`` alone, and
applies the same single-row rename / multi-row merge as the Dell backfill.

ASUS-specific wrinkle: the Stage 11 audit already hand-populated
``source_model_codes`` on these rows (e.g. the F16 row lists its A16
siblings). The shared ``_apply_single`` / ``_apply_merge`` helpers
OVERWRITE that column, so this backfill snapshots the existing codes first
and restores the union afterwards — audit-recorded lineage is preserved.

Unresolved ``review_queue`` rows keyed on a renamed/merged slug are
re-pointed at the new family_code (same as the Dell backfill); resolved
rows keep their original slug as history. Rows whose slug can't be parsed
(ROG, suffixed slugs) are left untouched. Re-running is a no-op.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Optional

from ..bridge.asus import _derive_asus_family_and_arch
from ..db.connection import connect, transaction
# Same cross-module reuse as backfill_dell_families: the apply helpers are
# vendor-agnostic (they key on model_code/year/family_code/arch only).
from .backfill_dell_families import _remap_unresolved_queue_rows
from .backfill_lenovo_families import _apply_merge, _apply_single


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "backfill-asus-families",
        help=(
            "One-time backfill: derive family_code / source_model_codes / "
            "arch_marker for ASUS TUF rows ingested before the T9.3 bridge."
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
    candidates = _select_unbackfilled_asus(conn)
    if not candidates:
        print("backfill-asus-families: no ASUS rows without family_code.")
        return

    parsed: list[tuple[str, int, str, Optional[str]]] = []
    unparseable: list[tuple[str, int]] = []
    for model_code, year in candidates:
        family, arch = _derive_asus_family_and_arch(model_code)
        if family is None:
            unparseable.append((model_code, year))
        else:
            parsed.append((model_code, year, family, arch))

    print(
        f"Found {len(candidates)} ASUS product(s) without family_code. "
        f"Parseable: {len(parsed)}. Unparseable (left untouched): "
        f"{len(unparseable)}."
    )
    for model_code, year, family, arch in parsed:
        arch_str = arch if arch is not None else "(no arch)"
        print(f"  {model_code} -> family {family}, arch {arch_str}")
    for model_code, year in unparseable:
        print(f"  {model_code} -> unparseable, left as-is")

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
        existing_codes = _read_existing_codes(conn, [model_code], year)
        _apply_single(conn, model_code, year, family_code, arch)
        _restore_code_union(conn, family_code, year, existing_codes, [model_code])
        requeued += _remap_unresolved_queue_rows(
            conn, [model_code], year, family_code
        )
        updated += 1

    for (family, year), members in merge_groups.items():
        members_sorted = sorted(members, key=lambda m: m[0])
        canonical = members_sorted[0]
        others = members_sorted[1:]
        member_codes = [m[0] for m in members_sorted]
        existing_codes = _read_existing_codes(conn, member_codes, year)
        _apply_merge(conn, year, family, canonical, others)
        _restore_code_union(conn, family, year, existing_codes, member_codes)
        requeued += _remap_unresolved_queue_rows(
            conn, member_codes, year, family
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


def _select_unbackfilled_asus(
    conn: sqlite3.Connection,
) -> list[tuple[str, int]]:
    """All ASUS rows with no family_code yet, ordered for determinism."""
    rows = conn.execute(
        "SELECT model_code, year FROM products "
        "WHERE family_code IS NULL "
        "AND json_extract(brand, '$.value') = 'ASUS' "
        "ORDER BY model_code, year"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _read_existing_codes(
    conn: sqlite3.Connection, model_codes: list[str], year: int
) -> list[str]:
    """Snapshot the pre-backfill ``source_model_codes`` across the rows.

    First-seen order across members; malformed JSON is skipped.
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for mc in model_codes:
        raw = conn.execute(
            "SELECT source_model_codes FROM products "
            "WHERE model_code = ? AND year = ?",
            (mc, year),
        ).fetchone()
        if raw is None or raw[0] is None:
            continue
        try:
            codes = json.loads(raw[0])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(codes, list):
            continue
        for code in codes:
            if isinstance(code, str) and code not in seen_set:
                seen_set.add(code)
                seen.append(code)
    return seen


def _restore_code_union(
    conn: sqlite3.Connection,
    family_code: str,
    year: int,
    existing_codes: list[str],
    member_codes: list[str],
) -> None:
    """Write the union of pre-backfill codes and the member slugs.

    The shared apply helpers overwrite ``source_model_codes`` with just the
    member slugs; ASUS rows carry Stage-11-audited sibling codes that must
    survive. Union order: audited codes first (first-seen), then any member
    slug not already present.
    """
    seen: list[str] = list(existing_codes)
    seen_set = set(existing_codes)
    for code in member_codes:
        if code not in seen_set:
            seen_set.add(code)
            seen.append(code)
    if not seen:
        return
    conn.execute(
        "UPDATE products SET source_model_codes = ? "
        "WHERE model_code = ? AND year = ?",
        (json.dumps(seen), family_code, year),
    )
