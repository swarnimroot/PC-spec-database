"""``backfill-dell-families`` CLI.

One-time backfill that derives ``family_code`` / ``source_model_codes`` /
``arch_marker`` for Dell rows ingested before the Dell bridge merge
derivation landed. Tests here cover the CLI command's behaviour
end-to-end; the per-code derivation is exercised in
``tests/bridge/test_dell.py``. Structure mirrors
``test_backfill_lenovo_families.py``; the Dell-specific additions are the
SKU-digit rule (0=Intel / 5=AMD) and the unresolved review_queue remap.
"""

from __future__ import annotations

import argparse
import json

from competitive_database.cli import backfill_dell_families
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    write_model_code,
    write_offerings,
    write_scalar,
)


_CAPTURED = "2026-06-11T12:00:00+00:00"
_SCRAPER = "dell.fetch_dell_product"
_URL_INTEL = (
    "https://www.dell.com/en-us/shop/dell-laptops/alienware-15-gaming-laptop"
    "/spd/alienware-da15260-gaming-laptop"
)
_URL_AMD = (
    "https://www.dell.com/en-us/shop/cty/pdp/spd/alienware-da15265-gaming-laptop"
)


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


def _seed_legacy_dell_row(
    conn,
    *,
    model_code,
    year,
    product=None,
    title=None,
    source_url=_URL_INTEL,
    boards=None,
    extra_scalars=None,
):
    """Write a Dell row in pre-backfill shape: family_code NULL,
    source_model_codes NULL, boards without arch_marker."""
    pk = {"product": product or model_code, "year": year}
    with transaction(conn):
        if title is not None:
            write_scalar(
                conn, "products", pk, "vendor_full_name",
                _scraped(title, source_url=source_url),
            )
        write_scalar(
            conn, "products", pk, "brand",
            _scraped("Dell", source_url=source_url),
        )
        write_model_code(conn, pk, model_code)
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
    backfill_dell_families.main(args)


# ---------------------------------------------------------------------------
# 1. Empty DB / no Dell rows
# ---------------------------------------------------------------------------


