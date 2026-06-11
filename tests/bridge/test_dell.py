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
# I/O counts — bare-USB Type-A fallback + weight regex (S60 Dell fixes)
# ---------------------------------------------------------------------------


def test_io_counts_bare_usb_lines_count_as_type_a():
    """Dell writes USB-A ports with no "Type-A" token (e.g.
    "2 USB 3.2 Gen 1 (5 Gbps) ports"). The bare-USB fallback must bucket
    those as Type-A while leaving Type-C lines as usbc, not folding them in."""
    text = (
        "2 USB 3.2 Gen 1 (5 Gbps) ports\n"
        "1 USB 3.2 Gen 2 (10 Gbps) Type-C port with Power Delivery and DisplayPort 1.4a\n"
        "1 USB 3.2 Gen 1 Type-C port\n"
        "1 HDMI 2.1 port\n"
        "1 Universal audio port\n"
        "1 RJ45 Ethernet port, 1GbE\n"
        "1 power-adapter port"
    )
    counts = dell_bridge._io_counts(text)
    # Bare "2 USB ... ports" → Type-A; the two Type-C lines stay usbc.
    assert counts["usba_count"] == 2
    assert counts["usbc_count"] == 2
    assert counts["tb_count"] == 0
    assert counts["hdmi_count"] == 1


def test_io_counts_explicit_type_a_not_double_counted_by_fallback():
    """A line that already carries "Type-A" must hit the Type-A branch and
    continue — the bare-USB fallback must NOT also count it (no double-count)."""
    text = (
        "2 USB Type-A 3.2 Gen 1 (5 Gbps)\n"
        "1 USB Type-A 3.2 Gen 1 (5 Gbps) with PowerShare\n"
        "1 USB Type-C port"
    )
    counts = dell_bridge._io_counts(text)
    assert counts["usba_count"] == 3  # 2 + 1, counted exactly once
    assert counts["usbc_count"] == 1


def test_weight_min_max_labels_parse_via_populate_dimensions():
    """Dell publishes "Minimum weight: 4.85 lb (2.20 kg)" /
    "Maximum weight: 4.96 lb (2.25 kg)". Both must flow through
    ``_populate_dimensions`` into the weight_kg_min/max bundles."""
    from competitive_database.bridge.types import CandidateProduct

    cand = CandidateProduct(model_code="test", year=2026)
    text = (
        "Minimum weight: 4.85 lb (2.20 kg)\n"
        "Maximum weight: 4.96 lb (2.25 kg)"
    )
    dell_bridge._populate_dimensions(
        cand,
        text,
        source_url="https://www.dell.com/example",
        captured_at="2026-06-10T00:00:00",
    )
    assert cand.weight_kg_min["value"] == 2.20
    assert cand.weight_kg_max["value"] == 2.25


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


def test_parse_synthetic_design_fields_vdp_when_no_chassis_section():
    """Area-51 live capture omits the Chassis section entirely. The
    bridge must still mark every Design field as ``vendor-doesn't-
    publish`` rather than leaving it ``None`` so the row carries
    provenance (Session 12 Finding #2).
    """
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads(
        (FIXTURE_DIR / "snapshot_aa18250_synthetic.json").read_text(encoding="utf-8")
    )
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    # Drop the Chassis / Materials sections to mirror the Area-51
    # live capture where Dell publishes neither.
    raw["specs"].pop("Chassis", None)
    raw["specs"].pop("Materials", None)
    snap = ProductSnapshot.model_validate(raw)
    cand = dell_bridge.parse(snap)

    for fld in (
        "a_cover_material",
        "c_cover_material",
        "d_cover_material",
        "lighting",
        "thermal_shelf",
    ):
        bundle = getattr(cand, fld)
        assert bundle is not None, f"{fld} should be populated as VDP, not None"
        assert bundle["status"] == "vendor-doesn't-publish", (
            f"{fld} expected VDP, got {bundle['status']}"
        )


