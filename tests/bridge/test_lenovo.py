"""Bridge tests against captured/synthetic Lenovo ProductSnapshot fixtures.

Two fixture flavours are exercised, mirroring Dell/HP:

* ``snapshot_legion_pro_7_16afr10h.json`` — captured live off the
  PSREF LoadSpecData endpoint for the Legion Pro 7 16AFR10H (the AMD
  cousin of the user-targeted Legion Pro 7i Gen 10; PSREF does not
  yet publish a Pro 7i Gen 10 page, see the session report). Real
  hierarchical 3-level path keys, real ``Att: AttV; Att: AttV`` rows,
  realistic multi-SKU alternative joining.
* ``snapshot_legion_pro_7i_synthetic.json`` — hand-crafted, exercises
  the year-from-title path (live PSREF titles do not carry a year),
  the ``Legion Pro 7i`` series tag, an unmapped GPU edge case, an
  ambiguous 20Gbps USB-C signaling label, and Thunderbolt 5.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from competitive_database.bridge import lenovo as lenovo_bridge

# ProductSnapshot is imported lazily so the test module loads even on a
# bare environment without scrapers-lib (the fixture loader will skip).
try:
    from scrapers_lib import ProductSnapshot
    _HAS_SCRAPERS = True
except Exception:  # pragma: no cover - import-time dep missing
    _HAS_SCRAPERS = False


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lenovo"

LIVE_LEGION = "snapshot_legion_pro_7_16afr10h.json"
SYNTH = "snapshot_legion_pro_7i_synthetic.json"


def _load_snapshot(name: str):
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    return ProductSnapshot.model_validate(raw)


# ---------------------------------------------------------------------------
# Live capture (Legion Pro 7 16AFR10H — AMD cousin of the user-targeted
# Pro 7i Gen 10; same PSREF payload shape)
# ---------------------------------------------------------------------------


def test_parse_live_legion_pro_7_basic_identity():
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.model_code == "16AFR10H"
    # Live PSREF titles don't carry a bare year → fallback path.
    assert cand.year == 2026
    assert cand.brand["value"] == "Lenovo"
    assert cand.brand["status"] == "verified"
    assert cand.sub_brand["value"] == "Legion"
    assert cand.series["value"] == "Legion Pro 7"
    # vendor_full_name flagged needs-review because year was inferred
    # from fetched_at (PSREF titles never include a year).
    assert cand.vendor_full_name["status"] == "needs-review"
    assert "Legion Pro 7" in cand.vendor_full_name["value"]
    # Provenance bundle wired up correctly.
    assert cand.brand["scraper_id"] == "lenovo.fetch_lenovo_product"


def test_parse_live_year_was_inferred_flag_set():
    """Live PSREF title carries no year → year_was_inferred True."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)
    assert cand.year_was_inferred is True


def test_parse_live_cpu_offerings_extracted_from_processor_name_field():
    """The ``Processor Name`` attribute inside each row is the canonical
    model token; we ignore the trailing structured attributes (Cores,
    Threads, etc.) and emit one offering per SKU alternative."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.cpu_offerings is not None
    models = sorted(o["model"]["value"] for o in cand.cpu_offerings)
    assert models == ["Ryzen 9 9955HX", "Ryzen 9 9955HX3D"]
    for o in cand.cpu_offerings:
        assert o["model"]["status"] == "verified"


def test_parse_live_boards_merge_by_static_label():
    """RTX 5070 Ti and RTX 5080 both map to MB1 via the static GPU →
    board map. Lenovo's per-GPU TGP attribute collapses to the max
    across the board (175W) per Session 7 decision; the schema column
    is literally ``tgp_max``."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.boards is not None
    assert len(cand.boards) == 1
    board = cand.boards[0]
    assert board["label"]["value"] == "MB1"
    gpu_names = sorted(g["value"] for g in board["gpus"])
    assert gpu_names == ["RTX 5070 Ti", "RTX 5080"]
    for g in board["gpus"]:
        assert g["status"] == "verified"
    assert board["tpp_max"]["status"] == "vendor-doesn't-publish"
    assert board["tgp_max"]["value"] == 175
    assert board["tgp_max"]["status"] == "verified"


