# Stage 11 — Per-row Audit (77 source rows → 56 product rows)

**Generated:** 2026-05-21 (Session 48, re-derived by 4 parallel subagents applying the locked Stage 11 hierarchy rules to the current DB state)

**Status:** Locked. Both judgment calls resolved in Session 48 (see "Resolved judgment calls" at the bottom).

**Phase 3 SHIPPED 2026-05-26 (Session 49):** Browse picker reshape — 3-rung Brand → Series → Product + Year/Status toggle blocks + union spec view; Policy B `·`-join union format and NULL-status-as-Active rule locked; tests 479 → 505 green.

**Phase 4 SHIPPED 2026-05-26 (Session 49):** Union spec table render primitive — `union_spec_table_html` + `_union_rollup_for_section` + `union_identity_strip_html` in `ui/_components.py`; N=1 byte-identical to legacy `spec_table_html`; landed alongside Browse Phase 3.

**Phase 5 SHIPPED 2026-05-26 (Session 50):** Compare adopts per-column picker + multi-column union grid — `ui/compare.py` rewritten on Phase 3/4 components; new `comparison_union_grid_html` helper reuses `_union_rollup_for_section` per (section, column) cell; render threshold ≥1 populated column; tests 505 → 508 green.

**Phase 6 SHIPPED 2026-05-26 (Session 51):** Echo-parent display rule — when a product's `sub_brand` is NULL, the nearest non-null ancestor (brand) renders in italic-faint in its slot; when `series` is NULL, the nearest non-null ancestor (sub_brand if populated, else brand) renders the same way. Pure rendering layer — no schema, no data, no CLI changes. New helper `_echo_parent_for_leaf(key, product) -> tuple[str | None, bool]` in `competitive_database/ui/_components.py` returns `(own_value, False)` / `(echoed_parent, True)` / `(None, False)` based on the leaf + parent chain. New CSS class `cd-identity__value--echo` (Browse + Compare identity strips) and `cd-findcard__crumb--echo` (Find result cards) both consume the existing `--cd-text-faint` token. **Mixed-case stays plain (locked):** in a union strip, if some rows have a real `sub_brand` and others are NULL, the cell renders the real value plain — echo only fills total-absence, never appears alongside a real value at the same rung. **Find card always emits 3 crumbs (locked):** brand + sub_brand-or-echo + series-or-echo + year; previously omitted null crumbs. Surfaces affected: Browse identity strip, Compare union grid, Find result card. Tests 508 → 521 green (+13).