def test_parse_cpu_with_series_disambiguator_preserves_parenthetical():
    # Intel's "Core N (Series M)" naming must not truncate at '(' — the
    # parenthetical disambiguates generation and must survive into the
    # canonical model name.
    offerings = dell_bridge._build_cpu_offerings(
        "Intel® Core™ 7 (Series 2) 240H",
        source_url="https://www.dell.com/example",
        captured_at="2026-05-15T00:00:00",
    )
    assert offerings is not None
    assert len(offerings) == 1
    assert offerings[0]["model"]["value"] == "Core 7 (Series 2) 240H"
    assert offerings[0]["model"]["status"] == "verified"


# ---------------------------------------------------------------------------
# Keyboard offerings — multi-option tiering (baseline, no configurator)
# ---------------------------------------------------------------------------


def test_build_keyboard_offerings_tiering_and_numpad():
    offerings = dell_bridge._build_keyboard_offerings(
        "Alienware backlit keyboard with numeric keypad\n"
        "Alienware per-key RGB keyboard, no numpad",
        source_url="https://www.dell.com/example",
        captured_at="2026-06-11T00:00:00",
    )
    assert offerings is not None
    assert len(offerings) == 2
    # Index 0 = base, every later entry = optional.
    assert offerings[0]["tier"]["value"] == "base"
    assert offerings[1]["tier"]["value"] == "optional"
    # Descriptions preserved verbatim; numpad detected per piece.
    assert offerings[0]["description"]["value"].startswith("Alienware backlit")
    assert offerings[0]["has_numpad"]["value"] is True
    assert offerings[1]["has_numpad"]["value"] is False


def test_build_keyboard_offerings_none_text_and_unknown_numpad():
    assert (
        dell_bridge._build_keyboard_offerings(
            None,
            source_url="https://www.dell.com/example",
            captured_at="2026-06-11T00:00:00",
        )
        is None
    )
    offerings = dell_bridge._build_keyboard_offerings(
        "Alienware mechanical keyboard",
        source_url="https://www.dell.com/example",
        captured_at="2026-06-11T00:00:00",
    )
    assert len(offerings) == 1
    # No numpad mention at all → vendor-doesn't-publish, not False.
    assert offerings[0]["has_numpad"]["status"] == "vendor-doesn't-publish"


# ---------------------------------------------------------------------------
# Configurator options (T9.4) — snapshot.options consumption
# ---------------------------------------------------------------------------


def _opt(label: str, status: str, oid: str) -> dict:
    return {"label": label, "status": status, "option_id": oid}


def _snapshot_with_options(
    options: dict, drop_specs: tuple[str, ...] = ()
) -> "ProductSnapshot":
    """Build a Dell snapshot off the synthetic fixture with ``options`` set.

    The tile Processor string carries a ``(24-Core ...)`` parenthetical so
    the chip-spec contamination guard can be exercised. ``drop_specs``
    removes tile spec keys, for options-only paths.
    """
    if not _HAS_SCRAPERS:
        pytest.skip("scrapers-lib not installed")
    raw = json.loads(
        (FIXTURE_DIR / "snapshot_aa18250_synthetic.json").read_text(encoding="utf-8")
    )
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    raw["specs"]["Processor"] = "Intel Core Ultra 9 285HX (24-Core, 36MB Cache)"
    for k in drop_specs:
        raw["specs"].pop(k, None)
    raw["options"] = options
    return ProductSnapshot.model_validate(raw)


