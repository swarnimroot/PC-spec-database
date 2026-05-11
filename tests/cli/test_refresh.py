"""Unit tests for ``refresh`` URL coercion + slug resolution + --from-db."""

import pytest

from competitive_database.cli.refresh import (
    _coerce_vendor_url,
    _collect_source_urls_from_product,
    _resolve_url,
    _walk_source_urls,
)
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_manual_bundle,
    make_scraped_bundle,
    write_offerings,
    write_scalar,
)


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
        with pytest.raises(SystemExit, match="product not found"):
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
        with pytest.raises(SystemExit, match="multiple yearly variants"):
            _collect_source_urls_from_product(conn, "shared", None)
        # Disambiguating with --year picks the right row.
        urls = _collect_source_urls_from_product(conn, "shared", 2026)
        assert urls == ["https://b/"]
    finally:
        conn.close()
