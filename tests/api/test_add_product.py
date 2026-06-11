"""Tests for the Add-product backend: ``scrape_only`` (pure, no DB writes),
GET /api/vendors, and the POST /api/products/scrape -> /api/products/add flow.

Scraping is never live here — ``scrape_only`` is monkeypatched to return
synthetic ``CandidateProduct`` groups (mirroring how ``tests/cli/test_refresh``
fakes ``_fetch_snapshots`` + ``dispatch``). The flow runs against a fresh temp
DB pinned via ``COMPETITIVE_DB_PATH`` so the real ``competitive.db`` is never
touched.
"""

from __future__ import annotations

import importlib
import os

import pytest

from competitive_database.bridge.types import CandidateProduct
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import make_scraped_bundle


# --- synthetic candidate builders ---------------------------------------


def _bundle(value, url="https://vendor/x"):
    return make_scraped_bundle(
        value=value,
        source_url=url,
        captured_at="2026-06-10T00:00:00+00:00",
        scraper_id="test",
    )


def _candidate(model_code, year, *, cpu="Core Ultra 9 285HX", gpu="RTX 5090"):
    """A minimal but realistic CandidateProduct (one CPU + one GPU board)."""
    return CandidateProduct(
        model_code=model_code,
        year=year,
        brand=_bundle("dell"),
        vendor_full_name=_bundle(f"Dell {model_code}"),
        cpu_offerings=[{"model": _bundle(cpu)}],
        boards=[{"label": _bundle("RTX 5090"), "gpus": [_bundle(gpu)]}],
        memory_max_gb=_bundle(64),
        storage_max_gb=_bundle(4096),
        display_offerings=[
            {
                "size_inches": _bundle(16),
                "resolution_label": _bundle("QHD+"),
                "refresh_rate_hz": _bundle(240),
            }
        ],
    )


# --- fixtures ------------------------------------------------------------


@pytest.fixture()
def app_module(tmp_path):
    """Fresh app bound to a temp DB. Reloaded per test so the module-level
    ``_PENDING_SCRAPES`` dict and the pinned DB path are isolated."""
    db_path = tmp_path / "add.db"
    conn = connect(db_path)
    with transaction(conn):
        apply_schema(conn)
    conn.close()

    os.environ["COMPETITIVE_DB_PATH"] = str(db_path)
    from competitive_database.api import app as app_mod

    importlib.reload(app_mod)
    return app_mod


@pytest.fixture()
def client(app_module):
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as c:
        yield c


def _open(app_module):
    return connect(app_module._db_path())


# --- scrape_only purity --------------------------------------------------


def test_scrape_only_returns_grouped_candidates_and_writes_nothing(
    monkeypatch, app_module
):
    """scrape_only groups by PK and never touches the DB."""
    from competitive_database.cli import refresh as refresh_mod
    from types import SimpleNamespace

    monkeypatch.setattr(
        refresh_mod,
        "_fetch_snapshots",
        lambda b, u, s, p: [SimpleNamespace(source="dell", source_id="t0")],
    )
    monkeypatch.setattr(
        refresh_mod, "dispatch", lambda snap: _candidate("ac16251", 2026)
    )

    groups = refresh_mod.scrape_only(
        brand="dell", url="https://dell/spd/ac16251"
    )
    assert len(groups) == 1
    assert groups[0][0].model_code == "ac16251"

    # Nothing was written.
    conn = _open(app_module)
    try:
        n = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


# --- GET /api/vendors ----------------------------------------------------


def test_get_vendors_shape(client):
    resp = client.get("/api/vendors")
    assert resp.status_code == 200
    vendors = resp.json()
    # One entry per brand; labels in display order.
    assert [v["brand"] for v in vendors] == ["dell", "hp", "lenovo", "asus"]
    assert [v["label"] for v in vendors] == ["Dell", "HP", "Lenovo", "ASUS"]
    for v in vendors:
        assert set(v) == {"brand", "label", "links"}
        assert v["links"]
        for lnk in v["links"]:
            assert set(lnk) == {"label", "url"}
            assert lnk["url"].startswith("http")
    by_brand = {v["brand"]: v for v in vendors}
    # ASUS carries two links (ROG + ASUS) on different hosts, one brand.
    asus_hosts = {lnk["url"].split("/")[2] for lnk in by_brand["asus"]["links"]}
    assert asus_hosts == {"rog.asus.com", "www.asus.com"}
    # Lenovo points at PSREF (the scrape target), not the retail store.
    assert "psref.lenovo.com" in by_brand["lenovo"]["links"][0]["url"]


# --- scrape -> add happy path -------------------------------------------