_FULL_OPTIONS = {
    "Processor": [
        _opt("Intel Core Ultra 9 285HX", "selected", "cpu-285hx"),
        _opt("Intel Core Ultra 7 265HX", "available", "cpu-265hx"),
        _opt("Intel Core Ultra 9 290HX", "available", "cpu-290hx"),
        _opt("Intel Core Ultra 5 245HX", "unavailable", "cpu-245hx"),
    ],
    "Graphics": [
        _opt("NVIDIA GeForce RTX 5090", "selected", "gpu-5090"),
        _opt("NVIDIA GeForce RTX 5080", "available", "gpu-5080"),
        _opt("NVIDIA GeForce RTX 5070 Ti", "available", "gpu-5070ti"),
    ],
    "Memory": [
        _opt("32 GB DDR5", "selected", "mem-32"),
        _opt("16 GB DDR5", "available", "mem-16"),
        _opt("64 GB DDR5", "available", "mem-64"),
    ],
    "Storage": [
        _opt("2 TB SSD", "selected", "ssd-2tb"),
        _opt("4 TB SSD", "available", "ssd-4tb"),
    ],
    "Display": [
        _opt('18" QHD+ (2560x1600) 300Hz IPS', "selected", "disp-qhd"),
        _opt('18" FHD+ (1920x1200) 165Hz IPS', "available", "disp-fhd"),
    ],
    # Module keys + label shapes below mirror the REAL captured Aurora 16
    # configurator (scrapers-lib fixture): "Keyboard" / "Primary Battery" /
    # "AC Adapter" / "Operating System", labels like
    # "6-Cell Battery, 96 Whr (Integrated)" and "180W Adapter".
    "Keyboard": [
        _opt("English US backlit Alienware keyboard", "selected", "kb-us"),
        _opt("English US per-key AlienFX RGB keyboard", "available", "kb-rgb"),
        _opt("English UK backlit Alienware keyboard", "unavailable", "kb-uk"),
    ],
    "Primary Battery": [
        _opt("6-Cell Battery, 96 Whr (Integrated)", "selected", "bat-96"),
        _opt("9-Cell Battery, 97 Whr (Integrated)", "available", "bat-97"),
        _opt("3-Cell Battery, 60 Whr (Integrated)", "unavailable", "bat-60"),
    ],
    "AC Adapter": [
        _opt("330W Adapter", "selected", "psu-330"),
        _opt("360W Adapter", "available", "psu-360"),
        _opt("240W Adapter", "unavailable", "psu-240"),
    ],
    # OS variants are explicitly out of scope (DATA_MODEL.md) — the bridge
    # must IGNORE this module entirely.
    "Operating System": [
        _opt("Windows 11 Home", "selected", "os-home"),
        _opt("Windows 11 Pro", "available", "os-pro"),
    ],
}


def test_options_cpu_adds_configurable_models_and_skips_unavailable():
    cand = dell_bridge.parse(_snapshot_with_options(_FULL_OPTIONS))
    models = {o["model"]["value"] for o in cand.cpu_offerings}
    assert "Core Ultra 9 285HX" in models  # tile + selected (merge dedups dup)
    assert "Core Ultra 7 265HX" in models
    assert "Core Ultra 9 290HX" in models
    # ``unavailable`` (out-of-stock) options must NOT be surfaced.
    assert "Core Ultra 5 245HX" not in models


def test_options_cpu_chip_specs_not_contaminated_across_configs():
    """The tile's 24-Core count must attach ONLY to the tile-named CPU, not
    to configurator-added CPUs that publish no core count."""
    cand = dell_bridge.parse(_snapshot_with_options(_FULL_OPTIONS))
    assert cand.cpu_chip_specs.get("Core Ultra 9 285HX") == {"cores": "24"}
    assert "Core Ultra 7 265HX" not in cand.cpu_chip_specs
    assert "Core Ultra 9 290HX" not in cand.cpu_chip_specs


def test_options_gpu_adds_boards_and_dedups_selected_against_tile():
    cand = dell_bridge.parse(_snapshot_with_options(_FULL_OPTIONS))
    gpu_names = [g["value"] for b in cand.boards for g in b["gpus"]]
    assert "RTX 5080" in gpu_names
    assert "RTX 5070 Ti" in gpu_names
    # tile GPU + ``selected`` restatement collapse to exactly one bundle.
    assert gpu_names.count("RTX 5090") == 1


