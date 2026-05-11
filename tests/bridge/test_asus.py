"""Bridge tests against captured/synthetic ASUS ProductSnapshot fixtures.

Two fixture flavours are exercised, mirroring Dell/HP/Lenovo:

* ``snapshot_rog_zephyrus_g16_2026.json`` — captured live off the ROG
  marketing spec page (``rog.asus.com/us/laptops/rog-zephyrus/rog-zephyrus-g16-2026/spec/``).
  Real h2-anchored sections, real per-SKU newline-joined variants, the
  single-line space-separated I/O Ports list, and the ``Manual mode:
  … at NW`` per-GPU TGP wording.
* ``snapshot_zephyrus_g16_synthetic.json`` — hand-crafted, exercises
  the year-from-title path, an unmapped GPU edge case (RTX 6090), an
  ambiguous 20Gbps USB-C signaling label, the cm-to-mm dimensions
  conversion with the ``~`` height range, the ``WHrs`` → Wh
  normalization, the explicit ``DDR5 5600`` memory speed shape, and
  the ``Thunderbolt 5`` extraction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from competitive_database.bridge import asus as asus_bridge

# ProductSnapshot is imported lazily so the test module loads even on a
# bare environment without scrapers-lib (the fixture loader will skip).
try:
    from scrapers_lib import ProductSnapshot
    _HAS_SCRAPERS = True
except Exception:  # pragma: no cover - import-time dep missing
    _HAS_SCRAPERS = False


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "asus"

LIVE_G16 = "snapshot_rog_zephyrus_g16_2026.json"
SYNTH = "snapshot_zephyrus_g16_synthetic.json"


def _load_snapshot(name: str):
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    return ProductSnapshot.model_validate(raw)


# ---------------------------------------------------------------------------
# Live capture (ROG Zephyrus G16 2026)
# ---------------------------------------------------------------------------


def test_parse_live_zephyrus_g16_basic_identity():
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    # Slug is the ASUS canonical PK token; no Dell-style alphanumeric
    # model code on the marketing spec page.
    assert cand.model_code == "rog-zephyrus-g16-2026"
    # Live ROG title carries ``(2026)`` in parens → year extracted, NOT
    # inferred from fetched_at.
    assert cand.year == 2026
    assert cand.year_was_inferred is False
    assert cand.brand["value"] == "ASUS"
    assert cand.brand["status"] == "verified"
    assert cand.sub_brand["value"] == "ROG"
    assert cand.series["value"] == "Zephyrus G16"
    # year was real → vendor_full_name verified.
    assert cand.vendor_full_name["status"] == "verified"
    assert "Zephyrus G16" in cand.vendor_full_name["value"]
    # Provenance bundle wired up correctly.
    assert cand.brand["scraper_id"] == "asus.fetch_asus_product"


def test_parse_live_year_extracted_from_title_paren():
    """Live ROG title carries ``(2026)`` → year=2026, year_was_inferred=False."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)
    assert cand.year_was_inferred is False


def test_parse_live_cpu_dropped_npu_only_clause():
    """ASUS appends ``"; Intel NPU up to 50TOPS"`` to the Processor
    line; the parser drops NPU-only pieces and emits exactly one CPU
    offering."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.cpu_offerings is not None
    models = [o["model"]["value"] for o in cand.cpu_offerings]
    assert models == ["Core Ultra 9 386H"]
    for o in cand.cpu_offerings:
        assert o["model"]["status"] == "verified"


def test_parse_live_boards_merge_by_static_label_max_per_gpu_tgp():
    """RTX 5070 Ti and RTX 5080 both map to MB1 via the static GPU →
    board map. ASUS publishes per-GPU Manual-mode TGPs (140W and
    160W); the parser collapses to ``tgp_max = max`` per board per the
    Session 7 decision (mirrors Lenovo). ASUS Manual mode is the
    unlocked ceiling, so we read that wattage rather than Turbo."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.boards is not None
    assert len(cand.boards) == 1
    board = cand.boards[0]
    assert board["label"]["value"] == "MB1"
    gpu_names = sorted(g["value"] for g in board["gpus"])
    assert gpu_names == ["RTX 5070 Ti", "RTX 5080"]
    for g in board["gpus"]:
        assert g["status"] == "verified"
    assert board["tpp_max"]["status"] == "vendor-doesn't-publish"
    # Manual mode wattages: 5070 Ti=140W, 5080=160W → max=160.
    assert board["tgp_max"]["value"] == 160
    assert board["tgp_max"]["status"] == "verified"


