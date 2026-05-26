# Population queue

URL inventory for the competitive-database. One heading per product. Under each heading, every vendor URL we want this product's data to come from (one per config variant — different SKUs, configurator paths, refresh-rate trims, etc.).

## How to find a product URL per vendor

When adding a new product, start at the **vendor's home/entry URL** below, drill down via the steps, and confirm the final URL matches the target shape. These home URLs are the **single point of maintenance**: if a vendor reorganizes their site and the entry stops working, update the `Start at` line here and the navigation steps below adapt. The bridges themselves don't validate URL patterns (they use permissive slug extraction with title fallback), so the "Target URL shape" lines describe good provenance, not parser requirements.

### Dell
- **Start at:** `https://www.dell.com/en-us/shop/dell-laptops/sr/laptops/gaming-laptops`
- **Navigate:** Click an Alienware tile → land on the product detail page. The URL must contain the `/spd/` segment (`/sr/` search-results URLs are not product pages).
- **Target URL shape:** `https://www.dell.com/en-us/shop/dell-laptops/<family-slug>/spd/<model-slug>`
- **Common gotcha:** Trailing `?ref=variantstack` query strings are harmless. The slug after `/spd/` is the model_code the bridge derives.

### HP
- **Start at:** `https://www.hp.com/us-en/shop/slp/hp-gaming/laptops` (OMEN & Victus gaming-laptops landing).
- **Navigate:** Click an OMEN / Victus tile → click "Customize and Buy" or the model card → URL becomes `…/shop/pdp/<long-slug>`.
- **Target URL shape:** `https://www.hp.com/us-en/shop/pdp/<sub-brand>-<series>-<size>-<model-code>`
- **Common gotcha:** HP attaches `-N` revision suffixes to the slug (e.g. `…-cn3g9av-1`); leave them on — the bridge uses the full slug.

### Lenovo
- **Start at:** `https://psref.lenovo.com/` — PSREF is the official spec database the scraper reads. **Not** the lenovo.com shopping site.
- **Navigate:** Use the search box or "Product Line → Legion → Series → Product" dropdowns → click a result → land on `/Product/Legion/<ProductKey>`. Optionally append `?tab=spec` so the specs panel opens.
- **Target URL shape:** `https://psref.lenovo.com/Product/<family>/<ProductKey>?tab=spec`
- **Common gotcha:** `?tab=spec` is cosmetic — the bridge strips it before parsing. Do NOT use lenovo.com shopping URLs; the bridge only handles PSREF.

### ASUS
- **Start at:** Per-family index pages — `https://rog.asus.com/us/laptops/rog-zephyrus-series/`, `…/rog-strix-series/`, `…/rog-flow-series/`. The bare `/us/laptops/` index currently 404s; family-series pages are the durable entry.
- **Navigate:** Click a year-tagged model card (e.g. "ROG Strix G16 (2026)") → click "Tech Specs" → URL ends in `/spec/`.
- **Target URL shape:** `https://rog.asus.com/[us/]laptops/<family>/<model-slug>/spec/`
- **Common gotcha:** Both `rog.asus.com/laptops/…` and `rog.asus.com/us/laptops/…` work — the bridge ignores region prefix. The trailing `/spec/` segment is required by convention but the parser walks back one path component, so the model slug is preserved.

### Acer (Tier 2 — parked, no scraper yet)
- **Start at:** `https://www.acer.com/us-en/predator/new-products` (2026 Predator launch hub) — the bare `/predator/laptops/` returns 404 at the moment.
- **Navigate:** Click a Helios / Helios Neo / Nitro tile → land on `/predator/laptops/<family>/<model-slug>` (e.g. `…/helios/helios-neo-16`).
- **Target URL shape:** `https://www.acer.com/us-en/predator/laptops/<family>/<model-slug>` (observation only — no scraper today).
- **Common gotcha:** URL collected as provenance for manual entry and for future Tier-2 scrape. The Acer store (`store.acer.com`) is a separate domain — prefer `acer.com/us-en/predator/...` for spec provenance.

