"""Stage 7 T7.0a M5 — ``backfill-lenovo-families`` CLI.

One-time backfill that derives ``family_code`` / ``source_model_codes`` /
``arch_marker`` from data already in the DB for Lenovo rows ingested
before the M2+M3 bridge work landed. Tests here cover the CLI command's
behaviour end-to-end; the per-row derivation is exercised in
``test_lenovo_bridge.py`` and the merge plumbing in ``test_lenovo_merge.py``.
"""

from __future__ import annotations

import argparse
import json

from competitive_database.cli import backfill_lenovo_families
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    write_offerings,
    write_scalar,
)


_CAPTURED = "2026-05-08T12:00:00+00:00"
_SCRAPER = "lenovo.fetch_lenovo_product"
_URL_INTEL = (
    "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16IRX10"
)
_URL_AMD = "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16ADR10"


def _scraped(value, *, source_url=_URL_INTEL, status="verified", scraper_id=_SCRAPER):
    return make_scraped_bundle(
        value=value,
        source_url=source_url,
        captured_at=_CAPTURED,
        scraper_id=scraper_id,
        status=status,
    )


def _board(label, gpus, *, source_url=_URL_INTEL):
    """Pre-backfill shape: no ``arch_marker``."""
    return {
        "label": _scraped(label, source_url=source_url),
        "tpp_max": _scraped(None, source_url=source_url, status="vendor-doesn't-publish"),
        "tgp_max": _scraped(None, source_url=source_url, status="vendor-doesn't-publish"),
        "gpus": [_scraped(g, source_url=source_url) for g in gpus],
    }


def _seed_legacy_lenovo_row(
    conn,
    *,
    model_code,
    year,
    title,
    source_url,
    boards=None,
    extra_scalars=None,
):
    """Write a Lenovo row in pre-backfill shape: family_code NULL,
    source_model_codes NULL, boards without arch_marker."""
    pk = {"model_code": model_code, "year": year}
    with transaction(conn):
        write_scalar(
            conn, "products", pk, "vendor_full_name",
            _scraped(title, source_url=source_url),
        )
        write_scalar(
            conn, "products", pk, "brand",
            _scraped("Lenovo", source_url=source_url),
        )
        if boards is not None:
            write_offerings(conn, "products", pk, "boards", boards)
        if extra_scalars:
            for col, bundle in extra_scalars.items():
                write_scalar(conn, "products", pk, col, bundle)


def _fresh_db(tmp_path):
    conn = connect(tmp_path / "backfill.db")
    with transaction(conn):
        apply_schema(conn)
    return conn


def _run(tmp_path):
    args = argparse.Namespace(db=str(tmp_path / "backfill.db"))
    backfill_lenovo_families.main(args)


# ---------------------------------------------------------------------------
# 1. Empty DB / no Lenovo rows
# ---------------------------------------------------------------------------