def test_parse_live_memory_lpddr5x_8533_64gb_onboard():
    """ASUS publishes ``"LPDDR5X 8533"`` (no MT/s unit); we extract
    the bare 4-digit speed token. ``"on board"`` wording → 0 slots."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.memory_max_gb["value"] == 64
    assert cand.memory_speed_mts["value"] == 8533
    assert cand.memory_type["value"] == "LPDDR5X"
    # "on board" → soldered → 0 slots.
    assert cand.memory_slots["value"] == 0
    # ASUS spec page doesn't structurally publish memory overclocking.
    assert cand.memory_overclocking["status"] == "vendor-doesn't-publish"


def test_parse_live_storage_two_slots_pcie_gen4():
    """Storage value lists 1TB and 2TB drives both at PCIe 4.0; the
    Expansion Slots key publishes ``"2x M.2 PCIe"`` → 2 slot entries."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.storage_slots is not None
    assert len(cand.storage_slots) == 2
    for s in cand.storage_slots:
        assert s["gen"]["value"] == 4
    assert cand.storage_max_gb["value"] == 2000
    assert cand.storage_max_gb["status"] == "verified"


def test_parse_live_battery_whrs_normalization():
    """ASUS publishes ``"90WHrs"`` (no separator, plural Hrs); the
    parser normalizes ``WHrs`` → ``Wh`` so the shared regex hits."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.battery_offerings is not None
    assert cand.battery_offerings[0]["wattage_wh"]["value"] == 90
    assert cand.battery_offerings[0]["cell_count"]["value"] == 4


def test_parse_live_network_wifi7_bt6_no_ethernet():
    """Live G16 carries Wi-Fi 7 + Bluetooth 6.0; no RJ45 in I/O Ports
    (Zephyrus is a thin/light, no Ethernet) → ``"none"``."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.wifi_standard["value"] == "Wi-Fi 7"
    assert cand.bluetooth_version["value"] == "6.0"
    assert cand.ethernet["value"] == "none"


def test_parse_live_io_ports_single_line_tokenization():
    """ASUS's I/O Ports value is one space-separated line with leading
    ``Nx`` count anchors. The ASUS-specific tokenizer splits on those
    anchors (HP's per-line / Lenovo's ``\\n``-joined shapes don't apply)."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    # 1 Thunderbolt 4 + 1 USB Type-C 3.2 Gen 2 + 2 USB Type-A 3.2 Gen 2.
    assert cand.usbc_thunderbolt_count["value"] == 1
    assert cand.usbc_thunderbolt_version["value"] == "TB4"
    assert cand.usbc_non_thunderbolt_count["value"] == 1
    assert cand.usbc_non_thunderbolt_version["value"] == "USB 3.2 Gen 2"
    assert cand.usbc_non_thunderbolt_version["status"] == "verified"
    assert cand.usba_count["value"] == 2
    assert cand.usba_version["value"] == "USB 3.2 Gen 2"
    assert cand.hdmi_count["value"] == 1
    assert cand.hdmi_version["value"] == "2.1"
    # Card reader (SD) (UHS-II, 312MB/s) → SD with UHS-II speed.
    assert cand.sd_card["value"] == "SD"
    assert cand.sd_card_speed["value"] == "UHS-II"
    assert cand.audio_jack["value"] == "combo"


def test_parse_live_adapter_250w_rectangle_connector():
    """ASUS publishes ``"Rectangle Conn, 250W AC Adapter"``; per the
    Session 7 user decision, the flat rectangular ROG plug is its own
    enum value (``rectangle``), distinct from Dell's round-pin barrel
    and Lenovo's slim-tip."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.adapter_offerings is not None
    assert cand.adapter_offerings[0]["wattage_w"]["value"] == 250
    assert cand.adapter_connector["value"] == "rectangle"


def test_parse_live_camera_1080p_ir_no_shutter():
    """Live G16 Camera key reads ``"1080P FHD IR Camera for Windows
    Hello"`` — IR yes, no shutter mention."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.camera_offerings is not None
    assert cand.camera_offerings[0]["resolution"]["value"] == "1080p"
    assert cand.camera_offerings[0]["ir_supported"]["value"] is True
    assert cand.camera_offerings[0]["privacy_shutter"]["value"] is False


def test_parse_live_audio_quad_speakers_with_woofer_dolby():
    """Audio key reads ``"4-speaker (dual-force woofer) system …
    Dolby Atmos"`` → speakers=4, tuning=Dolby Atmos, woofer=True."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.speaker_count["value"] == 4
    assert cand.tuning_brand["value"] == "Dolby Atmos"
    assert cand.has_subwoofer["value"] is True