### MSI (Tier 2 — parked, no scraper yet)
- **Start at:** `https://www.msi.com/news/` for the latest lineup announcement (e.g. CES 2026 launch post). Working alternatives: `https://us-store.msi.com/Raider-GE-Series`, `…/Titan-GT-Series`. The `/Laptops/c/Laptop-Gaming` catalog landing returns 403 to scripted fetchers but resolves in browsers.
- **Navigate:** From the lineup post or store-series page, click a model (Titan 18 HX, Raider 16 Max HX, Stealth 16 AI+) → land on the product page.
- **Target URL shape:** `https://www.msi.com/Laptop/<model-slug>/Specification` (observation only — no scraper today).
- **Common gotcha:** URL collected as provenance for manual entry and for future Tier-2 scrape. MSI splits content between `msi.com` (global product pages) and `us-store.msi.com` (US shop) — prefer the `msi.com/Laptop/...` spec page for provenance, not the store URL.

---

## How this gets consumed

Each session, Claude reads this file and runs `python -m competitive_database refresh --brand <slug> --url <URL>` for every unchecked `- [ ]` bullet, in order. Tick the bullet `- [x]` when the refresh has run successfully.

Offering lists (CPU, GPU, display, storage, battery, keyboard, adapter, camera) **union** across multiple URLs for the same product — different configs surface as new offering rows. Exactly what we want for "show every option available across configs."

Scalar fields (dimensions, weight, identity, etc.) that **disagree** between two URLs for the same product drop into the review queue — Claude runs `resolve` after the batch to triage them.

## Format

```
## <Brand display> — <Product display>
- brand: <slug>          # dell | hp | lenovo | asus | acer | msi
- model_code: <slug>     # vendor's URL slug or PSREF key; lowercase-kebab is fine
- year: <YYYY>
- [ ] <URL>              # <!-- optional inline note about which config -->
- [ ] <URL>              # <!-- another config -->
```

**Vendor slug must be one of `dell`, `hp`, `lenovo`, `asus`, `acer`, `msi`** — these are the recognized `--brand` values. Acer and MSI have no scraper yet (Tier 2, waiting on `scrapers-lib` upstream); their URLs sit here as parking-lot provenance for manual entry until the scraper lands.

`model_code` is the unique key per (model, year). It's user-chosen — usually the URL slug or a vendor-published identifier. Match the convention already used for that vendor when possible. Under the Stage 11 PK swap (Session 48), `(product, year)` is the actual unique key on the `products` table; `model_code` is now the operational vendor slug used during ingestion. The format spec above still works as-is — the `_normalize_products_pk` compat shim in `db/helpers.py` translates legacy `model_code` callsite keys to the new PK.

---

## Existing in DB (1 entry — fully refreshed; no pending URL adds)

Already scraped and live in `competitive.db`. Re-refresh anytime via `refresh --from-db --brand <slug> --model <model_code>`. Products with pending URL adds (extra configs to ingest) live in §To populate instead, with their already-refreshed URL pre-checked.

### Lenovo — Legion Pro 7 16AFR10H (Session 22 family-code merge artifact: shares vendor_full_name with `legion-pro-7-16-gen-10` below; same PSREF URL)
- brand: lenovo
- model_code: 16AFR10H
- year: 2026
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec

---

## To populate

Add one heading per new product below. For products with multiple config URLs, list every URL under the same heading.

### Dell — Alienware 16 Aurora
- brand: dell
- model_code: ac16250
- year: 2026
- [x] https://www.dell.com/en-us/shop/dell-laptops/alienware-16-aurora-gaming-laptop/spd/alienware-aurora-ac16250-gaming-laptop  <!-- bundle-less canonical (bundle-tagged /cty/pdp/ form unsupported by Dell fetcher) -->

### Dell — Alienware 16X Aurora
- brand: dell
- model_code: ac16251
- year: 2026
- [x] https://www.dell.com/en-us/shop/dell-laptops/alienware-16x-aurora-gaming-laptop/spd/alienware-aurora-ac16251-gaming-laptop  <!-- bundle-less canonical (S38 bundle-tagged pick reverted: Dell fetcher requires shop-landing form) -->

### Dell — Alienware 18 Area-51
- brand: dell
- model_code: aa18250
- year: 2026
- [x] https://www.dell.com/en-us/shop/dell-laptops/alienware-18-area-51-gaming-laptop/spd/alienware-area-51-aa18250-gaming-laptop  <!-- bundle-less canonical (S38 bundle-tagged pick reverted: Dell fetcher requires shop-landing form) -->

### Dell — Alienware 16 Area-51
- brand: dell
- model_code: aa16250
- year: 2026
- [x] https://www.dell.com/en-us/shop/dell-laptops/alienware-16-area-51-gaming-laptop/spd/alienware-area-51-aa16250-gaming-laptop

