"""``resolve`` CLI subcommand — single-transaction resolution of one
``review_queue`` row.

Four actions:

  - ``accept_candidate``: write the candidate bundle (or catalog text) to
    the target cell, mark queue row resolved with the candidate value.
  - ``kept_existing``: leave the target cell alone, mark queue row
    resolved with the existing value.
  - ``manual_override``: build a manual bundle (or catalog text) from
    ``--value`` / ``--value-json`` + ``--note`` and write it; mark queue
    row resolved with the new value.
  - ``dropped``: leave the target cell alone, mark queue row resolved
    with no value (the conflict is intentionally discarded).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from ..db.connection import connect, transaction
from ..db.helpers import make_manual_bundle
from ._paths import (
    parse_path,
    write_bundle_at_path,
    write_catalog_text_at_path,
)


_ACTIONS = ("accept_candidate", "kept_existing", "manual_override", "dropped")

# The DB column ``resolution`` uses the past-tense form for accept_candidate.
_ACTION_TO_RESOLUTION = {
    "accept_candidate": "accepted_candidate",
    "kept_existing": "kept_existing",
    "manual_override": "manual_override",
    "dropped": "dropped",
}


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "resolve",
        help="Resolve one review_queue row in a single transaction.",
    )
    p.add_argument(
        "--id",
        required=True,
        type=int,
        help="review_queue.id of the row to resolve.",
    )
    p.add_argument(
        "--action",
        required=True,
        choices=_ACTIONS,
        help="Resolution action.",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--value",
        help=(
            "Value for --action manual_override. Coerced int -> float -> string. "
            "Use --value-json for booleans / null / lists."
        ),
    )
    g.add_argument(
        "--value-json",
        help="Value for --action manual_override as a JSON literal.",
    )
    p.add_argument(
        "--note",
        default=None,
        help="Free-form resolver note (stored on the queue row; also used "
        "as the bundle source_note for manual_override).",
    )
    p.add_argument(
        "--entered-by",
        default=None,
        help="Override the bundle 'entered_by' for manual_override "
        "(default: $USER / $USERNAME).",
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

    if args.action == "manual_override" and args.value is None and args.value_json is None:
        raise SystemExit("resolve: --action manual_override requires --value or --value-json")
    if args.action != "manual_override" and (args.value is not None or args.value_json is not None):
        raise SystemExit(
            f"resolve: --value / --value-json is only valid with --action manual_override "
            f"(got --action {args.action})"
        )

    conn = connect(args.db)
    try:
        row = conn.execute(
            """
            SELECT id, product_model_code, product_year, field_path,
                   conflict_type, existing_value, existing_provenance,
                   candidate_value, candidate_provenance, resolved_at
            FROM review_queue
            WHERE id = ?
            """,
            (args.id,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"resolve: no review_queue row with id={args.id}")
        if row["resolved_at"] is not None:
            raise SystemExit(
                f"resolve: review_queue id={args.id} is already resolved "
                f"(resolved_at={row['resolved_at']})"
            )

        try:
            parsed = parse_path(row["field_path"])
        except ValueError as exc:
            raise SystemExit(
                f"resolve: queue row id={args.id} has a field_path "
                f"shape not supported by Stage 5 ({exc}). "
                f"new_chip_unverified rows over 4-level paths "
                f"(e.g. boards.N.gpus.M) need the catalog-vouching "
                f"workflow (deferred to a later stage)."
            ) from exc
        pk = {
            "model_code": row["product_model_code"],
            "year": row["product_year"],
        }

        with transaction(conn):
            resolution_value_raw, resolver_note = _apply_action(
                conn, args, row, parsed, pk
            )
            conn.execute(
                """
                UPDATE review_queue
                SET resolved_at = ?,
                    resolution = ?,
                    resolution_value = ?,
                    resolver_note = ?
                WHERE id = ?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    _ACTION_TO_RESOLUTION[args.action],
                    resolution_value_raw,
                    resolver_note,
                    args.id,
                ),
            )
    finally:
        conn.close()

    print(
        f"resolve OK: id={args.id} action={args.action} "
        f"field={row['field_path']} "
        f"target={row['product_model_code']}-{row['product_year']}"
    )


def _apply_action(
    conn,
    args: argparse.Namespace,
    row,
    parsed,
    pk: dict,
) -> tuple[str | None, str | None]:
    """Mutate target cell per action; return (resolution_value_raw, resolver_note)."""
    action = args.action
    note = args.note

    if action == "accept_candidate":
        if parsed.kind == "catalog_text":
            # candidate_value column stores JSON-encoded plain text for catalog
            decoded = (
                json.loads(row["candidate_value"])
                if row["candidate_value"] is not None
                else None
            )
            write_catalog_text_at_path(conn, parsed, decoded)
        else:
            if row["candidate_provenance"] is None:
                raise SystemExit(
                    "resolve: cannot accept_candidate — queue row has no candidate_provenance"
                )
            bundle = json.loads(row["candidate_provenance"])
            write_bundle_at_path(conn, pk, parsed, bundle)
        return row["candidate_value"], note

    if action == "kept_existing":
        # No write to target; queue update only.
        return row["existing_value"], note

    if action == "manual_override":
        value = _decode_value(args)
        if parsed.kind == "catalog_text":
            text = value if value is None or isinstance(value, str) else str(value)
            write_catalog_text_at_path(conn, parsed, text)
            return json.dumps(value), note
        bundle = make_manual_bundle(
            value=value,
            entered_by=args.entered_by or _default_entered_by(),
            source_note=note,
            status="vouched",
        )
        write_bundle_at_path(conn, pk, parsed, bundle)
        return json.dumps(value), note

    if action == "dropped":
        return None, note

    raise SystemExit(f"resolve: unknown action {action!r}")


def _decode_value(args: argparse.Namespace) -> Any:
    if args.value_json is not None:
        try:
            return json.loads(args.value_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--value-json is not valid JSON: {exc}") from exc
    raw: str = args.value
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