def test_options_memory_raises_max_ceiling():
    cand = dell_bridge.parse(_snapshot_with_options(_FULL_OPTIONS))
    # Tile ships 32 GB; configurator offers 64 GB → ceiling is 64.
    assert cand.memory_max_gb["value"] == 64
    assert cand.memory_max_gb["status"] == "verified"


def test_options_storage_raises_max_ceiling():
    cand = dell_bridge.parse(_snapshot_with_options(_FULL_OPTIONS))
    # Tile ships 2 TB; configurator offers 4 TB → 4000 GB ceiling.
    assert cand.storage_max_gb["value"] == 4000


def test_options_display_adds_configurable_panels():
    cand = dell_bridge.parse(_snapshot_with_options(_FULL_OPTIONS))
    refresh = {
        o["refresh_rate_hz"]["value"]
        for o in cand.display_offerings
        if o.get("refresh_rate_hz")
    }
    assert {300, 165}.issubset(refresh)


def test_options_keyboard_adds_offerings_and_skips_unavailable():
    cand = dell_bridge.parse(_snapshot_with_options(_FULL_OPTIONS))
    descs = [o["description"]["value"] for o in cand.keyboard_offerings]
    # Tile keyboard stays the base offering.
    assert descs[0].startswith("Alienware mSeries CherryMX")
    assert cand.keyboard_offerings[0]["tier"]["value"] == "base"
    # Selectable configurator keyboards land as optional offerings.
    assert "English US backlit Alienware keyboard" in descs
    assert "English US per-key AlienFX RGB keyboard" in descs
    for off in cand.keyboard_offerings[1:]:
        assert off["tier"]["value"] == "optional"
    # ``unavailable`` keyboard must NOT be surfaced.
    assert "English UK backlit Alienware keyboard" not in descs


def test_options_battery_adds_configurable_cells_and_dedups_at_merge():
    cand = dell_bridge.parse(_snapshot_with_options(_FULL_OPTIONS))
    pairs = [
        (o["wattage_wh"]["value"], o["cell_count"]["value"])
        for o in cand.battery_offerings
    ]
    # Tile battery stays the base offering; the real-label "Whr" available
    # option ("9-Cell Battery, 97 Whr (Integrated)") parses and lands.
    assert pairs[0] == (96, 6)
    assert cand.battery_offerings[0]["tier"]["value"] == "base"
    assert (97, 9) in pairs
    # ``unavailable`` battery must NOT be surfaced.
    assert (60, 3) not in pairs
    # The ``selected`` option restates the tile battery (96 Wh / 6-cell);
    # the ingest merge collapses the two by identity (wattage_wh, cell_count).
    from competitive_database.ingest.runner import _merge_offerings

    merged = _merge_offerings("battery_offerings", [cand])
    merged_pairs = [
        (o["wattage_wh"]["value"], o["cell_count"]["value"]) for o in merged
    ]
    assert merged_pairs.count((96, 6)) == 1


def test_options_adapter_adds_wattages_and_dedups_at_merge():
    cand = dell_bridge.parse(_snapshot_with_options(_FULL_OPTIONS))
    watts = [o["wattage_w"]["value"] for o in cand.adapter_offerings]
    # Tile psu stays the base offering; the available 360W option lands.
    assert watts[0] == 330
    assert cand.adapter_offerings[0]["tier"]["value"] == "base"
    assert 360 in watts
    # ``unavailable`` adapter must NOT be surfaced.
    assert 240 not in watts
    # Configurator adapter labels carry no connector info either — the
    # vendor-doesn't-publish marker still applies.
    assert cand.adapter_connector["status"] == "vendor-doesn't-publish"
    # The ``selected`` 330W option restates the tile psu; the ingest merge
    # collapses the two by identity (wattage_w).
    from competitive_database.ingest.runner import _merge_offerings

    merged = _merge_offerings("adapter_offerings", [cand])
    assert [o["wattage_w"]["value"] for o in merged].count(330) == 1


