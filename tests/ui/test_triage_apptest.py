"""T8.8 — AppTest write-path coverage for the triage screen.

Seeds one ``value_disagreement`` review_queue row, drives "Accept
candidate" via AppTest, asserts the resolve_row library handler ran
and the candidate bundle landed in the products cell.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from competitive_database.db.connection import connect, transaction
from competitive_database.db.helpers import make_scraped_bundle, write_scalar
from tests.ui.conftest import APP_SCRIPT


_PK = {"model_code": "alienware-m18", "year": 2026}
_FIELD = "series"
_EXISTING = "Alienware m18"
_CANDIDATE = "Alienware m18 R2"


def _scraped(value):
    return make_scraped_bundle(
        value=value,
        source_url="https://www.dell.com/test",
        captured_at="2026-05-07T00:00:00+00:00",
        scraper_id="test",
    )


def _seed_value_disagreement(db_path) -> int:
    conn = connect(db_path)
    try:
        with transaction(conn):
            existing_bundle = _scraped(_EXISTING)
            candidate_bundle = _scraped(_CANDIDATE)
            write_scalar(conn, "products", _PK, _FIELD, existing_bundle)
            cur = conn.execute(
                """
                INSERT INTO review_queue (
                    product_model_code, product_year, field_path,
                    conflict_type, existing_value, existing_provenance,
                    candidate_value, candidate_provenance, detected_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _PK["model_code"], _PK["year"], _FIELD,
                    "value_disagreement",
                    json.dumps(_EXISTING), json.dumps(existing_bundle),
                    json.dumps(_CANDIDATE), json.dumps(candidate_bundle),
                    "2026-05-07T00:00:00+00:00",
                ),
            )
            row_id = cur.lastrowid
    finally:
        conn.close()
    return row_id


def test_triage_accept_candidate_resolves_and_writes_through(empty_db):
    row_id = _seed_value_disagreement(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "queue"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    accept = next(
        (b for b in at.button if b.label == "Accept candidate"),
        None,
    )
    assert accept is not None, (
        "expected an 'Accept candidate' button on the seeded queue row; "
        f"saw labels={[b.label for b in at.button]}"
    )
    accept.click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    success_msgs = [s.value for s in at.success]
    assert any(
        f"Row #{row_id}" in m and "accept_candidate" in m
        for m in success_msgs
    ), f"missing resolve confirmation banner; saw {success_msgs}"
    assert any("Queue empty" in m for m in success_msgs), (
        f"expected 'Queue empty' banner after the only row resolved; "
        f"saw {success_msgs}"
    )

    conn = connect(empty_db)
    try:
        resolved_at = conn.execute(
            "SELECT resolved_at FROM review_queue WHERE id = ?", (row_id,)
        ).fetchone()[0]
        assert resolved_at is not None, "queue row not marked resolved"

        cell_raw = conn.execute(
            f"SELECT {_FIELD} FROM products "
            "WHERE model_code = ? AND year = ?",
            (_PK["model_code"], _PK["year"]),
        ).fetchone()[0]
        bundle = json.loads(cell_raw)
        assert bundle["value"] == _CANDIDATE, (
            f"candidate not written through; cell now {bundle!r}"
        )
    finally:
        conn.close()
