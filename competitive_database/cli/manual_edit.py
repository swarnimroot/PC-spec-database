"""``manual-edit`` CLI subcommand — write a manual cell at a dotted path.

Builds a manual-provenance bundle (status / entered_by / entered_at filled
in automatically) and writes it at ``--field`` on the named product, in
a single transaction. Prints the before/after for confirmation.

Path forms supported (see ``cli/_paths.py``):
  - Scalar bundle on products:    ``vendor_full_name``, ``audio_jack``, ...
  - Offering leaf on products:    ``display_offerings.0.nits_peak``

Catalog (plain-text) cells are not editable via ``manual-edit``; they are
not bundles and have no provenance scaffolding to apply.

The CLI surface is :func:`main`. The Phase 2 UI (``ui/edit.py``) calls
:func:`manual_edit_cell` directly with an open connection — same write
paths, same transaction discipline, no CLI shell. :func:`main` is a
thin wrapper around :func:`manual_edit_cell` that adds the argparse
plumbing, stdout reconfig, and the ``manual-edit: …`` SystemExit prefix
the tests already pin against.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any

from ..db.connection import connect, transaction
from ..db.helpers import make_manual_bundle, resolve_products_pk
from ..views import load
from ._paths import (
    format_product_pk,
    is_plain_offering_leaf,
    parse_path,
    parse_product_arg,
    read_at_path,
    write_bundle_at_path,
    write_plain_at_path,
)


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
        choices=("vouched", "needs-review", "manual"),
        default="vouched",
        help="Manual-bundle status.",
    )
    p.add_argument(
        "--source-url",
        default=None,
        help="Optional source URL persisted on the bundle (e.g. vendor spec sheet).",
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


def manual_edit_cell(
    conn: sqlite3.Connection,
    *,
    model_code: str,
    year: int | None = None,
    field_path: str,
    value: Any,
    status: str = "vouched",
    note: str | None = None,
    entered_by: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Write a manual cell at ``field_path`` on ``(model_code, year)``.

    Pure-library entry point used by both :func:`main` (CLI) and
    ``ui/edit.py`` (Phase 2 UI). Caller owns the connection — this
    function does not open or close it.

    Returns a summary dict ``{model_code, year, field_path, before,
    after}``. ``before`` and ``after`` are the pre/post reads at the
    same path: a bundle dict, a plain scalar (for plain-leaf paths
    like ``boards.N.arch_marker``), or ``None`` for an empty cell.

    Raises ``ValueError`` on user-fixable errors (bad path, catalog
    path, no matching product, ambiguous year, bad status). The CLI
    wrapper maps ``ValueError`` → ``SystemExit("manual-edit: …")``.

    ``year=None`` triggers :func:`views.load.resolve_year`, which raises
    ``ValueError`` if the model_code has zero or multiple yearly variants.
    """
    try:
        parsed = parse_path(field_path)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if parsed.kind == "catalog_text":
        raise ValueError(
            "catalog paths are not supported (catalog cells are plain "
            "text, not bundles). Use SQL directly or wait for a catalog "
            "helper."
        )

    plain_leaf = is_plain_offering_leaf(parsed)
    eb = entered_by or _default_entered_by()
    if plain_leaf:
        bundle = None
    else:
        bundle = make_manual_bundle(
            value=value,
            entered_by=eb,
            source_note=note,
            status=status,
            source_url=source_url,
        )

    if year is None:
        try:
            year = load.resolve_year(conn, model_code)
        except LookupError as exc:
            raise ValueError(str(exc)) from exc

    pk = resolve_products_pk(conn, model_code, year)

    before = read_at_path(conn, pk, parsed)
    with transaction(conn):
        if plain_leaf:
            write_plain_at_path(conn, pk, parsed, value)
        else:
            assert bundle is not None
            write_bundle_at_path(conn, pk, parsed, bundle)
    after = read_at_path(conn, pk, parsed)

    return {
        "model_code": model_code,
        "year": year,
        "field_path": field_path,
        "before": before,
        "after": after,
    }


def main(args: argparse.Namespace) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    value = _decode_value(args)

    conn = connect(args.db)
    try:
        # Accept both bare slug and the ``slug-YYYY`` display form
        # that ``refresh`` prints (Session 12 Finding #11).
        model_code, year = parse_product_arg(
            conn, args.product, year_arg=args.year
        )
        try:
            summary = manual_edit_cell(
                conn,
                model_code=model_code,
                year=year,
                field_path=args.field,
                value=value,
                status=args.status,
                note=args.note,
                entered_by=args.entered_by,
                source_url=args.source_url,
            )
        except ValueError as exc:
            raise SystemExit(f"manual-edit: {exc}") from exc
    finally:
        conn.close()

    print(
        f"manual-edit OK: {format_product_pk(summary['model_code'], summary['year'])} "
        f"{args.field}"
    )
    print(f"  before: {_fmt_bundle(summary['before'])}")
    print(f"  after:  {_fmt_bundle(summary['after'])}")


def _decode_value(args: argparse.Namespace) -> Any:
    if args.value_json is not None:
        try:
            return json.loads(args.value_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"manual-edit: --value-json is not valid JSON: {exc}") from exc
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
    if not isinstance(b, dict):
        # Plain-shape leaf (e.g. ``boards.N.arch_marker``) — no bundle
        # scaffolding to unpack.
        return f"value={b!r} (plain)"
    value = b.get("value")
    status = b.get("status")
    marker = "manual" if "entered_by" in b else "scraped"
    return f"value={value!r} status={status!r} ({marker})"