def test_options_adapter_from_configurator_only():
    """No tile psu key at all → the configurator alone still yields adapter
    offerings, and the connector vdp marker is set."""
    opts = {
        "AC Adapter": [
            _opt("180W Adapter", "selected", "psu-180"),
            _opt("240W Adapter", "available", "psu-240"),
        ]
    }
    cand = dell_bridge.parse(
        _snapshot_with_options(opts, drop_specs=("Power Supply",))
    )
    watts = [o["wattage_w"]["value"] for o in cand.adapter_offerings]
    assert watts == [180, 240]
    assert cand.adapter_offerings[0]["tier"]["value"] == "base"
    assert cand.adapter_connector["status"] == "vendor-doesn't-publish"


def test_options_operating_system_module_is_ignored():
    """OS variants are explicitly out of scope (DATA_MODEL.md §Out of scope);
    the "Operating System" module must not leak into any candidate field.
    The tile's own "Operating System" spec key was already unconsumed."""
    cand = dell_bridge.parse(_snapshot_with_options(_FULL_OPTIONS))
    # "Windows 11 Pro" exists ONLY in the OS options module — it must not
    # appear anywhere in the parsed candidate.
    assert "Windows 11 Pro" not in repr(vars(cand))


def test_no_options_path_is_unchanged():
    """A snapshot without ``.options`` must parse exactly as before."""
    snap = _load_snapshot("snapshot_useaa18250wmlkcto01.json")
    assert (snap.options or {}) == {}
    cand = dell_bridge.parse(snap)
    # Sanity: still produces the same shaped output (no crash, has CPU).
    assert cand.cpu_offerings is not None


# ---------------------------------------------------------------------------
# Configurator options (T9.4) — hardening against REAL Dell labels
# ---------------------------------------------------------------------------
#
# The 7 tests above use clean synthetic labels ("NVIDIA GeForce RTX 5090").
# Live Dell configurator labels carry trademark glyphs, trailing VRAM, and
# mixed-unit capacity copy. These guard the dedup / parse paths against the
# noisier real shapes and exercise the ComponentOption object branch.


def test_options_gpu_real_label_dedups_against_canonical_tile():
    """A real-shaped ``selected`` GPU label — ``"NVIDIA® GeForce RTX™ 5090
    16 GB GDDR7"`` (trademark glyphs + trailing VRAM) — must collapse onto
    the canonical tile GPU ``"RTX 5090"`` and NOT emit a duplicate board."""
    opts = {
        "Graphics": [
            _opt("NVIDIA® GeForce RTX™ 5090 16 GB GDDR7", "selected", "gpu-5090"),
            _opt("NVIDIA® GeForce RTX™ 5080 16 GB GDDR7", "available", "gpu-5080"),
        ]
    }
    cand = dell_bridge.parse(_snapshot_with_options(opts))
    gpu_names = [g["value"] for b in cand.boards for g in b["gpus"]]
    # ™/® and trailing "16 GB GDDR7" must all canonicalize to "RTX 5090".
    assert gpu_names.count("RTX 5090") == 1
    # The available option still lands as a distinct board GPU.
    assert "RTX 5080" in gpu_names
    # No phantom raw-label GPU survived (would mean the regex/canonicalizer
    # failed to strip the VRAM/trademark noise).
    assert not any("GDDR7" in str(n) or "GB" in str(n) for n in gpu_names)
    # Single power-tier (MB1) → exactly one board, both GPUs grouped.
    assert len(cand.boards) == 1


def test_options_memory_mixed_unit_label_parses_total_capacity():
    """Dell publishes RAM configs as ``"32 GB, 2 x 16 GB"`` (total first,
    then the DIMM breakdown). The configurator ceiling must read the TOTAL
    (32), not the 16 GB per-DIMM token."""
    opts = {
        "Memory": [
            _opt("32 GB, 2 x 16 GB", "selected", "mem-32"),
        ]
    }
    cand = dell_bridge.parse(_snapshot_with_options(opts))
    # CORRECT expected value is 32 (the published total). If the parser
    # latched onto "16" from "2 x 16 GB", this assertion FAILS — a real bug.
    assert cand.memory_max_gb["value"] == 32


