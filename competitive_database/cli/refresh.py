"""``refresh`` CLI subcommand + library entry points.

Fetches one (or all) vendor product page(s), parses every emitted snapshot
via the bridge, and ingests each into the SQLite DB.

Stage 3 wired up ``dell``, ``hp``, ``lenovo``, and ``asus``. Stage 8 T8.7
adds :func:`refresh_all_products` (the wire behind ``--all``) which loops
every product in the DB whose ``brand`` bundle resolves to a supported
vendor and whose row carries at least one stored scraped ``source_url``.

Single-product URL modes (Stage 7 T7.4 surface, unchanged):
  - per-vendor ``DEFAULT_*_URL_TMPL`` formatting (slug given as ``--model``)
  - explicit ``--url`` override
  - ``--from-db`` — read each product's stored ``source_url`` from bundle
    provenance and loop the fetch across every distinct URL on the row
    (handles Lenovo Intel+AMD merged products naturally).

The CLI surface is :func:`main`. The Phase 2 UI (``ui/refresh.py``) calls
:func:`refresh_product` and :func:`refresh_all_products` directly with an
open connection — same fetch / dispatch / ingest pipeline, no CLI shell.
Both lib fns accept an ``on_step`` callback that fires at every phase
transition (URL resolution, fetch start/done, dispatch, per-PK ingest,
complete) so callers can stream progress to the user.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any, Callable, Optional

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

# ASUS TUF spec pages live on ``www.asus.com`` (not ``rog.asus.com``)
# under ``for-gaming/tuf-gaming`` with a trailing ``/techspec/``. Slugs
# are the full model_code verbatim — including disambiguator suffixes
# (e.g. ``asus-tuf-gaming-a14-2026-fa401ea``) — verified against every
# stored TUF source_url in the DB.
DEFAULT_ASUS_TUF_URL_TMPL = (
    "https://www.asus.com/us/laptops/for-gaming/tuf-gaming/{slug}/techspec/"
)

# ASUS V16 spec pages also live on ``www.asus.com`` but under the
# ``for-gaming/all-series`` segment. Pattern observed on the single
# stored V16 source_url (``asus-v16-v3607``); widen the prefix below if
# future V-series products confirm the same shape.
DEFAULT_ASUS_V16_URL_TMPL = (
    "https://www.asus.com/us/laptops/for-gaming/all-series/{slug}/techspec/"
)


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "refresh",
        help="Fetch + parse + ingest a vendor product into the local DB.",
    )
    p.add_argument(
        "--brand",
        help=(
            "Vendor brand. Stage 3 supports 'dell', 'hp', 'lenovo', and "
            "'asus'. Required unless --all (which reads each product's "
            "brand from the DB)."
        ),
    )
    p.add_argument(
        "--model",
        help=(
            "URL slug (Dell: after /spd/; HP: after /pdp/; "
            "Lenovo: PSREF ProductKey, e.g. Legion_Pro_7_16AFR10H; "
            "ASUS: full model_code, e.g. rog-zephyrus-g16-2026 or "
            "asus-tuf-gaming-f16-2025 — series picks the template)."
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
        help=(
            "Refresh every product in the DB whose brand is a supported "
            "vendor and whose row carries at least one stored source_url. "
            "Uses each product's --from-db URLs. Per-product errors are "
            "collected and reported; the loop does not stop on one failure."
        ),
    )
    p.add_argument(
        "--from-db",
        action="store_true",
        dest="from_db",
        help=(
            "Read source_url(s) for this product from the local DB instead "
            "of formatting via the per-vendor URL template. Requires "
            "--model; use --year if the model has multiple yearly variants. "
            "Mutually exclusive with --url."
        ),
    )
    p.add_argument(
        "--year",
        type=int,
        help=(
            "Disambiguator for --from-db when --model has multiple yearly "
            "variants in the DB."
        ),
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


# Per-vendor URL template registry. Fetchers are imported lazily inside
# ``_fetch_snapshots`` so unit tests don't pull in the live HTTP stack
# when they don't need to. Phase G (Stage 10a) lifted this to a public
# name so the UI can plan refresh batches without importing a private
# helper; ``_VENDOR_TEMPLATES`` is kept as a back-compat alias for
# existing callers.
VENDOR_TEMPLATES: dict[str, str] = {
    "dell": DEFAULT_DELL_URL_TMPL,
    "hp": DEFAULT_HP_URL_TMPL,
    "lenovo": DEFAULT_LENOVO_URL_TMPL,
    "asus": DEFAULT_ASUS_URL_TMPL,
}


# ASUS spans two hosts with per-series path shapes, so a single
# ``VENDOR_TEMPLATES["asus"]`` entry can't cover every line. Template-mode
# URL resolution dispatches on the model_code (slug) prefix — first match
# wins; slugs matching no prefix fall back to ``VENDOR_TEMPLATES["asus"]``
# (the ROG template), which preserves the pre-dispatch behavior. Add new
# series here as their stored source_url pattern is confirmed in the DB.
ASUS_SERIES_TEMPLATES: dict[str, str] = {
    "rog-": DEFAULT_ASUS_URL_TMPL,
    "asus-tuf-gaming-": DEFAULT_ASUS_TUF_URL_TMPL,
    "asus-v16-": DEFAULT_ASUS_V16_URL_TMPL,
}


# --- Library entry points ------------------------------------------------


def _fetch_and_group(
    brand: str,
    urls: list[str],
    profiles_dir: str,
    emit: Callable[[dict[str, Any]], None],
) -> tuple[list[Any], dict[tuple[str, int], list], dict[tuple[str, int], list[str]]]:
    """Fetch + dispatch + group — the PURE (no-DB) core shared by
    :func:`refresh_product` and :func:`scrape_only`.

    Walks every URL, fetches its snapshots, dispatches each snapshot to the
    bridge, and groups the resulting candidates by ``(model_code, year)`` PK
    so cross-tile offerings union per Decision 3. Lenovo Intel/AMD merge
    (Stage 7 T7.0a M4): when a candidate carries ``family_code`` the merged
    row uses ``family_code`` as canonical ``model_code``; the original Lenovo
    machine code is preserved in ``source_model_codes`` by the bridge.

    ``emit`` fires the fetch/dispatch phase events; pass a no-op for callers
    that don't stream progress. No SQLite is touched.

    Returns ``(snapshots, candidates_by_pk, per_tile_ids)``.
    """
    snapshots: list[Any] = []
    for u in urls:
        coerced = _coerce_vendor_url(brand, u)
        slug = coerced.rstrip("/").rsplit("/", 1)[-1]
        emit({"phase": "fetch", "status": "start", "url": coerced})
        fetched = list(_fetch_snapshots(brand, coerced, slug, profiles_dir))
        snapshots.extend(fetched)
        emit({
            "phase": "fetch",
            "status": "done",
            "url": coerced,
            "snapshot_count": len(fetched),
        })

    emit({"phase": "dispatch", "status": "start"})
    candidates_by_pk: dict[tuple[str, int], list] = {}
    per_tile_ids: dict[tuple[str, int], list[str]] = {}
    for snapshot in snapshots:
        candidate = dispatch(snapshot)
        if candidate.family_code is not None:
            candidate.model_code = candidate.family_code
        pk = (candidate.model_code, candidate.year)
        candidates_by_pk.setdefault(pk, []).append(candidate)
        per_tile_ids.setdefault(pk, []).append(snapshot.source_id)
    emit({
        "phase": "dispatch",
        "status": "done",
        "pks": [list(pk) for pk in candidates_by_pk.keys()],
    })
    return snapshots, candidates_by_pk, per_tile_ids


def scrape_only(
    *,
    brand: str,
    url: str,
    profiles_dir: str = ".profiles",
) -> list[list[Any]]:
    """Fetch + parse one vendor URL WITHOUT touching the DB.

    Pure phase-1 of :func:`refresh_product`: resolves/coerces the URL,
    fetches snapshots, dispatches them through the bridge, and groups the
    resulting :class:`~competitive_database.bridge.types.CandidateProduct`
    objects by ``(model_code, year)`` PK (same grouping ``refresh_product``
    uses). Returns one candidate group (list) per PK — exactly the
    ``group`` value the runner's :func:`ingest_product` consumes — so an
    "Add product" flow can preview before writing.

    No connection, no writes, no ``review_queue`` side effects. Raises
    ``ValueError`` on an unsupported brand; vendor-side failures (network,
    parser) bubble up unchanged.
    """
    brand_l = (brand or "").lower()
    if brand_l not in VENDOR_TEMPLATES:
        raise ValueError(
            f"brand {brand!r} is not supported; "
            f"known: {sorted(VENDOR_TEMPLATES)}"
        )
    single_url, _slug = _resolve_url(brand_l, url, None)
    _snaps, candidates_by_pk, _tiles = _fetch_and_group(
        brand_l, [single_url], profiles_dir, lambda _event: None
    )
    return list(candidates_by_pk.values())


def refresh_product(
    conn: sqlite3.Connection,
    *,
    brand: str,
    model: Optional[str] = None,
    url: Optional[str] = None,
    from_db: bool = False,
    year: Optional[int] = None,
    profiles_dir: str = ".profiles",
    on_step: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Refresh one vendor product. Pure-library entry point.

    Validates args, resolves URL(s) (template / explicit / from-db),
    fetches snapshots, dispatches them to the bridge, groups candidates
    by ``(model_code, year)`` PK, and calls
    :func:`competitive_database.ingest.runner.ingest_product` per group.

    Caller owns ``conn``. Raises ``ValueError`` on user-fixable errors
    (unknown brand, invalid mode combo, no URLs collected). Vendor-side
    failures (network, parser) bubble up unchanged so callers can
    distinguish "user fix" from "vendor / infra problem".

    ``on_step`` (when provided) fires at every phase transition with a
    dict carrying ``phase`` plus contextual fields (urls, pk, tiles, count,
    ingest figures). The Phase 2 UI uses it to stream live progress; the
    CLI wrapper uses it to print the per-tile lines.

    Returns a summary dict with overall totals + per-PK reports.
    """
    def emit(event: dict[str, Any]) -> None:
        if on_step is not None:
            on_step(event)

    brand_l = (brand or "").lower()
    if brand_l not in VENDOR_TEMPLATES:
        raise ValueError(
            f"brand {brand!r} is not supported; "
            f"known: {sorted(VENDOR_TEMPLATES)}"
        )

    if from_db:
        if url is not None:
            raise ValueError("--from-db is mutually exclusive with --url")
        if not model:
            raise ValueError("--from-db requires --model")
    else:
        if not (url or model):
            raise ValueError("provide either --url or --model")

    if from_db:
        assert model is not None
        urls = collect_source_urls_from_product(
            conn, model_code=model, year=year
        )
        if not urls:
            year_str = f" year={year}" if year is not None else ""
            raise ValueError(
                f"from-db: no scraped source_urls found for "
                f"model_code={model!r}{year_str} "
                f"(product may be manual-only, or missing from DB)"
            )
        mode = "from_db"
    else:
        single_url, _slug = _resolve_url(brand_l, url, model)
        urls = [single_url]
        mode = "url" if url else "template"

    emit({"phase": "resolve_url", "mode": mode, "urls": list(urls)})

    snapshots, candidates_by_pk, per_tile_ids = _fetch_and_group(
        brand_l, urls, profiles_dir, emit
    )

    total = IngestReport()
    per_pk_reports: list[dict[str, Any]] = []
    for pk, group in candidates_by_pk.items():
        tiles = list(per_tile_ids[pk])
        emit({
            "phase": "ingest",
            "status": "start",
            "pk": list(pk),
            "tiles": tiles,
        })
        report = ingest_product(conn, group)
        total.add(report)
        pk_summary = {
            "pk": list(pk),
            "tiles": tiles,
            "inserted_fields": report.inserted_fields,
            "refreshed_fields": report.refreshed_fields,
            "conflicts": report.conflicts,
            "low_confidence": report.low_confidence,
            "year_inferred": report.year_inferred,
            "new_cpus": list(report.new_cpus),
            "new_gpus": list(report.new_gpus),
            "notes": list(report.notes),
        }
        per_pk_reports.append(pk_summary)
        emit({"phase": "ingest", "status": "done", **pk_summary})

    summary = {
        "brand": brand_l,
        "mode": mode,
        "urls": list(urls),
        "snapshot_count": len(snapshots),
        "pks": [list(pk) for pk in candidates_by_pk.keys()],
        "totals": {
            "inserted_fields": total.inserted_fields,
            "refreshed_fields": total.refreshed_fields,
            "conflicts": total.conflicts,
            "low_confidence": total.low_confidence,
            "year_inferred": total.year_inferred,
            "new_cpus": len(total.new_cpus),
            "new_gpus": len(total.new_gpus),
        },
        "per_pk_reports": per_pk_reports,
    }
    emit({"phase": "complete", "summary": summary})
    return summary


