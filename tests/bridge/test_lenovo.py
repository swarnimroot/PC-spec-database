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
    ``HD 720p``; both with E-shutter. The ``5.0MP`` form is normalized
    to ``1440p`` (Session 12 Finding #5) so resolution values are
    comparable across vendors.
    """
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.camera_offerings is not None
    assert len(cand.camera_offerings) == 2
    res_values = [c["resolution"]["value"] for c in cand.camera_offerings]
    assert res_values == ["1440p", "720p"]
    for c in cand.camera_offerings:
        assert c["resolution"]["status"] == "verified"
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
    # System Lighting key populates ``lighting``. Embedded quotes
    # around brand tokens (``"Legion" logo …``) get stripped so the
    # stored prose is clean (Session 12 Finding #8).
    assert cand.lighting["value"] is not None
    assert "RGB" in cand.lighting["value"]
    assert '"' not in cand.lighting["value"]
    assert "Legion logo" in cand.lighting["value"]


def test_parse_live_cpu_chip_specs_extracted_from_psref_attrs():
    """PSREF publishes per-CPU ``Cores`` / ``Base Frequency`` /
    ``Max Frequency`` attributes inside the row; we map them onto the
    matching ``cpu_catalog`` columns (cores, base_clock, boost_clock)
    so ``catalog_resolve`` can seed."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert "Ryzen 9 9955HX" in cand.cpu_chip_specs
    specs = cand.cpu_chip_specs["Ryzen 9 9955HX"]
    assert specs["cores"] == "16"
    assert specs["base_clock"] == "2.5GHz"
    assert specs["boost_clock"] == "5.4GHz"


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


def test_parse_synthetic_camera_unknown_mp_value_flags_needs_review():
    """An MP value not in the normalization table (Session 12 Finding
    #5) falls back to the raw ``NMP`` form and is flagged
    ``needs-review`` so manual normalization can resolve it.
    """
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads((FIXTURE_DIR / SYNTH).read_text(encoding="utf-8"))
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    raw["specs"]["Performance > Multi-Media > Camera"] = "3.0MP, fixed focus"
    snap = ProductSnapshot.model_validate(raw)
    cand = lenovo_bridge.parse(snap)

    assert cand.camera_offerings is not None
    res = cand.camera_offerings[0]["resolution"]
    assert res["value"] == "3.0MP"
    assert res["status"] == "needs-review"


# ---------------------------------------------------------------------------
# Lenovo slug parser — ``_derive_lenovo_family_and_arch`` (Stage 7 T7.0a M2)
# ---------------------------------------------------------------------------


def test_family_arch_compressed_intel_rtx_irx():
    """``Legion_Pro_5_16IRX10`` → Intel CPU + RTX GPU → intel-rtx."""
    family, arch = lenovo_bridge._derive_lenovo_family_and_arch(
        "Legion Pro 5 16IRX10",
        "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16IRX10",
        "16IRX10",
    )
    assert family == "legion-pro-5-16-gen-10"
    assert arch == "intel-rtx"


def test_family_arch_compressed_amd_radeon_adr():
    """``Legion_Pro_5_16ADR10`` → AMD CPU + Radeon GPU → amd-radeon.
    Family matches the IRX10 variant so merge ingest collapses them."""
    family, arch = lenovo_bridge._derive_lenovo_family_and_arch(
        "Legion Pro 5 16ADR10",
        "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16ADR10",
        "16ADR10",
    )
    assert family == "legion-pro-5-16-gen-10"
    assert arch == "amd-radeon"


def test_family_arch_compressed_amd_rtx_arx_different_gen():
    """``Legion_Pro_5_16ARX8`` → AMD CPU + RTX GPU → amd-rtx. Gen 8 lands
    on its own family (separate from the Gen 10 family above)."""
    family, arch = lenovo_bridge._derive_lenovo_family_and_arch(
        "Legion Pro 5 16ARX8",
        "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16ARX8",
        "16ARX8",
    )
    assert family == "legion-pro-5-16-gen-8"
    assert arch == "amd-rtx"


def test_family_arch_compressed_intel_amd_gpu_iax():
    """``Legion_Pro_5_16IAX10`` → Intel CPU + AMD GPU → intel-amd-gpu."""
    family, arch = lenovo_bridge._derive_lenovo_family_and_arch(
        "Legion Pro 5 16IAX10",
        "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16IAX10",
        "16IAX10",
    )
    assert family == "legion-pro-5-16-gen-10"
    assert arch == "intel-amd-gpu"


def test_family_arch_compressed_afr_collapses_to_amd_radeon():
    """``AFR`` is mapped to amd-radeon (same as ``ADR``). The trailing
    ``H`` suffix is dropped from arch_marker (variants that differ only
    in suffix collapse to the same marker — full code stays in
    source_model_codes)."""
    family, arch = lenovo_bridge._derive_lenovo_family_and_arch(
        "Legion Pro 7 16AFR10H",
        "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H",
        "16AFR10H",
    )
    assert family == "legion-pro-7-16-gen-10"
    assert arch == "amd-radeon"


def test_family_arch_verbose_gen_split_intel_hint_from_line_suffix():
    """``Legion_Pro_7i_Gen_10`` → split on ``_Gen_``; the trailing ``i``
    on the line indicates Intel. No size in slug → family has no size."""
    family, arch = lenovo_bridge._derive_lenovo_family_and_arch(
        "Legion Pro 7i Gen 10",
        "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7i_Gen_10",
        "",
    )
    assert family == "legion-pro-7-gen-10"
    assert arch == "intel"


def test_family_arch_intel_and_amd_variants_share_family_code():
    """The whole point of family_code: the AMD ``16AFR10H`` cousin and
    the Intel ``16IRX10H`` variant of the Pro 7 Gen 10 platform produce
    the same family_code so the merge dispatcher can pair them."""
    family_amd, _ = lenovo_bridge._derive_lenovo_family_and_arch(
        "Legion Pro 7 16AFR10H",
        "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H",
        "16AFR10H",
    )
    family_intel, _ = lenovo_bridge._derive_lenovo_family_and_arch(
        "Legion Pro 7i 16IRX10H (2026)",
        "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7i_16IRX10H",
        "16IRX10H",
    )
    assert family_amd == family_intel == "legion-pro-7-16-gen-10"


def test_family_arch_unparseable_returns_none_none():
    """A slug that matches neither convention returns ``(None, None)``;
    the caller skips merge dispatch (and does NOT raise)."""
    family, arch = lenovo_bridge._derive_lenovo_family_and_arch(
        "Some Random ThinkBook 14",
        "https://example.com/random",
        "ZZZZZ",
    )
    assert family is None
    assert arch is None


def test_family_arch_unknown_arch_token_returns_family_but_no_arch():
    """A compressed slug whose ``arch_token`` isn't in the known table
    still yields a family code (so the merge layer can group variants)
    but leaves ``arch_marker`` ``None``."""
    family, arch = lenovo_bridge._derive_lenovo_family_and_arch(
        "Legion Slim 5 14APH9",
        "https://psref.lenovo.com/l/Product/Legion/Legion_Slim_5_14APH9",
        "14APH9",
    )
    assert family == "legion-slim-5-14-gen-9"
    assert arch is None


# ---------------------------------------------------------------------------
# Lenovo bridge integration — family_code / source_model_codes / arch_marker
# stamping (Stage 7 T7.0a M3)
# ---------------------------------------------------------------------------


def test_parse_live_stamps_family_code_and_source_model_codes():
    """Live AMD fixture lands family_code + single-element source list."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.family_code == "legion-pro-7-16-gen-10"
    assert cand.source_model_codes == ["16AFR10H"]


def test_parse_live_stamps_arch_marker_on_every_board():
    """Every board in a single snapshot shares the snapshot's arch."""
    snap = _load_snapshot(LIVE_LEGION)
    cand = lenovo_bridge.parse(snap)

    assert cand.boards is not None
    for board in cand.boards:
        assert board["arch_marker"] == "amd-radeon"


def test_parse_synthetic_stamps_intel_rtx_arch_marker():
    """Synthetic Intel-variant fixture stamps the Intel-RTX arch."""
    snap = _load_snapshot(SYNTH)
    cand = lenovo_bridge.parse(snap)

    assert cand.family_code == "legion-pro-7-16-gen-10"
    assert cand.source_model_codes == ["16IRX10H"]
    assert cand.boards is not None
    for board in cand.boards:
        assert board["arch_marker"] == "intel-rtx"


def test_parse_unparseable_title_leaves_family_code_and_arch_marker_absent():
    """When neither slug convention matches, family_code and
    source_model_codes stay ``None`` and no board has an ``arch_marker``
    key (we don't write a literal ``null`` leaf)."""
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads((FIXTURE_DIR / LIVE_LEGION).read_text(encoding="utf-8"))
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    # Stomp the title + URL with shapes neither convention parses. The
    # underlying model code regex still matches ``ZZZZZ9`` (>=5 chars,
    # has digit+letter) so model_code is non-empty, but the compressed
    # arch token ``ZZZZZ`` isn't in the family-line allow-list.
    raw["title"] = "Generic Notebook ZZZZZ9"
    raw["url"] = "https://example.com/random/notebook"
    snap = ProductSnapshot.model_validate(raw)
    cand = lenovo_bridge.parse(snap)

    assert cand.family_code is None
    assert cand.source_model_codes is None
    assert cand.boards is not None
    for board in cand.boards:
        assert "arch_marker" not in board


def test_parse_synthetic_lighting_strips_curly_quotes():
    """Quotes around brand tokens — straight or curly — are stripped
    so the stored prose is clean (Session 12 Finding #8).
    """
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads((FIXTURE_DIR / SYNTH).read_text(encoding="utf-8"))
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    raw["specs"]["Design > Mechanical > System Lighting"] = (
        "“Legion” logo with RGB"
    )
    snap = ProductSnapshot.model_validate(raw)
    cand = lenovo_bridge.parse(snap)

    assert cand.lighting["value"] == "Legion logo with RGB"
    assert "“" not in cand.lighting["value"]
    assert "”" not in cand.lighting["value"]