### HP — Victus 15
- brand: hp
- model_code: victus-15
- year: 2026
- [x] https://www.hp.com/us-en/shop/pdp/victus-gaming-laptop-15-fa2047nr                                  <!-- fa generation (older) -->
- [x] https://www.hp.com/us-en/shop/pdp/victus-by-hp-156-inch-gaming-laptop-pc-a8vy4av-1                  <!-- fa generation (A8VY4AV → 15t-fa200) -->
- [x] https://www.hp.com/us-en/shop/pdp/victus-gaming-laptop-15-fb3025nr                                  <!-- fb generation (2026) -->
- [x] https://www.hp.com/us-en/shop/pdp/victus-by-hp-156-inch-gaming-laptop-pc-bd5f1av-1                  <!-- generation unconfirmed -->
- [x] https://www.hp.com/us-en/shop/pdp/victus-by-hp-gaming-laptop-15z-fb300-156-a8ru6av-1                <!-- fb generation (15z-fb300) -->

### HP — Omen 15 (HyperX Omen)
- brand: hp
- model_code: omen-15
- year: 2026
- [x] https://www.hp.com/us-en/shop/pdp/hyperx-omen-gaming-laptop-15t-ga000-15-c52b1av-1                  <!-- ga000 generation -->
- [x] https://www.hp.com/us-en/shop/pdp/hyperx-omen-15-inch-gaming-laptop-pc-gb0xxx-c51tpav-1             <!-- gb0xxx generation -->
- [x] https://www.hp.com/us-en/shop/pdp/hyperx-omen-gaming-laptop-15-gb0xxx-15-cj9d8av-1                  <!-- gb0xxx generation -->
- [x] https://www.hp.com/us-en/shop/pdp/hyperx-omen-15-inch-gaming-laptop-pc-15-gb0261nr                  <!-- gb0 SKU -->

### HP — Omen 16
- brand: hp
- model_code: omen-16
- year: 2026
- [x] https://www.hp.com/us-en/shop/pdp/omen-16-inch-gaming-laptop-pc-a58a5av-1                           <!-- AV-code customizer entry -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-gaming-laptop-16-ap0097nr                                    <!-- ap0 generation -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-gaming-laptop-16-ap0047nr                                    <!-- ap0 generation -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-16-inch-gaming-laptop-pc-a59pfav-1                           <!-- AV-code customizer entry -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-16-inch-gaming-laptop-pc-b8cj1av-1                           <!-- AV-code customizer entry -->

### HP — Omen 17
- brand: hp
- model_code: omen-17
- year: 2026
- [x] https://www.hp.com/us-en/shop/pdp/omen-gaming-laptop-17-db1097nr                                    <!-- db1 generation -->
<!-- omen-173-inch-…-a7jp9av-1 dropped Session 39 — HP delisted (HPProductNotFoundError on fetch) -->

### HP — HyperX OMEN MAX 16
- brand: hp
- model_code: 16t-ah100
- year: 2026
- [x] https://www.hp.com/us-en/shop/pdp/hyperx-omen-max-gaming-laptop-16t-ah100-16-cn3g9av-1              <!-- already in DB (refreshed) -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-max-gaming-laptop-16t-ah000-16-a4nq6av-1                     <!-- 16t-ah000 generation (older customizer) -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-max-gaming-laptop-16-ah0097nr                                <!-- ah0 SKU -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-max-16-inch-gaming-laptop-pc-a4sl1av-1                       <!-- AV-code customizer -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-max-16-inch-gaming-laptop-pc-b86wqav-3074457345621937826--1  <!-- AV-code with embedded catEntryId; may 404 -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-max-gaming-laptop-16-ak0098nr                                <!-- ak0 SKU (newer) -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-max-gaming-laptop-16-ah0057nr                                <!-- ah0 SKU -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-max-gaming-laptop-16-ak0047nr                                <!-- ak0 SKU (newer) -->

### HP — Omen Transcend 14
- brand: hp
- model_code: omen-transcend-14
- year: 2026
- [x] https://www.hp.com/us-en/shop/pdp/omen-transcend-14-inch-gaming-laptop-pc-pdk-a88y7av-1             <!-- AV-code customizer entry -->
- [x] https://www.hp.com/us-en/shop/pdp/omen-transcend-laptop-14-fb1047nr                                 <!-- fb1 SKU -->

### HP — Omen Transcend 16 (merged target for "Omen Slim 16" per user clarification)
- brand: hp
- model_code: omen-transcend-16
- year: 2026
- [x] https://www.hp.com/us-en/shop/pdp/omen-16-inch-gaming-laptop-pc-a59p7av-1                           <!-- jumpid says omen-slim-gaming-lap -->