def test_parse_live_dimensions_cm_to_mm_with_height_range():
    """ASUS publishes dimensions in cm with a ``~`` height range:
    ``"35.4 x 24.6 x 1.49 ~ 1.79 cm"``. Parser converts to mm."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    # 35.4 cm × 10 = 354 mm, etc.
    assert cand.width_mm["value"] == 354.0
    assert cand.depth_mm["value"] == 246.0
    assert cand.height_mm_min["value"] == 14.9
    assert cand.height_mm_max["value"] == 17.9


def test_parse_live_weight_single_value_min_only():
    """ASUS publishes one weight figure (``"1.95 Kg"``); → weight_kg_min
    only. weight_kg_max stays vendor-doesn't-publish (mirrors HP/Lenovo
    single-value rule)."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.weight_kg_min["value"] == 1.95
    assert cand.weight_kg_max["value"] is None


def test_parse_live_lighting_slash_lighting():
    """Device Lighting key publishes ``"Slash Lighting"`` → lighting
    bundle carries that string verbatim."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert cand.lighting["value"] == "Slash Lighting"
    assert cand.lighting["status"] == "verified"


def test_parse_live_thermals_marked_vendor_doesnt_publish():
    """ROG marketing spec page doesn't publish thermal_design / TIM /
    fan_count structurally."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    for col in ("thermal_design", "thermal_material", "tim", "fan_count"):
        bundle = getattr(cand, col)
        assert bundle["status"] == "vendor-doesn't-publish"
        assert bundle["value"] is None


def test_parse_live_cpu_chip_specs_npu_tops_and_cores_extracted():
    """ASUS publishes NPU TOPS in the dedicated ``Neural Processor`` h2
    (``"50TOPS"``) and core count in the Processor prose
    (``"... 16 cores ..."``); both flow into ``cpu_chip_specs`` keyed by
    canonical CPU model name so ``catalog_resolve`` can seed the
    ``cpu_catalog`` cells."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    assert "Core Ultra 9 386H" in cand.cpu_chip_specs
    specs = cand.cpu_chip_specs["Core Ultra 9 386H"]
    assert specs["npu_tops"] == "50"
    assert specs["cores"] == "16"


def test_parse_live_design_covers_marked_vendor_doesnt_publish():
    """ROG spec page doesn't structurally publish A/C/D cover materials
    (chassis prose lives in the page's marketing-highlights section,
    not the h2-anchored spec sheet)."""
    snap = _load_snapshot(LIVE_G16)
    cand = asus_bridge.parse(snap)

    for col in ("a_cover_material", "c_cover_material", "d_cover_material", "thermal_shelf"):
        bundle = getattr(cand, col)
        assert bundle["status"] == "vendor-doesn't-publish"
        assert bundle["value"] is None


# ---------------------------------------------------------------------------
# Synthetic
# ---------------------------------------------------------------------------


def test_parse_synthetic_year_extracted_from_title_paren():
    """Synthetic title also carries ``(2026)`` → year=2026, not inferred."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    assert cand.year == 2026
    assert cand.year_was_inferred is False
    assert cand.vendor_full_name["status"] == "verified"


def test_parse_synthetic_unmapped_gpu_routes_to_needs_review_board():
    """RTX 6090 isn't in the static GPU → board map → board with
    label=null + needs-review; the mapped 5050/5070 fold into one MB2
    entry."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    assert cand.boards is not None
    labels = [b["label"]["value"] for b in cand.boards]
    assert "MB2" in labels
    assert None in labels

    nonebd = next(b for b in cand.boards if b["label"]["value"] is None)
    assert nonebd["label"]["status"] == "needs-review"
    assert any(g["value"] == "RTX 6090" for g in nonebd["gpus"])
    assert all(g["status"] == "needs-review" for g in nonebd["gpus"])


def test_parse_synthetic_per_gpu_tgp_max_collapse_for_mapped_board():
    """The mapped MB2 board has 5070 (115W Manual) and 5050 (95W Manual);
    tgp_max = 115."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    mb2 = next(b for b in cand.boards if b["label"]["value"] == "MB2")
    assert mb2["tgp_max"]["value"] == 115
    assert mb2["tgp_max"]["status"] == "verified"


def test_parse_synthetic_ambiguous_usbc_20gbps_flags_needs_review():
    """20Gbps USB-C labeling is ambiguous — version attaches with
    ``status: 'needs-review'`` per the (value, status) tuple pattern."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    # Synthetic ports list: 1 Thunderbolt 5 + 1 USB-C 20Gbps + 2 USB-A.
    assert cand.usbc_non_thunderbolt_count["value"] == 1
    assert cand.usbc_non_thunderbolt_version["value"] == "USB 3.2 Gen 2x2"
    assert cand.usbc_non_thunderbolt_version["status"] == "needs-review"


def test_parse_synthetic_thunderbolt_5_extracted():
    """Thunderbolt 5 line → tb_version = TB5, tb_count = 1."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    assert cand.usbc_thunderbolt_count["value"] == 1
    assert cand.usbc_thunderbolt_version["value"] == "TB5"


