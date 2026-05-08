"""``audit-normalize`` CLI subcommand — surface normalization gaps across
products.

Walks every product in the DB, collects the distinct values written at
each fillable cell path (via ``views/orchestrator.all_field_paths``), and
prints any path where the same conceptual field appears with two or more
different value strings across products. That's how gaps like
``"Wi-Fi 7"`` vs ``"WiFi 7"`` (T6.2 in TASKS.md) surface — they show up
as a single ``wifi_standard`` path with two distinct values.

By default only paths with 2+ distinct values are printed (the gaps).
``--all`` prints every filled path with its distinct values.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Any

from ..db.connection import connect
from ..views import load
from ..views.orchestrator import all_field_paths


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "audit-normalize",
        help="List distinct values per fillable field across all products "
        "to surface normalization gaps.",
    )
    p.add_argument(
        "--db",
        default="competitive.db",
        help="Path to the SQLite DB file.",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Print every filled path with its values, not just the gaps.",
    )
    p.add_argument(
        "--strings-only",
        action="store_true",
        help="Skip non-string values (numbers / booleans). Strings are where "
        "normalization issues live.",
    )
    p.set_defaults(func=main)


def main(args: argparse.Namespace) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    conn = connect(args.db)
    try:
        rows = conn.execute(
            "SELECT model_code, year FROM products ORDER BY model_code, year"
        ).fetchall()
        if not rows:
            print("(no products in DB)")
            return

        # path -> {value_repr -> [(model_code, year), ...]}
        per_path: dict[str, dict[str, list[tuple[str, int]]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for row in rows:
            product = load.load_product(conn, row[0], year=row[1])
            for _section, path, _label in all_field_paths(product):
                value = _lookup(product, path)
                if value is None:
                    continue
                if isinstance(value, dict):
                    if value.get("status") == "vendor-doesn't-publish":
                        continue
                    val = value.get("value")
                else:
                    val = value
                if val is None:
                    continue
                if args.strings_only and not isinstance(val, str):
                    continue
                key = json.dumps(val, sort_keys=True)
                per_path[path][key].append((row[0], row[1]))
    finally:
        conn.close()

    if not per_path:
        print(f"(no filled cells across {len(rows)} product(s))")
        return

    if not args.all:
        gaps = {p: v for p, v in per_path.items() if len(v) > 1}
        if not gaps:
            print(
                f"(no normalization gaps across {len(rows)} product(s); "
                f"--all to list every filled path)"
            )
            return
        target = gaps
        header = f"{len(gaps)} path(s) with more than one distinct value:"
    else:
        target = per_path
        header = f"{len(per_path)} filled path(s):"

    print(header)
    print()
    for path in sorted(target):
        values = target[path]
        print(path)
        for val_key, products in sorted(values.items(), key=lambda kv: -len(kv[1])):
            decoded = json.loads(val_key)
            print(f"  {decoded!r}  ({len(products)} product(s))")
            for mc, yr in products:
                print(f"    - {mc}-{yr}")
        print()


def _lookup(product: dict, field_path: str) -> Any:
    """Walk a dotted path within an already-loaded product dict."""
    parts = field_path.split(".")
    if len(parts) == 1:
        return product.get(parts[0])
    if len(parts) == 3:
        col, idx_s, leaf = parts
        offerings = product.get(col) or []
        try:
            idx = int(idx_s)
        except ValueError:
            return None
        if idx >= len(offerings):
            return None
        return offerings[idx].get(leaf)
    return None
