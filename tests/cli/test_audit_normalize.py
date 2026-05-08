"""Stage 6 happy-path tests for ``audit-normalize``."""

from __future__ import annotations

import argparse

from competitive_database.cli import audit_normalize
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    write_offerings,
    write_scalar,
)


def _fresh_db(tmp_path):
    conn = connect(tmp_path / "an.db")
    with transaction(conn):
        apply_schema(conn)
    return conn


def _scraped(value):
    return make_scraped_bundle(
        value=value,
        source_url="https://example.com",
        captured_at="2026-05-08T00:00:00+00:00",
        scraper_id="test",
    )


def test_audit_surfaces_string_gap(tmp_path, capsys):
    """Two products with different spellings of Wi-Fi 7 → flagged as a gap."""
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(
                conn,
                "products",
                {"model_code": "alpha", "year": 2026},
                "wifi_standard",
                _scraped("Wi-Fi 7"),
            )
            write_scalar(
                conn,
                "products",
                {"model_code": "beta", "year": 2026},
                "wifi_standard",
                _scraped("WiFi 7"),
            )
            # Same value across products on a different field — should NOT show
            # under default (gaps only).
            write_scalar(
                conn,
                "products",
                {"model_code": "alpha", "year": 2026},
                "audio_jack",
                _scraped("yes"),
            )
            write_scalar(
                conn,
                "products",
                {"model_code": "beta", "year": 2026},
                "audio_jack",
                _scraped("yes"),
            )
    finally:
        conn.close()

    args = argparse.Namespace(db=str(tmp_path / "an.db"), all=False, strings_only=False)
    audit_normalize.main(args)
    out = capsys.readouterr().out

    assert "1 path(s) with more than one distinct value" in out
    assert "wifi_standard" in out
    assert "'Wi-Fi 7'" in out
    assert "'WiFi 7'" in out
    # audio_jack is uniform → not in gap-only output
    assert "audio_jack" not in out


def test_audit_no_gaps_when_uniform(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(
                conn,
                "products",
                {"model_code": "alpha", "year": 2026},
                "wifi_standard",
                _scraped("Wi-Fi 7"),
            )
            write_scalar(
                conn,
                "products",
                {"model_code": "beta", "year": 2026},
                "wifi_standard",
                _scraped("Wi-Fi 7"),
            )
    finally:
        conn.close()

    args = argparse.Namespace(db=str(tmp_path / "an.db"), all=False, strings_only=False)
    audit_normalize.main(args)
    out = capsys.readouterr().out
    assert "no normalization gaps across 2 product(s)" in out


def test_audit_all_lists_every_path(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(
                conn,
                "products",
                {"model_code": "alpha", "year": 2026},
                "wifi_standard",
                _scraped("Wi-Fi 7"),
            )
    finally:
        conn.close()

    args = argparse.Namespace(db=str(tmp_path / "an.db"), all=True, strings_only=False)
    audit_normalize.main(args)
    out = capsys.readouterr().out
    assert "wifi_standard" in out


def test_audit_offering_leaves_aggregate_across_products(tmp_path, capsys):
    """A leaf inside an offerings list should aggregate across products at the
    same path index. e.g. display_offerings.0.panel_type."""
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_offerings(
                conn,
                "products",
                {"model_code": "alpha", "year": 2026},
                "display_offerings",
                [{"panel_type": _scraped("OLED")}],
            )
            write_offerings(
                conn,
                "products",
                {"model_code": "beta", "year": 2026},
                "display_offerings",
                [{"panel_type": _scraped("oled")}],
            )
    finally:
        conn.close()

    args = argparse.Namespace(db=str(tmp_path / "an.db"), all=False, strings_only=False)
    audit_normalize.main(args)
    out = capsys.readouterr().out
    assert "display_offerings.0.panel_type" in out
    assert "'OLED'" in out
    assert "'oled'" in out


def test_audit_skips_vendor_doesnt_publish(tmp_path, capsys):
    """vendor-doesn't-publish bundles should not contribute to value distinct set."""
    conn = _fresh_db(tmp_path)
    try:
        from competitive_database.db.helpers import make_vendor_doesnt_publish_bundle

        with transaction(conn):
            write_scalar(
                conn,
                "products",
                {"model_code": "alpha", "year": 2026},
                "wifi_standard",
                _scraped("Wi-Fi 7"),
            )
            write_scalar(
                conn,
                "products",
                {"model_code": "beta", "year": 2026},
                "wifi_standard",
                make_vendor_doesnt_publish_bundle(
                    source_url="https://example.com",
                    captured_at="2026-05-08T00:00:00+00:00",
                    scraper_id="test",
                ),
            )
    finally:
        conn.close()

    args = argparse.Namespace(db=str(tmp_path / "an.db"), all=False, strings_only=False)
    audit_normalize.main(args)
    out = capsys.readouterr().out
    # Only one product contributes a value → uniform → no gap
    assert "no normalization gaps" in out


def test_audit_empty_db(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    conn.close()

    args = argparse.Namespace(db=str(tmp_path / "an.db"), all=False, strings_only=False)
    audit_normalize.main(args)
    out = capsys.readouterr().out
    assert "(no products in DB)" in out