### Lenovo — LOQ 15 (Gen 11)
- brand: lenovo
- model_code: loq-15-gen-11
- year: 2026
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15AHP11?tab=spec                                         <!-- AMD -->
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15IPH11?tab=spec                                         <!-- Intel -->

### Lenovo — LOQ 15 (Gen 10)
- brand: lenovo
- model_code: loq-15-gen-10
- year: 2025
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15IRX10?tab=spec                                         <!-- Intel -->
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15AHP10?tab=spec                                         <!-- AMD -->

### Lenovo — LOQ 15 (Gen 9)
- brand: lenovo
- model_code: loq-15-gen-9
- year: 2024
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15IAX9I?tab=spec                                         <!-- Intel IAX (suffix I) -->
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15ARP9?tab=spec                                          <!-- AMD ARP -->
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15IRX9?tab=spec                                          <!-- Intel IRX -->
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15IAX9?tab=spec                                          <!-- Intel IAX -->
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15AHP9?tab=spec                                          <!-- AMD AHP -->

### Lenovo — LOQ 17 (Gen 10)
- brand: lenovo
- model_code: loq-17-gen-10
- year: 2025
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_17IRX10?tab=spec                                         <!-- Intel -->

### Lenovo — LOQ Essential 15 (Gen 11)
- brand: lenovo
- model_code: loq-essential-15-gen-11
- year: 2026
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_Essential_15IRX11?tab=spec                               <!-- Intel -->
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_Essential_15ARP11?tab=spec                               <!-- AMD -->

### Lenovo — LOQ Essential 15 (Gen 10)
- brand: lenovo
- model_code: loq-essential-15-gen-10
- year: 2025
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15ARP10E?tab=spec                                        <!-- AMD ARP, E suffix = Essential precursor -->

### Lenovo — LOQ Essential 15 (Gen 9)
- brand: lenovo
- model_code: loq-essential-15-gen-9
- year: 2024
- [x] https://psref.lenovo.com/l/Product/LOQ/LOQ_15IAX9E?tab=spec                                         <!-- Intel IAX, E suffix = Essential precursor -->

### Lenovo — Legion 5 15" (Gen 11)
- brand: lenovo
- model_code: legion-5-15-gen-11
- year: 2026
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_15IPH11?tab=spec                                 <!-- Intel IPH -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_15IAX11?tab=spec                                 <!-- Intel IAX -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_15AHP11?tab=spec                                 <!-- AMD AHP -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_15AGP11?tab=spec                                 <!-- AMD AGP -->

### Lenovo — Legion 5 15" (Gen 10)
- brand: lenovo
- model_code: legion-5-15-gen-10
- year: 2025
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_15IRX10?tab=spec                                 <!-- Intel IRX -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_15IAX10?tab=spec                                 <!-- Intel IAX -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_15AKP10?tab=spec                                 <!-- AMD AKP -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_15AHP10?tab=spec                                 <!-- AMD AHP -->

### Lenovo — Legion 5 15" (Gen 9)
- brand: lenovo
- model_code: legion-5-15-gen-9
- year: 2024
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_15IRX9?tab=spec                                  <!-- Intel IRX -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_15APH9?tab=spec                                  <!-- AMD APH -->

### Lenovo — Legion 5 16" (Gen 10)
- brand: lenovo
- model_code: legion-5-16-gen-10
- year: 2025
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_16IAX10?tab=spec                                 <!-- Intel IAX -->

### Lenovo — Legion 5 16" (Gen 9)
- brand: lenovo
- model_code: legion-5-16-gen-9
- year: 2024
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_5_16IRX9?tab=spec                                  <!-- Intel IRX -->

### Lenovo — Legion Pro 5 16" (Gen 10)
- brand: lenovo
- model_code: legion-pro-5-16-gen-10
- year: 2025
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16IRX10?tab=spec                             <!-- Intel IRX -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16IAX10?tab=spec                             <!-- Intel IAX -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16IAX10H?tab=spec                            <!-- Intel IAX, H suffix (SKU-trim variant) -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16ADR10?tab=spec                             <!-- AMD ADR -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16AFR10?tab=spec                             <!-- AMD AFR -->

### Lenovo — Legion Pro 5 16" (Gen 9)
- brand: lenovo
- model_code: legion-pro-5-16-gen-9
- year: 2024
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16IRX9?tab=spec                              <!-- Intel IRX -->

