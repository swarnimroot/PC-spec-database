"""Bridge tests against captured/synthetic HP ProductSnapshot fixtures.

Two fixture flavours are exercised, mirroring the Dell test layout:

* ``snapshot_3074457345621913323.json`` (and siblings) — captured live
  off the OMEN Transcend 14 PDP. Real config-picker + async tech-specs
  payload, slightly noisy.
* ``snapshot_transcend14_synthetic.json`` — hand-crafted, mirrors the
  documented HP shape. Used to assert behaviour for fields HP did not
  publish on the live page and to drive the year-extraction-from-title
  branch (which the live PDP does not cover — HP titles do not carry a
  bare year).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from competitive_database.bridge import hp as hp_bridge

# ProductSnapshot is imported lazily so the test module loads even on a
# bare environment without scrapers-lib (the fixture loader will skip).
try:
    from scrapers_lib import ProductSnapshot
    _HAS_SCRAPERS = True
except Exception:  # pragma: no cover - import-time dep missing
    _HAS_SCRAPERS = False


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "hp"

# The live captures from the OMEN Transcend 14 PDP. Tile 1's combined
# "Processor, graphics & memory" line carries the widest mix of CPUs
# and GPUs, so most live assertions key off that one.
LIVE_TILE_1 = "snapshot_3074457345621913323.json"
LIVE_TILE_2 = "snapshot_3074457345621913324.json"
LIVE_TILE_3 = "snapshot_3074457345621913325.json"
SYNTH = "snapshot_transcend14_synthetic.json"


def _load_snapshot(name: str):
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    return ProductSnapshot.model_validate(raw)


# ---------------------------------------------------------------------------
# Live capture
# ---------------------------------------------------------------------------


def test_parse_live_omen_transcend14_basic_identity():
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    assert cand.model_code == "14t-fb100"
    # Live HP titles don't carry a bare year → fallback path; year_inferred
    # check has its own dedicated test below.
    assert cand.year == 2026
    assert cand.brand["value"] == "HP"
    assert cand.brand["status"] == "verified"
    assert cand.sub_brand["value"] == "OMEN"
    assert cand.series["value"] == "Transcend 14"
    # vendor_full_name flagged needs-review because year was inferred
    # from fetched_at (live HP title does not include a year).
    assert cand.vendor_full_name["status"] == "needs-review"
    assert "OMEN" in cand.vendor_full_name["value"]
    # Provenance bundle wired up correctly.
    assert cand.brand["scraper_id"] == "hp.fetch_hp_product"


def test_parse_live_year_was_inferred_flag_set():
    """Live OMEN Transcend 14 title carries no year → year_was_inferred True."""
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)
    assert cand.year_was_inferred is True


def test_parse_live_cpu_offerings_dedupe_across_options():
    """The combined PG&M string repeats CPUs across upgrade options;
    cpu_offerings should dedupe by canonical model name."""
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    assert cand.cpu_offerings is not None
    models = [o["model"]["value"] for o in cand.cpu_offerings]
    # The live tile mixes Core Ultra 7 255H (multiple lines) and Core
    # Ultra 9 285H (a couple more) — we want exactly two unique CPUs.
    assert sorted(models) == ["Core Ultra 7 255H", "Core Ultra 9 285H"]
    for o in cand.cpu_offerings:
        assert o["model"]["status"] == "verified"


def test_parse_live_boards_merge_by_static_label():
    """RTX 5050 / 5060 / 5070 all map to MB2 via the static GPU → board map."""
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    assert cand.boards is not None
    assert len(cand.boards) == 1
    board = cand.boards[0]
    assert board["label"]["value"] == "MB2"
    gpu_names = sorted(g["value"] for g in board["gpus"])
    assert gpu_names == ["RTX 5050", "RTX 5060", "RTX 5070"]
    for g in board["gpus"]:
        assert g["status"] == "verified"
    # HP doesn't publish board-level TPP/TGP.
    assert board["tpp_max"]["status"] == "vendor-doesn't-publish"
    assert board["tgp_max"]["status"] == "vendor-doesn't-publish"


def test_parse_live_display_oled_3k_120hz():
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    assert cand.display_offerings is not None
    d = cand.display_offerings[0]
    assert d["size_inches"]["value"] == 14.0
    assert d["panel_type"]["value"] == "OLED"
    assert d["resolution_label"]["value"] == "3K"
    # HP publishes "48-120 Hz" — high end wins.
    assert d["refresh_rate_hz"]["value"] == 120
    # HDR nits preferred over SDR nits.
    assert d["nits_peak"]["value"] == 500
    assert d["dci_p3_pct"]["value"] == 100.0
    assert d["tier"]["value"] == "base"


def test_parse_live_battery_and_storage_and_memory():
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    assert cand.battery_offerings is not None
    bat = cand.battery_offerings[0]
    assert bat["wattage_wh"]["value"] == 71
    assert bat["cell_count"]["value"] == 6

    # Live tile publishes 1 TB and 2 TB → max 2000 GB.
    assert cand.storage_max_gb["value"] == 2000
    assert cand.storage_max_gb["status"] == "verified"

    # HP advertises 16 / 32 / 64 GB onboard — we surface 64 as the
    # platform ceiling and 0 slots (soldered).
    assert cand.memory_max_gb["value"] == 64
    assert cand.memory_slots["value"] == 0
    # HP gaming PDPs don't publish memory speed / type / OC structurally.
    assert cand.memory_speed_mts["status"] == "vendor-doesn't-publish"
    assert cand.memory_type["status"] == "vendor-doesn't-publish"
    assert cand.memory_overclocking["status"] == "vendor-doesn't-publish"


def test_parse_live_network_picks_highest_wifi_and_bt():
    """HP lists Wi-Fi 6E + Wi-Fi 7 as base/optional; we surface the highest."""
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    assert cand.wifi_standard["value"] == "Wi-Fi 7"
    assert cand.bluetooth_version["value"] == "5.4"
    # No Ethernet on the OMEN Transcend 14.
    assert cand.ethernet["value"] == "none"


def test_parse_live_io_ports_count_and_versions():
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    # 1 Thunderbolt 4 + 1 USB Type-C 10Gbps = 1 TB + 1 non-TB USB-C.
    assert cand.usbc_thunderbolt_count["value"] == 1
    assert cand.usbc_thunderbolt_version["value"] == "TB4"
    assert cand.usbc_non_thunderbolt_count["value"] == 1
    assert cand.usbc_non_thunderbolt_version["value"] == "USB 3.2 Gen 2"
    # 2 USB Type-A 10Gbps signaling rate → USB 3.2 Gen 2.
    assert cand.usba_count["value"] == 2
    assert cand.usba_version["value"] == "USB 3.2 Gen 2"
    assert cand.hdmi_count["value"] == 1
    assert cand.hdmi_version["value"] == "2.1"
    assert cand.audio_jack["value"] == "combo"
    # 10Gbps and 40Gbps map unambiguously to USB-IF version names; both
    # leave the version cell at status=verified.
    assert cand.usbc_non_thunderbolt_version["status"] == "verified"


def test_parse_synthetic_ambiguous_usbc_rate_flags_needs_review():
    """20Gbps / 80Gbps are ambiguous USB-C signaling rates — version
    attaches with ``status: 'needs-review'`` so the runner queues it."""
    snap = _load_snapshot(LIVE_TILE_1)
    raw = json.loads((FIXTURE_DIR / LIVE_TILE_1).read_text(encoding="utf-8"))
    raw["specs"]["External I/O Ports"] = (
        "1 USB Type-C 20Gbps signaling rate (DisplayPort 1.4, HP Sleep and Charge); "
        "1 HDMI 2.1"
    )
    raw.pop("_skip_keys", None)
    snap = ProductSnapshot.model_validate(
        {k: v for k, v in raw.items() if not k.startswith("_")}
    )
    cand = hp_bridge.parse(snap)

    assert cand.usbc_non_thunderbolt_count["value"] == 1
    assert cand.usbc_non_thunderbolt_version["value"] == "USB 3.2 Gen 2x2"
    assert cand.usbc_non_thunderbolt_version["status"] == "needs-review"


def test_parse_live_keyboard_tier_flags_base_and_optional():
    """HP's multi-line Keyboard value: line 0 → base, rest → optional."""
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    assert cand.keyboard_offerings is not None
    assert len(cand.keyboard_offerings) >= 2
    assert cand.keyboard_offerings[0]["tier"]["value"] == "base"
    for k in cand.keyboard_offerings[1:]:
        assert k["tier"]["value"] == "optional"


