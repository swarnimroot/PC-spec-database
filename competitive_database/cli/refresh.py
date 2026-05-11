"""``refresh`` CLI subcommand.

Fetches one (or, eventually, all) vendor product page(s), parses every
emitted snapshot via the bridge, and ingests each into the SQLite DB.

Stage 3 supports ``dell``, ``hp``, ``lenovo``, and ``asus``. ``--all`` is
recognized but errors out with "not implemented yet" — multi-vendor
whole-catalog refresh is deferred until later stages.
"""

from __future__ import annotations

import argparse
from typing import Callable, Optional

from scrapers_lib import Anchor, AttributionRegex

from ..bridge.dispatcher import dispatch
from ..db.connection import connect
from ..ingest.runner import IngestReport, ingest_product
from ._paths import format_product_pk


# Default URL prefix for Alienware spd pages. Other Dell laptop families
# use different segments in the path; the user's canonical URL inserts
# the ``alienware-18-area-51-gaming-laptop`` middle segment.
DEFAULT_DELL_URL_TMPL = (
    "https://www.dell.com/en-us/shop/dell-laptops/"
    "alienware-18-area-51-gaming-laptop/spd/{slug}"
)

# Default URL template for HP shop PDPs. Slugs land directly under
# ``/us-en/shop/pdp/`` — no per-family middle segment like Dell.
DEFAULT_HP_URL_TMPL = "https://www.hp.com/us-en/shop/pdp/{slug}"

# Default URL template for Lenovo PSREF product pages. Slugs are the
# PSREF ProductKey segment (e.g. ``Legion_Pro_7_16AFR10H``); the line
# segment is required by PSREF's URL shape but is informational — we
# default it to ``Legion`` since the only gaming line we currently
# target lives there. Override with ``--url`` for any other line.
DEFAULT_LENOVO_URL_TMPL = (
    "https://psref.lenovo.com/l/Product/Legion/{slug}?tab=spec"
)