def test_scrape_then_add_inserts_new_product(monkeypatch, app_module, client):
    monkeypatch.setattr(
        app_module, "scrape_only", lambda **kw: [[_candidate("ac16251", 2026)]]
    )

    scrape = client.post(
        "/api/products/scrape",
        json={"brand": "dell", "url": "https://dell/spd/ac16251"},
    )
    assert scrape.status_code == 200
    body = scrape.json()
    assert body["token"]
    assert len(body["products"]) == 1
    prod = body["products"][0]
    assert prod["model_code"] == "ac16251"
    assert prod["year"] == 2026
    assert prod["already_exists"] is False
    assert prod["summary"]["cpu"] == "Core Ultra 9 285HX"
    assert prod["summary"]["gpu"] == "RTX 5090"
    assert prod["summary"]["memory_max_gb"] == 64
    assert prod["summary"]["display"]

    add = client.post("/api/products/add", json={"token": body["token"]})
    assert add.status_code == 200
    items = add.json()["items"]
    assert len(items) == 1
    assert items[0]["inserted"] is True
    assert items[0]["already_existed"] is False
    assert items[0]["inserted_fields"] > 0

    # A products row now exists.
    conn = _open(app_module)
    try:
        row = conn.execute(
            "SELECT product FROM products WHERE model_code = ? AND year = ?",
            ("ac16251", 2026),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    # Without a names override, product defaults to the model_code.
    assert row["product"] == "ac16251"
    assert items[0]["product"] == "ac16251"


# --- name override on add ------------------------------------------------


def test_add_with_name_override_sets_product(monkeypatch, app_module, client):
    """Passing names={"<mc>|<year>": "Alienware 15"} writes products.product."""
    monkeypatch.setattr(
        app_module, "scrape_only", lambda **kw: [[_candidate("da15265", 2026)]]
    )
    scrape = client.post(
        "/api/products/scrape", json={"brand": "dell", "url": "https://x/"}
    )
    token = scrape.json()["token"]

    add = client.post(
        "/api/products/add",
        json={"token": token, "names": {"da15265|2026": "Alienware 15"}},
    )
    assert add.status_code == 200
    item = add.json()["items"][0]
    assert item["inserted"] is True
    assert item["product"] == "Alienware 15"

    conn = _open(app_module)
    try:
        row = conn.execute(
            "SELECT product FROM products WHERE model_code = ? AND year = ?",
            ("da15265", 2026),
        ).fetchone()
    finally:
        conn.close()
    # product is the chosen name, NOT the model_code.
    assert row["product"] == "Alienware 15"


def test_add_name_override_not_applied_to_existing_pk(
    monkeypatch, app_module, client
):
    """A names entry for an already-existing PK is ignored (skip, no update)."""
    monkeypatch.setattr(
        app_module, "scrape_only", lambda **kw: [[_candidate("da15265", 2026)]]
    )
    # First insert (no name) -> product == model_code.
    first = client.post(
        "/api/products/scrape", json={"brand": "dell", "url": "https://x/"}
    )
    client.post("/api/products/add", json={"token": first.json()["token"]})

    # Re-scrape same PK, try to rename on the (now duplicate) add.
    second = client.post(
        "/api/products/scrape", json={"brand": "dell", "url": "https://x/"}
    )
    add = client.post(
        "/api/products/add",
        json={
            "token": second.json()["token"],
            "names": {"da15265|2026": "Should Not Apply"},
        },
    )
    item = add.json()["items"][0]
    assert item["already_existed"] is True
    assert item["inserted"] is False
    assert "product" not in item  # skipped items carry no applied name

    conn = _open(app_module)
    try:
        row = conn.execute(
            "SELECT product FROM products WHERE model_code = ? AND year = ?",
            ("da15265", 2026),
        ).fetchone()
    finally:
        conn.close()
    assert row["product"] == "da15265"


# --- duplicate detection -------------------------------------------------


def test_duplicate_pk_flagged_and_add_skips_without_queueing(
    monkeypatch, app_module, client
):
    """A pre-existing PK: scrape flags already_exists, add SKIPS it (no
    ingest, so no new review_queue rows)."""
    # Seed the PK by inserting it first via the normal add flow.
    monkeypatch.setattr(
        app_module, "scrape_only", lambda **kw: [[_candidate("ac16251", 2026)]]
    )
    first = client.post(
        "/api/products/scrape", json={"brand": "dell", "url": "https://x/"}
    )
    client.post("/api/products/add", json={"token": first.json()["token"]})

    conn = _open(app_module)
    try:
        before = conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0]
    finally:
        conn.close()

    # Re-scrape the SAME PK with a *different* CPU (would normally conflict).
    monkeypatch.setattr(
        app_module,
        "scrape_only",
        lambda **kw: [[_candidate("ac16251", 2026, cpu="Ryzen 9 9955HX3D")]],
    )
    scrape = client.post(
        "/api/products/scrape", json={"brand": "dell", "url": "https://x/"}
    )
    assert scrape.status_code == 200
    prod = scrape.json()["products"][0]
    assert prod["already_exists"] is True

    add = client.post(
        "/api/products/add", json={"token": scrape.json()["token"]}
    )
    assert add.status_code == 200
    item = add.json()["items"][0]
    assert item["already_existed"] is True
    assert item["inserted"] is False

    # No new review_queue rows — the skip avoided conflict enqueue.
    conn = _open(app_module)
    try:
        after = conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0]
    finally:
        conn.close()
    assert after == before


# --- error paths ---------------------------------------------------------


def test_add_unknown_token_returns_404(client):
    resp = client.post("/api/products/add", json={"token": "nope"})
    assert resp.status_code == 404


def test_scrape_bad_brand_returns_422(client):
    resp = client.post(
        "/api/products/scrape", json={"brand": "acer", "url": "https://x/"}
    )
    assert resp.status_code == 422


def test_scrape_parser_failure_returns_422(monkeypatch, app_module, client):
    def boom(**kw):
        raise RuntimeError("vendor page changed shape")

    monkeypatch.setattr(app_module, "scrape_only", boom)
    resp = client.post(
        "/api/products/scrape", json={"brand": "dell", "url": "https://x/"}
    )
    assert resp.status_code == 422
    assert "vendor page changed shape" in resp.json()["detail"]


# --- scrape preview name cleaning ---------------------------------------


def test_serialize_scrape_preview_cleans_marketing_suffix():
    """The DERIVED default name drops a trailing "Gaming Laptop" so the
    frontend Name field is pre-trimmed for every vendor."""
    from competitive_database.api.serializers import serialize_scrape_preview

    cand = _candidate("da15265", 2026)
    cand.vendor_full_name = _bundle("Alienware 15 Gaming Laptop")
    preview = serialize_scrape_preview(cand)
    assert preview["name"] == "Alienware 15"
