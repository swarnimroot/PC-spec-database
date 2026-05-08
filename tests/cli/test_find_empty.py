"""Stage 5 happy-path tests for ``find-empty``."""

from __future__ import annotations

import argparse

from competitive_database.cli import find_empty
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    make_vendor_doesnt_publish_bundle,
    write_offerings,
    write_scalar,
)


_PK = {"model_code": "alienware-m18", "year": 2026}


def _fresh_db(tmp_path):
    conn = connect(tmp_path / "fe.db")
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


def _vdp():
    return make_vendor_doesnt_publish_bundle(
        source_url="https://example.com",
        captured_at="2026-05-07T00:00:00+00:00",
        scraper_id="test",
    )


def test_find_empty_groups_by_section(tmp_path, capsys):
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            # Identity: brand filled, others empty
            write_scalar(conn, "products", _PK, "brand", _scraped("Alienware"))
            # Audio: speaker_count vendor-doesn't-publish, rest empty
            write_scalar(conn, "products", _PK, "speaker_count", _vdp())
            # Display: one offering with one filled leaf and two empty
            offerings = [
                {
                    "size_inches": _scraped(18),
                    # nits_peak intentionally absent → empty
                    "panel_type": _vdp(),
                }
            ]
            write_offerings(conn, "products", _PK, "display_offerings", offerings)
    finally:
        conn.close()

    args = argparse.Namespace(
        product="alienware-m18",
        year=None,
        all=False,
        db=str(tmp_path / "fe.db"),
    )
    find_empty.main(args)
    out = capsys.readouterr().out

    assert "alienware-m18 (2026)" in out
    assert "Identity" in out
    assert "vendor_full_name: empty" in out
    assert "brand" not in out.split("Identity")[1].split("\n\n")[0] or "- brand" not in out
    assert "Audio" in out
    assert "speaker_count: vendor doesn't publish" in out
    assert "Display" in out
    # nits_peak absent in offering dict → empty; panel_type set vdp.
    assert "offering 0 - nits_peak: empty" in out
    assert "offering 0 - panel_type: vendor doesn't publish" in out
    # Filled leaves should NOT appear
    assert "offering 0 - size_inches" not in out
    # Summary line
    assert "missing" in out


def test_find_empty_clean_product(tmp_path, capsys):
    """A product with every fillable cell filled prints the clean-state line."""
    conn = _fresh_db(tmp_path)
    try:
        with transaction(conn):
            # Fill every Identity scalar so at least Identity is fully covered.
            for col in (
                "vendor_full_name",
                "brand",
                "sub_brand",
                "series",
                "status",
                "segment",
            ):
                write_scalar(conn, "products", _PK, col, _scraped("x"))
            # Fill every Audio / Network / Memory / IO / Thermals / Dimensions /
            # Weight / Design column.
            for col in (
                "speaker_count",
                "tuning_brand",
                "has_subwoofer",
                "wifi_standard",
                "ethernet",
                "bluetooth_version",
                "memory_type",
                "memory_max_gb",
                "memory_speed_mts",
                "memory_slots",
                "memory_overclocking",
                "usbc_thunderbolt_count",
                "usbc_thunderbolt_version",
                "usbc_non_thunderbolt_count",
                "usbc_non_thunderbolt_version",
                "usba_count",
                "usba_version",
                "hdmi_count",
                "hdmi_version",
                "sd_card",
                "sd_card_speed",
                "audio_jack",
                "thermal_design",
                "thermal_material",
                "tim",
                "fan_count",
                "width_mm",
                "depth_mm",
                "height_mm_min",
                "height_mm_max",
                "weight_kg_min",
                "weight_kg_max",
                "a_cover_material",
                "c_cover_material",
                "d_cover_material",
                "thermal_shelf",
                "lighting",
                "cpu_tdp_max",
                "storage_max_gb",
                "adapter_connector",
            ):
                write_scalar(conn, "products", _PK, col, _scraped("x"))
    finally:
        conn.close()

    args = argparse.Namespace(
        product="alienware-m18",
        year=None,
        all=False,
        db=str(tmp_path / "fe.db"),
    )
    find_empty.main(args)
    out = capsys.readouterr().out
    # No offerings → those sections contribute zero paths.
    # All scalar sections filled → clean.
    assert "(no empty or vendor-doesn't-publish cells)" in out