# Default URL template for ASUS ROG marketing spec pages. Slugs are
# kebab-case ``rog-<line>-<model>-<year>`` (e.g.
# ``rog-zephyrus-g16-2026``, ``rog-strix-g18-2026``). The path requires
# the regional ``/us/`` prefix, the gaming-line segment
# (``rog-zephyrus`` / ``rog-strix`` / ``rog-flow`` / ...), and the
# trailing ``/spec/`` to land on the spec sheet directly. Override
# ``--url`` for any product where the line segment differs.
DEFAULT_ASUS_URL_TMPL = (
    "https://rog.asus.com/us/laptops/rog-zephyrus/{slug}/spec/"
)


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "refresh",
        help="Fetch + parse + ingest a vendor product into the local DB.",
    )
    p.add_argument(
        "--brand",
        required=True,
        help="Vendor brand. Stage 3 supports 'dell', 'hp', 'lenovo', and 'asus'.",
    )
    p.add_argument(
        "--model",
        help=(
            "URL slug (Dell: after /spd/; HP: after /pdp/; "
            "Lenovo: PSREF ProductKey, e.g. Legion_Pro_7_16AFR10H; "
            "ASUS: ROG slug, e.g. rog-zephyrus-g16-2026)."
        ),
    )
    p.add_argument(
        "--url",
        help="Override the full vendor URL. Recommended; --model fallback "
        "uses a per-vendor template.",
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


# Per-vendor (URL template, fetcher) registry. Fetchers are referenced by
# name and imported lazily inside ``_fetch_snapshots`` so unit tests don't
# pull in the live HTTP stack when they don't need to.
_VENDOR_TEMPLATES: dict[str, str] = {
    "dell": DEFAULT_DELL_URL_TMPL,
    "hp": DEFAULT_HP_URL_TMPL,
    "lenovo": DEFAULT_LENOVO_URL_TMPL,
    "asus": DEFAULT_ASUS_URL_TMPL,
}


def main(args: argparse.Namespace) -> None:
    if args.all:
        raise SystemExit(
            "refresh --all is not implemented yet (Stage 3+). "
            "Use --brand <vendor> --model <slug> for now."
        )

    brand = (args.brand or "").lower()
    if brand not in _VENDOR_TEMPLATES:
        raise SystemExit(
            f"refresh: brand {brand!r} is not supported; "
            f"known: {sorted(_VENDOR_TEMPLATES)}"
        )

    if not (args.url or args.model):
        raise SystemExit("refresh: provide either --url or --model")

    url, slug = _resolve_url(brand, args.url, args.model)
    snapshots = _fetch_snapshots(brand, url, slug, args.profiles_dir)

    conn = connect(args.db)
    try:
        # Group all candidates by product PK so cross-tile offerings
        # union per Decision 3. In practice Dell ships several tiles
        # all targeting the same model_code+year — they should land as
        # one merged product, one transaction.
        #
        # Lenovo Intel/AMD merge (Stage 7 T7.0a M4): when a candidate
        # carries ``family_code`` (Lenovo only, and only when the slug
        # parser produced one), the merged row uses ``family_code`` as
        # its canonical ``model_code``. The original Lenovo machine code
        # is preserved in ``source_model_codes``. This keeps the
        # ``(model_code, year)`` PK intact and lets the runner stay
        # generic — by the time it sees a group, every member already
        # shares the coerced PK.
        candidates_by_pk: dict[tuple[str, int], list] = {}
        per_tile_ids: dict[tuple[str, int], list[str]] = {}
        for snapshot in snapshots:
            candidate = dispatch(snapshot)
            if candidate.family_code is not None:
                # Coerce model_code to the shared family_code so all
                # Intel/AMD variants of the same Lenovo platform group
                # under one PK. The original machine code is already
                # captured in source_model_codes by the bridge.
                candidate.model_code = candidate.family_code
            pk = (candidate.model_code, candidate.year)
            candidates_by_pk.setdefault(pk, []).append(candidate)
            per_tile_ids.setdefault(pk, []).append(snapshot.source_id)

        total = IngestReport()
        for pk, group in candidates_by_pk.items():
            report = ingest_product(conn, group)
            total.add(report)
            tile_str = ",".join(per_tile_ids[pk])
            print(
                f"[{format_product_pk(pk[0], pk[1])} tiles={tile_str}] "
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


def _resolve_url(
    brand: str, url_arg: Optional[str], slug_arg: Optional[str]
) -> tuple[str, str]:
    if url_arg:
        url = _coerce_vendor_url(brand, url_arg)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return url, slug
    assert slug_arg is not None
    template = _VENDOR_TEMPLATES[brand]
    return template.format(slug=slug_arg), slug_arg


def _coerce_vendor_url(brand: str, url: str) -> str:
    """Apply per-vendor URL normalizations.

    ASUS ROG spec pages require a trailing ``/spec/`` subpath; landing-
    page URLs without it cause the fetcher to fail. Auto-append it so
    users can paste either form.
    """
    if brand == "asus":
        path = url.rstrip("/")
        if path.endswith("/spec"):
            return path + "/"
        return path + "/spec/"
    return url


def _fetch_snapshots(brand: str, url: str, slug: str, profiles_dir: str):
    """Live fetch via scrapers-lib. Per-vendor fetchers imported lazily so
    unit tests don't pull in Playwright / curl_cffi when they don't need to."""
    anchor = Anchor(
        anchor_id=slug,
        anchor_type="product",
        name=slug,
        attribution_regex=AttributionRegex(primary=[slug]),
        source_urls={brand: url},
    )
    if brand == "dell":
        from scrapers_lib.tier2.dell import fetch_dell_product

        return fetch_dell_product(
            url, anchors=[anchor], profiles_dir=profiles_dir, warm=True
        )
    if brand == "hp":
        from scrapers_lib.tier2.hp import fetch_hp_product

        # The HP fetcher uses curl_cffi rather than Playwright and does
        # not need a profiles_dir; it is accepted on the CLI for parity
        # with Dell but ignored here.
        return fetch_hp_product(url, anchors=[anchor], warm=True)
    if brand == "lenovo":
        from scrapers_lib.tier2.lenovo import fetch_lenovo_product

        # Lenovo's PSREF endpoint is a plain JSON API — no Playwright,
        # no curl_cffi, no profiles_dir, no warm-up. The fetcher accepts
        # only the keyword args it needs.
        return fetch_lenovo_product(url, anchors=[anchor])
    if brand == "asus":
        from scrapers_lib.tier2.asus import fetch_asus_product

        # ASUS's ROG marketing spec page is plain HTML over httpx — no
        # Playwright, no curl_cffi, no profiles_dir, no warm-up. The
        # fetcher accepts ``url`` + ``anchors`` (+ ``timeout`` kw).
        return fetch_asus_product(url, anchors=[anchor])
    raise SystemExit(
        f"refresh: brand {brand!r} has no fetcher wired in; "
        f"known: {sorted(_VENDOR_TEMPLATES)}"
    )
