"""API endpoint tests against the REAL ``competitive.db`` (read-only).

The DB path is pinned via ``COMPETITIVE_DB_PATH`` before the app module is
imported so a fresh per-request connection always opens the real DB. Tests
assert shapes and relationships, not brittle exact values, so they stay
green as the data evolves.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DB_PATH = _PROJECT_ROOT / "competitive.db"


@pytest.fixture(scope="module")
def client():
    if not _DB_PATH.exists():
        pytest.skip(f"real DB not found at {_DB_PATH}")
    os.environ["COMPETITIVE_DB_PATH"] = str(_DB_PATH)
    # Import after the env var is set so the app resolves the right DB.
    from fastapi.testclient import TestClient

    from competitive_database.api.app import app

    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_schema_has_expected_sections(client):
    resp = client.get("/api/schema")
    assert resp.status_code == 200
    body = resp.json()
    labels = {cat["label"] for cat in body["categories"]}
    # Our visual sections must be present.
    for expected in ("Processor", "Graphics", "Display", "I/O"):
        assert expected in labels, f"missing section {expected!r}"
    # Each category carries an ordered, non-empty fields list with labels.
    for cat in body["categories"]:
        assert cat["fields"], f"category {cat['label']!r} has no fields"
        for field in cat["fields"]:
            assert "key" in field and "label" in field


def test_catalog_shape(client):
    resp = client.get("/api/catalog")
    assert resp.status_code == 200
    models = resp.json()
    # One model per identity — there are ~37 identities across 56 rows.
    assert len(models) >= 30
    sample = models[0]
    for key in ("id", "brand", "series", "model", "segment", "years", "updated", "base", "byYear"):
        assert key in sample, f"model missing {key!r}"
    assert isinstance(sample["years"], list) and sample["years"]
    assert isinstance(sample["base"], dict) and sample["base"]
    assert isinstance(sample["byYear"], dict)
    # At least one base cell is a {v, s, ...} value object.
    a_value = next(iter(sample["base"].values()))
    for vkey in ("v", "s", "src", "ts", "note"):
        assert vkey in a_value, f"value object missing {vkey!r}"
    # Display state is one of the five recognized states.
    assert a_value["s"] in {"confirmed", "not_published", "hand", "review", "blank"}


def test_catalog_byyear_overrides_reproduce_years(client):
    """For a multi-year model, base + byYear[year] must merge cleanly and the
    override keys are a strict subset of base keys (overrides only)."""
    models = client.get("/api/catalog").json()
    multi = [m for m in models if len(m["years"]) > 1]
    assert multi, "expected at least one multi-year model"
    m = multi[0]
    base_keys = set(m["base"].keys())
    for year, override in m["byYear"].items():
        assert set(override).issubset(base_keys)


def test_model_detail_and_year_resolution(client):
    models = client.get("/api/catalog").json()
    m = models[0]
    mid = m["id"]
    full = client.get(f"/api/model/{mid}")
    assert full.status_code == 200
    assert full.json()["model"] == m["model"]

    year = m["years"][0]
    resolved = client.get(f"/api/model/{mid}", params={"year": year})
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["year"] == year
    assert isinstance(body["spec"], dict) and body["spec"]


def test_model_not_found(client):
    resp = client.get("/api/model/__does_not_exist__")
    assert resp.status_code == 404


def test_find_is_empty(client):
    resp = client.post(
        "/api/find",
        json={
            "field_path": "memory_overclocking",
            "operator": "is_empty",
            "value": "",
            "narrow_by": {},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == len(body["matches"])
    assert body["count"] >= 0
    for match in body["matches"]:
        assert set(match) == {"id", "value", "marker"}


def test_find_vendor_unavailable(client):
    resp = client.post(
        "/api/find",
        json={
            "field_path": "memory_overclocking",
            "operator": "vendor_unavailable",
            "narrow_by": {},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # This field has known vendor-doesn't-publish cells in the real DB.
    assert body["count"] > 0
    assert body["count"] == len(body["matches"])


def test_find_eq_returns_sane_result(client):
    resp = client.post(
        "/api/find",
        json={
            "field_path": "wifi_standard",
            "operator": "eq",
            "value": "Wi-Fi 7",
            "narrow_by": {},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == len(body["matches"])
    assert body["count"] > 0
    for match in body["matches"]:
        assert "Wi-Fi 7" in match["value"]


def test_find_narrow_by_brand_reduces(client):
    base = client.post(
        "/api/find",
        json={"field_path": "wifi_standard", "operator": "is_set", "narrow_by": {}},
    ).json()
    narrowed = client.post(
        "/api/find",
        json={
            "field_path": "wifi_standard",
            "operator": "is_set",
            "narrow_by": {"brands": "ASUS"},
        },
    ).json()
    assert narrowed["count"] <= base["count"]


def test_find_rejects_bad_operator(client):
    resp = client.post(
        "/api/find",
        json={"field_path": "wifi_standard", "operator": "nonsense"},
    )
    assert resp.status_code == 422