### Lenovo — Legion Pro 5 16" (Gen 8)
- brand: lenovo
- model_code: legion-pro-5-16-gen-8
- year: 2023
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16ARX8?tab=spec                              <!-- AMD ARX -->

### Lenovo — Legion 7 16" (Gen 11)
- brand: lenovo
- model_code: legion-7-16-gen-11
- year: 2026
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_7_16AGP11?tab=spec                                 <!-- AMD AGP -->

### Lenovo — Legion 7 16" (Gen 10)
- brand: lenovo
- model_code: legion-7-16-gen-10
- year: 2025
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_7_16IAX10?tab=spec                                 <!-- Intel IAX -->

### Lenovo — Legion 7 16" (Gen 9)
- brand: lenovo
- model_code: legion-7-16-gen-9
- year: 2024
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_7_16IRX9?tab=spec                                  <!-- Intel IRX -->

### Lenovo — Legion Pro 7 16" (Gen 10)
- brand: lenovo
- model_code: legion-pro-7-16-gen-10
- year: 2025
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec                            <!-- AMD AFR, already in DB (refreshed) -->
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16IAX10H?tab=spec                            <!-- Intel IAX H -->

### Lenovo — Legion Pro 7 16" (Gen 9)
- brand: lenovo
- model_code: legion-pro-7-16-gen-9
- year: 2024
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16IRX9H?tab=spec                             <!-- Intel IRX H -->

### Lenovo — Legion 9 18" (Gen 10)
- brand: lenovo
- model_code: legion-9-18-gen-10
- year: 2025
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_9_18IAX10?tab=spec                                 <!-- Intel IAX, 18" flagship -->

### Lenovo — Legion 9 16" (Gen 9)
- brand: lenovo
- model_code: legion-9-16-gen-9
- year: 2024
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_9_16IRX9?tab=spec                                  <!-- Intel IRX -->

### ASUS — ROG Zephyrus G14 (2026)
- brand: asus
- model_code: rog-zephyrus-g14-2026-gu405
- year: 2026
- [x] https://rog.asus.com/us/laptops/rog-zephyrus/rog-zephyrus-g14-2026-gu405/spec/

### ASUS — ROG Zephyrus G14 (2025)
- brand: asus
- model_code: rog-zephyrus-g14-2025
- year: 2025
- [x] https://rog.asus.com/us/laptops/rog-zephyrus/rog-zephyrus-g14-2025/spec/

### ASUS — ROG Zephyrus G16 (2026)
- brand: asus
- model_code: rog-zephyrus-g16-2026
- year: 2026
- [x] https://rog.asus.com/us/laptops/rog-zephyrus/rog-zephyrus-g16-2026/spec/                            <!-- already in DB (refreshed) -->

### ASUS — ROG Zephyrus G16 (2025)
- brand: asus
- model_code: rog-zephyrus-g16-2025-gu605
- year: 2025
- [x] https://rog.asus.com/us/laptops/rog-zephyrus/rog-zephyrus-g16-2025-gu605/spec/

### ASUS — ROG Zephyrus Duo 16 (2026)
- brand: asus
- model_code: rog-zephyrus-duo-2026
- year: 2026
- [x] https://rog.asus.com/us/laptops/rog-zephyrus/rog-zephyrus-duo-2026/spec/                            <!-- dual-screen flagship -->

### ASUS — TUF Gaming 14 (2026)
- brand: asus
- model_code: asus-tuf-gaming-14-2026
- year: 2026
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a14-2026-fa401ea/techspec/    <!-- AMD A14 -->

### ASUS — TUF Gaming 14 (2025)
- brand: asus
- model_code: asus-tuf-gaming-14-2025
- year: 2025
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a14-2025/techspec/            <!-- AMD A14 -->

### ASUS — TUF Gaming 15 (2023)
- brand: asus
- model_code: asus-tuf-gaming-15-2023
- year: 2023
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-f15-2023/techspec/            <!-- Intel F15 -->
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a15-2023/techspec/            <!-- AMD A15 -->

### ASUS — TUF Gaming 16 (2026)
- brand: asus
- model_code: asus-tuf-gaming-16-2026
- year: 2026
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-f16-2026/techspec/            <!-- Intel F16 -->

### ASUS — TUF Gaming 16 (2025)
- brand: asus
- model_code: asus-tuf-gaming-16-2025
- year: 2025
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-f16-2025/techspec/            <!-- Intel F16 -->
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a16-2025/techspec/            <!-- AMD A16 -->

