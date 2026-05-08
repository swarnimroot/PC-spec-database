"""``inspect-product`` CLI subcommand.

Loads one product (by model_code, optionally disambiguated by --year),
plus the catalogs, runs the view orchestrator, and prints the result.
"""

from __future__ import annotations

import argparse
import sys

from ..db.connection import connect
from ..views import load, orchestrator
from ._paths import parse_product_arg


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "inspect-product",
        help="Print the full readable spec dump for one product.",
    )
    p.add_argument(
        "model_code",
        help="Product slug (matches products.model_code, e.g. rog-zephyrus-g16-2026).",
    )
    p.add_argument(
        "--year",
        type=int,
        help="Disambiguator if the model_code has multiple yearly variants.",
    )
    p.add_argument(
        "--db",
        default="competitive.db",
        help="Path to the SQLite DB file.",
    )
    p.set_defaults(func=main)


def main(args: argparse.Namespace) -> None:
    # The default Windows console encoding (cp1252) can't render the
    # em-dash marker [—] or the × in display resolutions. Force UTF-8
    # on this CLI's stdout so the markers come through cleanly.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    conn = connect(args.db)
    try:
        # Accept both bare slug and the ``slug-YYYY`` display form
        # that ``refresh`` prints (Session 12 Finding #11).
        model_code, year = parse_product_arg(
            conn, args.model_code, year_arg=args.year
        )
        product = load.load_product(conn, model_code, year=year)
        cpu_catalog = load.load_cpu_catalog(conn)
        gpu_catalog = load.load_gpu_catalog(conn)
    finally:
        conn.close()
    print(orchestrator.render_product(product, cpu_catalog, gpu_catalog))