def test_parse_live_adapter_extracts_wattage_and_usbc_connector():
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    assert cand.adapter_offerings is not None
    assert cand.adapter_offerings[0]["wattage_w"]["value"] == 140
    # HP's "USB Type-C® power adapter" string → USB-C PD.
    assert cand.adapter_connector["value"] == "USB-C PD"


def test_parse_live_cpu_chip_specs_cores_extracted_from_pgm():
    """HP publishes core counts inline in the combined PG&M parenthetical
    (``"Core Ultra 9 285H (up to 5.4 GHz, 24 MB L3 cache, 16 cores, 16
    threads)"``); we attach ``cores`` to each canonical CPU model name."""
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    assert "Core Ultra 9 285H" in cand.cpu_chip_specs
    assert cand.cpu_chip_specs["Core Ultra 9 285H"]["cores"] == "16"


def test_parse_live_thermals_marked_vendor_doesnt_publish():
    """HP doesn't publish thermal_design / TIM / fan_count on the PDP."""
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    for col in ("thermal_design", "thermal_material", "tim", "fan_count"):
        bundle = getattr(cand, col)
        assert bundle["status"] == "vendor-doesn't-publish"
        assert bundle["value"] is None


def test_parse_live_design_covers_marked_vendor_doesnt_publish():
    """HP gaming PDPs don't structurally publish A/C/D cover materials."""
    snap = _load_snapshot(LIVE_TILE_1)
    cand = hp_bridge.parse(snap)

    for col in (
        "a_cover_material",
        "c_cover_material",
        "d_cover_material",
        "thermal_shelf",
        "lighting",
    ):
        bundle = getattr(cand, col)
        assert bundle["status"] == "vendor-doesn't-publish"
        assert bundle["value"] is None


