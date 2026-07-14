"""``backfill-asus-families`` CLI.

One-time backfill for ASUS TUF rows ingested before the T9.3 bridge
derivation. Structure mirrors ``test_backfill_dell_families.py``; the
ASUS-specific behaviour under test is the ``source_model_codes``
union-not-overwrite (Stage-11-audited sibling codes must survive the
rename) and the TUF-only scope (ROG slugs untouched).
"""

from __future__ import annotations

import argparse
import json

from competitive_database.cli import backfill_asus_families
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    write_model_code,
    write_offerings,
    write_scalar,
)


_CAPTURED = "2026-05-13T12:00:00+00:00"
_SCRAPER = "asus.fetch_asus_product"
_URL_F16 = "https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-f16-2024/techspec/"
_URL_A16 = "https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a16-2024/techspec/"


def _scraped(value, *, source_url=_URL_F16, status="verified", scraper_id=_SCRAPER):
    return make_scraped_bundle(
        value=value,
        source_url=source_url,
        captured_at=_CAPTURED,
        scraper_id=scraper_id,
        status=status,
    )


def _board(label, gpus, *, source_url=_URL_F16):
    """Pre-backfill shape: no ``arch_marker``."""
    return {
        "label": _scraped(label, source_url=source_url),
        "tpp_max": _scraped(None, source_url=source_url, status="vendor-doesn't-publish"),
        "tgp_max": _scraped(None, source_url=source_url, status="vendor-doesn't-publish"),
        "gpus": [_scraped(g, source_url=source_url) for g in gpus],
    }


def _seed_legacy_asus_row(
    conn,
    *,
    model_code,
    year,
    product=None,
    source_url=_URL_F16,
    boards=None,
    source_model_codes=None,
):
    """Write an ASUS row in pre-backfill shape: family_code NULL, but
    (unlike Lenovo/Dell legacy rows) possibly carrying Stage-11-audited
    ``source_model_codes``."""
    pk = {"product": product or model_code, "year": year}
    with transaction(conn):
        write_scalar(
            conn, "products", pk, "brand",
            _scraped("ASUS", source_url=source_url),
        )
        write_model_code(conn, pk, model_code)
        if boards is not None:
            write_offerings(conn, "products", pk, "boards", boards)
        if source_model_codes is not None:
            conn.execute(
                "UPDATE products SET source_model_codes = ? "
                "WHERE model_code = ? AND year = ?",
                (json.dumps(source_model_codes), model_code, year),
            )


def _fresh_db(tmp_path):
    conn = connect(tmp_path / "backfill.db")
    with transaction(conn):
        apply_schema(conn)
    return conn


def _run(tmp_path):
    args = argparse.Namespace(db=str(tmp_path / "backfill.db"))
    backfill_asus_families.main(args)


# ---------------------------------------------------------------------------
# 1. Empty DB / TUF rename with audited codes preserved
# ---------------------------------------------------------------------------


