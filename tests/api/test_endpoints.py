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


# ---------------------------------------------------------------------------
# Detail endpoints (accordion expand + field-visibility schema)
# ---------------------------------------------------------------------------

_COMPARE_SECTIONS = {
    "processor", "graphics", "display", "memory", "storage", "camera",
    "audio", "network", "battery", "adapter", "dimensions", "weight",
    "design", "io",
}


def _model_with_gpu(client):
    """Return a (model_id, year) whose graphics detail has a real GPU name."""
    for m in client.get("/api/catalog").json():
        for year in m["years"]:
            d = client.get(f"/api/model/{m['id']}/detail", params={"year": year})
            if d.status_code != 200:
                continue
            gpu_rows = [
                r for r in d.json()["sections"].get("graphics", [])
                if r["label"] == "GPU"
            ]
            if gpu_rows and gpu_rows[0]["value"]["v"]:
                return m["id"], year
    return None


def test_model_detail_shape_and_sections(client):
    found = _model_with_gpu(client)
    assert found is not None, "expected a model with a populated GPU detail leaf"
    mid, year = found
    resp = client.get(f"/api/model/{mid}/detail", params={"year": year})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == mid
    assert body["year"] == year
    sections = body["sections"]
    # Only compare-schema section keys appear (Identity/Keyboard/Thermals skipped).
    assert set(sections).issubset(_COMPARE_SECTIONS)
    for rows in sections.values():
        for row in rows:
            assert set(row) == {"key", "label", "value"}
            assert set(row["value"]) == {"v", "s", "src", "ts", "note"}


def test_model_detail_processor_has_cpu_model_string(client):
    found = _model_with_gpu(client)
    mid, year = found
    body = client.get(f"/api/model/{mid}/detail", params={"year": year}).json()
    proc = body["sections"]["processor"]
    assert proc, "processor section should have rows"
    # At least one processor row carries an actual CPU model name string.
    values = [r["value"]["v"] for r in proc if r["value"]["v"]]
    assert values, "expected at least one populated processor leaf (CPU model)"
    assert any(isinstance(v, str) and v.strip() for v in values)


def test_model_detail_graphics_has_gpu_row(client):
    found = _model_with_gpu(client)
    mid, year = found
    body = client.get(f"/api/model/{mid}/detail", params={"year": year}).json()
    graphics = body["sections"]["graphics"]
    gpu_rows = [r for r in graphics if r["label"] == "GPU"]
    assert gpu_rows, "graphics detail must include a synthetic 'GPU' row"
    # The GPU row is PREPENDED — it comes first in the section.
    assert graphics[0]["label"] == "GPU"
    assert gpu_rows[0]["key"] == "graphics.gpu"
    assert gpu_rows[0]["value"]["v"], "GPU row should carry a real GPU name"


def test_model_detail_year_required(client):
    m = client.get("/api/catalog").json()[0]
    resp = client.get(f"/api/model/{m['id']}/detail")
    assert resp.status_code == 422


def test_model_detail_not_found(client):
    resp = client.get("/api/model/__nope__/detail", params={"year": 2026})
    assert resp.status_code == 404


def test_detail_schema_lists_leaves_per_section(client):
    resp = client.get("/api/schema/detail")
    assert resp.status_code == 200
    sections = resp.json()["sections"]
    # Every compare section is present, in compare order.
    assert list(sections) == [
        "processor", "graphics", "display", "memory", "storage", "camera",
        "audio", "network", "battery", "adapter", "dimensions", "weight",
        "design", "io",
    ]
    # Graphics lists the synthetic GPU leaf.
    gfx_labels = {f["label"] for f in sections["graphics"]}
    assert "GPU" in gfx_labels
    # Each listed leaf is a {key, label} pair.
    for leaves in sections.values():
        for leaf in leaves:
            assert set(leaf) == {"key", "label"}
    # Processor should expose at least one leaf across the corpus.
    assert sections["processor"]