# ---------------------------------------------------------------------------
# Synthetic
# ---------------------------------------------------------------------------


def test_parse_synthetic_year_extracted_from_title_paren():
    """Title "(2026)" → year=2026, year_was_inferred=False (full identity verified)."""
    snap = _load_snapshot(SYNTH)
    cand = hp_bridge.parse(snap)

    assert cand.year == 2026
    assert cand.year_was_inferred is False
    # vendor_full_name verified (not needs-review) when year is real.
    assert cand.vendor_full_name["status"] == "verified"


def test_parse_synthetic_unmapped_gpu_routes_to_needs_review_board():
    """RTX 6090 isn't in the static map → board with label=null + needs-review."""
    snap = _load_snapshot(SYNTH)
    cand = hp_bridge.parse(snap)

    assert cand.boards is not None
    # Two boards: MB2 for the mapped 5050/5070 set, and a label=null
    # entry for the unmapped 6090.
    labels = [b["label"]["value"] for b in cand.boards]
    assert "MB2" in labels
    assert None in labels

    nonebd = next(b for b in cand.boards if b["label"]["value"] is None)
    assert nonebd["label"]["status"] == "needs-review"
    assert any(g["value"] == "RTX 6090" for g in nonebd["gpus"])
    assert all(g["status"] == "needs-review" for g in nonebd["gpus"])


def test_parse_synthetic_keyboard_first_line_is_base_rest_optional():
    """HP convention: line 0 → tier='base', rest → tier='optional'."""
    snap = _load_snapshot(SYNTH)
    cand = hp_bridge.parse(snap)

    assert cand.keyboard_offerings is not None
    assert len(cand.keyboard_offerings) == 2
    assert cand.keyboard_offerings[0]["tier"]["value"] == "base"
    assert cand.keyboard_offerings[1]["tier"]["value"] == "optional"


def test_parse_synthetic_storage_slots_from_hp_lane_shorthand():
    """HP's "(4x4 SSD)" shorthand → PCIe gen 4."""
    snap = _load_snapshot(SYNTH)
    cand = hp_bridge.parse(snap)

    assert cand.storage_slots is not None
    assert len(cand.storage_slots) == 2
    for s in cand.storage_slots:
        assert s["gen"]["value"] == 4


def test_parse_synthetic_storage_max_gb_picks_largest_capacity():
    """1 TB / 2 TB Storage tokens → storage_max_gb = 2000."""
    snap = _load_snapshot(SYNTH)
    cand = hp_bridge.parse(snap)

    assert cand.storage_max_gb["value"] == 2000
    assert cand.storage_max_gb["status"] == "verified"


def test_parse_synthetic_audio_features_includes_dts_and_dual_speakers():
    """HP's "DTS:X Ultra" line + "Dual speakers" line."""
    snap = _load_snapshot(SYNTH)
    cand = hp_bridge.parse(snap)

    assert cand.tuning_brand["value"] == "DTS"
    assert cand.speaker_count["value"] == 2


def test_parse_synthetic_dimensions_converted_from_inches():
    """HP publishes dimensions in inches; we convert to mm."""
    snap = _load_snapshot(SYNTH)
    cand = hp_bridge.parse(snap)

    # 12.32 in × 25.4 = 312.93 mm (rounded).
    assert cand.width_mm["value"] == 312.93
    # Two H lines: 0.67 / 0.71 in → min/max mm pair.
    assert cand.height_mm_min["value"] == 17.02
    assert cand.height_mm_max["value"] == 18.03


def test_parse_synthetic_weight_single_lb_value():
    """HP publishes a single "3.6 lb" → weight_kg_min only."""
    snap = _load_snapshot(SYNTH)
    cand = hp_bridge.parse(snap)

    # 3.6 lb × 0.453592 ≈ 1.63 kg.
    assert cand.weight_kg_min["value"] == 1.63
    assert cand.weight_kg_max["value"] is None


def test_parse_synthetic_battery_71wh_6cell():
    snap = _load_snapshot(SYNTH)
    cand = hp_bridge.parse(snap)

    assert cand.battery_offerings is not None
    assert cand.battery_offerings[0]["wattage_wh"]["value"] == 71
    assert cand.battery_offerings[0]["cell_count"]["value"] == 6
    assert cand.battery_offerings[0]["tier"]["value"] == "base"