### ASUS — TUF Gaming 16 (2024)
- brand: asus
- model_code: asus-tuf-gaming-16-2024
- year: 2024
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-f16-2024/techspec/            <!-- Intel F16 -->
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a16-2024/techspec/            <!-- AMD A16 -->
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a16-2024-fa608/techspec/      <!-- AMD A16 SKU variant (fa608) -->

### ASUS — TUF Gaming 17 (2023)
- brand: asus
- model_code: asus-tuf-gaming-17-2023
- year: 2023
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-f17-2023/techspec/            <!-- Intel F17 -->
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a17-2023/techspec/            <!-- AMD A17 -->

### ASUS — TUF Gaming 18 (2025)
- brand: asus
- model_code: asus-tuf-gaming-18-2025
- year: 2025
- [x] https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a18-2025/techspec/            <!-- AMD A18 (scope add: not on original list) -->

> **NOTE:** ASUS entries below are grouped by (size, year) per user preference, but until ASUS `family_code` support lands (deferred T9.3, see TASKS.md), refresh will create one DB row per URL slug. Multiple-URL ASUS groupings (e.g. TUF 16 2025 = F16+A16 URLs, Strix G16 2025 = g614+non-g614 URLs) will temporarily appear as separate DB rows; they fold into the grouped products once T9.3 ships.

### ASUS — ROG Strix G16 (2026)
- brand: asus
- model_code: rog-strix-g16-2026
- year: 2026
- [x] https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2026/spec/                                     <!-- already in DB (refreshed) -->
- [ ] https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec/                                  <!-- /us/ variant (same model_code, will union) -->

### ASUS — ROG Strix G16 (2025)
- brand: asus
- model_code: rog-strix-g16-2025
- year: 2025
- [x] https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2025-g614/spec/                             <!-- with g614 internal code -->
- [x] https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2025/spec/

### ASUS — ROG Strix G18 (2026)
- brand: asus
- model_code: rog-strix-g18-2026
- year: 2026
- [x] https://rog.asus.com/us/laptops/rog-strix/rog-strix-g18-2026/spec/                                  <!-- /spec/ auto-appended -->

### ASUS — ROG Strix G18 (2025)
- brand: asus
- model_code: rog-strix-g18-2025
- year: 2025
- [x] https://rog.asus.com/us/laptops/rog-strix/rog-strix-g18-2025-g814/spec/                             <!-- g814 internal -->

### ASUS — ROG Strix Scar 16 (2025)
- brand: asus
- model_code: rog-strix-scar-16-2025
- year: 2025
- [x] https://rog.asus.com/us/laptops/rog-strix/rog-strix-scar-16-2025/spec/

### ASUS — ROG Strix Scar 18 (2026)
- brand: asus
- model_code: rog-strix-scar-18-2026
- year: 2026
- [x] https://rog.asus.com/us/laptops/rog-strix/rog-strix-scar-18-2026/spec/

### ASUS — ROG Strix Scar 18 (2025)
- brand: asus
- model_code: rog-strix-scar-18-2025
- year: 2025
- [x] https://rog.asus.com/us/laptops/rog-strix/rog-strix-scar-18-2025/spec/

### ASUS — V16 (V3607)
- brand: asus
- model_code: asus-v16-v3607
- year: 2026
- [x] https://www.asus.com/us/laptops/for-gaming/all-series/asus-v16-v3607/techspec/                      <!-- mainstream gaming line, www.asus.com -->

### ASUS — ROG Flow Z13 (2025)
- brand: asus
- model_code: rog-flow-z13-2025
- year: 2025
- [x] https://rog.asus.com/us/laptops/rog-flow/rog-flow-z13-2025/spec/                                    <!-- Z13 only; X13 not on lineup -->