def test_parse_live_display_extracts_attributes_from_row():
    """PSREF Display key is one ``Att: AttV; ...`` row — we read each
    attribute by name rather than running broad regexes over the whole
    string."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.display_offerings is not None
    assert len(cand.display_offerings) == 1
    d = cand.display_offerings[0]
    assert d["size_inches"]["value"] == 16.0
    assert d["panel_type"]["value"] == "OLED"
    assert d["resolution_label"]["value"] == "WQXGA"
    assert d["resolution_pixels"]["value"] == "2560×1600"
    assert d["refresh_rate_hz"]["value"] == 240
    # PSREF publishes ``"1100nits (HDR peak) / 500nits (SDR typical)"``
    # — we prefer the HDR-tagged figure.
    assert d["nits_peak"]["value"] == 1100
    assert d["dci_p3_pct"]["value"] == 100.0
    assert d["hdr_certification"]["value"] == "DisplayHDR True Black 1000"
    assert d["vrr"]["value"] == "G-Sync"
    assert d["tier"]["value"] == "base"


def test_parse_live_memory_max_64gb_two_slots_ddr5():
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.memory_max_gb["value"] == 64
    assert cand.memory_slots["value"] == 2
    assert cand.memory_type["value"] == "DDR5"
    # PSREF doesn't structurally publish memory overclocking on the spec
    # page.
    assert cand.memory_overclocking["status"] == "vendor-doesn't-publish"


def test_parse_live_storage_slots_pcie_gen5_and_gen4():
    """Lenovo publishes per-slot PCIe gens in the Storage Slot key; we
    surface one slot entry per bullet."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.storage_slots is not None
    gens = sorted(s["gen"]["value"] for s in cand.storage_slots if s["gen"]["value"] is not None)
    assert gens == [4, 5]
    assert cand.storage_max_gb["value"] == 2000
    assert cand.storage_max_gb["status"] == "verified"


