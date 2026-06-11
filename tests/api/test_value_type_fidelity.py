"""Type-fidelity tests for POST /api/value.

The React Cockpit edits values in a text box, so any commit on a bool/int
cell used to silently rewrite the stored value as its string form ("true",
"32") — including annotation-only edits. The endpoint now coerces a string
input to the stored cell's scalar type before writing (and rejects
non-boolean text for bool cells with a 400). Runs against a fresh temp DB
pinned via ``COMPETITIVE_DB_PATH`` so the real ``competitive.db`` is never
touched (mirrors ``test_add_product.py``).
"""

from __future__ import annotations

import importlib
import os

import pytest

from competitive_database.db.connection import apply_schema, connect, transaction

_MC = "fidelity-test"
_YEAR = 2026


@pytest.fixture()
def app_module(tmp_path):
    """Fresh app bound to a temp DB seeded with one bare product row."""
    db_path = tmp_path / "fidelity.db"
    conn = connect(db_path)
    with transaction(conn):
        apply_schema(conn)
        conn.execute(
            "INSERT INTO products (product, model_code, year) VALUES (?, ?, ?)",
            (_MC, _MC, _YEAR),
        )
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


def _post_value(client, field_path, value):
    return client.post(
        "/api/value",
        json={
            "model_code": _MC,
            "year": _YEAR,
            "field_path": field_path,
            "value": value,
            "status": "manual",
            "entered_by": "pytest",
        },
    )


def _read_value(client, field_path):
    resp = client.get(
        "/api/value/history",
        params={"model_code": _MC, "year": _YEAR, "field_path": field_path},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["value"]


def test_bool_field_string_true_stays_bool(client):
    # Seed a real bool (JSON true), then commit the string the UI box sends —
    # the annotation-only round-trip that used to corrupt true -> "true".
    assert _post_value(client, "has_subwoofer", True).status_code == 200
    resp = _post_value(client, "has_subwoofer", "true")
    assert resp.status_code == 200, resp.text
    assert resp.json()["after"]["value"] is True
    assert _read_value(client, "has_subwoofer") is True


def test_bool_field_garbage_string_is_400_and_unchanged(client):
    assert _post_value(client, "has_subwoofer", True).status_code == 200
    resp = _post_value(client, "has_subwoofer", "banana")
    assert resp.status_code == 400
    assert "boolean" in resp.json()["detail"]
    assert _read_value(client, "has_subwoofer") is True


def test_int_field_string_coerces_to_int(client):
    assert _post_value(client, "memory_max_gb", 64).status_code == 200
    resp = _post_value(client, "memory_max_gb", "32")
    assert resp.status_code == 200, resp.text
    assert resp.json()["after"]["value"] == 32
    stored = _read_value(client, "memory_max_gb")
    assert stored == 32
    assert isinstance(stored, int)


def test_str_field_true_string_stays_string(client):
    # A str cell must NOT be over-coerced — "true" stays the literal string.
    assert _post_value(client, "audio_jack", "3.5mm combo").status_code == 200
    resp = _post_value(client, "audio_jack", "true")
    assert resp.status_code == 200, resp.text
    assert resp.json()["after"]["value"] == "true"
    assert _read_value(client, "audio_jack") == "true"