def test_options_component_option_object_path():
    """All 7 existing tests pass option dicts; real snapshots carry
    ``ComponentOption`` objects. Exercise the attribute branch of
    ``_option_labels`` so the object path is covered too."""
    from scrapers_lib import ComponentOption

    opts = {
        "Graphics": [
            ComponentOption(
                label="NVIDIA GeForce RTX 5080", status="available", option_id="gpu-5080"
            ),
            ComponentOption(
                label="NVIDIA GeForce RTX 5070 Ti",
                status="unavailable",
                option_id="gpu-5070ti",
            ),
        ],
        "Memory": [
            ComponentOption(label="64 GB DDR5", status="available", option_id="mem-64"),
        ],
        "Primary Battery": [
            ComponentOption(
                label="9-Cell Battery, 97 Whr (Integrated)",
                status="available",
                option_id="bat-97",
            ),
        ],
        "AC Adapter": [
            ComponentOption(
                label="360W Adapter", status="available", option_id="psu-360"
            ),
        ],
        "Keyboard": [
            ComponentOption(
                label="English US per-key AlienFX RGB keyboard",
                status="available",
                option_id="kb-rgb",
            ),
        ],
    }
    cand = dell_bridge.parse(_snapshot_with_options(opts))
    gpu_names = [g["value"] for b in cand.boards for g in b["gpus"]]
    # ``available`` object option is surfaced...
    assert "RTX 5080" in gpu_names
    # ...``unavailable`` object option is skipped (same rule as dict path).
    assert "RTX 5070 Ti" not in gpu_names
    # Object-path Memory option raises the ceiling.
    assert cand.memory_max_gb["value"] == 64
    # Object-path battery / adapter / keyboard options land as offerings.
    assert (97, 9) in [
        (o["wattage_wh"]["value"], o["cell_count"]["value"])
        for o in cand.battery_offerings
    ]
    assert 360 in [o["wattage_w"]["value"] for o in cand.adapter_offerings]
    assert "English US per-key AlienFX RGB keyboard" in [
        o["description"]["value"] for o in cand.keyboard_offerings
    ]


def test_options_malformed_inputs_do_not_crash():
    """Empty / None / None-valued-module options must parse without error
    and preserve the tile base specs."""
    # 1. Explicit empty dict.
    cand = dell_bridge.parse(_snapshot_with_options({}))
    assert cand.cpu_offerings is not None
    assert cand.boards[0]["gpus"][0]["value"] == "RTX 5090"
    assert cand.memory_max_gb["value"] == 32
    # Battery / adapter / keyboard tile specs stay byte-identical too.
    assert cand.battery_offerings[0]["wattage_wh"]["value"] == 96
    assert cand.adapter_offerings[0]["wattage_w"]["value"] == 330
    assert len(cand.keyboard_offerings) == 1

    # 2. options=None (snapshot.options absent).
    cand = dell_bridge.parse(_snapshot_with_options(None))
    assert cand.cpu_offerings is not None
    assert cand.boards[0]["gpus"][0]["value"] == "RTX 5090"

    # 3. A module key whose value is None (no option list). The
    #    ProductSnapshot schema rejects None-valued option lists at
    #    validation, so this shape can't reach ``parse`` via a snapshot —
    #    exercise the defensive ``options.get(key) or []`` branch in
    #    ``_option_labels`` directly instead.
    assert dell_bridge._option_labels({"Graphics": None}, ("Graphics",)) == []
    assert dell_bridge._option_labels(None, ("Graphics",)) == []
    assert dell_bridge._option_labels({}, ("Graphics",)) == []
