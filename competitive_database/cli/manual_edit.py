"""``manual-edit`` CLI subcommand — write a manual cell at a dotted path.

Builds a manual-provenance bundle (status / entered_by / entered_at filled
in automatically) and writes it at ``--field`` on the named product, in
a single transaction. Prints the before/after for confirmation.

Path forms supported (see ``cli/_paths.py``):
  - Scalar bundle on products:    ``vendor_full_name``, ``audio_jack``, ...
  - Offering leaf on products:    ``display_offerings.0.nits_peak``

Catalog (plain-text) cells are not editable via ``manual-edit``; they are
not bundles and have no provenance scaffolding to apply.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from ..db.connection import connect, transaction
from ..db.helpers import make_manual_bundle
from ..views import load
from ._paths import parse_path, read_at_path, write_bundle_at_path


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "manual-edit",
        help="Write a manual cell with provenance scaffolding.",
    )
    p.add_argument(
        "--product",
        required=True,
        help="Product slug (matches products.model_code).",
    )
    p.add_argument(
        "--year",
        type=int,
        help="Disambiguator if the model_code has multiple yearly variants.",
    )
    p.add_argument(
        "--field",
        required=True,
        help=(
            "Dotted field path. Examples: 'audio_jack' (scalar), "
            "'display_offerings.0.nits_peak' (offering leaf)."
        ),
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--value",
        help="Cell value. Coerced int -> float -> string. Use --value-json for booleans / null / lists.",
    )
    g.add_argument(
        "--value-json",
        help="Cell value as a JSON literal (e.g. 'true', 'null', '[1,2]').",
    )
    p.add_argument(
        "--note",
        default=None,
        help="Free-form source note (stored as bundle 'source_note').",
    )
    p.add_argument(
        "--status",
        choices=("vouched", "needs-review"),
        default="vouched",
        help="Manual-bundle status.",
    )
    p.add_argument(
        "--entered-by",
        default=None,
        help="Override the bundle 'entered_by' field (default: $USER / $USERNAME).",
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

    try:
        parsed = parse_path(args.field)
    except ValueError as exc:
        raise SystemExit(f"manual-edit: {exc}") from exc
    if parsed.kind == "catalog_text":
        raise SystemExit(
            "manual-edit does not support catalog paths (catalog cells "
            "are plain text, not bundles). Use SQL directly or wait for a "
            "catalog helper."
        )

    value = _decode_value(args)
    entered_by = args.entered_by or _default_entered_by()
    bundle = make_manual_bundle(
        value=value,
        entered_by=entered_by,
        source_note=args.note,
        status=args.status,
    )

    conn = connect(args.db)
    try:
        year = args.year
        if year is None:
            year = load.resolve_year(conn, args.product)
        pk = {"model_code": args.product, "year": year}

        before = read_at_path(conn, pk, parsed)
        with transaction(conn):
            write_bundle_at_path(conn, pk, parsed, bundle)
        after = read_at_path(conn, pk, parsed)
    finally:
        conn.close()

    print(f"manual-edit OK: {args.product}-{year} {args.field}")
    print(f"  before: {_fmt_bundle(before)}")
    print(f"  after:  {_fmt_bundle(after)}")


def _decode_value(args: argparse.Namespace) -> Any:
    if args.value_json is not None:
        try:
            return json.loads(args.value_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--value-json is not valid JSON: {exc}") from exc
    raw: str = args.value
    # Try int, then float, else keep as string.
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _default_entered_by() -> str:
    return (
        os.environ.get("USER")
        or os.environ.get("USERNAME")
        or "unknown"
    )


def _fmt_bundle(b) -> str:
    if b is None:
        return "(empty)"
    value = b.get("value")
    status = b.get("status")
    marker = "manual" if "entered_by" in b else "scraped"
    return f"value={value!r} status={status!r} ({marker})"
