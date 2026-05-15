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

For ``new_chip_unverified`` rows the dispatch routes off
``candidate_value`` (which encodes the catalog target) rather than
``field_path``, so depth-3 ``cpu_offerings.N.model`` and depth-4
``boards.N.gpus.M`` are handled uniformly. ``accept_candidate`` flips
the catalog row's ``catalog_status`` from ``needs-review`` to
``vouched``; ``dropped`` resolves the queue row without touching the
catalog. ``kept_existing`` / ``manual_override`` are rejected.

The CLI surface is ``main(args)``. The Phase 2 UI (``ui/triage.py``)
calls :func:`resolve_row` directly with an open connection — same
write paths, same transaction discipline, no CLI shell. ``main`` is a
thin wrapper around :func:`resolve_row` that adds the argparse plumbing,
stdout reconfig, and the ``resolve: …`` SystemExit prefix the tests
already pin against.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any

from ..db.connection import connect, transaction
from ..db.helpers import make_manual_bundle, write_offerings
from ..ingest.catalog_resolve import vouch_catalog_row
from ._paths import (
    format_product_pk,
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

# Sentinel: ``None`` is a valid manual_override value (e.g. clearing a cell
# with manual provenance), so a distinct missing-marker is needed for the
# library API to tell "no value passed" from "value=None".
_MISSING: Any = object()


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


def resolve_row(
    conn: sqlite3.Connection,
    *,
    row_id: int,
    action: str,
    value: Any = _MISSING,
    note: str | None = None,
    entered_by: str | None = None,
) -> dict[str, Any]:
    """Resolve one ``review_queue`` row inside a single transaction.

    Pure-library entry point used by both :func:`main` (CLI) and
    ``ui/triage.py`` (Phase 2 UI). Caller owns the connection — this
    function does not open or close it.

    Returns a summary dict ``{id, action, field_path, product_model_code,
    product_year, conflict_type}``. Raises ``ValueError`` on queue-row
    state issues (no such row, already resolved, action not supported
    for the row type, missing candidate payload, etc.). The CLI wrapper
    maps ``ValueError`` → ``SystemExit("resolve: …")``.

    ``value`` is required when ``action == "manual_override"`` (and the
    target isn't ``new_chip_unverified``). Pass the already-decoded
    Python value — no JSON / string coercion happens here.
    """
    if action not in _ACTIONS:
        raise ValueError(f"unknown action {action!r}")

    row = conn.execute(
        """
        SELECT id, product_model_code, product_year, field_path,
               conflict_type, existing_value, existing_provenance,
               candidate_value, candidate_provenance, resolved_at
        FROM review_queue
        WHERE id = ?
        """,
        (row_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no review_queue row with id={row_id}")
    if row["resolved_at"] is not None:
        raise ValueError(
            f"review_queue id={row_id} is already resolved "
            f"(resolved_at={row['resolved_at']})"
        )

    is_new_chip = row["conflict_type"] == "new_chip_unverified"
    if is_new_chip:
        parsed = None
    else:
        try:
            parsed = parse_path(row["field_path"])
        except ValueError as exc:
            raise ValueError(
                f"queue row id={row_id} has a field_path "
                f"shape not supported ({exc})."
            ) from exc

    pk = {
        "model_code": row["product_model_code"],
        "year": row["product_year"],
    }

    with transaction(conn):
        if is_new_chip:
            resolution_value_raw, resolver_note = _apply_action_new_chip(
                conn, row, action=action, note=note,
            )
        else:
            resolution_value_raw, resolver_note = _apply_action(
                conn, row, parsed, pk,
                action=action, note=note, value=value, entered_by=entered_by,
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
                _ACTION_TO_RESOLUTION[action],
                resolution_value_raw,
                resolver_note,
                row_id,
            ),
        )

    return {
        "id": row_id,
        "action": action,
        "field_path": row["field_path"],
        "product_model_code": row["product_model_code"],
        "product_year": row["product_year"],
        "conflict_type": row["conflict_type"],
    }


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

    if args.action == "manual_override":
        if args.value_json is not None:
            try:
                value: Any = json.loads(args.value_json)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"resolve: --value-json is not valid JSON: {exc}") from exc
        else:
            value = coerce_value_string(args.value)
    else:
        value = _MISSING

    conn = connect(args.db)
    try:
        try:
            summary = resolve_row(
                conn,
                row_id=args.id,
                action=args.action,
                value=value,
                note=args.note,
                entered_by=args.entered_by,
            )
        except ValueError as exc:
            raise SystemExit(f"resolve: {exc}") from exc
    finally:
        conn.close()

    print(
        f"resolve OK: id={summary['id']} action={summary['action']} "
        f"field={summary['field_path']} "
        f"target={format_product_pk(summary['product_model_code'], summary['product_year'])}"
    )


def _apply_action(
    conn,
    row,
    parsed,
    pk: dict,
    *,
    action: str,
    note: str | None,
    value: Any,
    entered_by: str | None,
) -> tuple[str | None, str | None]:
    """Mutate target cell per action; return (resolution_value_raw, resolver_note)."""
    if action == "accept_candidate":
        if parsed.kind == "catalog_text":
            # candidate_value column stores JSON-encoded plain text for catalog
            decoded = (
                json.loads(row["candidate_value"])
                if row["candidate_value"] is not None
                else None
            )
            # Catalog disagreement rows wrap the value as {"value": "..."}
            # (see ingest/catalog_resolve.py::_enqueue_catalog_disagreement);
            # unwrap before writing so sqlite3 receives a plain string.
            if isinstance(decoded, dict) and "value" in decoded:
                decoded = decoded["value"]
            write_catalog_text_at_path(conn, parsed, decoded)
        elif parsed.kind == "products_offering_list":
            # Column-level offering diffs: candidate_value holds the full
            # offerings list (leaves already carry their own provenance
            # bundles); candidate_provenance is NULL for this shape
            # (see ingest/runner.py::_enqueue, list-level branch).
            if row["candidate_value"] is None:
                raise ValueError(
                    "cannot accept_candidate — queue row has no candidate_value"
                )
            offerings = json.loads(row["candidate_value"])
            write_offerings(conn, "products", pk, parsed.column, offerings)
        else:
            if row["candidate_provenance"] is None:
                raise ValueError(
                    "cannot accept_candidate — queue row has no candidate_provenance"
                )
            bundle = json.loads(row["candidate_provenance"])
            write_bundle_at_path(conn, pk, parsed, bundle)
        return row["candidate_value"], note

    if action == "kept_existing":
        # No write to target; queue update only.
        return row["existing_value"], note

    if action == "manual_override":
        if parsed.kind == "products_offering_list":
            # Column-level manual_override would require constructing a
            # full list of offering dicts with embedded provenance bundles —
            # not a sensible CLI contract. Drive single-leaf edits through
            # `manual-edit` on a leaf path (<column>.<idx>.<leaf>) instead.
            raise ValueError(
                f"manual_override not supported for column-level "
                f"offering paths ({parsed.column!r}). Use manual-edit on an "
                f"offering leaf (<column>.<idx>.<leaf>) or pick "
                f"accept_candidate / kept_existing / dropped."
            )
        if value is _MISSING:
            raise ValueError("manual_override requires a value")
        if parsed.kind == "catalog_text":
            text = value if value is None or isinstance(value, str) else str(value)
            write_catalog_text_at_path(conn, parsed, text)
            return json.dumps(value), note
        bundle = make_manual_bundle(
            value=value,
            entered_by=entered_by or _default_entered_by(),
            source_note=note,
            status="vouched",
        )
        write_bundle_at_path(conn, pk, parsed, bundle)
        return json.dumps(value), note

    if action == "dropped":
        return None, note

    raise ValueError(f"unknown action {action!r}")


def _apply_action_new_chip(
    conn,
    row,
    *,
    action: str,
    note: str | None,
) -> tuple[str | None, str | None]:
    """Resolve a ``new_chip_unverified`` queue row by vouching the catalog row.

    The queue row's ``candidate_value`` carries a JSON object
    ``{"table", "model", "value"}`` pointing at the catalog stub.
    ``accept_candidate`` flips that row's ``catalog_status`` to
    ``vouched``; ``dropped`` resolves the queue row without touching
    the catalog. ``kept_existing`` and ``manual_override`` have no
    well-defined meaning here (``existing_value`` is always NULL for
    these rows) and are rejected.
    """
    if action == "accept_candidate":
        if row["candidate_value"] is None:
            raise ValueError(
                "cannot accept_candidate — new_chip_unverified row "
                "has no candidate_value"
            )
        try:
            payload = json.loads(row["candidate_value"])
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"new_chip_unverified candidate_value is not valid "
                f"JSON ({exc})"
            ) from exc
        table = payload.get("table") if isinstance(payload, dict) else None
        model = payload.get("model") if isinstance(payload, dict) else None
        if not table or not model:
            raise ValueError(
                f"new_chip_unverified candidate_value missing "
                f"'table' or 'model' (got {payload!r})"
            )
        # vouch_catalog_row already raises ValueError on bad table / missing
        # row, which propagates with the existing message.
        vouch_catalog_row(conn, table, model)
        return row["candidate_value"], note

    if action == "dropped":
        return None, note

    raise ValueError(
        f"--action {action} is not supported for "
        f"new_chip_unverified rows (existing_value is always NULL). "
        f"Use accept_candidate to vouch the catalog row, or dropped "
        f"to discard without vouching."
    )


def coerce_value_string(raw: str) -> Any:
    """Coerce a CLI-style string value to int → float → string."""
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
