"""Unit tests for ``refresh`` URL coercion + slug resolution + --from-db +
T8.7 library entry points (``refresh_product`` / ``refresh_all_products``)."""

import argparse
from types import SimpleNamespace

import pytest

from competitive_database.cli.refresh import (
    _coerce_vendor_url,
    _collect_source_urls_from_product,
    _resolve_url,
    _walk_source_urls,
    refresh_all_products,
    refresh_product,
)
from competitive_database.cli.refresh import main as refresh_main
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_manual_bundle,
    make_scraped_bundle,
    write_offerings,
    write_scalar,
)
from competitive_database.ingest.runner import IngestReport


def test_coerce_asus_url_without_spec_appends_subpath():
    coerced = _coerce_vendor_url(
        "asus",
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/",
    )
    assert coerced == (
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec/"
    )


def test_coerce_asus_url_with_spec_keeps_form():
    coerced = _coerce_vendor_url(
        "asus",
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec/",
    )
    assert coerced == (
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec/"
    )


def test_coerce_asus_url_spec_without_trailing_slash_gets_one():
    coerced = _coerce_vendor_url(
        "asus",
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec",
    )
    assert coerced == (
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec/"
    )


def test_coerce_non_asus_url_unchanged():
    url = "https://www.dell.com/en-us/shop/dell-laptops/foo/spd/ac16251"
    assert _coerce_vendor_url("dell", url) == url


def test_resolve_asus_url_without_spec_gets_coerced():
    url, _slug = _resolve_url(
        "asus",
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/",
        None,
    )
    assert url.endswith("/spec/")


def test_resolve_dell_template_used_when_only_slug_given():
    url, slug = _resolve_url("dell", None, "ac16251")
    assert "ac16251" in url
    assert slug == "ac16251"


# --- T7.4 --from-db: source_url walker (pure) ----------------------------


def test_walk_source_urls_scalar_bundle():
    sink: list[str] = []
    _walk_source_urls(
        {"value": "Alienware", "source_url": "https://a/", "status": "verified"},
        sink,
    )
    assert sink == ["https://a/"]


def test_walk_source_urls_offering_list_dedup_handled_by_caller():
    sink: list[str] = []
    _walk_source_urls(
        [
            {
                "nits_peak": {"value": 500, "source_url": "https://a/"},
                "refresh_rate_hz": {"value": 240, "source_url": "https://a/"},
            }
        ],
        sink,
    )
    # walker yields each occurrence; dedup is the caller's responsibility.
    assert sink == ["https://a/", "https://a/"]


def test_walk_source_urls_multi_url_offerings():
    sink: list[str] = []
    _walk_source_urls(
        [
            {"chip": {"value": "i9", "source_url": "https://intel-page/"}},
            {"chip": {"value": "R9", "source_url": "https://amd-page/"}},
        ],
        sink,
    )
    assert sink == ["https://intel-page/", "https://amd-page/"]


def test_walk_source_urls_manual_bundle_skipped():
    sink: list[str] = []
    _walk_source_urls(
        {
            "value": "yes",
            "source_note": "hands-on review",
            "entered_by": "tester",
            "status": "vouched",
        },
        sink,
    )
    assert sink == []


def test_walk_source_urls_ignores_empty_string_source_url():
    sink: list[str] = []
    _walk_source_urls({"value": "x", "source_url": ""}, sink)
    assert sink == []


# --- T7.4 --from-db: DB collector ----------------------------------------


_PK = {"model_code": "alienware-area-51", "year": 2026}


def _fresh_db(tmp_path):
    conn = connect(tmp_path / "refresh.db")
    with transaction(conn):
        apply_schema(conn)
    return conn


def _scraped(value, url):
    return make_scraped_bundle(
        value=value,
        source_url=url,
        captured_at="2026-05-07T00:00:00+00:00",
        scraper_id="test",
    )


def _manual(value):
    return make_manual_bundle(
        value=value,
        entered_by="tester",
        source_note="manual",
    )


