"""``find-conflicts`` CLI subcommand — list unresolved ``review_queue`` rows.

A queue row is unresolved iff ``resolved_at IS NULL``. Output is one line
per row with id, product PK, conflict type, field path, and a one-glance
summary of the existing vs. candidate values.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..db.connection import connect
from ._paths import format_product_pk, parse_product_arg


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "find-conflicts",
        help="List unresolved review_queue rows.",
    )
    p.add_argument(
        "--product",
        help="Filter to one product slug (matches review_queue.product_model_code).",
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
        if args.product:
            # Accept both bare slug and the ``slug-YYYY`` display form
            # that ``refresh`` prints (Session 12 Finding #11). When the
            # year is recovered from the suffix, narrow the filter to
            # that year too.
            model_code, year = parse_product_arg(conn, args.product)
            if year is not None:
                rows = conn.execute(
                    """
                    SELECT id, product_model_code, product_year, field_path,
                           conflict_type, existing_value, candidate_value, detected_at
                    FROM review_queue
                    WHERE resolved_at IS NULL
                      AND product_model_code = ?
                      AND product_year = ?
                    ORDER BY id
                    """,
                    (model_code, year),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, product_model_code, product_year, field_path,
                           conflict_type, existing_value, candidate_value, detected_at
                    FROM review_queue
                    WHERE resolved_at IS NULL AND product_model_code = ?
                    ORDER BY id
                    """,
                    (model_code,),
                ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, product_model_code, product_year, field_path,
                       conflict_type, existing_value, candidate_value, detected_at
                FROM review_queue
                WHERE resolved_at IS NULL
                ORDER BY id
                """
            ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("(no unresolved conflicts)")
        return

    print(f"{len(rows)} unresolved conflict(s):")
    print()
    for row in rows:
        existing = _summarize(row["existing_value"])
        candidate = _summarize(row["candidate_value"])
        pk_label = format_product_pk(row["product_model_code"], row["product_year"])
        print(
            f"  #{row['id']}  {pk_label}  "
            f"{row['conflict_type']}"
        )
        print(f"      field:     {row['field_path']}")
        print(f"      existing:  {existing}")
        print(f"      candidate: {candidate}")
        print(f"      detected:  {row['detected_at']}")
        print()


def _summarize(raw: str | None) -> str:
    """One-line repr of a JSON-encoded value column. None / 'null' / missing → '(none)'."""
    if raw is None:
        return "(none)"
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if decoded is None:
        return "(none)"
    if isinstance(decoded, (str, int, float, bool)):
        return repr(decoded)
    return json.dumps(decoded, separators=(",", ":"))
