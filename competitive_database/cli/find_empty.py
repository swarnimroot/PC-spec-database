"""``find-empty`` CLI subcommand — list empty + ``vendor-doesn't-publish``
cells across one product, grouped by section.

Section headings + leaf paths come from each view module's
``field_paths(product)`` helper, so the output groups match
``inspect-product``'s 16-section structure.
"""

from __future__ import annotations

import argparse
import sys

from ..db.connection import connect
from ..views import load
from ..views.orchestrator import all_field_paths


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "find-empty",
        help="List empty + vendor-doesn't-publish cells per product.",
    )
    p.add_argument(
        "--product",
        help="Product slug (matches products.model_code). Required unless --all.",
    )
    p.add_argument(
        "--year",
        type=int,
        help="Disambiguator if the model_code has multiple yearly variants.",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Walk every product in the DB. --product / --year are ignored.",
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

    if not args.all and not args.product:
        raise SystemExit("find-empty: provide --product <slug> or --all")

    conn = connect(args.db)
    try:
        if args.all:
            rows = conn.execute(
                "SELECT model_code, year FROM products ORDER BY model_code, year"
            ).fetchall()
            blocks: list[str] = []
            for row in rows:
                product = load.load_product(conn, row[0], year=row[1])
                blocks.append(_render_product_block(product))
            print("\n\n".join(blocks))
        else:
            product = load.load_product(conn, args.product, year=args.year)
            print(_render_product_block(product))
    finally:
        conn.close()


def _classify(value) -> str | None:
    """Return ``"empty"`` / ``"vendor doesn't publish"`` / None (filled)."""
    if value is None:
        return "empty"
    # bundles carry status; ``vendor-doesn't-publish`` is the only filled-but-unset state
    if isinstance(value, dict) and value.get("status") == "vendor-doesn't-publish":
        return "vendor doesn't publish"
    return None


def _render_product_block(product: dict) -> str:
    model_code = product.get("model_code", "?")
    year = product.get("year", "?")
    paths = all_field_paths(product)

    sections: dict[str, list[tuple[str, str]]] = {}
    section_order: list[str] = []
    empty_count = 0
    vdp_count = 0

    for section, path, label in paths:
        # Resolve the current value by walking the loaded product dict
        value = _lookup(product, path)
        state = _classify(value)
        if state is None:
            continue
        if section not in sections:
            sections[section] = []
            section_order.append(section)
        sections[section].append((label, state))
        if state == "empty":
            empty_count += 1
        else:
            vdp_count += 1

    out = [f"{model_code} ({year})"]
    if not section_order:
        out.append("")
        out.append("(no empty or vendor-doesn't-publish cells)")
        return "\n".join(out)

    for section in section_order:
        out.append("")
        out.append(section)
        for label, state in sections[section]:
            out.append(f"  - {label}: {state}")

    total = empty_count + vdp_count
    summary = f"{total} missing across {len(section_order)} section(s)"
    if vdp_count:
        summary += f" ({empty_count} empty, {vdp_count} vendor-doesn't-publish)"
    out.append("")
    out.append(summary)
    return "\n".join(out)


def _lookup(product: dict, field_path: str):
    """Walk a dotted path within an already-loaded product dict.

    Mirrors ``cli._paths.parse_path`` for the products-scoped subset:
      - ``<col>``                 → product[col]
      - ``<col>.<idx>.<leaf>``    → product[col][idx][leaf]  (idx in range)

    Catalog paths are not used by find-empty; if encountered, returns None.
    """
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
