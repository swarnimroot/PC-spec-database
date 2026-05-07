"""CLI entry point for ``python -m competitive_database``."""

from __future__ import annotations

import argparse

from .cli import db_init


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="competitive_database")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("db-init", help="Initialize the SQLite DB with the full schema.")
    p_init.add_argument("--path", default="competitive.db", help="Path to the SQLite DB file.")
    p_init.set_defaults(func=db_init.main)

    # Future subcommands wired in later stages:
    #   refresh, resolve, manual-edit, find-empty, find-conflicts, inspect-product

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