def test_parse_live_battery_two_capacity_options():
    """PSREF publishes ``80Wh`` and ``99.9Wh`` battery alternatives;
    cell count is not published."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.battery_offerings is not None
    assert len(cand.battery_offerings) == 2
    assert cand.battery_offerings[0]["wattage_wh"]["value"] == 80
    # 99.9Wh truncates to 99 via the shared ``parse_int`` helper. PSREF
    # cell count isn't published structurally → status vendor-doesn't-publish.
    assert cand.battery_offerings[1]["wattage_wh"]["value"] == 99
    for b in cand.battery_offerings:
        assert b["cell_count"]["status"] == "vendor-doesn't-publish"


def test_parse_live_network_wifi7_bt54_eth_25gbe():
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.wifi_standard["value"] == "Wi-Fi 7"
    assert cand.bluetooth_version["value"] == "5.4"
    assert cand.ethernet["value"] == "2.5GbE"


def test_parse_live_io_ports_count_and_versions():
    """Lenovo's "Standard Ports" lines lead with ``Nx`` count tokens
    (rather than HP's ``N ``); the parser handles both."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    # 3 USB-A, 2 USB-C, 0 Thunderbolt on this product.
    assert cand.usba_count["value"] == 3
    assert cand.usbc_thunderbolt_count["value"] == 0
    assert cand.usbc_non_thunderbolt_count["value"] == 2
    # Lenovo's ``USB 10Gbps`` wording maps unambiguously to USB 3.2 Gen 2.
    assert cand.usbc_non_thunderbolt_version["value"] == "USB 3.2 Gen 2"
    assert cand.usbc_non_thunderbolt_version["status"] == "verified"
    assert cand.usba_version["value"] == "USB 3.2 Gen 2"
    assert cand.hdmi_count["value"] == 1
    assert cand.hdmi_version["value"] == "2.1"
    assert cand.audio_jack["value"] == "combo"


def test_parse_live_adapter_slim_tip_two_wattage_options():
    """PSREF publishes 300W / 400W / "No power adapter" options. We
    drop the "No power adapter" SKU and surface the two real ones."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.adapter_offerings is not None
    wattages = [a["wattage_w"]["value"] for a in cand.adapter_offerings]
    assert wattages == [300, 400]
    assert cand.adapter_connector["value"] == "slim-tip"


def test_parse_live_camera_two_offerings_with_e_shutter():
    """PSREF Camera key carries two SKU alternatives: ``5.0MP`` and
    ``HD 720p``; both with E-shutter."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.camera_offerings is not None
    assert len(cand.camera_offerings) == 2
    res_values = [c["resolution"]["value"] for c in cand.camera_offerings]
    assert res_values == ["5.0MP", "720p"]
    for c in cand.camera_offerings:
        assert c["privacy_shutter"]["value"] is True


def test_parse_live_audio_nahimic_quad_speakers_subwoofer():
    """Speakers row carries ``"4 stereo speakers, 2W x2 (woofers), ...
    optimized with Nahimic Audio"`` — count, tuning brand, and
    woofer presence all extract."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.speaker_count["value"] == 4
    assert cand.tuning_brand["value"] == "Nahimic"
    assert cand.has_subwoofer["value"] is True


def test_parse_live_keyboard_description_includes_backlight():
    """We append the sibling ``Keyboard Backlight`` key into the base
    keyboard description so the view layer sees the full picture."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.keyboard_offerings is not None
    assert len(cand.keyboard_offerings) == 1
    desc = cand.keyboard_offerings[0]["description"]["value"]
    assert "numeric keypad" in desc
    assert "RGB backlight" in desc
    assert cand.keyboard_offerings[0]["has_numpad"]["value"] is True
    assert cand.keyboard_offerings[0]["tier"]["value"] == "base"


def test_parse_live_dimensions_min_max_height_from_range():
    """PSREF publishes ``"21.9-26.65 mm"`` height range — both bundles
    populated."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.width_mm["value"] == 364.38
    assert cand.depth_mm["value"] == 275.94
    assert cand.height_mm_min["value"] == 21.9
    assert cand.height_mm_max["value"] == 26.65


def test_parse_live_weight_starting_at_min_only():
    """PSREF publishes ``"Starting at 2.56 kg"`` → weight_kg_min only."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.weight_kg_min["value"] == 2.56
    assert cand.weight_kg_max["value"] is None


def test_parse_live_design_top_and_bottom_aluminum():
    """Case Material reads ``"Aluminium (top), aluminium (bottom)"``;
    A-cover and D-cover are aluminum, C-cover not separately published."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.a_cover_material["value"] == "aluminum"
    assert cand.d_cover_material["value"] == "aluminum"
    # C-cover (palm rest) not separately called out → vendor-doesn't-publish.
    assert cand.c_cover_material["status"] == "vendor-doesn't-publish"
    # System Lighting key populates ``lighting``.
    assert cand.lighting["value"] is not None
    assert "RGB" in cand.lighting["value"]


def test_parse_live_thermals_marked_vendor_doesnt_publish():
    """PSREF doesn't publish thermal_design / TIM / fan_count."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    for col in ("thermal_design", "thermal_material", "tim", "fan_count"):
        bundle = getattr(cand, col)
        assert bundle["status"] == "vendor-doesn't-publish"
        assert bundle["value"] is None


# ---------------------------------------------------------------------------
# Synthetic
# ---------------------------------------------------------------------------


def test_parse_synthetic_year_extracted_from_title_paren():
    """Title "(2026)" → year=2026, year_was_inferred=False."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.year == 2026
    assert cand.year_was_inferred is False
    assert cand.vendor_full_name["status"] == "verified"


def test_parse_synthetic_model_code_extracted_from_title_token():
    """Title's machine-type token (``"16IRX10H"``) wins over the URL
    slug, even when the title also carries a trailing ``(year)``."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.model_code == "16IRX10H"


def test_parse_synthetic_series_legion_pro_7i():
    """``Legion Pro 7i`` is recognized as a distinct series from
    ``Legion Pro 7`` (the trailing ``i`` is the Intel-variant marker)."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.series["value"] == "Legion Pro 7i"


def test_parse_synthetic_unmapped_gpu_routes_to_needs_review_board():
    """RTX 6090 isn't in the static map → board with label=null +
    needs-review; the mapped 5050/5070 fold into one MB2 entry."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.boards is not None
    labels = [b["label"]["value"] for b in cand.boards]
    assert "MB2" in labels
    assert None in labels

    nonebd = next(b for b in cand.boards if b["label"]["value"] is None)
    assert nonebd["label"]["status"] == "needs-review"
    assert any(g["value"] == "RTX 6090" for g in nonebd["gpus"])
    assert all(g["status"] == "needs-review" for g in nonebd["gpus"])


def test_parse_synthetic_ambiguous_usbc_20gbps_flags_needs_review():
    """20Gbps USB-C labeling could be USB 3.2 Gen 2x2 or early USB4
    wording — version attaches with ``status: 'needs-review'`` so the
    runner queues it (mirrors HP's tuple-pattern)."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.usbc_non_thunderbolt_count["value"] == 1
    assert cand.usbc_non_thunderbolt_version["value"] == "USB 3.2 Gen 2x2"
    assert cand.usbc_non_thunderbolt_version["status"] == "needs-review"


def test_parse_synthetic_thunderbolt_5_extracted():
    """Thunderbolt 5 line → tb_version = TB5, tb_count = 1."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.usbc_thunderbolt_count["value"] == 1
    assert cand.usbc_thunderbolt_version["value"] == "TB5"


def test_parse_synthetic_display_mini_led_matte_hdr():
    """Synthetic display row exercises mini-LED, matte surface, and a
    plain DisplayHDR 1000 cert (vs the live True-Black-1000 cert)."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.display_offerings is not None
    d = cand.display_offerings[0]
    assert d["panel_type"]["value"] == "mini-LED"
    assert d["anti_glare"]["value"] == "matte"
    assert d["hdr_certification"]["value"] == "DisplayHDR 1000"


def test_parse_synthetic_audio_dolby_atmos_dual_speakers():
    """``"2 stereo speakers, 2W x2, optimized with Dolby Atmos"`` →
    speakers=2, tuning=Dolby Atmos, no woofer."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.speaker_count["value"] == 2
    assert cand.tuning_brand["value"] == "Dolby Atmos"
    assert cand.has_subwoofer["value"] is False


def test_parse_synthetic_camera_ir_supported():
    """Synthetic Camera row carries ``"IR camera"`` → ir_supported=True."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.camera_offerings is not None
    assert cand.camera_offerings[0]["resolution"]["value"] == "1080p"
    assert cand.camera_offerings[0]["ir_supported"]["value"] is True


def test_parse_synthetic_design_covers_marked_when_unanchored():
    """Synthetic Case Material publishes top + bottom only; C-cover
    stays ``vendor-doesn't-publish``."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.a_cover_material["value"] == "aluminum"
    assert cand.d_cover_material["value"] == "aluminum"
    assert cand.c_cover_material["status"] == "vendor-doesn't-publish"
