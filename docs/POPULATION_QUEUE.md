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

`model_code` is the unique key per (model, year). It's user-chosen — usually the URL slug or a vendor-published identifier. Match the convention already used for that vendor when possible.

---

## Existing in DB (7 products, refreshed)

Already scraped and live in `competitive.db`. Re-refresh anytime via `refresh --from-db --brand <slug> --model <model_code>`.

### Dell — Alienware 18 Area-51
- brand: dell
- model_code: aa18250
- year: 2026
- [x] https://www.dell.com/en-us/shop/dell-laptops/alienware-18-area-51-gaming-laptop/spd/alienware-area-51-aa18250-gaming-laptop

### Dell — Alienware 16X Aurora
- brand: dell
- model_code: ac16251
- year: 2026
- [x] https://www.dell.com/en-us/shop/dell-laptops/alienware-16x-aurora-gaming-laptop/spd/alienware-aurora-ac16251-gaming-laptop

### HP — HyperX OMEN MAX 16
- brand: hp
- model_code: 16t-ah100
- year: 2026
- [x] https://www.hp.com/us-en/shop/pdp/hyperx-omen-max-gaming-laptop-16t-ah100-16-cn3g9av-1

### Lenovo — Legion Pro 7 16AFR10H (Session 22 family-code merge artifact: shares vendor_full_name with `legion-pro-7-16-gen-10` below; same PSREF URL)
- brand: lenovo
- model_code: 16AFR10H
- year: 2026
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec

### Lenovo — Legion Pro 7 Gen 10
- brand: lenovo
- model_code: legion-pro-7-16-gen-10
- year: 2026
- [x] https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec

### ASUS — ROG Strix G16 (2026)
- brand: asus
- model_code: rog-strix-g16-2026
- year: 2026
- [x] https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2026/spec/

### ASUS — ROG Zephyrus G16 (2026)
- brand: asus
- model_code: rog-zephyrus-g16-2026
- year: 2026
- [x] https://rog.asus.com/us/laptops/rog-zephyrus/rog-zephyrus-g16-2026/spec/

---

## To populate

Add one heading per new product below. For products with multiple config URLs, list every URL under the same heading. Delete this placeholder block once you've filled it in.

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