def test_empty_db_runs_clean(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "no Lenovo rows without family_code" in out


def test_no_lenovo_rows_runs_clean(tmp_path, capsys):
    """An ASUS-only DB has no Lenovo rows; backfill is a no-op."""
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            write_scalar(
                conn, "products",
                {"model_code": "rog-zephyrus-g16-2026", "year": 2026},
                "brand",
                _scraped("ASUS", source_url="https://rog.asus.com/"),
            )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "no Lenovo rows without family_code" in out


# ---------------------------------------------------------------------------
# 2. All Lenovo rows already have family_code → idempotent
# ---------------------------------------------------------------------------


def test_already_backfilled_rows_are_skipped(tmp_path, capsys):
    """Lenovo rows already carrying family_code are excluded from the
    candidate set — the command reports zero work to do."""
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            pk = {"model_code": "legion-pro-5-16-gen-10", "year": 2025}
            write_scalar(
                conn, "products", pk, "vendor_full_name",
                _scraped("Lenovo Legion Pro 5 16IRX10", source_url=_URL_INTEL),
            )
            write_scalar(
                conn, "products", pk, "brand",
                _scraped("Lenovo", source_url=_URL_INTEL),
            )
            conn.execute(
                "UPDATE products SET family_code = ?, source_model_codes = ? "
                "WHERE model_code = ? AND year = ?",
                (
                    "legion-pro-5-16-gen-10",
                    json.dumps(["16IRX10"]),
                    "legion-pro-5-16-gen-10",
                    2025,
                ),
            )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "no Lenovo rows without family_code" in out


# ---------------------------------------------------------------------------
# 3. Single Lenovo row, parseable slug → in-place update
# ---------------------------------------------------------------------------


def test_single_row_in_place_update(tmp_path, capsys):
    """16IRX10 → legion-pro-5-16-gen-10, intel-rtx. model_code renamed,
    family_code stamped, source_model_codes=[16IRX10], boards now carry
    arch_marker on every entry."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_lenovo_row(
            conn,
            model_code="16IRX10",
            year=2025,
            title="Lenovo Legion Pro 5 16IRX10",
            source_url=_URL_INTEL,
            boards=[_board("MB1", ["RTX 5070"], source_url=_URL_INTEL)],
        )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "Parseable: 1" in out
    assert "16IRX10 -> family legion-pro-5-16-gen-10" in out
    assert "1 product(s) updated" in out

    # Re-open and verify the DB.
    conn = connect(tmp_path / "backfill.db")
    try:
        row = conn.execute(
            "SELECT model_code, family_code, source_model_codes, boards "
            "FROM products"
        ).fetchone()
        assert row["model_code"] == "legion-pro-5-16-gen-10"
        assert row["family_code"] == "legion-pro-5-16-gen-10"
        assert json.loads(row["source_model_codes"]) == ["16IRX10"]
        boards = json.loads(row["boards"])
        assert len(boards) == 1
        assert boards[0]["arch_marker"] == "intel-rtx"
        # Original board leaves still intact
        assert boards[0]["label"]["value"] == "MB1"
        assert [g["value"] for g in boards[0]["gpus"]] == ["RTX 5070"]

        # The legacy PK row should be gone.
        legacy = conn.execute(
            "SELECT COUNT(*) FROM products WHERE model_code = ?", ("16IRX10",)
        ).fetchone()[0]
        assert legacy == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Two rows sharing a family → merged
# ---------------------------------------------------------------------------


def test_two_rows_sharing_family_merge(tmp_path, capsys):
    """16IRX10 + 16ADR10 → one row with 2 boards, source_model_codes
    union (sorted), 16ADR10 deleted (it sorts after 16IRX10 in alphabetic
    order, so canonical = 16IRX10)."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_lenovo_row(
            conn,
            model_code="16IRX10",
            year=2025,
            title="Lenovo Legion Pro 5 16IRX10",
            source_url=_URL_INTEL,
            boards=[_board("MB1", ["RTX 5070"], source_url=_URL_INTEL)],
        )
        _seed_legacy_lenovo_row(
            conn,
            model_code="16ADR10",
            year=2025,
            title="Lenovo Legion Pro 5 16ADR10",
            source_url=_URL_AMD,
            boards=[_board("MB1", ["Radeon RX 8060S"], source_url=_URL_AMD)],
        )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "Parseable: 2" in out
    assert "1 merge group" in out
    assert "legion-pro-5-16-gen-10" in out
    assert "1 product(s) updated, 1 row(s) deleted" in out

    conn = connect(tmp_path / "backfill.db")
    try:
        rows = conn.execute(
            "SELECT model_code, family_code, source_model_codes, boards "
            "FROM products"
        ).fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["model_code"] == "legion-pro-5-16-gen-10"
        assert row["family_code"] == "legion-pro-5-16-gen-10"
        assert json.loads(row["source_model_codes"]) == ["16ADR10", "16IRX10"]
        boards = json.loads(row["boards"])
        # Two boards keyed by (label="MB1", arch). _merge_boards keeps
        # them distinct because arch_marker differs.
        assert len(boards) == 2
        arches = {b["arch_marker"] for b in boards}
        assert arches == {"intel-rtx", "amd-radeon"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. Unparseable slug → row left untouched
# ---------------------------------------------------------------------------


def test_unparseable_slug_left_alone(tmp_path, capsys):
    """A bare alphanumeric like ``21A0`` (PSREF machine-type code that
    doesn't match the compressed-slug regex) leaves the row as-is."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_lenovo_row(
            conn,
            model_code="21A0",
            year=2024,
            title="Lenovo 21A0",
            source_url="https://psref.lenovo.com/l/Product/Other/21A0",
        )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "Parseable: 0" in out
    assert "Unparseable (left untouched): 1" in out
    assert "21A0 -> unparseable" in out

    conn = connect(tmp_path / "backfill.db")
    try:
        row = conn.execute(
            "SELECT model_code, family_code, source_model_codes FROM products"
        ).fetchone()
        assert row["model_code"] == "21A0"
        assert row["family_code"] is None
        assert row["source_model_codes"] is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. Non-Lenovo rows are not touched
# ---------------------------------------------------------------------------


def test_non_lenovo_rows_not_touched(tmp_path, capsys):
    """An ASUS row stays exactly as it was — the backfill only filters on
    Lenovo via the brand bundle."""
    conn = _fresh_db(tmp_path)
    try:
        asus_pk = {"model_code": "rog-zephyrus-g16-2026", "year": 2026}
        with transaction(conn):
            write_scalar(
                conn, "products", asus_pk, "vendor_full_name",
                _scraped("ASUS ROG Zephyrus G16 (2026)",
                         source_url="https://rog.asus.com/.../spec/",
                         scraper_id="asus.fetch_asus_product"),
            )
            write_scalar(
                conn, "products", asus_pk, "brand",
                _scraped("ASUS",
                         source_url="https://rog.asus.com/.../spec/",
                         scraper_id="asus.fetch_asus_product"),
            )
        # And one parseable Lenovo row to verify the filter is by brand,
        # not "do nothing".
        _seed_legacy_lenovo_row(
            conn,
            model_code="16IRX10",
            year=2025,
            title="Lenovo Legion Pro 5 16IRX10",
            source_url=_URL_INTEL,
            boards=[_board("MB1", ["RTX 5070"], source_url=_URL_INTEL)],
        )
    finally:
        conn.close()

    _run(tmp_path)

    conn = connect(tmp_path / "backfill.db")
    try:
        asus = conn.execute(
            "SELECT model_code, family_code, source_model_codes FROM products "
            "WHERE model_code = ?", ("rog-zephyrus-g16-2026",),
        ).fetchone()
        assert asus is not None
        assert asus["family_code"] is None
        assert asus["source_model_codes"] is None
        lenovo = conn.execute(
            "SELECT model_code, family_code FROM products "
            "WHERE model_code = ?", ("legion-pro-5-16-gen-10",),
        ).fetchone()
        assert lenovo is not None
        assert lenovo["family_code"] == "legion-pro-5-16-gen-10"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. Re-run is idempotent
# ---------------------------------------------------------------------------


def test_rerun_is_idempotent(tmp_path, capsys):
    """First run does the work; second run is a no-op."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_lenovo_row(
            conn,
            model_code="16IRX10",
            year=2025,
            title="Lenovo Legion Pro 5 16IRX10",
            source_url=_URL_INTEL,
            boards=[_board("MB1", ["RTX 5070"], source_url=_URL_INTEL)],
        )
        _seed_legacy_lenovo_row(
            conn,
            model_code="16ADR10",
            year=2025,
            title="Lenovo Legion Pro 5 16ADR10",
            source_url=_URL_AMD,
            boards=[_board("MB1", ["Radeon RX 8060S"], source_url=_URL_AMD)],
        )
    finally:
        conn.close()

    _run(tmp_path)
    first_out = capsys.readouterr().out
    assert "1 product(s) updated" in first_out

    # Snapshot DB state, run again, confirm unchanged.
    conn = connect(tmp_path / "backfill.db")
    try:
        before = conn.execute(
            "SELECT model_code, year, family_code, source_model_codes, boards "
            "FROM products ORDER BY model_code"
        ).fetchall()
        before_tuples = [tuple(r) for r in before]
    finally:
        conn.close()

    _run(tmp_path)
    second_out = capsys.readouterr().out
    assert "no Lenovo rows without family_code" in second_out

    conn = connect(tmp_path / "backfill.db")
    try:
        after = conn.execute(
            "SELECT model_code, year, family_code, source_model_codes, boards "
            "FROM products ORDER BY model_code"
        ).fetchall()
        after_tuples = [tuple(r) for r in after]
    finally:
        conn.close()

    assert before_tuples == after_tuples