def refresh_all_products(
    conn: sqlite3.Connection,
    *,
    profiles_dir: str = ".profiles",
    on_step: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Refresh every product in the DB via from-db mode.

    Iterates ``products`` ordered by ``(model_code, year)``. Per row:

    - Parses the ``brand`` bundle. If missing/malformed or the value is
      not in ``VENDOR_TEMPLATES``, the product is skipped with a reason.
    - Calls :func:`collect_source_urls_from_product` to check that at
      least one scraped ``source_url`` exists on the row. If not, skipped.
    - Otherwise invokes :func:`refresh_product` with ``from_db=True``.
      Per-product errors (``ValueError`` and any other exception) are
      caught and recorded; the loop continues.

    Returns a summary dict with overall totals, per-product summaries,
    skipped list, and per-product error list. Caller owns ``conn``.
    """
    def emit(event: dict[str, Any]) -> None:
        if on_step is not None:
            on_step(event)

    rows = conn.execute(
        "SELECT model_code, year, brand FROM products "
        "ORDER BY model_code, year"
    ).fetchall()

    items: list[tuple[str, int, Optional[str], Optional[str]]] = []
    for row in rows:
        mc = row["model_code"]
        yr = row["year"]
        brand_json = row["brand"]
        brand_value: Optional[str] = None
        if isinstance(brand_json, str) and brand_json:
            try:
                b = json.loads(brand_json)
            except (TypeError, json.JSONDecodeError):
                b = None
            if isinstance(b, dict):
                raw = b.get("value")
                if isinstance(raw, str) and raw.strip():
                    brand_value = raw.strip().lower()
        if brand_value is None:
            items.append((mc, yr, None, "brand bundle is empty or missing"))
            continue
        if brand_value not in VENDOR_TEMPLATES:
            items.append(
                (mc, yr, brand_value, f"brand {brand_value!r} not supported")
            )
            continue
        try:
            urls = collect_source_urls_from_product(
                conn, model_code=mc, year=yr
            )
        except ValueError as exc:
            items.append((mc, yr, brand_value, str(exc)))
            continue
        if not urls:
            items.append(
                (mc, yr, brand_value, "no scraped source_url on this row")
            )
            continue
        items.append((mc, yr, brand_value, None))

    plan = [
        {"model_code": mc, "year": yr, "brand": br, "skip_reason": reason}
        for (mc, yr, br, reason) in items
    ]
    emit({"phase": "plan", "products": plan})

    per_product: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    totals = {
        "inserted_fields": 0,
        "refreshed_fields": 0,
        "conflicts": 0,
        "low_confidence": 0,
        "year_inferred": 0,
        "new_cpus": 0,
        "new_gpus": 0,
    }
    for (mc, yr, br, reason) in items:
        if reason is not None:
            skipped.append(
                {"model_code": mc, "year": yr, "brand": br, "reason": reason}
            )
            emit({
                "phase": "skip",
                "model_code": mc, "year": yr, "reason": reason,
            })
            continue
        assert br is not None
        emit({
            "phase": "product_start",
            "model_code": mc, "year": yr, "brand": br,
        })
        try:
            sub = refresh_product(
                conn,
                brand=br,
                model=mc,
                from_db=True,
                year=yr,
                profiles_dir=profiles_dir,
                on_step=on_step,
            )
        except ValueError as exc:
            errors.append({
                "model_code": mc, "year": yr, "brand": br,
                "error": str(exc), "error_type": "ValueError",
            })
            emit({
                "phase": "product_error",
                "model_code": mc, "year": yr, "error": str(exc),
            })
            continue
        except Exception as exc:  # noqa: BLE001 — vendor-side, want to keep looping
            errors.append({
                "model_code": mc, "year": yr, "brand": br,
                "error": f"{type(exc).__name__}: {exc}",
                "error_type": type(exc).__name__,
            })
            emit({
                "phase": "product_error",
                "model_code": mc, "year": yr,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        per_product.append({
            "model_code": mc, "year": yr, "brand": br, "summary": sub,
        })
        t = sub["totals"]
        for k in totals:
            totals[k] += t[k]
        emit({"phase": "product_done", "model_code": mc, "year": yr})

    summary = {
        "totals": totals,
        "per_product": per_product,
        "skipped": skipped,
        "errors": errors,
        "refreshed_count": len(per_product),
        "skipped_count": len(skipped),
        "error_count": len(errors),
    }
    emit({"phase": "complete", "summary": summary})
    return summary


# --- CLI wrapper ---------------------------------------------------------


def main(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        if args.all:
            _run_all(conn, args)
        else:
            _run_single(conn, args)
    finally:
        conn.close()


def _run_single(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    if not args.brand:
        raise SystemExit("refresh: --brand is required (unless --all)")

    from_db = getattr(args, "from_db", False)

    def emit(event: dict[str, Any]) -> None:
        # CLI print lines match the pre-T8.7 output shape so existing
        # downstream tooling keeps working.
        phase = event["phase"]
        if phase == "fetch" and event.get("status") == "start":
            url = event["url"]
            print(f"[from-db] fetching {url}" if from_db else f"fetching {url}")
        elif phase == "ingest" and event.get("status") == "done":
            pk = event["pk"]
            tile_str = ",".join(event["tiles"])
            print(
                f"[{format_product_pk(pk[0], pk[1])} tiles={tile_str}] "
                f"inserted={event['inserted_fields']} "
                f"refreshed={event['refreshed_fields']} "
                f"conflicts={event['conflicts']} "
                f"low_confidence={event['low_confidence']} "
                f"year_inferred={event['year_inferred']} "
                f"new_cpus={len(event['new_cpus'])} "
                f"new_gpus={len(event['new_gpus'])}"
            )
            for note in event["notes"]:
                print(f"  note: {note}")

    try:
        summary = refresh_product(
            conn,
            brand=args.brand,
            model=args.model,
            url=args.url,
            from_db=from_db,
            year=getattr(args, "year", None),
            profiles_dir=args.profiles_dir,
            on_step=emit,
        )
    except ValueError as exc:
        raise SystemExit(f"refresh: {exc}") from exc
    except Exception as exc:
        # HP-specific typed exception (scrapers-lib v1.6.0+): the slug
        # was silently redirected to the homepage (delisted product).
        # Exit non-zero with a clear message so retry tooling leaves the
        # URL bullet unticked and the user can replace or drop it.
        # Lazy import keeps tier2.hp (httpx, curl_cffi) off the CLI
        # startup path for non-HP commands.
        if _is_hp_product_not_found(exc):
            raise SystemExit(
                f"refresh: hp product page not found (delisted slug): {exc}"
            ) from exc
        raise

    t = summary["totals"]
    print(
        f"refresh done: {summary['snapshot_count']} snapshot(s) | "
        f"inserted={t['inserted_fields']} refreshed={t['refreshed_fields']} "
        f"conflicts={t['conflicts']} low_confidence={t['low_confidence']} "
        f"year_inferred={t['year_inferred']} "
        f"new_cpus={t['new_cpus']} new_gpus={t['new_gpus']}"
    )


def _run_all(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    def emit(event: dict[str, Any]) -> None:
        phase = event["phase"]
        if phase == "plan":
            n = len(event["products"])
            n_skip = sum(1 for p in event["products"] if p["skip_reason"])
            print(
                f"refresh --all: {n} product(s) considered, "
                f"{n_skip} will be skipped"
            )
        elif phase == "skip":
            print(
                f"[skip] {format_product_pk(event['model_code'], event['year'])} "
                f"— {event['reason']}"
            )
        elif phase == "product_start":
            print(
                f"[refresh] {format_product_pk(event['model_code'], event['year'])} "
                f"({event['brand']})"
            )
        elif phase == "ingest" and event.get("status") == "done":
            pk = event["pk"]
            tile_str = ",".join(event["tiles"])
            print(
                f"  [{format_product_pk(pk[0], pk[1])} tiles={tile_str}] "
                f"inserted={event['inserted_fields']} "
                f"refreshed={event['refreshed_fields']} "
                f"conflicts={event['conflicts']}"
            )
        elif phase == "product_error":
            print(f"  ERROR: {event['error']}")

    try:
        summary = refresh_all_products(
            conn,
            profiles_dir=args.profiles_dir,
            on_step=emit,
        )
    except ValueError as exc:
        raise SystemExit(f"refresh: {exc}") from exc

    t = summary["totals"]
    print(
        f"refresh --all done: "
        f"refreshed={summary['refreshed_count']} "
        f"skipped={summary['skipped_count']} "
        f"errors={summary['error_count']} | "
        f"inserted={t['inserted_fields']} refreshed_fields={t['refreshed_fields']} "
        f"conflicts={t['conflicts']} low_confidence={t['low_confidence']}"
    )


# --- URL + fetcher helpers ----------------------------------------------


def _resolve_url(
    brand: str, url_arg: Optional[str], slug_arg: Optional[str]
) -> tuple[str, str]:
    if url_arg:
        url = _coerce_vendor_url(brand, url_arg)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return url, slug
    assert slug_arg is not None
    template = _template_for_slug(brand, slug_arg)
    return template.format(slug=slug_arg), slug_arg


def _template_for_slug(brand: str, slug: str) -> str:
    """Pick the URL template for ``brand`` + ``slug``.

    ASUS dispatches per series via ``ASUS_SERIES_TEMPLATES`` (model_code
    prefix match, first hit wins); unmatched slugs fall back to the
    per-vendor default. Every other vendor uses its single
    ``VENDOR_TEMPLATES`` entry directly.
    """
    if brand == "asus":
        for prefix, template in ASUS_SERIES_TEMPLATES.items():
            if slug.startswith(prefix):
                return template
    return VENDOR_TEMPLATES[brand]


def _is_hp_product_not_found(exc: BaseException) -> bool:
    """True iff ``exc`` is scrapers-lib's ``HPProductNotFoundError``.

    Lazy import so tier2.hp (httpx + curl_cffi) stays off the CLI startup
    path for non-HP invocations. Returns ``False`` cleanly if scrapers-lib
    is missing or the symbol isn't exported (older versions).
    """
    try:
        from scrapers_lib.tier2.hp import HPProductNotFoundError
    except ImportError:
        return False
    return isinstance(exc, HPProductNotFoundError)


def _coerce_vendor_url(brand: str, url: str) -> str:
    """Apply per-vendor URL normalizations.

    ASUS ROG spec pages require a trailing ``/spec/`` subpath; landing-
    page URLs without it cause the fetcher to fail. Auto-append it so
    users can paste either form. ASUS TUF / V-series live on
    ``www.asus.com`` and use ``/techspec/`` instead — those URLs are
    left alone (the ``asus_www`` bridge regex rejects ``/techspec/spec/``).
    """
    if brand == "asus":
        from urllib.parse import urlparse

        if urlparse(url).hostname != "rog.asus.com":
            return url
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

        # ``include_options=True`` (scrapers-lib v1.5.0+) pulls the
        # configurator option menu (CPU/GPU/RAM/etc.) on top of the 3 tile
        # snapshots. ~5–8s extra per fetch. The option dict lands on every
        # snapshot's ``options`` field; ``bridge/dell.py`` consumes it (T9.4)
        # to surface every configurable CPU/GPU/RAM/storage/display variant.
        return fetch_dell_product(
            url,
            anchors=[anchor],
            profiles_dir=profiles_dir,
            warm=True,
            include_options=True,
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
    raise ValueError(
        f"brand {brand!r} has no fetcher wired in; "
        f"known: {sorted(VENDOR_TEMPLATES)}"
    )


# --- --from-db helpers ---------------------------------------------------


def collect_source_urls_from_product(
    conn: sqlite3.Connection,
    model_code: str,
    year: Optional[int],
) -> list[str]:
    """Return the distinct scraped ``source_url`` values stored on the
    product identified by ``(model_code, year)``.

    Year disambiguation: when ``year`` is None and the model has multiple
    rows in ``products``, raises ``ValueError`` and asks the caller to
    pass --year. Manual bundles (no ``source_url``) are skipped silently
    — a product composed entirely of manual cells returns an empty list,
    which the caller surfaces as a user-facing error. Returns urls in
    column-walk order, deduplicated.
    """
    if year is not None:
        rows = conn.execute(
            "SELECT * FROM products WHERE model_code = ? AND year = ?",
            (model_code, year),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM products WHERE model_code = ?",
            (model_code,),
        ).fetchall()
    if not rows:
        year_str = f" year={year}" if year is not None else ""
        raise ValueError(
            f"product not found in DB: model_code={model_code!r}{year_str}"
        )
    if len(rows) > 1:
        years = sorted(r["year"] for r in rows)
        raise ValueError(
            f"model_code={model_code!r} has multiple yearly variants "
            f"({years}); pass --year to disambiguate"
        )
    row = rows[0]

    collected: list[str] = []
    for key in row.keys():
        if key in ("model_code", "year"):
            continue
        raw = row[key]
        if raw is None:
            continue
        try:
            decoded = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            # Plain-text columns (family_code, arch_marker, etc.).
            continue
        _walk_source_urls(decoded, collected)

    seen: set[str] = set()
    out: list[str] = []
    for u in collected:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _walk_source_urls(payload: Any, sink: list[str]) -> None:
    """Recursively append every non-empty string ``source_url`` value
    found in ``payload`` into ``sink``. Handles scalar bundles (dict
    with ``source_url``) and offering lists (list of dicts whose values
    are leaf bundles)."""
    if isinstance(payload, dict):
        url = payload.get("source_url")
        if isinstance(url, str) and url:
            sink.append(url)
        for v in payload.values():
            if isinstance(v, (dict, list)):
                _walk_source_urls(v, sink)
    elif isinstance(payload, list):
        for item in payload:
            _walk_source_urls(item, sink)


# --- Back-compat aliases (Phase G, Stage 10a) ----------------------------
#
# The UI Refresh screen (and any external callers) reach for the public
# names; existing tests and pre-Phase-G code use the underscore-prefixed
# private forms. Keep both bound to the same object so ``is`` comparisons
# succeed and there's only one source of truth.
_VENDOR_TEMPLATES = VENDOR_TEMPLATES
_collect_source_urls_from_product = collect_source_urls_from_product
