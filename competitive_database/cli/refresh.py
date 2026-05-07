"""``refresh`` CLI subcommand.

Fetches one (or, eventually, all) Dell product page(s), parses every
emitted snapshot via the bridge, and ingests each into the SQLite DB.

For Stage 2 the only supported brand is ``dell``. ``--all`` is recognized
but errors out with "not implemented yet" — the multi-vendor refresh
arrives in Stage 3+.
"""

from __future__ import annotations

import argparse
from typing import Optional

from scrapers_lib import Anchor, AttributionRegex

from ..bridge.dispatcher import dispatch
from ..db.connection import connect
from ..ingest.runner import IngestReport, ingest_product


# Default URL prefix for Alienware spd pages. Other Dell laptop families
# use different segments in the path; the user's canonical URL inserts
# the ``alienware-18-area-51-gaming-laptop`` middle segment.
DEFAULT_DELL_URL_TMPL = (
    "https://www.dell.com/en-us/shop/dell-laptops/"
    "alienware-18-area-51-gaming-laptop/spd/{slug}"
)


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "refresh",
        help="Fetch + parse + ingest a vendor product into the local DB.",
    )
    p.add_argument("--brand", required=True, help="Vendor brand. Stage 2 only supports 'dell'.")
    p.add_argument(
        "--model",
        help="URL slug after /spd/ (e.g. alienware-area-51-aa18250-gaming-laptop).",
    )
    p.add_argument(
        "--url",
        help="Override the full vendor URL. Recommended; --model fallback "
        "uses an Alienware-shaped template.",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Refresh every product configured. NOT YET IMPLEMENTED.",
    )
    p.add_argument(
        "--db",
        default="competitive.db",
        help="Path to the SQLite DB file.",
    )
    p.add_argument(
        "--profiles-dir",
        default=".profiles",
        help="Persistent browser profiles dir (Playwright stealth context).",
    )
    p.set_defaults(func=main)


def main(args: argparse.Namespace) -> None:
    if args.all:
        raise SystemExit(
            "refresh --all is not implemented yet (Stage 3+). "
            "Use --brand dell --model <slug> for now."
        )

    brand = (args.brand or "").lower()
    if brand != "dell":
        raise SystemExit(
            f"refresh: only 'dell' is supported in Stage 2, got {brand!r}"
        )

    if not (args.url or args.model):
        raise SystemExit("refresh: provide either --url or --model")

    url, slug = _resolve_dell_url(args.url, args.model)
    snapshots = _fetch_dell_snapshots(url, slug, args.profiles_dir)

    conn = connect(args.db)
    try:
        # Group all candidates by product PK so cross-tile offerings
        # union per Decision 3. In practice Dell ships several tiles
        # all targeting the same model_code+year — they should land as
        # one merged product, one transaction.
        candidates_by_pk: dict[tuple[str, int], list] = {}
        per_tile_ids: dict[tuple[str, int], list[str]] = {}
        for snapshot in snapshots:
            candidate = dispatch(snapshot)
            pk = (candidate.model_code, candidate.year)
            candidates_by_pk.setdefault(pk, []).append(candidate)
            per_tile_ids.setdefault(pk, []).append(snapshot.source_id)

        total = IngestReport()
        for pk, group in candidates_by_pk.items():
            report = ingest_product(conn, group)
            total.add(report)
            tile_str = ",".join(per_tile_ids[pk])
            print(
                f"[{pk[0]}-{pk[1]} tiles={tile_str}] "
                f"inserted={report.inserted_fields} "
                f"refreshed={report.refreshed_fields} "
                f"conflicts={report.conflicts} "
                f"low_confidence={report.low_confidence} "
                f"year_inferred={report.year_inferred} "
                f"new_cpus={len(report.new_cpus)} "
                f"new_gpus={len(report.new_gpus)}"
            )
            for note in report.notes:
                print(f"  note: {note}")
    finally:
        conn.close()

    print(
        f"refresh done: {len(snapshots)} snapshot(s) | "
        f"inserted={total.inserted_fields} refreshed={total.refreshed_fields} "
        f"conflicts={total.conflicts} low_confidence={total.low_confidence} "
        f"year_inferred={total.year_inferred} "
        f"new_cpus={len(total.new_cpus)} new_gpus={len(total.new_gpus)}"
    )


def _resolve_dell_url(
    url_arg: Optional[str], slug_arg: Optional[str]
) -> tuple[str, str]:
    if url_arg:
        slug = url_arg.rstrip("/").rsplit("/", 1)[-1]
        return url_arg, slug
    assert slug_arg is not None
    return DEFAULT_DELL_URL_TMPL.format(slug=slug_arg), slug_arg


def _fetch_dell_snapshots(url: str, slug: str, profiles_dir: str):
    """Live fetch via scrapers-lib. Imported lazily so unit tests don't
    pull in Playwright when they don't need to."""
    from scrapers_lib.tier2.dell import fetch_dell_product

    anchor = Anchor(
        anchor_id=slug,
        anchor_type="product",
        name=slug,
        attribution_regex=AttributionRegex(primary=[slug]),
        source_urls={"dell": url},
    )
    return fetch_dell_product(
        url, anchors=[anchor], profiles_dir=profiles_dir, warm=True
    )