# ---------------------------------------------------------------------------
# 8. Scalar conflict during merge → enqueued
# ---------------------------------------------------------------------------


def test_scalar_conflict_during_merge_enqueues(tmp_path, capsys):
    """Two rows in the same family with disagreeing ``weight_kg_max`` →
    merge proceeds with canonical's value kept; the disagreement is
    queued as a ``value_disagreement`` against the merged (family_code,
    year) PK."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_lenovo_row(
            conn,
            model_code="16IRX10",
            year=2025,
            title="Lenovo Legion Pro 5 16IRX10",
            source_url=_URL_INTEL,
            boards=[_board("MB1", ["RTX 5070"], source_url=_URL_INTEL)],
            extra_scalars={"weight_kg_max": _scraped(2.5, source_url=_URL_INTEL)},
        )
        _seed_legacy_lenovo_row(
            conn,
            model_code="16ADR10",
            year=2025,
            title="Lenovo Legion Pro 5 16ADR10",
            source_url=_URL_AMD,
            boards=[_board("MB1", ["Radeon RX 8060S"], source_url=_URL_AMD)],
            extra_scalars={"weight_kg_max": _scraped(2.6, source_url=_URL_AMD)},
        )
    finally:
        conn.close()

    _run(tmp_path)

    conn = connect(tmp_path / "backfill.db")
    try:
        # Canonical is the alphabetic-first machine code (16ADR10 < 16IRX10),
        # so its weight (2.6) is the kept value.
        bundle_raw = conn.execute(
            "SELECT weight_kg_max FROM products WHERE model_code = ?",
            ("legion-pro-5-16-gen-10",),
        ).fetchone()[0]
        assert json.loads(bundle_raw)["value"] == 2.6

        queued = conn.execute(
            "SELECT product_model_code, product_year, field_path, "
            "conflict_type, existing_value, candidate_value "
            "FROM review_queue WHERE field_path = 'weight_kg_max'"
        ).fetchall()
        assert len(queued) == 1
        q = queued[0]
        assert q["product_model_code"] == "legion-pro-5-16-gen-10"
        assert q["product_year"] == 2025
        assert q["conflict_type"] == "value_disagreement"
        assert json.loads(q["existing_value"])["value"] == 2.6
        assert json.loads(q["candidate_value"])["value"] == 2.5
    finally:
        conn.close()
