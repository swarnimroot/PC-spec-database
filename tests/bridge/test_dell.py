"""Bridge tests against captured/synthetic Dell ProductSnapshot fixtures.

Two fixture flavours are exercised:

* ``snapshot_useaa18250wmlkcto01.json`` — captured live (real Dell
  techspecs payload, slightly noisy).
* ``snapshot_aa18250_synthetic.json`` — hand-crafted, mirrors the
  documented Dell techspecs shape. Used to assert behaviour for fields
  Dell did not publish on the live page.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from competitive_database.bridge import dell as dell_bridge

# ProductSnapshot is imported lazily so the test module loads even on a
# bare environment without scrapers-lib (the fixture loader will skip).
try:
    from scrapers_lib import ProductSnapshot
    _HAS_SCRAPERS = True
except Exception:  # pragma: no cover - import-time dep missing
    _HAS_SCRAPERS = False


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "dell"


def _load_snapshot(name: str):
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    # Strip synthetic-only marker keys before validating.
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    return ProductSnapshot.model_validate(raw)


# ---------------------------------------------------------------------------
# Live capture
# ---------------------------------------------------------------------------


def test_parse_live_aa18250_basic_identity_and_cpu():
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)

    assert cand.model_code == "aa18250"
    assert cand.year == 2026  # year inferred from fetched_at
    assert cand.brand["value"] == "Dell"
    assert cand.brand["status"] == "verified"
    assert cand.sub_brand["value"] == "Alienware"
    assert cand.series["value"] == "Area-51"
    # vendor_full_name flagged needs-review because year was inferred.
    assert cand.vendor_full_name["status"] == "needs-review"
    assert "Alienware" in cand.vendor_full_name["value"]

    # CPU offering present and verified.
    assert cand.cpu_offerings is not None
    assert len(cand.cpu_offerings) == 1
    cpu = cand.cpu_offerings[0]["model"]
    assert cpu["status"] == "verified"
    assert "Core Ultra 9" in cpu["value"]
    assert cpu["scraper_id"] == "dell.fetch_dell_product"


def test_parse_live_display_extracts_size_and_refresh():
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)

    assert cand.display_offerings is not None
    d = cand.display_offerings[0]
    assert d["size_inches"]["value"] == 18.0
    assert d["refresh_rate_hz"]["value"] == 300
    assert d["nits_peak"]["value"] == 500
    assert d["dci_p3_pct"]["value"] == 100.0
    assert d["resolution_label"]["value"] == "WQXGA"
    assert d["vrr"]["value"] == "G-Sync"
    assert d["tier"]["value"] == "base"


def test_parse_live_memory_battery_storage():
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)

    assert cand.memory_max_gb["value"] == 32
    assert cand.memory_speed_mts["value"] == 6400
    assert cand.memory_slots["value"] == 2
    assert cand.memory_type["value"] == "DDR5"
    # Dell doesn't advertise overclocking on this page.
    assert cand.memory_overclocking["status"] == "vendor-doesn't-publish"

    assert cand.battery_offerings is not None
    bat = cand.battery_offerings[0]
    assert bat["wattage_wh"]["value"] == 96
    assert bat["cell_count"]["value"] == 6

    assert cand.storage_slots is not None
    assert len(cand.storage_slots) == 1
    assert cand.storage_slots[0]["gen"]["value"] == 4


def test_parse_live_io_and_network():
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)

    assert cand.wifi_standard["value"] == "Wi-Fi 7"
    assert cand.bluetooth_version["value"] == "5.4"
    # Real product line carries a 5GbE port.
    assert cand.ethernet["value"] == "5GbE"
    # Two TB4 + two TB5 lines = 4 thunderbolt ports.
    assert cand.usbc_thunderbolt_count["value"] == 4
    # Higher TB version wins.
    assert cand.usbc_thunderbolt_version["value"] in {"TB5", "TB4"}
    assert cand.usba_count["value"] == 3
    assert cand.hdmi_count["value"] == 1
    assert cand.hdmi_version["value"] == "2.1"


def test_parse_live_dimensions_inch_with_mm_paren():
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)

    # Width/Depth come from "(410.00 mm)" / "(320.00 mm)" parens.
    assert cand.width_mm["value"] == 410.00
    assert cand.depth_mm["value"] == 320.00
    # Height single-line: 0.95 in. (24.32 mm) → max only.
    assert cand.height_mm_max["value"] == 24.32
    assert cand.height_mm_min["value"] is None
    # Weight (maximum): 9.56 lb (4.34 kg) → max only.
    assert cand.weight_kg_max["value"] == 4.34


def test_parse_live_audio_and_camera():
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)

    assert cand.tuning_brand["value"] == "Dolby Atmos"

    assert cand.camera_offerings is not None
    cam = cand.camera_offerings[0]
    assert cam["resolution"]["value"] == "1080p"
    assert cam["ir_supported"]["value"] is True


def test_parse_live_cpu_chip_specs_cores_extracted_from_processor_prose():
    """Dell's Processor prose carries the core count as ``"24-Core"``
    inside the parenthetical (``"... (24-Core, 36MB Cache, ...)"``);
    the parser pulls it into ``cpu_chip_specs`` so ``catalog_resolve``
    can seed the catalog cell."""
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)

    # Live tile names "Core Ultra 9 290HX Plus" with 24-Core in the
    # parenthetical. Whatever the canonical model name comes out as,
    # we expect cores=24 to flow through.
    assert cand.cpu_chip_specs
    for model, specs in cand.cpu_chip_specs.items():
        assert specs.get("cores") == "24"


def test_parse_live_thermals_marked_vendor_doesnt_publish():
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)

    for col in ("thermal_design", "thermal_material", "tim", "fan_count"):
        bundle = getattr(cand, col)
        assert bundle["status"] == "vendor-doesn't-publish"
        assert bundle["value"] is None


# ---------------------------------------------------------------------------
# Synthetic
# ---------------------------------------------------------------------------


def test_parse_synthetic_handles_simple_techspecs_shape():
    snap = _load_snapshot("snapshot_aa18250_synthetic.json")
    cand = dell_bridge.parse(snap)

    assert cand.model_code == "aa18250"
    assert cand.cpu_offerings[0]["model"]["value"] == "Core Ultra 9 285HX"
    # RTX 5090 → MB1 via the static GPU → board map (Decision 5).
    assert cand.boards[0]["label"]["value"] == "MB1"
    assert cand.boards[0]["gpus"][0]["value"] == "RTX 5090"
    assert cand.memory_max_gb["value"] == 32
    assert cand.battery_offerings[0]["wattage_wh"]["value"] == 96
    assert cand.adapter_offerings[0]["wattage_w"]["value"] == 330
    assert cand.adapter_connector["status"] == "vendor-doesn't-publish"


def test_parse_live_board_label_from_static_map():
    """RTX 5070 Ti must land on MB1, not 'MB1' from a per-tile counter."""
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)

    assert cand.boards is not None
    assert len(cand.boards) == 1
    assert cand.boards[0]["label"]["value"] == "MB1"
    assert cand.boards[0]["gpus"][0]["value"] == "RTX 5070 Ti"
    assert cand.boards[0]["gpus"][0]["status"] == "verified"


def test_parse_year_was_inferred_flag_set_when_year_falls_back():
    """Live snapshot title carries no year → year_was_inferred should be True."""
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)
    assert cand.year_was_inferred is True


def test_parse_live_storage_max_gb_extracted_from_storage_spec():
    """The live Dell tile publishes ``"1 TB, ..."`` → storage_max_gb = 1000 GB."""
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    cand = dell_bridge.parse(snap)

    assert cand.storage_max_gb is not None
    assert cand.storage_max_gb["status"] == "verified"
    assert cand.storage_max_gb["value"] == 1000


def test_parse_synthetic_storage_max_gb_matches_2tb():
    """Synthetic fixture publishes ``"2 TB, ..."`` → storage_max_gb = 2000 GB."""
    snap = _load_snapshot("snapshot_aa18250_synthetic.json")
    cand = dell_bridge.parse(snap)

    assert cand.storage_max_gb is not None
    assert cand.storage_max_gb["status"] == "verified"
    assert cand.storage_max_gb["value"] == 2000


def test_parse_area_51_synthetic_unions_two_gpus_into_mb1():
    """Two-GPU 'or' string in one tile → ONE MB1 entry with both GPUs."""
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads(
        (FIXTURE_DIR / "snapshot_aa18250_synthetic.json").read_text(encoding="utf-8")
    )
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    # Substitute a two-option GPU string.
    raw["specs"]["Graphics Card"] = (
        "NVIDIA GeForce RTX 5090, 24 GB GDDR7\n"
        "NVIDIA GeForce RTX 5070 Ti, 12 GB GDDR7"
    )
    snap = ProductSnapshot.model_validate(raw)
    cand = dell_bridge.parse(snap)

    # Both GPUs share MB1 → exactly one boards entry, two GPUs.
    assert cand.boards is not None
    assert len(cand.boards) == 1
    assert cand.boards[0]["label"]["value"] == "MB1"
    gpu_names = sorted(g["value"] for g in cand.boards[0]["gpus"])
    assert gpu_names == ["RTX 5070 Ti", "RTX 5090"]