def test_collect_source_urls_single_scraped_scalar(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(
                conn, "products", _PK, "brand",
                _scraped("Alienware", "https://dell/spd/aa18250"),
            )
        urls = _collect_source_urls_from_product(
            conn, "alienware-area-51", 2026
        )
    finally:
        conn.close()
    assert urls == ["https://dell/spd/aa18250"]


def test_collect_source_urls_dedups_across_scalars_and_offerings(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            url = "https://dell/spd/aa18250"
            write_scalar(conn, "products", _PK, "brand", _scraped("Alienware", url))
            write_offerings(
                conn, "products", _PK, "display_offerings",
                [{"nits_peak": _scraped(500, url),
                  "refresh_rate_hz": _scraped(240, url)}],
            )
        urls = _collect_source_urls_from_product(
            conn, "alienware-area-51", 2026
        )
    finally:
        conn.close()
    assert urls == ["https://dell/spd/aa18250"]


def test_collect_source_urls_multi_url_lenovo_pattern(tmp_path):
    """Lenovo Intel+AMD merge stores distinct source_urls per offering."""
    conn = _fresh_db(tmp_path)
    try:
        intel_url = "https://psref/Legion_Pro_7_16AHR10H"
        amd_url = "https://psref/Legion_Pro_7_16AFR10H"
        with transaction(conn):
            write_scalar(conn, "products", _PK, "brand", _scraped("Lenovo", intel_url))
            write_offerings(
                conn, "products", _PK, "cpu_offerings",
                [
                    {"chip": _scraped("i9", intel_url)},
                    {"chip": _scraped("R9", amd_url)},
                ],
            )
        urls = _collect_source_urls_from_product(
            conn, "alienware-area-51", 2026
        )
    finally:
        conn.close()
    assert urls == [intel_url, amd_url]


def test_collect_source_urls_manual_only_returns_empty(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(conn, "products", _PK, "audio_jack", _manual("yes"))
        urls = _collect_source_urls_from_product(
            conn, "alienware-area-51", 2026
        )
    finally:
        conn.close()
    assert urls == []


def test_collect_source_urls_missing_product_errors(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with pytest.raises(ValueError, match="product not found"):
            _collect_source_urls_from_product(conn, "does-not-exist", 2026)
    finally:
        conn.close()


def test_collect_source_urls_year_disambiguator_required(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(
                conn, "products", {"model_code": "shared", "year": 2025},
                "brand", _scraped("X", "https://a/"),
            )
            write_scalar(
                conn, "products", {"model_code": "shared", "year": 2026},
                "brand", _scraped("X", "https://b/"),
            )
        with pytest.raises(ValueError, match="multiple yearly variants"):
            _collect_source_urls_from_product(conn, "shared", None)
        # Disambiguating with --year picks the right row.
        urls = _collect_source_urls_from_product(conn, "shared", 2026)
        assert urls == ["https://b/"]
    finally:
        conn.close()


# --- T8.7 refresh_product (lib fn) --------------------------------------
#
# These tests monkeypatch ``_fetch_snapshots`` + ``dispatch`` +
# ``ingest_product`` so the orchestrator is exercised in isolation —
# no live HTTP, no real bridge parsing, no real IngestReport math. The
# real integrations are covered by ``tests/bridge/`` and ``tests/ingest/``.


def _stub_snap(source, source_id):
    """Stand-in for ``scrapers_lib.ProductSnapshot``. The dispatcher key
    and tile-id label are all ``refresh_product`` reads off it."""
    return SimpleNamespace(source=source, source_id=source_id)


def _stub_candidate(model_code, year, *, family_code=None):
    """Stand-in for ``bridge.CandidateProduct``. ``refresh_product`` only
    touches ``.model_code``, ``.year``, ``.family_code`` for the merge
    coercion + PK grouping."""
    return SimpleNamespace(
        model_code=model_code, year=year, family_code=family_code
    )


def _seed_brand(conn, model_code, year, brand_name, url):
    """Write a scraped ``brand`` bundle on a product so
    ``refresh_all_products`` sees it as eligible."""
    with transaction(conn):
        write_scalar(
            conn,
            "products",
            {"model_code": model_code, "year": year},
            "brand",
            _scraped(brand_name, url),
        )


def _stub_fetch_dispatch_ingest(monkeypatch, *, fetcher, dispatcher, ingester):
    monkeypatch.setattr(
        "competitive_database.cli.refresh._fetch_snapshots", fetcher
    )
    monkeypatch.setattr(
        "competitive_database.cli.refresh.dispatch", dispatcher
    )
    monkeypatch.setattr(
        "competitive_database.cli.refresh.ingest_product", ingester
    )


def test_refresh_product_template_mode_uses_vendor_template(monkeypatch, tmp_path):
    conn = _fresh_db(tmp_path)
    calls = []

    def fake_fetch(brand, url, slug, profiles_dir):
        calls.append({"brand": brand, "url": url, "slug": slug})
        return [_stub_snap("dell", "tile0")]

    _stub_fetch_dispatch_ingest(
        monkeypatch,
        fetcher=fake_fetch,
        dispatcher=lambda s: _stub_candidate("alienware-area-51", 2026),
        ingester=lambda c, cs: IngestReport(inserted_fields=5),
    )
    try:
        summary = refresh_product(conn, brand="dell", model="ac16251")
    finally:
        conn.close()
    assert len(calls) == 1
    assert calls[0]["brand"] == "dell"
    assert "ac16251" in calls[0]["url"]
    assert summary["mode"] == "template"
    assert summary["snapshot_count"] == 1
    assert summary["totals"]["inserted_fields"] == 5
    assert summary["pks"] == [["alienware-area-51", 2026]]


def test_refresh_product_url_mode_overrides_template(monkeypatch, tmp_path):
    conn = _fresh_db(tmp_path)
    calls = []
    _stub_fetch_dispatch_ingest(
        monkeypatch,
        fetcher=lambda b, u, s, p: (calls.append(u) or [_stub_snap("hp", "tile0")]),
        dispatcher=lambda s: _stub_candidate("16t-ah100", 2026),
        ingester=lambda c, cs: IngestReport(),
    )
    try:
        summary = refresh_product(conn, brand="hp", url="https://custom.hp/x")
    finally:
        conn.close()
    assert calls == ["https://custom.hp/x"]
    assert summary["mode"] == "url"


def test_refresh_product_from_db_walks_stored_urls(monkeypatch, tmp_path):
    """from-db mode hands every distinct stored URL to the fetcher
    (covers the Lenovo Intel+AMD merge case)."""
    conn = _fresh_db(tmp_path)
    intel_url = "https://psref/Legion_Pro_7_16AHR10H"
    amd_url = "https://psref/Legion_Pro_7_16AFR10H"
    try:
        with transaction(conn):
            write_scalar(
                conn, "products", _PK, "brand",
                _scraped("Lenovo", intel_url),
            )
            write_offerings(
                conn, "products", _PK, "cpu_offerings",
                [
                    {"chip": _scraped("i9", intel_url)},
                    {"chip": _scraped("R9", amd_url)},
                ],
            )

        urls_fetched: list[str] = []
        _stub_fetch_dispatch_ingest(
            monkeypatch,
            fetcher=lambda b, u, s, p: (
                urls_fetched.append(u)
                or [_stub_snap("lenovo", f"tile{len(urls_fetched)}")]
            ),
            dispatcher=lambda s: _stub_candidate("alienware-area-51", 2026),
            ingester=lambda c, cs: IngestReport(),
        )

        summary = refresh_product(
            conn,
            brand="lenovo",
            model="alienware-area-51",
            from_db=True,
            year=2026,
        )
    finally:
        conn.close()
    assert urls_fetched == [intel_url, amd_url]
    assert summary["mode"] == "from_db"
    assert summary["snapshot_count"] == 2


def test_refresh_product_unknown_brand_raises_value_error(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with pytest.raises(ValueError, match="not supported"):
            refresh_product(conn, brand="acer", model="x")
    finally:
        conn.close()


def test_refresh_product_no_mode_raises_value_error(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with pytest.raises(ValueError, match="either --url or --model"):
            refresh_product(conn, brand="dell")
    finally:
        conn.close()


def test_refresh_product_from_db_with_url_raises_value_error(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with pytest.raises(ValueError, match="mutually exclusive"):
            refresh_product(
                conn, brand="dell", url="https://x/", from_db=True, model="m",
            )
    finally:
        conn.close()


def test_refresh_product_from_db_without_model_raises_value_error(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with pytest.raises(ValueError, match="requires --model"):
            refresh_product(conn, brand="dell", from_db=True)
    finally:
        conn.close()


def test_refresh_product_from_db_no_urls_raises_value_error(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(conn, "products", _PK, "audio_jack", _manual("yes"))
        with pytest.raises(ValueError, match="no scraped source_urls"):
            refresh_product(
                conn, brand="dell", model="alienware-area-51",
                from_db=True, year=2026,
            )
    finally:
        conn.close()


def test_refresh_product_on_step_event_order(monkeypatch, tmp_path):
    conn = _fresh_db(tmp_path)
    _stub_fetch_dispatch_ingest(
        monkeypatch,
        fetcher=lambda b, u, s, p: [
            _stub_snap("dell", "tile0"), _stub_snap("dell", "tile1"),
        ],
        dispatcher=lambda s: _stub_candidate("alienware-area-51", 2026),
        ingester=lambda c, cs: IngestReport(inserted_fields=2),
    )
    events: list[dict] = []
    try:
        refresh_product(
            conn, brand="dell", model="ac16251",
            on_step=events.append,
        )
    finally:
        conn.close()
    phases = [(e["phase"], e.get("status")) for e in events]
    assert phases[0] == ("resolve_url", None)
    assert phases[1] == ("fetch", "start")
    assert phases[2] == ("fetch", "done")
    assert ("dispatch", "start") in phases
    assert ("dispatch", "done") in phases
    assert ("ingest", "start") in phases
    assert ("ingest", "done") in phases
    assert phases[-1] == ("complete", None)


def test_refresh_product_family_code_coerces_pk(monkeypatch, tmp_path):
    """Lenovo merge: candidates with family_code group under the family PK."""
    conn = _fresh_db(tmp_path)
    candidates = iter([
        _stub_candidate("16AHR10H", 2026, family_code="legion-pro-7-16-gen-10"),
        _stub_candidate("16AFR10H", 2026, family_code="legion-pro-7-16-gen-10"),
    ])
    _stub_fetch_dispatch_ingest(
        monkeypatch,
        fetcher=lambda b, u, s, p: [
            _stub_snap("lenovo", "intel"), _stub_snap("lenovo", "amd"),
        ],
        dispatcher=lambda s: next(candidates),
        ingester=lambda c, cs: IngestReport(),
    )
    try:
        summary = refresh_product(
            conn, brand="lenovo", model="legion-pro-7-16-gen-10",
        )
    finally:
        conn.close()
    assert summary["pks"] == [["legion-pro-7-16-gen-10", 2026]]
    assert summary["per_pk_reports"][0]["tiles"] == ["intel", "amd"]


# --- T8.7 refresh_all_products (lib fn) ---------------------------------


def test_refresh_all_iterates_supported_products(monkeypatch, tmp_path):
    conn = _fresh_db(tmp_path)
    _seed_brand(conn, "ac16251", 2026, "Dell", "https://dell/spd/ac16251")
    _seed_brand(conn, "16t-ah100", 2026, "HP", "https://hp/pdp/16t-ah100")
    fetch_calls: list[str] = []
    try:
        _stub_fetch_dispatch_ingest(
            monkeypatch,
            fetcher=lambda b, u, s, p: (
                fetch_calls.append(u) or [_stub_snap(b, "tile0")]
            ),
            dispatcher=lambda s: _stub_candidate(
                "ac16251" if s.source == "dell" else "16t-ah100", 2026
            ),
            ingester=lambda c, cs: IngestReport(inserted_fields=1),
        )
        summary = refresh_all_products(conn)
    finally:
        conn.close()
    assert summary["refreshed_count"] == 2
    assert summary["skipped_count"] == 0
    assert summary["error_count"] == 0
    assert summary["totals"]["inserted_fields"] == 2
    assert len(fetch_calls) == 2


def test_refresh_all_skips_unknown_brand(monkeypatch, tmp_path):
    conn = _fresh_db(tmp_path)
    _seed_brand(conn, "acer-x", 2026, "Acer", "https://acer/x")
    try:
        _stub_fetch_dispatch_ingest(
            monkeypatch,
            fetcher=lambda *a, **k: pytest.fail(
                "fetch must not be called for skipped product"
            ),
            dispatcher=lambda s: pytest.fail("dispatch must not be called"),
            ingester=lambda c, cs: pytest.fail("ingest must not be called"),
        )
        summary = refresh_all_products(conn)
    finally:
        conn.close()
    assert summary["refreshed_count"] == 0
    assert summary["skipped_count"] == 1
    assert "not supported" in summary["skipped"][0]["reason"]


def test_refresh_all_skips_product_without_source_url(monkeypatch, tmp_path):
    """Manual-only product (brand=Dell, no source_url anywhere) is skipped."""
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(
                conn, "products",
                {"model_code": "manual-only", "year": 2026},
                "brand",
                _manual("Dell"),
            )
        _stub_fetch_dispatch_ingest(
            monkeypatch,
            fetcher=lambda *a, **k: pytest.fail("fetch must not be called"),
            dispatcher=lambda s: pytest.fail("dispatch must not be called"),
            ingester=lambda c, cs: pytest.fail("ingest must not be called"),
        )
        summary = refresh_all_products(conn)
    finally:
        conn.close()
    assert summary["refreshed_count"] == 0
    assert summary["skipped_count"] == 1
    assert "no scraped source_url" in summary["skipped"][0]["reason"]


def test_refresh_all_continues_after_one_product_errors(monkeypatch, tmp_path):
    conn = _fresh_db(tmp_path)
    _seed_brand(conn, "good", 2026, "Dell", "https://good/")
    _seed_brand(conn, "bad", 2026, "HP", "https://bad/")
    try:
        def fake_fetch(brand, url, slug, profiles_dir):
            if url == "https://bad/":
                raise RuntimeError("network down")
            return [_stub_snap(brand, "tile0")]
        _stub_fetch_dispatch_ingest(
            monkeypatch,
            fetcher=fake_fetch,
            dispatcher=lambda s: _stub_candidate("good", 2026),
            ingester=lambda c, cs: IngestReport(inserted_fields=1),
        )
        summary = refresh_all_products(conn)
    finally:
        conn.close()
    assert summary["refreshed_count"] == 1
    assert summary["error_count"] == 1
    assert summary["errors"][0]["model_code"] == "bad"
    assert "network down" in summary["errors"][0]["error"]
    assert summary["totals"]["inserted_fields"] == 1


def test_refresh_all_empty_db_returns_empty_summary(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        summary = refresh_all_products(conn)
    finally:
        conn.close()
    assert summary["refreshed_count"] == 0
    assert summary["skipped_count"] == 0
    assert summary["error_count"] == 0
    assert summary["totals"]["inserted_fields"] == 0


# --- T8.7 main() CLI wrapper --------------------------------------------


def test_main_maps_value_error_to_sys_exit_refresh_prefix(tmp_path):
    args = argparse.Namespace(
        brand="acer", model="x", url=None, all=False, from_db=False,
        year=None, db=str(tmp_path / "x.db"), profiles_dir=".profiles",
    )
    with pytest.raises(SystemExit, match="refresh: brand 'acer' is not supported"):
        refresh_main(args)


def test_main_all_invokes_refresh_all(monkeypatch, tmp_path):
    called = {"hit": False}

    def fake_all(conn, *, profiles_dir, on_step=None):
        called["hit"] = True
        return {
            "totals": {"inserted_fields": 0, "refreshed_fields": 0,
                       "conflicts": 0, "low_confidence": 0,
                       "year_inferred": 0, "new_cpus": 0, "new_gpus": 0},
            "per_product": [], "skipped": [], "errors": [],
            "refreshed_count": 0, "skipped_count": 0, "error_count": 0,
        }

    monkeypatch.setattr(
        "competitive_database.cli.refresh.refresh_all_products", fake_all
    )
    args = argparse.Namespace(
        brand=None, model=None, url=None, all=True, from_db=False,
        year=None, db=str(tmp_path / "x.db"), profiles_dir=".profiles",
    )
    refresh_main(args)
    assert called["hit"] is True


def test_main_single_requires_brand(tmp_path):
    args = argparse.Namespace(
        brand=None, model="x", url=None, all=False, from_db=False,
        year=None, db=str(tmp_path / "x.db"), profiles_dir=".profiles",
    )
    with pytest.raises(SystemExit, match="--brand is required"):
        refresh_main(args)
