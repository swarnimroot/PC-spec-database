"""Unit tests for bridge.helpers (unit parsing + name decomposition)."""

from __future__ import annotations

from datetime import datetime, timezone

from competitive_database.bridge import helpers as h


# ---------------------------------------------------------------------------
# Unit parsing
# ---------------------------------------------------------------------------


def test_parse_gb_with_and_without_space():
    assert h.parse_gb("16GB") == 16
    assert h.parse_gb("32 GB") == 32
    assert h.parse_gb("32GB DDR5 5600 MT/s") == 32
    assert h.parse_gb("no number here") is None


def test_parse_mts_with_and_without_space():
    assert h.parse_mts("5600 MT/s") == 5600
    assert h.parse_mts("DDR5 5600MHz") == 5600
    assert h.parse_mts("6400MT/s") == 6400


def test_parse_hz():
    assert h.parse_hz("240Hz") == 240
    assert h.parse_hz("240 Hz") == 240
    assert h.parse_hz("18 inches") is None


def test_parse_inches_with_quote():
    assert h.parse_inches('18"') == 18.0
    assert h.parse_inches("18-inch") == 18.0
    assert h.parse_inches("18 inches") == 18.0
    assert h.parse_inches("16.0 in.") == 16.0


def test_parse_wh_handles_whr_suffix():
    assert h.parse_wh("96 Whr") == 96
    assert h.parse_wh("99Wh") == 99
    assert h.parse_wh("99 Wh (integrated)") == 99


def test_parse_kg_and_lb():
    assert h.parse_kg("3.86 kg") == 3.86
    assert h.parse_lb("8.51 lb") == 8.51


def test_parse_cell_count():
    assert h.parse_cell_count("6-cell, 96 Wh") == 6
    assert h.parse_cell_count("3 cell battery") == 3


def test_parse_resolution_pixels():
    assert h.parse_resolution_pixels("2560 x 1600") == "2560×1600"
    assert h.parse_resolution_pixels("1920×1080") == "1920×1080"


# ---------------------------------------------------------------------------
# split_options
# ---------------------------------------------------------------------------


def test_split_options_preserves_commas_inside_parens():
    pieces = h.split_options(
        "Intel Core Ultra 9 285HX (24-Core, 36MB Cache, 2.7GHz to 5.5GHz)"
    )
    assert pieces == ["Intel Core Ultra 9 285HX (24-Core, 36MB Cache, 2.7GHz to 5.5GHz)"]


def test_split_options_splits_on_newlines_and_or():
    text = '16" QHD+ 240Hz\n18" UHD+ 120Hz'
    assert h.split_options(text) == ['16" QHD+ 240Hz', '18" UHD+ 120Hz']
    assert h.split_options("RTX 5090 or RTX 5080") == ["RTX 5090", "RTX 5080"]


def test_split_options_aggressive_splits_top_level_commas():
    pieces = h.split_options_aggressive("a, b, c")
    assert pieces == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Name decomposition
# ---------------------------------------------------------------------------


def test_derive_year_from_parens_in_title():
    fb = datetime(2026, 5, 7, tzinfo=timezone.utc)
    year, inferred = h.derive_year("ROG Strix G16 (2025)", "https://example.com/x", fb)
    assert (year, inferred) == (2025, False)


def test_derive_year_from_bare_year_in_url():
    fb = datetime(2026, 5, 7, tzinfo=timezone.utc)
    year, inferred = h.derive_year(
        "Generic Laptop", "https://example.com/2024-flagship", fb
    )
    assert (year, inferred) == (2024, False)


def test_derive_year_falls_back_to_fetched_at():
    fb = datetime(2026, 5, 7, tzinfo=timezone.utc)
    year, inferred = h.derive_year(
        "Alienware 18 Area-51 Gaming Laptop",
        "https://www.dell.com/en-us/shop/.../alienware-area-51-aa18250-gaming-laptop",
        fb,
    )
    assert (year, inferred) == (2026, True)


def test_derive_dell_model_code_from_alienware_slug():
    url = (
        "https://www.dell.com/en-us/shop/dell-laptops/"
        "alienware-18-area-51-gaming-laptop/spd/"
        "alienware-area-51-aa18250-gaming-laptop"
    )
    assert h.derive_dell_model_code(url) == "aa18250"


def test_derive_sub_brand_alienware():
    title = "Alienware 18 Area-51 Gaming Laptop"
    url = "https://www.dell.com/en-us/shop/dell-laptops/alienware-..."
    assert h.derive_sub_brand(title, url) == "Alienware"


def test_derive_alienware_series_picks_area_51():
    title = "Alienware 18 Area-51 Gaming Laptop"
    url = "https://www.dell.com/en-us/shop/dell-laptops/alienware-..."
    assert h.derive_alienware_series(title, url) == "Area-51"