def test_empty_db_runs_clean(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "no Dell rows without family_code" in out


def test_non_dell_rows_not_touched(tmp_path, capsys):
    """An ASUS row stays exactly as it was — the backfill only filters on
    Dell via the brand bundle."""
    conn = _fresh_db(tmp_path)
    try:
        asus_pk = {"product": "rog-strix-g16-2026", "year": 2026}
        with transaction(conn):
            write_scalar(
                conn, "products", asus_pk, "brand",
                _scraped("ASUS",
                         source_url="https://rog.asus.com/.../spec/",
                         scraper_id="asus.fetch_asus_product"),
            )
            write_model_code(conn, asus_pk, "rog-strix-g16-2026")
        _seed_legacy_dell_row(
            conn,
            model_code="aa18250",
            year=2026,
            title="Alienware 18 Area-51 Gaming Laptop",
            boards=[_board("MB1", ["RTX 5090"])],
        )
    finally:
        conn.close()

    _run(tmp_path)

    conn = connect(tmp_path / "backfill.db")
    try:
        asus = conn.execute(
            "SELECT family_code, source_model_codes FROM products "
            "WHERE model_code = ?", ("rog-strix-g16-2026",),
        ).fetchone()
        assert asus is not None
        assert asus["family_code"] is None
        assert asus["source_model_codes"] is None
        dell = conn.execute(
            "SELECT model_code, family_code FROM products "
            "WHERE model_code = ?", ("aa18250x",),
        ).fetchone()
        assert dell is not None
        assert dell["family_code"] == "aa18250x"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Single Dell row, parseable code → in-place update
# ---------------------------------------------------------------------------


def test_single_row_in_place_update(tmp_path, capsys):
    """aa18250 → aa18250x, intel. model_code renamed, family_code stamped,
    source_model_codes=[aa18250], boards now carry arch_marker."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_dell_row(
            conn,
            model_code="aa18250",
            year=2026,
            product="Area-51 18",
            title="Alienware 18 Area-51 Gaming Laptop",
            boards=[_board("MB1", ["RTX 5090"])],
        )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "Parseable: 1" in out
    assert "aa18250 -> family aa18250x, arch intel" in out
    assert "1 product(s) updated" in out

    conn = connect(tmp_path / "backfill.db")
    try:
        row = conn.execute(
            "SELECT model_code, product, family_code, source_model_codes, boards "
            "FROM products"
        ).fetchone()
        assert row["model_code"] == "aa18250x"
        # The user-facing product name is untouched by the backfill.
        assert row["product"] == "Area-51 18"
        assert row["family_code"] == "aa18250x"
        assert json.loads(row["source_model_codes"]) == ["aa18250"]
        boards = json.loads(row["boards"])
        assert len(boards) == 1
        assert boards[0]["arch_marker"] == "intel"
        assert [g["value"] for g in boards[0]["gpus"]] == ["RTX 5090"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Intel + AMD sibling rows → merged
# ---------------------------------------------------------------------------


def test_intel_amd_siblings_merge(tmp_path, capsys):
    """da15260 + da15265 → one row (canonical = da15260, alphabetic first).
    Boards stay distinct via arch_marker; source_model_codes unions."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_dell_row(
            conn,
            model_code="da15260",
            year=2026,
            title="Alienware 15 Gaming Laptop",
            source_url=_URL_INTEL,
            boards=[_board("MB2", ["RTX 5050", "RTX 5060"], source_url=_URL_INTEL)],
        )
        _seed_legacy_dell_row(
            conn,
            model_code="da15265",
            year=2026,
            title="Alienware 15 Gaming Laptop",
            source_url=_URL_AMD,
            boards=[_board("MB2", ["RTX 5060"], source_url=_URL_AMD)],
        )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "Parseable: 2" in out
    assert "1 merge group" in out
    assert "da15260x (year 2026): merging da15260 + da15265" in out
    assert "1 product(s) updated, 1 row(s) deleted" in out

    conn = connect(tmp_path / "backfill.db")
    try:
        rows = conn.execute(
            "SELECT model_code, family_code, source_model_codes, boards "
            "FROM products"
        ).fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["model_code"] == "da15260x"
        assert row["family_code"] == "da15260x"
        assert json.loads(row["source_model_codes"]) == ["da15260", "da15265"]
        boards = json.loads(row["boards"])
        # Same label "MB2" but distinct arch_marker → two entries.
        assert len(boards) == 2
        arches = {b["arch_marker"] for b in boards}
        assert arches == {"intel", "amd"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Unparseable / non-pair codes → left untouched
# ---------------------------------------------------------------------------


def test_non_pair_digit_left_alone(tmp_path, capsys):
    """ac16251 (Aurora 16X — final digit 1 is a distinct chassis, not an
    arch twin) must NOT get a family; merging it with Aurora 16 (ac16250)
    would collapse two different products."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_dell_row(
            conn,
            model_code="ac16251",
            year=2026,
            title="Alienware 16X Aurora Gaming Laptop",
        )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "Unparseable (left untouched): 1" in out
    assert "ac16251 -> unparseable" in out

    conn = connect(tmp_path / "backfill.db")
    try:
        row = conn.execute(
            "SELECT model_code, family_code, source_model_codes FROM products"
        ).fetchone()
        assert row["model_code"] == "ac16251"
        assert row["family_code"] is None
        assert row["source_model_codes"] is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. Unresolved review_queue rows follow the rename; resolved stay put
# ---------------------------------------------------------------------------


def test_queue_rows_remap_on_merge(tmp_path, capsys):
    """Unresolved queue rows keyed on either merged SKU code re-point at
    the family_code; resolved rows keep their original code as history."""
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_dell_row(
            conn,
            model_code="da15260",
            year=2026,
            title="Alienware 15 Gaming Laptop",
            source_url=_URL_INTEL,
        )
        _seed_legacy_dell_row(
            conn,
            model_code="da15265",
            year=2026,
            title="Alienware 15 Gaming Laptop",
            source_url=_URL_AMD,
        )
        with transaction(conn):
            conn.execute(
                "INSERT INTO review_queue (product_model_code, product_year, "
                "field_path, conflict_type, detected_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("da15265", 2026, "vendor_full_name", "year_inferred", _CAPTURED),
            )
            conn.execute(
                "INSERT INTO review_queue (product_model_code, product_year, "
                "field_path, conflict_type, detected_at, resolved_at, resolution) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "da15260", 2026, "weight_kg_max", "value_disagreement",
                    _CAPTURED, _CAPTURED, "keep_existing",
                ),
            )
    finally:
        conn.close()

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "1 unresolved review_queue row(s) re-pointed" in out

    conn = connect(tmp_path / "backfill.db")
    try:
        unresolved = conn.execute(
            "SELECT product_model_code FROM review_queue "
            "WHERE resolved_at IS NULL"
        ).fetchone()
        assert unresolved["product_model_code"] == "da15260x"
        resolved = conn.execute(
            "SELECT product_model_code FROM review_queue "
            "WHERE resolved_at IS NOT NULL"
        ).fetchone()
        assert resolved["product_model_code"] == "da15260"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. Re-run is idempotent
# ---------------------------------------------------------------------------


def test_rerun_is_idempotent(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    try:
        _seed_legacy_dell_row(
            conn,
            model_code="da15260",
            year=2026,
            title="Alienware 15 Gaming Laptop",
            source_url=_URL_INTEL,
            boards=[_board("MB2", ["RTX 5050"], source_url=_URL_INTEL)],
        )
        _seed_legacy_dell_row(
            conn,
            model_code="da15265",
            year=2026,
            title="Alienware 15 Gaming Laptop",
            source_url=_URL_AMD,
            boards=[_board("MB2", ["RTX 5060"], source_url=_URL_AMD)],
        )
    finally:
        conn.close()

    _run(tmp_path)
    first_out = capsys.readouterr().out
    assert "1 product(s) updated" in first_out

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
    assert "no Dell rows without family_code" in second_out

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
