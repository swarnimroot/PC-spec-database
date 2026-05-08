"""Stage 5 happy-path tests for ``manual-edit``."""

from __future__ import annotations

import argparse

import pytest

from competitive_database.cli import manual_edit
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    read_offerings,
    read_scalar,
    write_offerings,
    write_scalar,
)


_PK = {"model_code": "alienware-m18", "year": 2026}


def _fresh_db(tmp_path):
    conn = connect(tmp_path / "me.db")
    with transaction(conn):
        apply_schema(conn)
    return conn


def _scraped(value):
    return make_scraped_bundle(
        value=value,
        source_url="https://example.com",
        captured_at="2026-05-07T00:00:00+00:00",
        scraper_id="test",
    )


def test_manual_edit_writes_scalar(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    try:
        # Need at least one column written for the row to exist.
        with transaction(conn):
            write_scalar(conn, "products", _PK, "brand", _scraped("Alienware"))
    finally:
        conn.close()

    args = argparse.Namespace(
        product="alienware-m18",
        year=2026,
        field="audio_jack",
        value="yes",
        value_json=None,
        note="DisplayMate review",
        status="vouched",
        entered_by="tester",
        db=str(tmp_path / "me.db"),
    )
    manual_edit.main(args)

    conn = connect(tmp_path / "me.db")
    try:
        bundle = read_scalar(conn, "products", _PK, "audio_jack")
    finally:
        conn.close()

    assert bundle is not None
    assert bundle["value"] == "yes"
    assert bundle["status"] == "vouched"
    assert bundle["entered_by"] == "tester"
    assert bundle["source_note"] == "DisplayMate review"
    assert "entered_at" in bundle

    out = capsys.readouterr().out
    assert "manual-edit OK" in out
    assert "before: (empty)" in out
    assert "value='yes'" in out


def test_manual_edit_value_int_coercion(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(conn, "products", _PK, "brand", _scraped("Alienware"))
    finally:
        conn.close()

    args = argparse.Namespace(
        product="alienware-m18",
        year=2026,
        field="cpu_tdp_max",
        value="200",
        value_json=None,
        note=None,
        status="vouched",
        entered_by="tester",
        db=str(tmp_path / "me.db"),
    )
    manual_edit.main(args)

    conn = connect(tmp_path / "me.db")
    try:
        bundle = read_scalar(conn, "products", _PK, "cpu_tdp_max")
    finally:
        conn.close()
    assert bundle["value"] == 200  # coerced to int, not string


def test_manual_edit_value_json_bool(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(conn, "products", _PK, "brand", _scraped("Alienware"))
    finally:
        conn.close()

    args = argparse.Namespace(
        product="alienware-m18",
        year=2026,
        field="audio_jack",
        value=None,
        value_json="true",
        note=None,
        status="vouched",
        entered_by="tester",
        db=str(tmp_path / "me.db"),
    )
    manual_edit.main(args)

    conn = connect(tmp_path / "me.db")
    try:
        bundle = read_scalar(conn, "products", _PK, "audio_jack")
    finally:
        conn.close()
    assert bundle["value"] is True


def test_manual_edit_writes_offering_leaf(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        offerings = [{"size_inches": _scraped(18)}]  # offering 0 exists, no nits_peak
        with transaction(conn):
            write_offerings(conn, "products", _PK, "display_offerings", offerings)
            write_scalar(conn, "products", _PK, "brand", _scraped("Alienware"))
    finally:
        conn.close()

    args = argparse.Namespace(
        product="alienware-m18",
        year=2026,
        field="display_offerings.0.nits_peak",
        value="600",
        value_json=None,
        note=None,
        status="vouched",
        entered_by="tester",
        db=str(tmp_path / "me.db"),
    )
    manual_edit.main(args)

    conn = connect(tmp_path / "me.db")
    try:
        offerings = read_offerings(conn, "products", _PK, "display_offerings")
    finally:
        conn.close()
    assert offerings is not None
    assert offerings[0]["nits_peak"]["value"] == 600
    assert offerings[0]["nits_peak"]["entered_by"] == "tester"
    # Sibling leaf untouched
    assert offerings[0]["size_inches"]["value"] == 18


def test_manual_edit_rejects_catalog_path(tmp_path):
    conn = _fresh_db(tmp_path)
    conn.close()

    args = argparse.Namespace(
        product="alienware-m18",
        year=2026,
        field="cpu_catalog.X.architecture",
        value="Lunar Lake",
        value_json=None,
        note=None,
        status="vouched",
        entered_by="tester",
        db=str(tmp_path / "me.db"),
    )
    with pytest.raises(SystemExit) as exc:
        manual_edit.main(args)
    assert "catalog" in str(exc.value)


def test_manual_edit_rejects_pk_path(tmp_path):
    conn = _fresh_db(tmp_path)
    conn.close()

    args = argparse.Namespace(
        product="alienware-m18",
        year=2026,
        field="model_code",
        value="x",
        value_json=None,
        note=None,
        status="vouched",
        entered_by="tester",
        db=str(tmp_path / "me.db"),
    )
    with pytest.raises(SystemExit):
        manual_edit.main(args)