**Phase 7 SHIPPED 2026-05-26 (Session 52):** Find narrow-by reshape — `ui/find.py::_render_narrow_by` rewritten end-to-end against the Phase 3 components. Legacy 3-selectbox shape (Company / Series / Year with `_ANY = "(any)"` sentinel) replaced by `brand_series_product_picker(conn, key_prefix="find", strict=True)` + `year_toggle_block` (scoped to products consistent with the upstream Section/Feature/Match/Value query) + `status_toggle_block` (default empty — no filter, unlike Browse/Compare's Active default). **Partial picks narrow (locked):** Brand-only is a valid narrow — strict cascade is intentionally rejected here because Find's goal is "narrow the result set," not "resolve to one product." Legacy session keys (`find.narrow.company` / `.series` / `.year`) and the `_ANY` sentinel removed. New CSS class `cd-find__narrow-label` for visual continuity. Pure UI layer — no schema, no data, no CLI changes. Tests 521 → 525 green (+4 new, 2 fixed for the new shape).

**Phase 8 SHIPPED 2026-05-26 (Session 52):** Tests slice + docs alignment shipped (this entry + SESSION_LOG + TASKS + README + ARCHITECTURE) **plus the status curation pass** — all 56 products now carry a manual `status` provenance bundle (0/56 → 56/56). Applied via one-shot `scripts/curate_status_session52.py` (idempotent; uses canonical `make_manual_bundle` + `write_scalar` helpers; each bundle carries `status="vouched"`, `entered_by="session52-curation"`, `source_note` quoting the rule). DB backup taken at `competitive.db.stage11-backup-pre-session52-curation` before writes.

**Curation rule applied:**

| year | status | rows |
|---|---|---|
| 2025 | Active | 24 |
| 2026 | Active | 20 |
| 2023 | Discontinued | 3 |
| 2024 | Discontinued | 9 |

Total 44 Active + 12 Discontinued = 56. Rule is intentionally rough — user locked the year-based pass in plain language ("anything 2025 or 2026 → Active. for all, not just ASUS. we will correct if needed later") with 2023/2024 → Discontinued via follow-up. Follow-up: spot-check the 12 Discontinued rows for products still on sale and flip them to Active as needed; same in reverse for any 2025/2026 row that turns out to be discontinued.

This file is the source of truth for the Phase 2 data-recurate step. The migration script reads it row-by-row.

---

## ASUS — 28 source rows → 22 product rows (5 merges, 0 year corrections)

| product | year | sub_brand | series | source_model_codes |
|---|---|---|---|---|
| V16 | 2026 | (NULL) | V | ["asus-v16-v3607"] |
| Flow Z13 | 2025 | ROG | Flow | ["rog-flow-z13-2025"] |
| Strix G16 | 2025 | ROG | Strix | ["rog-strix-g16-2025", "rog-strix-g16-2025-g614"] |
| Strix G16 | 2026 | ROG | Strix | ["rog-strix-g16-2026"] |
| Strix G18 | 2025 | ROG | Strix | ["rog-strix-g18-2025-g814"] |
| Strix G18 | 2026 | ROG | Strix | ["rog-strix-g18-2026"] |
| Strix Scar 16 | 2025 | ROG | Strix | ["rog-strix-scar-16-2025"] |
| Strix Scar 18 | 2025 | ROG | Strix | ["rog-strix-scar-18-2025"] |
| Strix Scar 18 | 2026 | ROG | Strix | ["rog-strix-scar-18-2026"] |
| Zephyrus Duo | 2026 | ROG | Zephyrus | ["rog-zephyrus-duo-2026"] |
| Zephyrus G14 | 2025 | ROG | Zephyrus | ["rog-zephyrus-g14-2025"] |
| Zephyrus G14 | 2026 | ROG | Zephyrus | ["rog-zephyrus-g14-2026-gu405"] |
| Zephyrus G16 | 2025 | ROG | Zephyrus | ["rog-zephyrus-g16-2025-gu605"] |
| Zephyrus G16 | 2026 | ROG | Zephyrus | ["rog-zephyrus-g16-2026"] |
| TUF 14 | 2025 | (NULL) | TUF | ["asus-tuf-gaming-a14-2025"] |
| TUF 14 | 2026 | (NULL) | TUF | ["asus-tuf-gaming-a14-2026-fa401ea"] |
| TUF 15 | 2023 | (NULL) | TUF | ["asus-tuf-gaming-f15-2023", "asus-tuf-gaming-a15-2023"] |
| TUF 16 | 2024 | (NULL) | TUF | ["asus-tuf-gaming-f16-2024", "asus-tuf-gaming-a16-2024", "asus-tuf-gaming-a16-2024-fa608"] |
| TUF 16 | 2025 | (NULL) | TUF | ["asus-tuf-gaming-f16-2025", "asus-tuf-gaming-a16-2025"] |
| TUF 16 | 2026 | (NULL) | TUF | ["asus-tuf-gaming-f16-2026"] |
| TUF 17 | 2023 | (NULL) | TUF | ["asus-tuf-gaming-f17-2023", "asus-tuf-gaming-a17-2023"] |
| TUF 18 | 2025 | (NULL) | TUF | ["asus-tuf-gaming-a18-2025"] |

### Notes — ASUS

- 5 merges, 6 row reductions: TUF-16-2024 triple (3→1, saves 2) + TUF-15-2023 pair + TUF-16-2025 pair + TUF-17-2023 pair + Strix-G16-2025 pair (4×2→1, saves 4) = 6 total reductions. 28 − 6 = 22. ✓
- TUF sub_brand reclassifies from "TUF Gaming" → NULL (TUF lives at brand level per Stage 11 lock).
- TUF series reclassifies from "TUF A14"/"TUF A15"/"TUF A16"/"TUF A17"/"TUF A18"/"TUF" → "TUF" (uniform).
- ROG series reclassifies from "Strix G16"/"Strix G18"/"Strix Scar 16"/"Strix Scar 18" → "Strix" (uniform; size + Scar modifier ride on Product per Stage 11 lock).
- ROG series for Zephyrus rows reclassifies from "Zephyrus G14"/"Zephyrus G16"/"Zephyrus Duo" → "Zephyrus" (uniform; size + Duo modifier ride on Product).
- Product names drop the "ROG" prefix and parenthetical "(YYYY)" suffix from vendor_full_name.
- **Judgment call A flagged**: 2023 F+A pairs (TUF 15 and TUF 17) merge per the Session 47 "TUF F+A collapse per (Product, Year)" rule. If you remember intending to keep 2023 split, see the question below.

---

## Dell — 5 source rows → 5 product rows (incl. 1 net-new `da15260`)

| product | year | sub_brand | series | source_model_codes |
|---|---|---|---|---|
| Alienware 15 | 2026 | Alienware | (NULL) | ["da15260"] |
| Area-51 16 | 2026 | Alienware | Area-51 | ["aa16250"] |
| Area-51 18 | 2026 | Alienware | Area-51 | ["aa18250"] |
| Aurora 16 | 2026 | Alienware | Aurora | ["ac16250"] |
| Aurora 16X | 2026 | Alienware | Aurora | ["ac16251"] |

### Notes — Dell

- `da15260` is net-new — does not exist in DB yet. The migration must INSERT it (vendor=Dell, sub_brand=Alienware, series=NULL, product="Alienware 15", year=2026) with minimal fields; spec backfill deferred to future curation.
- `da15260` canonical source_url drops the trailing `/useda15260wcto01#customization-anchor` CTO suffix — store the SPD slug only.
- "Alienware 15" anchors on sub-brand directly (series=NULL) because plain Alienware-numbered models have no named series line — per locked Stage 11 rule.
- 0 year corrections, 0 (Product, Year) merges on existing rows.

---

## HP — 23 source rows → 9 product rows (14 merges, 18 year corrections)

| product | year | sub_brand | series | source_model_codes |
|---|---|---|---|---|
| OMEN 16 | 2025 | OMEN | (NULL) | ["16-ap0047nr", "16-ap0097nr", "16t-am000", "16z-ap000"] |
| OMEN 17 | 2025 | OMEN | (NULL) | ["17-db1097nr"] |
| OMEN Max 16 | 2025 | OMEN | (NULL) | ["16-ah0057nr", "16-ah0097nr", "16-ak0047nr", "16-ak0098nr", "16t-ah000", "16z-ak000"] |
| OMEN Slim 16 | 2025 | OMEN | (NULL) | ["16t-an000"] |
| OMEN Transcend 14 | 2025 | OMEN | (NULL) | ["14-fb1047nr", "14t-fb100"] |
| OMEN 15 | 2026 | HyperX | OMEN | ["15-gb0261nr", "15t-ga000", "hyperx-omen-15-inch-gaming-laptop-pc-gb0xxx-c51tpav-1", "hyperx-omen-gaming-laptop-15-gb0xxx-15-cj9d8av-1"] |
| OMEN Max 16 | 2026 | HyperX | OMEN | ["16t-ah100"] |
| Victus 15 | 2024 | (NULL) | Victus | ["15-fa2047nr", "15-fb3025nr"] |
| Victus 15 | 2025 | (NULL) | Victus | ["15t-fa200", "15z-fb300"] |

### Notes — HP

- **18 year corrections** (all 2026 → 2025 except the two Victus retail SKUs which go 2026 → 2024):
  - 2026 → 2025: `16-ap0047nr`, `16-ap0097nr`, `16t-am000`, `16z-ap000`, `17-db1097nr`, `16-ah0057nr`, `16-ah0097nr`, `16-ak0047nr`, `16-ak0098nr`, `16t-ah000`, `16z-ak000`, `16t-an000`, `14-fb1047nr`, `14t-fb100`, `15t-fa200`, `15z-fb300`
  - 2026 → 2024: `15-fa2047nr`, `15-fb3025nr`
- 5 rows stay at year=2026 per Session 47 lock: `15-gb0261nr`, `15t-ga000`, `hyperx-omen-15-inch-gaming-laptop-pc-gb0xxx-c51tpav-1`, `hyperx-omen-gaming-laptop-15-gb0xxx-15-cj9d8av-1`, `16t-ah100` (all HyperX-branded CES 2026 launches).
- **14 merges**: 3 (HyperX OMEN 15) + 3 (legacy OMEN 16) + 5 (legacy OMEN Max 16) + 1 (OMEN Transcend 14) + 1 (Victus 15 2024) + 1 (Victus 15 2025) = 14 ✓
- HyperX classification by vendor_full_name containing "HyperX" — yields exactly 5 rows = the 5 that stay at 2026.
- Victus sub_brand reclassifies from "Victus" → NULL (Victus lives at brand level per Stage 11 lock); Victus moves to series.
- OMEN sub_brand stays at "OMEN" (legacy classification) for the 12 non-HyperX OMEN rows.
- **Judgment call B flagged**: `15t-fa200` (Intel CTO) and `15z-fb300` (AMD CTO) Victus shells could plausibly belong to either the 2024 platform (RTX 4050 + 13th-gen / Ryzen 7445HS, merging with the retail pair) or 2025 (separate row). Audit defaulted to 2025-separate per the Session 47 9-row target. If they should merge to 2024, the row count drops to 8 (and HP merges become 15).

---

## Lenovo — 21 source rows → 20 product rows (1 merge, 1 year correction)

| product | year | sub_brand | series | source_model_codes |
|---|---|---|---|---|
| LOQ 15 | 2024 | (NULL) | LOQ | ["loq-15-gen-9"] |
| LOQ 15 | 2025 | (NULL) | LOQ | ["loq-15-gen-10"] |
| LOQ 15 | 2026 | (NULL) | LOQ | ["loq-15-gen-11"] |
| LOQ 17 | 2025 | (NULL) | LOQ | ["loq-17-gen-10"] |
| LOQ Essential 15 | 2026 | (NULL) | LOQ | ["loq-essential-15-gen-11"] |
| Legion 5 15 | 2024 | Legion | Legion 5 | ["legion-5-15-gen-9"] |
| Legion 5 15 | 2025 | Legion | Legion 5 | ["legion-5-15-gen-10"] |
| Legion 5 15 | 2026 | Legion | Legion 5 | ["legion-5-15-gen-11"] |
| Legion 5 16 | 2024 | Legion | Legion 5 | ["legion-5-16-gen-9"] |
| Legion 5 16 | 2025 | Legion | Legion 5 | ["legion-5-16-gen-10"] |
| Legion Pro 5 16 | 2023 | Legion | Legion 5 | ["legion-pro-5-16-gen-8"] |
| Legion Pro 5 16 | 2024 | Legion | Legion 5 | ["legion-pro-5-16-gen-9"] |
| Legion Pro 5 16 | 2025 | Legion | Legion 5 | ["legion-pro-5-16-gen-10"] |
| Legion 7 16 | 2024 | Legion | Legion 7 | ["legion-7-16-gen-9"] |
| Legion 7 16 | 2025 | Legion | Legion 7 | ["legion-7-16-gen-10"] |
| Legion 7 16 | 2026 | Legion | Legion 7 | ["legion-7-16-gen-11"] |
| Legion Pro 7 16 | 2024 | Legion | Legion 7 | ["legion-pro-7-16-gen-9"] |
| Legion Pro 7 16 | 2025 | Legion | Legion 7 | ["legion-pro-7-16-gen-10", "16AFR10H"] |
| Legion 9 16 | 2024 | Legion | Legion 9 | ["legion-9-16-gen-9"] |
| Legion 9 18 | 2025 | Legion | Legion 9 | ["legion-9-18-gen-10"] |

### Notes — Lenovo

- **1 year correction**: orphan `16AFR10H` corrected from 2026 → 2025.
- **1 new merge**: orphan `16AFR10H` merges into existing `legion-pro-7-16-gen-10` (Legion Pro 7 16, 2025).
- Series reclassifies from `Legion Pro 5`/`Legion Pro 7` → `Legion 5`/`Legion 7` (Pro modifier moves to Product per Stage 11 lock — "Pro" never repeats in Product).
- LOQ sub_brand reclassifies from "LOQ" → NULL; LOQ moves to series.
- All existing Lenovo rows already had correct (Product, Year) shape from Stage 7 work — Stage 11 changes are pure relabeling + the 1 orphan merge.
- `source_model_codes` values listed above are migration-layer parent identifiers (current row `model_code` keys). The inner per-vendor codes (e.g. `["16IRX10", "16AHP10"]`) stay intact inside each row's existing bundle.

---

## Roll-up

| Brand  | Source | Product | Merges | Year fix | Notes |
|---|---|---|---|---|---|
| ASUS   | 28 | 22 | 5  | 0  | Judgment call A pending |
| Dell   | 5  | 5  | 0  | 0  | Includes 1 net-new (`da15260`) |
| HP     | 23 | 9  | 14 | 18 | Judgment call B pending |
| Lenovo | 21 | 20 | 1  | 1  | orphan merge |
| **TOTAL** | **77** | **56** | **20** | **19** | ✓ matches Session 47 audit lock |

---

## Resolved judgment calls (Session 48)

**A. ASUS 2023 F+A pair merges.** RESOLVED — merges proceed unconditionally per the locked Session 47 rule. The chassis-letter prefix (F=Intel / A=AMD) is the same screen size in both variants (the digit is the size); two source SKUs at the same (Product, Year) merge regardless of year. ASUS lands at **22 rows**.

**B. HP Victus 15 CTO shell year.** RESOLVED — `15t-fa200` and `15z-fb300` keep year=2025 (separate row from the 2024 retail pair). Matches Session 47's stated 9-row target. HP lands at **9 rows**.