def test_empty_db_runs_clean(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "no ASUS rows without family_code" in out


def test_tuf_rename_preserves_audited_sibling_codes(tmp_path, capsys):
    """The real-DB shape: one hand-merged TUF row whose source_model_codes
    already lists the A16 siblings. The rename must keep them — the shared
    apply helper would overwrite with just the F16 slug."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_asus_row(
            conn,
            model_code="asus-tuf-gaming-f16-2024",
            year=2024,
            product="TUF 16",
            boards=[_board("MB3", ["RTX 4050"])],
            source_model_codes=[
                "asus-tuf-gaming-f16-2024",
                "asus-tuf-gaming-a16-2024",
                "asus-tuf-gaming-a16-2024-fa608",
            ],
        )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "Parseable: 1" in out
    assert "asus-tuf-gaming-f16-2024 -> family asus-tuf-gaming-16-2024, arch intel" in out
    assert "1 product(s) updated" in out

    conn = connect(tmp_path / "backfill.db")
    try:
        row = conn.execute(
            "SELECT model_code, product, family_code, source_model_codes, boards "
            "FROM products"
        ).fetchone()
        assert row["model_code"] == "asus-tuf-gaming-16-2024"
        assert row["product"] == "TUF 16"
        assert row["family_code"] == "asus-tuf-gaming-16-2024"
        # Audited codes survive verbatim (F16 slug already among them).
        assert json.loads(row["source_model_codes"]) == [
            "asus-tuf-gaming-f16-2024",
            "asus-tuf-gaming-a16-2024",
            "asus-tuf-gaming-a16-2024-fa608",
        ]
        boards = json.loads(row["boards"])
        assert boards[0]["arch_marker"] == "intel"
    finally:
        conn.close()


def test_tuf_rename_without_audited_codes_gets_own_slug(tmp_path, capsys):
    """A row with source_model_codes NULL (never audited) ends up with the
    standard single-element list, same as the Lenovo/Dell backfills."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_asus_row(
            conn,
            model_code="asus-tuf-gaming-a18-2025",
            year=2025,
            product="TUF 18",
        )
    finally:
        conn.close()

    _run(tmp_path)

    conn = connect(tmp_path / "backfill.db")
    try:
        row = conn.execute(
            "SELECT model_code, family_code, source_model_codes FROM products"
        ).fetchone()
        assert row["model_code"] == "asus-tuf-gaming-18-2025"
        assert row["family_code"] == "asus-tuf-gaming-18-2025"
        assert json.loads(row["source_model_codes"]) == ["asus-tuf-gaming-a18-2025"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Two un-merged sibling rows → merged (codes unioned across both)
# ---------------------------------------------------------------------------


def test_sibling_rows_merge_and_union_codes(tmp_path, capsys):
    """F16 + A16 rows that were never hand-merged collapse into one row;
    boards stay distinct via arch_marker; codes union across members."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_asus_row(
            conn,
            model_code="asus-tuf-gaming-f16-2024",
            year=2024,
            source_url=_URL_F16,
            boards=[_board("MB3", ["RTX 4050"], source_url=_URL_F16)],
            source_model_codes=["asus-tuf-gaming-f16-2024"],
        )
        _seed_legacy_asus_row(
            conn,
            model_code="asus-tuf-gaming-a16-2024",
            year=2024,
            source_url=_URL_A16,
            boards=[_board("MB3", ["RTX 4060"], source_url=_URL_A16)],
            source_model_codes=["asus-tuf-gaming-a16-2024"],
        )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "1 merge group" in out
    assert "1 product(s) updated, 1 row(s) deleted" in out

    conn = connect(tmp_path / "backfill.db")
    try:
        rows = conn.execute(
            "SELECT model_code, family_code, source_model_codes, boards "
            "FROM products"
        ).fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["model_code"] == "asus-tuf-gaming-16-2024"
        codes = json.loads(row["source_model_codes"])
        assert sorted(codes) == [
            "asus-tuf-gaming-a16-2024",
            "asus-tuf-gaming-f16-2024",
        ]
        boards = json.loads(row["boards"])
        assert len(boards) == 2
        assert {b["arch_marker"] for b in boards} == {"intel", "amd"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. ROG / suffixed slugs left untouched; queue remap; idempotence
# ---------------------------------------------------------------------------


def test_rog_and_suffixed_slugs_left_alone(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_asus_row(
            conn,
            model_code="rog-strix-g16-2026",
            year=2026,
            source_url="https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2026/spec/",
        )
        _seed_legacy_asus_row(
            conn,
            model_code="asus-tuf-gaming-a14-2026-fa401ea",
            year=2026,
        )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "Unparseable (left untouched): 2" in out

    conn = connect(tmp_path / "backfill.db")
    try:
        for mc in ("rog-strix-g16-2026", "asus-tuf-gaming-a14-2026-fa401ea"):
            row = conn.execute(
                "SELECT family_code FROM products WHERE model_code = ?", (mc,)
            ).fetchone()
            assert row is not None
            assert row["family_code"] is None
    finally:
        conn.close()


def test_queue_rows_remap_on_rename(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_asus_row(
            conn,
            model_code="asus-tuf-gaming-f16-2025",
            year=2025,
        )
        with transaction(conn):
            conn.execute(
                "INSERT INTO review_queue (product_model_code, product_year, "
                "field_path, conflict_type, detected_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "asus-tuf-gaming-f16-2025", 2025,
                    "vendor_full_name", "year_inferred", _CAPTURED,
                ),
            )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "1 unresolved review_queue row(s) re-pointed" in out

    conn = connect(tmp_path / "backfill.db")
    try:
        row = conn.execute(
            "SELECT product_model_code FROM review_queue"
        ).fetchone()
        assert row["product_model_code"] == "asus-tuf-gaming-16-2025"
    finally:
        conn.close()


def test_rerun_is_idempotent(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_asus_row(
            conn,
            model_code="asus-tuf-gaming-f16-2024",
            year=2024,
            boards=[_board("MB3", ["RTX 4050"])],
            source_model_codes=[
                "asus-tuf-gaming-f16-2024",
                "asus-tuf-gaming-a16-2024",
            ],
        )
    finally:
        conn.close()

    _run(tmp_path)
    first_out = capsys.readouterr().out
    assert "1 product(s) updated" in first_out

    conn = connect(tmp_path / "backfill.db")
    try:
        before = [
            tuple(r)
            for r in conn.execute(
                "SELECT model_code, year, family_code, source_model_codes, boards "
                "FROM products ORDER BY model_code"
            ).fetchall()
        ]
    finally:
        conn.close()

    _run(tmp_path)
    second_out = capsys.readouterr().out
    assert "no ASUS rows without family_code" in second_out

    conn = connect(tmp_path / "backfill.db")
    try:
        after = [
            tuple(r)
            for r in conn.execute(
                "SELECT model_code, year, family_code, source_model_codes, boards "
                "FROM products ORDER BY model_code"
            ).fetchall()
        ]
    finally:
        conn.close()

    assert before == after
