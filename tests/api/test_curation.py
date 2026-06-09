"""Curation Cockpit API tests — run against a COPY of competitive.db.

SAFETY: every write test runs against a temp-file copy of the project-root
``competitive.db``. The real DB is never opened for writing — ``COMPETITIVE_DB_PATH``
is pointed at the copy for the whole module, and a guard test asserts the real
file's mtime/size is unchanged across the suite.

The app resolves ``COMPETITIVE_DB_PATH`` per request (``app._db_path``), so a
single TestClient bound while the env var points at the copy is enough.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REAL_DB = _PROJECT_ROOT / "competitive.db"


@pytest.fixture(scope="module")
def real_db_fingerprint():
    """Capture the real DB's (size, mtime) so we can prove it was untouched."""
    if not _REAL_DB.exists():
        pytest.skip(f"real DB not found at {_REAL_DB}")
    st = _REAL_DB.stat()
    return (st.st_size, st.st_mtime_ns)


@pytest.fixture(scope="module")
def client(tmp_path_factory, real_db_fingerprint):
    db_copy = tmp_path_factory.mktemp("curation_db") / "competitive_copy.db"
    shutil.copy2(_REAL_DB, db_copy)
    os.environ["COMPETITIVE_DB_PATH"] = str(db_copy)

    from fastapi.testclient import TestClient

    from competitive_database.api.app import app

    with TestClient(app) as c:
        c._db_copy = db_copy  # type: ignore[attr-defined]
        yield c


def test_queue_counts_returns_ints(client):
    resp = client.get("/api/queue/counts")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"conflicts", "review", "missing", "hand"}
    for key, val in body.items():
        assert isinstance(val, int), f"{key} is not an int"
        assert val >= 0


def test_queue_conflicts_tab_shape(client):
    resp = client.get("/api/queue", params={"tab": "conflicts"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tab"] == "conflicts"
    assert body["count"] == len(body["items"])
    for item in body["items"]:
        for key in ("id", "model_code", "year", "field_path", "conflict_kind"):
            assert key in item, f"conflict item missing {key!r}"
        assert item["id"].startswith("conflict:")
        assert item["conflict_kind"] in {
            "value-mismatch",
            "low-confidence",
            "catalog-vouch",
            "year-guess",
        }
        # candidate key present (value may be None for some shapes)
        assert "candidate" in item


@pytest.mark.parametrize("tab", ["review", "missing", "hand"])
def test_queue_field_state_tabs_shape(client, tab):
    resp = client.get("/api/queue", params={"tab": tab})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tab"] == tab
    assert body["count"] == len(body["items"])
    for item in body["items"]:
        for key in ("id", "model_code", "year", "field_path", "label", "state"):
            assert key in item, f"{tab} item missing {key!r}"
        assert item["id"].startswith("field:")
        assert "byYearDiff" in item


def test_queue_rejects_bad_tab(client):
    resp = client.get("/api/queue", params={"tab": "nonsense"})
    assert resp.status_code == 422


def test_post_value_edits_copy_and_persists(client):
    # Pick a real product from the copy via the catalog endpoint.
    models = client.get("/api/catalog").json()
    assert models, "no models in DB copy"
    model = models[0]
    model_code = model["id"]
    year = model["years"][-1]
    field_path = "audio_jack"
    new_value = "edited-by-test-3.5mm"

    resp = client.post(
        "/api/value",
        json={
            "model_code": model_code,
            "year": year,
            "field_path": field_path,
            "value": new_value,
            "status": "manual",
            "note": "curation test edit",
            "entered_by": "pytest",
        },
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["model_code"] == model_code
    after = summary["after"]
    assert isinstance(after, dict)
    assert after["value"] == new_value
    assert after["status"] == "manual"

    # Follow-up read via history confirms value + status + provenance persisted.
    hist = client.get(
        "/api/value/history",
        params={"model_code": model_code, "year": year, "field_path": field_path},
    ).json()
    assert hist["value"] == new_value
    assert hist["provenance"]["status"] == "manual"
    assert hist["provenance"]["entered_by"] == "pytest"
    assert hist["provenance"]["entered_at"] is not None


def test_post_value_validates_input(client):
    resp = client.post("/api/value", json={"field_path": "audio_jack", "value": "x"})
    assert resp.status_code == 422  # missing model_code


def test_post_resolve_resolves_one_conflict(client):
    conflicts = client.get("/api/queue", params={"tab": "conflicts"}).json()["items"]
    if not conflicts:
        pytest.skip("no unresolved conflicts in DB copy to resolve")
    # Prefer a value_disagreement we can 'kept_existing' on (safe, no catalog
    # side effects); fall back to dropping any conflict.
    target = next(
        (c for c in conflicts if c["conflict_kind"] == "value-mismatch"), conflicts[0]
    )
    action = "kept_existing" if target["conflict_kind"] == "value-mismatch" else "dropped"

    before_count = client.get("/api/queue/counts").json()["conflicts"]
    resp = client.post(
        "/api/resolve",
        json={"id": target["id"], "action": action, "note": "curation test resolve"},
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["id"] == target["row_id"]
    assert summary["action"] == action

    # The resolved row has left the queue.
    after_count = client.get("/api/queue/counts").json()["conflicts"]
    assert after_count == before_count - 1
    remaining_ids = {
        c["id"] for c in client.get("/api/queue", params={"tab": "conflicts"}).json()["items"]
    }
    assert target["id"] not in remaining_ids


def test_value_history_shape(client):
    models = client.get("/api/catalog").json()
    model = models[0]
    hist = client.get(
        "/api/value/history",
        params={
            "model_code": model["id"],
            "year": model["years"][-1],
            "field_path": "audio_jack",
        },
    )
    assert hist.status_code == 200
    body = hist.json()
    assert set(body) >= {"model_code", "year", "field_path", "value", "provenance"}
    for key in (
        "source_url",
        "captured_at",
        "scraper_id",
        "entered_by",
        "entered_at",
        "status",
    ):
        assert key in body["provenance"], f"provenance missing {key!r}"


def test_refresh_validates_without_scraping(client):
    """/api/refresh must reject bad input WITHOUT performing a live scrape.

    A real refresh is the heavy/external op (network + writes); we only assert
    the validation gate here and never trigger an actual fetch.
    """
    resp = client.post("/api/refresh", json={})
    assert resp.status_code == 422  # missing brand and not all=true

    resp = client.post("/api/refresh", json={"brand": "not-a-vendor", "model": "x"})
    assert resp.status_code == 422  # unsupported brand, rejected before fetch


def test_real_db_untouched(client, real_db_fingerprint):
    """The real competitive.db must be byte-for-byte unchanged after all writes."""
    st = _REAL_DB.stat()
    assert (st.st_size, st.st_mtime_ns) == real_db_fingerprint
    # And the app was wired to the copy, not the real file.
    assert str(client._db_copy) == os.environ["COMPETITIVE_DB_PATH"]
    assert os.environ["COMPETITIVE_DB_PATH"] != str(_REAL_DB)
