"""T9.1 — AppTest coverage for the Find-products value dropdown.

The "Find products where…" screen now drives the value input from
``_distinct_values_for_template`` instead of a free-text input. These
tests seed products against an isolated temp DB, drive the cascade
selectboxes, and assert the value selectbox content + the empty-field
info branch.

Cascade selectboxes on this screen are positional and keyless:
  - ``at.selectbox[0]`` = Section
  - ``at.selectbox[1]`` = Field
  - ``at.selectbox[2]`` = Op
The value selectbox is the only one with a key (``find-value-select``).
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from competitive_database.db.connection import connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    write_offerings,
    write_scalar,
)
from tests.ui.conftest import APP_SCRIPT


_CAPTURED_AT = "2026-05-12T00:00:00+00:00"
_SOURCE_URL = "https://example.com/test"
_SCRAPER_ID = "test"


def _bundle(value):
    return make_scraped_bundle(
        value=value,
        source_url=_SOURCE_URL,
        captured_at=_CAPTURED_AT,
        scraper_id=_SCRAPER_ID,
    )


def _seed_two_vendors(db_path) -> None:
    """Two products with distinct vendor_full_name values."""
    conn = connect(db_path)
    try:
        with transaction(conn):
            write_scalar(
                conn, "products",
                {"model_code": "dell-x", "year": 2026},
                "vendor_full_name", _bundle("Dell Inc."),
            )
            write_scalar(
                conn, "products",
                {"model_code": "hp-y", "year": 2026},
                "vendor_full_name", _bundle("HP Inc."),
            )
    finally:
        conn.close()


def _seed_three_refresh_rates(db_path) -> None:
    """Three products, each with a distinct refresh_rate_hz on a display.

    vendor_full_name is also set on each so the default cascade landing
    (Identity / vendor_full_name) has values; Section will be flipped to
    Display in the test body.
    """
    conn = connect(db_path)
    try:
        with transaction(conn):
            for mc, vendor, hz in [
                ("a-laptop", "Vendor A", 60),
                ("b-laptop", "Vendor B", 120),
                ("c-laptop", "Vendor C", 240),
            ]:
                pk = {"model_code": mc, "year": 2026}
                write_scalar(
                    conn, "products", pk,
                    "vendor_full_name", _bundle(vendor),
                )
                write_offerings(
                    conn, "products", pk,
                    "display_offerings",
                    [{"refresh_rate_hz": _bundle(hz)}],
                )
    finally:
        conn.close()


def _seed_only_vendor(db_path) -> None:
    """One product with vendor_full_name set, brand left NULL."""
    conn = connect(db_path)
    try:
        with transaction(conn):
            write_scalar(
                conn, "products",
                {"model_code": "lonely-x", "year": 2026},
                "vendor_full_name", _bundle("Lonely Vendor"),
            )
    finally:
        conn.close()


def test_value_dropdown_populated_for_default_cascade(empty_db):
    """Default cascade lands on Identity/vendor_full_name with Op '='.

    Seeds two products with distinct vendors and asserts the
    ``find-value-select`` selectbox carries exactly those two values,
    sorted casefold-alphabetically (Dell before HP).
    """
    _seed_two_vendors(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # Sanity: default cascade landed where we expect.
    assert at.selectbox[0].value == "Identity"
    assert at.selectbox[1].value == "vendor_full_name"
    assert at.selectbox[2].value == "="

    value_boxes = [s for s in at.selectbox if s.key == "find-value-select"]
    assert len(value_boxes) == 1, (
        f"expected exactly one find-value-select; got {len(value_boxes)}"
    )
    value_box = value_boxes[0]
    assert list(value_box.options) == ["Dell Inc.", "HP Inc."], (
        f"unexpected dropdown options: {value_box.options!r}"
    )


def test_value_dropdown_numeric_sort_on_refresh_rate(empty_db):
    """Numeric leaf sorts numerically ascending, not alphabetically.

    Three products with refresh_rate_hz of 60/120/240 — alphabetic sort
    would give ["120", "240", "60"]; numeric sort gives ["60", "120", "240"].
    """
    _seed_three_refresh_rates(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # Drive Section → Display.
    at.selectbox[0].set_value("Display").run()
    assert not at.exception, [str(e) for e in at.exception]

    # Field selectbox shows templates with the offering-index wildcard
    # rendered as ".N." via format_func — AppTest exposes those formatted
    # strings as ``options``, but ``set_value`` still takes the raw value.
    field_box = at.selectbox[1]
    target_raw = "display_offerings.*.refresh_rate_hz"
    target_formatted = "display_offerings.N.refresh_rate_hz"
    assert target_formatted in list(field_box.options), (
        f"missing {target_formatted} in field options: {list(field_box.options)!r}"
    )
    field_box.set_value(target_raw).run()
    assert not at.exception, [str(e) for e in at.exception]

    value_boxes = [s for s in at.selectbox if s.key == "find-value-select"]
    assert len(value_boxes) == 1
    assert list(value_boxes[0].options) == ["60", "120", "240"], (
        f"numeric sort broken: got {value_boxes[0].options!r}"
    )


def test_empty_field_shows_info_banner_and_hides_value_select(empty_db):
    """When no product has a filled cell at the chosen template, the
    info banner renders and the value selectbox is absent.

    Seeds one product with vendor_full_name only, then drives the Field
    selectbox to ``brand`` (which no product has filled).
    """
    _seed_only_vendor(empty_db)

    at = AppTest.from_file(str(APP_SCRIPT), default_timeout=10.0)
    at.session_state["view"] = "find"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # Section stays "Identity"; flip Field to "brand" (NULL on the one product).
    at.selectbox[1].set_value("brand").run()
    assert not at.exception, [str(e) for e in at.exception]

    info_msgs = [i.value for i in at.info]
    assert any(
        "No values to filter on for this field" in m for m in info_msgs
    ), f"expected empty-field info banner; saw infos {info_msgs!r}"

    value_boxes = [s for s in at.selectbox if s.key == "find-value-select"]
    assert value_boxes == [], (
        f"value selectbox should be absent when no values exist; "
        f"got {value_boxes!r}"
    )
