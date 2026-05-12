"""Tests for display + parsing helpers in ``cli._paths``."""

import pytest

from competitive_database.cli._paths import (
    format_product_pk,
    parse_path,
    parse_product_arg,
)
from competitive_database.db.connection import apply_schema, connect, transaction


def test_format_product_pk_dell_alphanumeric_slug_appends_year():
    assert format_product_pk("ac16251", 2026) == "ac16251-2026"


def test_format_product_pk_hp_slug_appends_year():
    assert format_product_pk("16t-ah100", 2026) == "16t-ah100-2026"


def test_format_product_pk_lenovo_psref_slug_appends_year():
    assert format_product_pk("16AFR10H", 2026) == "16AFR10H-2026"


def test_format_product_pk_asus_embedded_year_collapses():
    # ASUS ROG slugs bake the year into the URL token; without the
    # collapse the display would render ``rog-strix-g16-2026-2026``.
    assert format_product_pk("rog-strix-g16-2026", 2026) == "rog-strix-g16-2026"


def test_format_product_pk_year_mismatch_keeps_both():
    # If the slug ends with a year that differs from the row's year,
    # both stay — the display reflects what's actually stored.
    assert format_product_pk("rog-strix-g16-2025", 2026) == "rog-strix-g16-2025-2026"


def test_format_product_pk_partial_year_match_does_not_collapse():
    # ``-026`` is not a year suffix.
    assert format_product_pk("foo-026", 2026) == "foo-026-2026"


# ---------------------------------------------------------------------------
# parse_product_arg
# ---------------------------------------------------------------------------


def _seed_db(tmp_path, rows):
    """Build a fresh DB with the given (model_code, year) rows."""
    conn = connect(tmp_path / "pp.db")
    with transaction(conn):
        apply_schema(conn)
        for model_code, year in rows:
            conn.execute(
                "INSERT INTO products (model_code, year) VALUES (?, ?)",
                (model_code, year),
            )
    return conn


def test_parse_product_arg_bare_slug_returns_unchanged(tmp_path):
    conn = _seed_db(tmp_path, [("ac16251", 2026)])
    try:
        assert parse_product_arg(conn, "ac16251") == ("ac16251", None)
    finally:
        conn.close()


def test_parse_product_arg_display_form_splits_when_split_row_exists(tmp_path):
    """Dell/HP/Lenovo case: ``ac16251-2026`` paste form resolves to
    the split (slug, year) PK because that row exists.
    """
    conn = _seed_db(tmp_path, [("ac16251", 2026)])
    try:
        assert parse_product_arg(conn, "ac16251-2026") == ("ac16251", 2026)
    finally:
        conn.close()


def test_parse_product_arg_asus_baked_year_falls_back_to_whole_arg(tmp_path):
    """ASUS case: model_code is ``rog-strix-g16-2026`` itself; the
    split form ``rog-strix-g16/2026`` doesn't exist as a row, so the
    whole string is returned as the model_code.
    """
    conn = _seed_db(tmp_path, [("rog-strix-g16-2026", 2026)])
    try:
        assert parse_product_arg(conn, "rog-strix-g16-2026") == (
            "rog-strix-g16-2026",
            None,
        )
    finally:
        conn.close()


def test_parse_product_arg_explicit_year_arg_wins(tmp_path):
    conn = _seed_db(tmp_path, [("ac16251", 2026), ("ac16251", 2025)])
    try:
        # User passed --year 2025 alongside the suffix form for 2026 —
        # explicit --year always wins.
        assert parse_product_arg(
            conn, "ac16251-2026", year_arg=2025
        ) == ("ac16251", 2025)
    finally:
        conn.close()


def test_parse_product_arg_display_form_falls_back_when_no_match(tmp_path):
    """If neither the split form nor the whole-arg form exists in the
    DB, fall back to the whole arg with year_arg unchanged. Caller
    handles the missing-row error downstream.
    """
    conn = _seed_db(tmp_path, [("other", 2026)])
    try:
        assert parse_product_arg(conn, "ac16251-2026") == (
            "ac16251-2026",
            None,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# parse_path — column-level offering paths (Stage 5 CLI gap fix)
# ---------------------------------------------------------------------------


def test_parse_path_offering_column_only_returns_list_kind():
    """Bare offering column (e.g. ``camera_offerings``) parses as a
    whole-list replacement target. The ingest runner emits this shape
    for offering value_disagreement conflicts (list-level by design).
    """
    parsed = parse_path("camera_offerings")
    assert parsed.kind == "products_offering_list"
    assert parsed.table == "products"
    assert parsed.column == "camera_offerings"
    assert parsed.offering_idx is None
    assert parsed.leaf_key is None


def test_parse_path_offering_leaf_still_returns_leaf_kind():
    parsed = parse_path("camera_offerings.0.resolution")
    assert parsed.kind == "products_offering_leaf"
    assert parsed.column == "camera_offerings"
    assert parsed.offering_idx == 0
    assert parsed.leaf_key == "resolution"


def test_parse_path_offering_two_parts_rejected():
    """Two-part offering path (column + index, no leaf) is not a valid
    target shape — fall through to the contract error.
    """
    with pytest.raises(ValueError, match="must be"):
        parse_path("camera_offerings.0")


def test_parse_path_offering_four_parts_rejected():
    with pytest.raises(ValueError, match="must be"):
        parse_path("camera_offerings.0.resolution.extra")
