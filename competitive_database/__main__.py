"""CLI entry point for ``python -m competitive_database``."""

from __future__ import annotations

import argparse

from .cli import (
    audit_normalize,
    backfill_lenovo_families,
    db_init,
    find_conflicts,
    find_empty,
    inspect_product,
    manual_edit,
    refresh,
    resolve,
    ui_launch,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="competitive_database")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("db-init", help="Initialize the SQLite DB with the full schema.")
    p_init.add_argument("--path", default="competitive.db", help="Path to the SQLite DB file.")
    p_init.set_defaults(func=db_init.main)

    refresh.add_subparser(sub)
    inspect_product.add_subparser(sub)
    find_empty.add_subparser(sub)
    find_conflicts.add_subparser(sub)
    manual_edit.add_subparser(sub)
    resolve.add_subparser(sub)
    audit_normalize.add_subparser(sub)
    backfill_lenovo_families.add_subparser(sub)
    ui_launch.add_subparser(sub)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