def test_tier_for_index():
    assert h.tier_for_index(0) == "base"
    assert h.tier_for_index(1) == "optional"
    assert h.tier_for_index(99) == "optional"


def test_infer_cpu_brand_intel_amd():
    assert h.infer_cpu_brand("Core Ultra 9 285HX") == "Intel"
    assert h.infer_cpu_brand("Intel Core i9-14900HX") == "Intel"
    assert h.infer_cpu_brand("Ryzen 9 9955HX3D") == "AMD"
    assert h.infer_cpu_brand("AMD Ryzen AI 9 HX 370") == "AMD"
    assert h.infer_cpu_brand("Mystery Chip") is None


def test_infer_gpu_brand_nvidia_amd():
    assert h.infer_gpu_brand("RTX 5090") == "NVIDIA"
    assert h.infer_gpu_brand("Radeon RX 9070M") == "AMD"
    assert h.infer_gpu_brand("Arc A770") == "Intel"


# ---------------------------------------------------------------------------
# lookup_board (Decision 5: static GPU → board map)
# ---------------------------------------------------------------------------


def test_lookup_board_top_tier_maps_to_mb1():
    assert h.lookup_board("RTX 5070 Ti") == "MB1"
    assert h.lookup_board("RTX 5080") == "MB1"
    assert h.lookup_board("RTX 5090") == "MB1"


def test_lookup_board_mid_tier_maps_to_mb2():
    assert h.lookup_board("RTX 5050") == "MB2"
    assert h.lookup_board("RTX 5060") == "MB2"
    assert h.lookup_board("RTX 5070") == "MB2"


def test_lookup_board_entry_tier_maps_to_mb3():
    assert h.lookup_board("RTX 3050") == "MB3"
    assert h.lookup_board("RTX 4050") == "MB3"


def test_lookup_board_strips_vendor_prefix():
    # Vendor prefixes must be stripped before lookup.
    assert h.lookup_board("NVIDIA GeForce RTX 5090") == "MB1"
    assert h.lookup_board("GeForce RTX 5070") == "MB2"


def test_lookup_board_case_insensitive():
    assert h.lookup_board("rtx 5090") == "MB1"
    assert h.lookup_board("RTX 5070 ti") == "MB1"


def test_lookup_board_returns_none_for_unmapped():
    assert h.lookup_board("RTX 6090") is None
    assert h.lookup_board("Radeon RX 9070M") is None
    assert h.lookup_board("") is None
    assert h.lookup_board("garbage chip") is None


# ---------------------------------------------------------------------------
# clean_product_name (strip trailing generic marketing suffixes)
# ---------------------------------------------------------------------------


def test_clean_product_name_strips_gaming_laptop():
    assert h.clean_product_name("Alienware 15 Gaming Laptop") == "Alienware 15"


def test_clean_product_name_preserves_internal_tokens():
    # Area-51 has an internal hyphen; only the trailing suffix is stripped.
    assert (
        h.clean_product_name("Alienware 18 Area-51 Gaming Laptop")
        == "Alienware 18 Area-51"
    )


def test_clean_product_name_strips_bare_laptop():
    assert h.clean_product_name("OMEN 16 Laptop") == "OMEN 16"


def test_clean_product_name_strips_gaming_laptop_rog():
    assert h.clean_product_name("ROG Strix G16 Gaming Laptop") == "ROG Strix G16"


def test_clean_product_name_leaves_clean_name_unchanged():
    assert h.clean_product_name("Legion Pro 7") == "Legion Pro 7"


def test_clean_product_name_preserves_remaining_casing():
    # Trailing "gaming laptop" strips; the rest keeps its original lower case.
    assert h.clean_product_name("aurora 16 gaming laptop") == "aurora 16"


def test_clean_product_name_empty_guard():
    # Stripping everything would empty the name -> return original unchanged.
    assert h.clean_product_name("Gaming Laptop") == "Gaming Laptop"
    assert h.clean_product_name("Gaming") == "Gaming"


def test_clean_product_name_idempotent():
    once = h.clean_product_name("ROG Strix G16 Gaming Laptop")
    assert h.clean_product_name(once) == once
    assert h.clean_product_name("Alienware 15") == "Alienware 15"


def test_clean_product_name_midname_token_preserved():
    # "Gaming" is not trailing here -> must stay intact.
    assert h.clean_product_name("Gaming Beast 17") == "Gaming Beast 17"
    assert h.clean_product_name("Laptop Pro Edition") == "Laptop Pro Edition"


def test_clean_product_name_trims_trailing_punctuation():
    assert h.clean_product_name("Nitro 5, Gaming Laptop") == "Nitro 5"


def test_clean_product_name_empty_input():
    assert h.clean_product_name("") == ""
