# Data Model — Field-by-Field Schema Reference

Full schema reference for the competitive gaming-laptop spec database. For project scope, architecture, and policy, see [`README.md`](README.md).

---

## Tables

1. **`cpu_catalog`** — one row per CPU model.
2. **`gpu_catalog`** — one row per GPU model.
3. **`products`** — one row per gaming-laptop product, identified by **(model code, year)**.

Plus per-cell metadata — see [Provenance and status](#provenance-and-status).

---

## CPU Catalog

One row per distinct CPU model (e.g., Core Ultra 9 285HX, Ryzen 9 8945HX). Populated deterministically from Intel ARK and AMD spec pages plus name-suffix rules. New chips found in scrapes are auto-added with `status = needs-review`; user confirms once → `vouched`.

**Vendor-published chip-spec seeding (Session 7).** When a laptop spec page surfaces chip-level data (e.g., ASUS publishes NPU TOPS in its `Neural Processor` section, Lenovo publishes per-CPU cores/clocks/process-node in its PSREF attribute rows, HP/Dell publish core counts inline with the CPU prose), the bridge attaches those values to the candidate. The runner applies them per spec field:

* If the catalog cell is `NULL` → write the new value (no queue row).
* If `catalog_status = 'needs-review'` and the existing cell matches → no-op.
* If `catalog_status = 'needs-review'` and the existing cell differs → overwrite (freshest extraction wins) **and** insert a `review_queue` row (`conflict_type = 'value_disagreement'`, `field_path = 'cpu_catalog.<model>.<column>'`).
* If `catalog_status = 'vouched'` → keep the existing value, queue a `value_disagreement` row.

Vendor coverage today: ASUS (`npu_tops`, `cores`); Lenovo (`cores`, `base_clock`, `boost_clock`, `architecture`, `process_node`); HP (`cores`); Dell (`cores`). Vendors only seed fields they actually publish.

| Field | Type | Description |
|---|---|---|
| `model` | string (PK) | Canonical model name as published by manufacturer (e.g., "Core Ultra 9 285HX"). Foreign key target from `products.cpu_offerings`. |
| `brand` | string | Intel / AMD / *open enum* |
| `architecture` | string | e.g., Arrow Lake HX, Hawk Point, Raptor Lake H |
| `cores` | number | Total core count |
| `npu_tops` | number | NPU TOPS — chip-level NPU performance |
| `base_clock` | number (GHz) | Optional |
| `boost_clock` | number (GHz) | Optional |
| `process_node` | string | e.g., "Intel 3", "TSMC 4nm" — optional |
| `nominal_tdp` | number (W) | Chip's nominal TDP — optional reference |

---

## GPU Catalog

One row per distinct GPU model (e.g., RTX 5070 Ti, Radeon RX 9070M). Populated deterministically from NVIDIA and AMD spec pages. Same auto-add + review flow as CPU.

| Field | Type | Description |
|---|---|---|
| `model` | string (PK) | Canonical model name (e.g., "RTX 5070 Ti"). Foreign key target from `products.boards.gpus`. |
| `brand` | string | NVIDIA / AMD / Intel / *open enum* |
| `architecture` | string | e.g., Blackwell, RDNA 4, Battlemage |
| `cuda_cores` | number | Or stream processors / Xe cores per brand |
| `vram_base` | number (GB) | |
| `base_clock` | number | Optional |
| `boost_clock` | number | Optional |

---

## Products Table — Field Categories

Each product identified by `(model_code, year)`.

### Identity

| Field | Type | Notes |
|---|---|---|
| `vendor_full_name` | string | Scraped as-is (e.g., "ASUS ROG Strix G16 (2025)"). |
| `brand` | string | Mechanically derived (Dell / HP / Lenovo / ASUS / Acer / MSI). |
| `sub_brand` | string | Mechanically derived (e.g., Alienware, ROG, Legion). |
| `series` | string | Mechanically derived (e.g., Strix, Aurora). |
| `model_code` | string | Mechanically derived (e.g., G16, m18). **Part of identity.** |
| `year` | number | Mechanically derived where in name; manual where not. **Part of identity.** |
| `status` | string | Manual. `active` / `discontinued`. |
| `segment` | string | Manual. `entry` / `premium` / `flagship`. |

### CPU

| Field | Type | Notes |
|---|---|---|
| `cpu_offerings` | list of strings | Each = a CPU `model` from `cpu_catalog`. Variable length. |
| `cpu_tdp_max` | number (W) | Single product-level max. |

**Trade-off accepted:** no per-CPU TDP variance tracked. Implicit answer for "what TDP does the U9 run at on this product" = min(catalog `nominal_tdp`, product `cpu_tdp_max`).

### GPU + Power (unified into "boards")

| Field | Type | Notes |
|---|---|---|
| `boards` | list of board entries | Each board = a structured entry below. Variable length. |

**Each `boards[i]` entry:**

| Sub-field | Type | Notes |
|---|---|---|
| `label` | string | Vendor convention (e.g., MB1, MB2, MB3). |
| `tpp_max` | number (W) | Total platform power cap on this board. Sometimes scraped, often manual. |
| `tgp_max` | number (W) | Board's max GPU TGP — single ceiling value. When a vendor publishes per-GPU TGPs (e.g., Lenovo PSREF lists `TGP: 175W` for one GPU and `TGP: 140W` for another on the same board), the bridge stores the **maximum** across the board's GPUs. The column name (`tgp_max`) reflects this aggregation. |
| `gpus` | list of strings | All GPUs supported on this board. Each = a GPU `model` from `gpu_catalog`. |

**Derived view "GPUs available on this product"** = distinct set of GPU model refs across all boards (deduped).

**Trade-off accepted:** one `tgp_max` per board collapses per-GPU TGP variance within a board. (E.g., MB1 with 5090 at 175W, 5080 at 150W, 5070 Ti at 140W — only the 175W ceiling is stored.) The bridge layer takes the **max** across the board's GPUs when the vendor publishes per-GPU TGPs.

#### GPU → Board mapping (static)

Vendors don't publish per-product board labels. The bridge layer assigns labels deterministically from the GPU's power class using the table below. Cross-tile, all GPUs in the same tier collapse into one boards entry.

| GPU model | Board |
|---|---|
| RTX 5070 Ti | MB1 |
| RTX 5080 | MB1 |
| RTX 5090 | MB1 |
| RTX 5050 | MB2 |
| RTX 5060 | MB2 |
| RTX 5070 | MB2 |
| RTX 3050 | MB3 |
| RTX 4050 | MB3 |

Implemented as `bridge/helpers.GPU_TO_BOARD` plus `bridge/helpers.lookup_board(gpu_model)`. Match is case-insensitive on the canonical model token (NVIDIA / GeForce / AMD / Radeon prefixes are stripped before lookup).

**Unmapped GPUs:** the bridge emits a boards entry with `label: null` and the GPU bundle marked `needs-review`. The runner's existing `low_confidence_extraction` queue (and `new_chip_unverified` via catalog auto-add) covers it — no separate "unmapped GPU" queue type. Add the GPU to the table when its power class is known.

`tpp_max` stays `vendor-doesn't-publish` across all current vendors (Dell, HP, Lenovo) — no vendor exposes board-level TPP. `tgp_max` stays `vendor-doesn't-publish` for Dell and HP, and is populated by Lenovo (max of the per-GPU TGPs PSREF publishes per row). ASUS coverage to be confirmed when its parser lands.

### Display

| Field | Type | Notes |
|---|---|---|
| `display_offerings` | list of display entries | Variable length. |

**Each display offering:**

| Sub-field | Type | Notes |
|---|---|---|
| `size_inches` | number | E.g., 16, 18 |
| `panel_type` | string | IPS / OLED / mini-LED / IPS-level / *open enum* |
| `resolution_label` | string | e.g., "QHD+", "WQXGA" |
| `resolution_pixels` | string | e.g., "2560×1600" |
| `refresh_rate_hz` | number | |
| `nits_peak` | number | |
| `hdr_certification` | string | HDR400 / HDR1000 / DisplayHDR True Black / none / *open enum* |
| `dci_p3_pct` | number, nullable | |
| `srgb_pct` | number, nullable | |
| `response_time_ms` | number | |
| `vrr` | string | G-Sync / FreeSync / Adaptive Sync / none / *open enum* |
| `anti_glare` | string | matte / glossy |
| `tier` | string | base / optional |

### Battery

| Field | Type |
|---|---|
| `battery_offerings` | list of battery entries |

**Each battery offering:**

| Sub-field | Type | Notes |
|---|---|---|
| `wattage_wh` | number | E.g., 90, 99 |
| `cell_count` | number | E.g., 3, 4, 6 |
| `tier` | string | base / optional |

### Memory

(Single-value per product — platform capability.)

| Field | Type | Notes |
|---|---|---|
| `memory_max_gb` | number | |
| `memory_speed_mts` | number | MT/s |
| `memory_slots` | number | 0 = soldered (no upgrade) |
| `memory_type` | string | DDR5 / DDR4 / LPDDR5X / LPDDR5 / *open enum* |
| `memory_overclocking` | boolean | Vendor advertises OC support? |

### Storage

(Mirrors the Memory section's shape: a list-of-slots field plus a single platform-level capacity ceiling.)

| Field | Type | Notes |
|---|---|---|
| `storage_slots` | list of slot entries | Length = number of physical slots. Mixed-gen configs preserved. |
| `storage_max_gb` | number | Single value: maximum published storage capacity, in GB. Platform ceiling — parallels `memory_max_gb`. 1 TB → 1000 GB; if the vendor publishes "1024GB" we keep 1024 (no silent unit conversion). |

**Each slot entry:**

| Sub-field | Type | Notes |
|---|---|---|
| `gen` | number | PCIe gen (4, 5) |

### Network

| Field | Type | Notes |
|---|---|---|
| `wifi_standard` | string | Wi-Fi 5 / 6 / 6E / 7 / *open enum* |
| `ethernet` | string | none / 1GbE / 2.5GbE / 5GbE |
| `bluetooth_version` | string | 5.0 / 5.1 / 5.2 / 5.3 / 5.4 / *open enum* |

### I/O

| Field | Type | Notes |
|---|---|---|
| `usbc_thunderbolt` | `{count, version}` | TB3 / TB4 / TB5 |
| `usbc_non_thunderbolt` | `{count, version}` | USB 3.2 Gen 1 / Gen 2 / USB4 |
| `usba` | `{count, version}` | USB 3.2 Gen 1 / Gen 2 |
| `hdmi` | `{count, version}` | 2.0 / 2.1 |
| `sd_card` | string | none / SD / microSD |
| `sd_card_speed` | string, nullable | UHS-I / UHS-II / UHS-III |
| `audio_jack` | string | combo / separate / none |

### Adapter

| Field | Type | Notes |
|---|---|---|
| `adapter_offerings` | list | Each = `{wattage_w, tier}`. |
| `adapter_connector` | string | USB-C PD / barrel (Dell round pin) / slim-tip (Lenovo Legion) / rectangle (ASUS ROG flat plug) / proprietary. **Product-level**, assumes uniform across offerings. |

### Camera

| Field | Type |
|---|---|
| `camera_offerings` | list of camera entries |

**Each camera offering:**

| Sub-field | Type | Notes |
|---|---|---|
| `resolution` | string | 720p / 1080p / 1440p / 4K |
| `ir_supported` | boolean | Windows Hello support |
| `privacy_shutter` | boolean | |
| `tier` | string | base / optional |

### Audio

| Field | Type | Notes |
|---|---|---|
| `speaker_count` | number | |
| `tuning_brand` | string | Dolby Atmos / B&O / JBL / Harman / none / *open enum* |
| `has_subwoofer` | boolean | |

### Keyboard

| Field | Type |
|---|---|
| `keyboard_offerings` | list of keyboard entries |

**Each keyboard offering:**

| Sub-field | Type | Notes |
|---|---|---|
| `description` | string | Free-form (e.g., "RGB per-key, 1.5mm travel") |
| `has_numpad` | boolean | |
| `tier` | string | base / optional |

### Thermals

(Mostly manual entries — vendors rarely publish.)

| Field | Type | Notes |
|---|---|---|
| `thermal_design` | string | heatpipe / vapor-chamber / hybrid |
| `thermal_material` | string | copper / aluminum / mixed |
| `tim` | string | Free-form (e.g., "Thermal Grizzly on CPU and GPU") |
| `fan_count` | number | |

### Dimensions

| Field | Type | Notes |
|---|---|---|
| `width_mm` | number | Left-right, longest dimension |
| `depth_mm` | number | Front-to-back |
| `height_mm_min` | number, nullable | |
| `height_mm_max` | number | Always populated. |

**Single-value rule for height:** if a vendor publishes only one number, store it in `height_mm_max`, leave min null.

### Weight

| Field | Type | Notes |
|---|---|---|
| `weight_kg_min` | number | "Starting at" config. |
| `weight_kg_max` | number, nullable | |

**Single-value rule for weight (opposite of height):** if a vendor publishes only one number ("starting at X kg"), store in `weight_kg_min`, leave max null.

### Design

| Field | Type | Notes |
|---|---|---|
| `a_cover_material` | string | aluminum / magnesium / plastic / carbon-fiber / mixed / *open enum* |
| `c_cover_material` | string | (same enum) |
| `d_cover_material` | string | (same enum) |
| `thermal_shelf` | boolean | |
| `lighting` | string | Free-form (e.g., "RGB logo, rear light bar") |

---

## Provenance and Status

Every cell carries an attached provenance record + status flag. List-of-offerings fields carry **per-leaf-cell** status — each sub-field of each offering can be statused independently.

### Scraped cell metadata

| Field | Type |
|---|---|
| `source_url` | string |
| `captured_at` | timestamp |
| `scraper_id` | string |
| `status` | `verified` / `needs-review` / `vendor-doesn't-publish` |

### Manual cell metadata

| Field | Type |
|---|---|
| `entered_by` | string |
| `entered_at` | timestamp |
| `source_note` | string (free-form) |
| `status` | `vouched` / `needs-review` |

---

## Field-shape patterns (cross-reference)

| Pattern | Used by |
|---|---|
| **List of offerings** | CPU offerings, boards (GPU + power), display, battery, keyboard, camera, adapter |
| **Tier flag** (`base` / `optional`) | Battery, keyboard, adapter, camera, display |
| **Free-form text** (filterability not worth entry overhead) | TIM, keyboard description, lighting |
| **Structured / categorical** (filterable) | Camera, audio, display, I/O port versions, cover materials |
| **Single value per product** | Memory, storage (`storage_max_gb`), network, dimensions, weight, audio, thermals, design |
| **Catalogs** (chip-level data) | CPU, GPU only |

---

## Naming and enum policy

- All field names: **snake_case**.
- Categorical fields start as **open enums** — values listed are the seed set, not exhaustive. As data accumulates, enums tighten to closed sets.

---

## Out of scope (explicit)

- **OS variants** (Windows 11 Home / Pro).
- **Release date.**
- **Color / finish options.**
- **Pricing.**
- **Per-SKU configurations** (e.g., specific CPU + GPU + RAM combinations).
- **Display panel models** as catalog rows (panels treated as spec bundles).
- **Audit / history log** of changing values — deferred; design preserves the option to add it later.

---

## Trade-offs explicitly accepted

- **No per-CPU TDP variance tracked.** Single `cpu_tdp_max` per product. Loses "what TDP does the U9 run at vs. the U7."
- **One `tgp_max` per board** collapses per-GPU TGP variance within a board. Vendors sometimes publish per-GPU TGP within a single board (e.g., MB1 with 5090 at 175W, 5080 at 150W, 5070 Ti at 140W); these distinctions are lost.
- **Display panels not catalog'd.** Vendors rarely publish panel models, so panels are stored as spec bundles per product.
- **`adapter_connector` is product-level.** If a product offers adapters with different connector types (barrel + USB-C PD), the difference is lost.

These were deliberate simplifications. Revisit if any of them bite during real use.