def test_parse_synthetic_microsd_with_uhs_speed():
    """microSD card reader (UHS-II) → sd_card='microSD', speed='UHS-II'."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    assert cand.sd_card["value"] == "microSD"
    assert cand.sd_card_speed["value"] == "UHS-II"


def test_parse_synthetic_ethernet_25gbe_from_io_ports():
    """Synthetic ports list carries ``"1x RJ45 LAN (2.5GbE)"`` →
    ethernet = 2.5GbE (parsed off the I/O Ports value since ASUS
    doesn't publish a dedicated Ethernet key)."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    assert cand.ethernet["value"] == "2.5GbE"


def test_parse_synthetic_memory_socketed_ddr5_with_explicit_speed():
    """Synthetic Memory key publishes ``"32GB DDR5 5600 (16GB SO-DIMM
    x2)"`` — parser pulls type=DDR5, speed=5600 (bare-number form),
    max_gb=32, no soldered language so memory_slots stays VDP."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    assert cand.memory_max_gb["value"] == 32
    assert cand.memory_type["value"] == "DDR5"
    assert cand.memory_speed_mts["value"] == 5600
    # No "on board" / "soldered" — stays vendor-doesn't-publish.
    assert cand.memory_slots["status"] == "vendor-doesn't-publish"


def test_parse_synthetic_keyboard_numpad_detected():
    """Synthetic Keyboard description includes ``"numeric keypad"`` →
    has_numpad=True."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    assert cand.keyboard_offerings is not None
    assert cand.keyboard_offerings[0]["has_numpad"]["value"] is True
    assert cand.keyboard_offerings[0]["tier"]["value"] == "base"


def test_parse_synthetic_camera_with_privacy_shutter():
    """Synthetic Camera carries ``"with privacy shutter"`` →
    privacy_shutter=True."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    assert cand.camera_offerings is not None
    assert cand.camera_offerings[0]["privacy_shutter"]["value"] is True
    assert cand.camera_offerings[0]["ir_supported"]["value"] is True


def test_parse_synthetic_camera_known_mp_value_normalized_to_p_form():
    """A vendor MP value present in ``CAMERA_MP_TO_P_FORM`` maps to
    canonical p-form with ``status="verified"`` (mirrors Lenovo; shared
    via ``helpers.normalize_camera_resolution``)."""
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads((FIXTURE_DIR / SYNTH).read_text(encoding="utf-8"))
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    raw["specs"]["Camera"] = "2.0MP IR camera"
    snap = ProductSnapshot.model_validate(raw)
    cand = asus_bridge.parse(snap)

    assert cand.camera_offerings is not None
    res = cand.camera_offerings[0]["resolution"]
    assert res["value"] == "1080p"
    assert res["status"] == "verified"


def test_parse_synthetic_camera_unknown_mp_value_flags_needs_review():
    """An MP value not in ``CAMERA_MP_TO_P_FORM`` falls back to the
    raw ``NMP`` form and is flagged ``needs-review`` (shared via
    ``helpers.normalize_camera_resolution``)."""
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads((FIXTURE_DIR / SYNTH).read_text(encoding="utf-8"))
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    raw["specs"]["Camera"] = "3.0MP IR camera"
    snap = ProductSnapshot.model_validate(raw)
    cand = asus_bridge.parse(snap)

    assert cand.camera_offerings is not None
    res = cand.camera_offerings[0]["resolution"]
    assert res["value"] == "3.0MP"
    assert res["status"] == "needs-review"


def test_parse_synthetic_adapter_usbc_pd_connector():
    """Synthetic Power Supply: ``"USB Type-C, 100W AC Adapter"`` →
    connector USB-C PD."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    assert cand.adapter_offerings is not None
    assert cand.adapter_offerings[0]["wattage_w"]["value"] == 100
    assert cand.adapter_connector["value"] == "USB-C PD"


def test_parse_synthetic_display_full_attributes_extracted():
    """Synthetic Display row inlines the highlight-section info that
    the live ROG h2 spec block doesn't carry: refresh rate, HDR cert,
    nits, color gamut, VRR, response time."""
    snap = _load_snapshot(SYNTH)
    cand = asus_bridge.parse(snap)

    assert cand.display_offerings is not None
    d = cand.display_offerings[0]
    assert d["size_inches"]["value"] == 16.0
    assert d["panel_type"]["value"] == "OLED"
    assert d["resolution_label"]["value"] == "2.5K"
    assert d["resolution_pixels"]["value"] == "2560×1600"
    assert d["refresh_rate_hz"]["value"] == 240
    assert d["nits_peak"]["value"] == 500
    assert d["dci_p3_pct"]["value"] == 100.0
    assert d["hdr_certification"]["value"] == "DisplayHDR True Black 500"
    assert d["vrr"]["value"] == "G-Sync"
    # ASUS uses "Anti-reflection" wording → matte.
    assert d["anti_glare"]["value"] == "matte"