> **NOTE (Acer year decoder):** Acer is Tier 2 (no scraper yet — deferred per `scrapers-lib` upstream). URLs below are parking-lot provenance; no refresh fires today. `#pdpSpecs` fragments jump the browser to the spec panel. Grouped by family variant from URL slug, not year.
>
> **Year cannot be inferred from URL path or NH.xxxxxAA.xxx part number** — those are SKU/config identifiers, not year identifiers. To decode launch year with high confidence, open each PDP and read the **Model line** at the top of the page, format `AN[V]<size>[S]-XX-<sku-suffix>` (e.g. `ANV16-72-73VJ`, `AN16-41-R7FA`). The middle two-digit code XX maps deterministically to an Acer press-release announcement.
>
> **Nitro 16 year map** (anchored to news.acer.com press releases dated Dec 7 2023, April 10 2024, April 15 2025, Sept 3 2025):
> - Non-slim lines (`AN16-…`, `ANV16-…`): XX = 41 / 51 / 71 → **2024**; XX = 61 / 72 / 42 → **2025**; XX = A71 / I51 → **2026**
> - Slim "S" lines (`AN16S-…`, `ANV16S-…`): always **2025** regardless of XX
> - Nitro Lite (`NL16-71G-…`): **2025** product line (ships with older Intel 13th-gen + RTX 30-series — don't infer year from components, Acer ships fresh model years with last-gen silicon in budget configs)
>
> The `NH.U…AA` vs `NH.Q…AA` prefix correlates ~60-70% with 2025 vs 2024 but has exceptions (e.g. `NH.QZLAA` is a 2025 `ANV16-72`) — **not reliable on its own**.
>
> **Nitro 15 / 17, Helios, Helios Neo, Triton**: same general Model-code structure but the XX→year mapping isn't published yet for those lines. Treat as **"year unverified"** until a fetch-and-decode pass runs (sample PDPs cross-referenced with press releases).
>
> **Current state:** year placeholders below (2025 / 2023 / 2024) are from an earlier slug-heuristic and are NOT verified per the decoder. A future decoder sweep will WebFetch each PDP, extract the Model code, apply the rules, and either (α) keep merged family-variant products with a representative year, or (β) re-split products by decoded year. Decision deferred to post-collection.

### Acer — Nitro V 15
- brand: acer
- model_code: acer-nitro-v-15
- year: 2025
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U0NAA.008#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U1NAA.004#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U1NAA.003#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.QZ9AA.005#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U1PAA.002#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U1PAA.003#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U1NAA.002#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U1PAA.005#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U0NAA.006#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U1PAA.006#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U1PAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.QZ9AA.004#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.U1NAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-15/pdp/NH.QN8AA.00D#pdpSpecs

### Acer — Nitro V 16
- brand: acer
- model_code: acer-nitro-v-16
- year: 2025
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.U59AA.002#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.QZLAA.006#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.U2EAA.002#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.U2FAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.U2EAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.QZLAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.U2EAA.004#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.U2EAA.003#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.U2FAA.002#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.QZLAA.004#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.QZLAA.003#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.U2FAA.003#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16/pdp/NH.QTMAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16-ai-amd/pdp/NH.U25AA.003#pdpSpecs                <!-- merged: V 16 AI AMD = V 16 -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16-ai-amd/pdp/NH.QUEAA.001#pdpSpecs                <!-- merged: V 16 AI AMD = V 16 -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16-ai-amd/pdp/NH.U25AA.002#pdpSpecs                <!-- merged: V 16 AI AMD = V 16 -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16-ai-amd/pdp/NH.U2NAA.001#pdpSpecs                <!-- merged: V 16 AI AMD = V 16 -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-16-amd/pdp/NH.QKDAA.001#pdpSpecs                     <!-- pre-V slug, merged into V 16 -->

### Acer — Nitro V 16s
- brand: acer
- model_code: acer-nitro-v-16s
- year: 2025
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/pdp/NH.U0ZAA.002#pdpSpecs               <!-- AI AMD variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/pdp/NH.U34AA.002#pdpSpecs               <!-- AI AMD variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/pdp/NH.U08AA.001#pdpSpecs               <!-- AI AMD variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/pdp/NH.U0EAA.002#pdpSpecs               <!-- AI AMD variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/pdp/NH.U18AA.002#pdpSpecs               <!-- AI AMD variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/pdp/NH.U19AA.001#pdpSpecs               <!-- AI AMD variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/pdp/NH.U10AA.001#pdpSpecs               <!-- AI AMD variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/pdp/NH.U10AA.003#pdpSpecs               <!-- AI AMD variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/pdp/NH.QZYAA.001#pdpSpecs               <!-- AI AMD variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-intel/pdp/NH.U24AA.005#pdpSpecs                <!-- Intel variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-intel/pdp/NH.U23AA.001#pdpSpecs                <!-- Intel variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-intel/pdp/NH.U24AA.003#pdpSpecs                <!-- Intel variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-intel/pdp/NH.U23AA.002#pdpSpecs                <!-- Intel variant -->
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-16s-ai-amd/pdp/NH.U18AA.001#pdpSpecs                 <!-- pre-V slug (no V), merged into V 16s -->

### Acer — Nitro V 17 AI AMD
- brand: acer
- model_code: acer-nitro-v-17-ai-amd
- year: 2025
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-17-ai-amd/pdp/NH.U1VAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-17-ai-amd/pdp/NH.U1VAA.002#pdpSpecs
- [ ] https://www.acer.com/us-en/laptops/nitro/nitro-v-17-ai-amd/pdp/NH.U2YAA.001#pdpSpecs

### Acer — Predator Helios Neo 16
- brand: acer
- model_code: acer-helios-neo-16
- year: 2025
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-16-ai/pdp/NH.U1QAA.001#pdpSpecs       <!-- AI variant -->
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-16-ai/pdp/NH.U0UAA.003#pdpSpecs       <!-- AI variant -->
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-16-ai/pdp/NH.U0UAA.004#pdpSpecs       <!-- AI variant -->
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-16-ai/pdp/NH.QZ6AA.002#pdpSpecs       <!-- AI variant -->
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-16-ai/pdp/NH.QX2AA.001#pdpSpecs       <!-- AI variant -->
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-16-ai/pdp/NH.U0QAA.001#pdpSpecs       <!-- AI variant -->
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-16-ai/pdp/NH.U1QAA.002#pdpSpecs       <!-- AI variant -->
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-16/pdp/NH.QLUAA.001#pdpSpecs          <!-- pre-AI slug, merged -->

### Acer — Predator Helios Neo 16s
- brand: acer
- model_code: acer-helios-neo-16s
- year: 2025
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-16s-ai/pdp/NH.U0KAA.001#pdpSpecs      <!-- slim variant; original list "Helios Neo 16S AI" -->
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-16s-ai/pdp/NH.QZQAA.001#pdpSpecs      <!-- slim variant; original list "Helios Neo 16S AI" -->

### Acer — Predator Helios 18
- brand: acer
- model_code: acer-helios-18
- year: 2025
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-18-ai/pdp/NH.U0AAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-18-ai/pdp/NH.U1DAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-18-ai/pdp/NH.U09AA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-18-ai/pdp/NH.QVWAA.002#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-18-ai/pdp/NH.U1RAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-18-ai/pdp/NH.U0FAA.001#pdpSpecs

### Acer — Predator Helios Neo 18
- brand: acer
- model_code: acer-helios-neo-18
- year: 2025
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-18-ai/pdp/NH.QVLAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-18-ai/pdp/NH.U0HAA.003#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-18-ai/pdp/NH.U0HAA.002#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-18-ai/pdp/NH.U0HAA.001#pdpSpecs

### Acer — Predator Helios Neo 14
- brand: acer
- model_code: acer-helios-neo-14
- year: 2025
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-14-ai/pdp/NH.U2TAA.001#pdpSpecs       <!-- scope add: not on original list -->
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-14-ai/pdp/NH.U1BAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-14-ai/pdp/NH.U2UAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/helios/helios-neo-14-ai/pdp/NH.U1AAA.001#pdpSpecs

### Acer — Predator Triton 14
- brand: acer
- model_code: acer-triton-14
- year: 2025
- [ ] https://www.acer.com/us-en/predator/laptops/triton/triton-14-ai/pdp/NH.U0GAA.001#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/triton/triton-14-ai/pdp/NH.U0GAA.002#pdpSpecs
- [ ] https://www.acer.com/us-en/predator/laptops/triton/triton-14-ai/pdp/NH.U0GAA.004#pdpSpecs


<!--
### Dell — <Product display>
- brand: dell
- model_code: <slug>
- year: 2026
- [ ] https://www.dell.com/...

### Lenovo — <Product display>
- brand: lenovo
- model_code: <slug>
- year: 2026
- [ ] https://psref.lenovo.com/l/Product/Legion/...?tab=spec
- [ ] https://psref.lenovo.com/l/Product/Legion/...?tab=spec  <!-- second config -->

### ASUS — <Product display>
- brand: asus
- model_code: <slug>
- year: 2026
- [ ] https://rog.asus.com/.../spec/

### HP — <Product display>
- brand: hp
- model_code: <slug>
- year: 2026
- [ ] https://www.hp.com/us-en/shop/pdp/...

### Acer — <Product display> (Tier 2 — parked; no scraper, manual entry only)
- brand: acer
- model_code: <slug>
- year: 2026
- [ ] https://www.acer.com/...

### MSI — <Product display> (Tier 2 — parked; no scraper, manual entry only)
- brand: msi
- model_code: <slug>
- year: 2026
- [ ] https://www.msi.com/...
-->
