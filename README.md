# Competitive Database — Gaming Laptop Spec Catalog

A persistent, queryable database of competitor gaming-laptop specs from Dell, HP, Lenovo, ASUS, Acer, and MSI. Most fields auto-populate from public US vendor pages; the rest are manual. Every cell carries provenance and a status flag.

---

## Status

**Phase: Data layer + view layer + operational CLI — Stages 1–7 complete. Stage 6 (validation pass) closed in Session 12 (2026-05-08); Stage 7 (polish) closed in Session 19 (2026-05-11) — T7.0a, T7.0b, T7.0c, T7.0e, T7.1, T7.2, T7.3, T7.4 shipped; T7.0d deferred. Stage 10a (UI visual polish, 8 phases) closed Session 43 (2026-05-19); Stage 10b (data display rollup) FULLY closed Session 46 (2026-05-20) across two batches — CPU + Graphics S44, remaining 14 sections + Browse/Compare/Find redesigns S46. Stage 11 (database hierarchy layer) brainstorm complete Session 47 (2026-05-21); **Phase 1+2 shipped Session 48 (2026-05-21)** — schema migration applied (PK swapped to `(product, year)`, new `product TEXT NOT NULL` column, `source_model_codes` universalized) and 76 source rows audited down to **56 product rows** (20 cross-row merges, 19 year corrections, 1 net-new Dell `da15260`, 1 Lenovo orphan merged + deleted). Helpers compat shim in `db/helpers.py` keeps the tests green while UI/CLI callsites continue to use legacy `{"model_code": ..., "year": ...}` pk dicts (Phase 1.5 follow-up will rename them). **Phase 3 shipped Session 49 (2026-05-26)** — Browse picker reshape: 3-rung Brand → Series → Product dropdowns + Year toggle block (multi-select, default 2026) + Status toggle block (Active / Discontinued, default Active) + union spec view. Union cells dedupe and join with ` · ` (Policy B, locked); NULL status treated as Active (locked); N=1 byte-identical to the legacy single-product renderer. Five new DB helpers in `db/helpers.py` + six new UI components in `ui/_components.py`; `ui/browse.py` rewired against them. **Phase 4 shipped Session 49 (2026-05-26)** — union spec table primitive (`_union_rollup_for_section` + `union_spec_table_html`) extracted as the rendering primitive that Browse uses today and Compare adopts next. **Phase 5 shipped Session 50 (2026-05-26)** — Compare adopts the same per-column 3-rung Brand → Series → Product picker as Browse, with the new multi-column union grid (`comparison_union_grid_html`) replacing the legacy single-product Compare grid. **Phase 6 shipped Session 51 (2026-05-26)** — echo-parent display rule across Browse + Compare + Find: when `sub_brand` or `series` is NULL, the nearest non-null ancestor renders in italic-faint at the empty slot via the new `_echo_parent_for_leaf(key, product)` helper in `ui/_components.py`. Mixed-case (some rows populated, some NULL at the same rung in a union strip) renders plain — echo only fills total-absence. Find result card now always emits three identity crumbs (brand + sub_brand-or-echo + series-or-echo) + year. Pure rendering layer — no schema, no data, no CLI changes. **Phase 7 shipped Session 52 (2026-05-26)** — Find narrow-by reshape: `ui/find.py::_render_narrow_by` rewritten against the Phase 3 components (`brand_series_product_picker` + `year_toggle_block` + `status_toggle_block`) replacing the legacy 3-selectbox shape (Company / Series / Year with `(any)` sentinel). Partial picks narrow (Brand-only is valid — not a strict cascade; user-locked UX decision for the exploratory workflow); Year pills scoped to products matching the upstream query; Status defaults to empty filter (different from Browse/Compare's Active default). **Phase 8 shipped Session 52 (2026-05-26)** — tests slice (+4 new, 2 fixed) + docs alignment landed, **plus the status curation pass** — all 56 products now carry a manual `status` bundle via a one-shot year rule (2025/2026 → Active 24+20; 2023/2024 → Discontinued 3+9); follow-up is spot-checking older-year Discontinued rows for products still on sale.** **Stage 10c (review queue triage redesign) — brainstorm locked + P1 + P2 shipped Session 53 (2026-05-26).** Layout locked across 5 design questions: master-detail preserved; sidebar restructured into a 2-level collapsible tree (product folder → conflict-type sub-folder → row leaf); filter chips + sort dropdown + product search at the top; fully-resolved products hide; friendly labels (`Value mismatch / Low confidence / Catalog vouch / Year guess`) replace the abbreviated `value_dis / low_conf / new_chip / year_inf` IDs across the sidebar + detail-pane caption + new-chip explanatory caption. P1 = friendly-label swap shipped; the `T8.5 scope` / `Stage 8 / Phase 2` historical docstrings in `ui/triage.py` + `ui/__init__.py` also cleaned (the explicit fold-into-10c carve-out from S43). P2 = sidebar restructure shipped: new `_list_unresolved` LEFT-JOINs `products` for friendly product names, new `_pkey` / `_ckey` / `_friendly_product_name` / `_group_by_product_and_type` helpers, two new session-state sets (`queue_expanded_products` + `queue_expanded_cts`) hold tree open/closed state per the Edit-screen `edit.active_rows` precedent, auto-expand of the selected row's path on selection change. P3 (filter chips + sort dropdown + product search) and P4 (done-hides + counts wire-through) queued for next session; small UI polish brainstorm still queued behind 10c. Tests stayed at 525/525 across both phases. Foundation, schema, provenance helpers, all four Stage 3 vendor bridges, the Stage 4 view layer + `inspect-product` CLI, the Stage 5 operational helpers (`find-conflicts`, `find-empty`, `manual-edit`, `resolve`), the Stage 6 `audit-normalize` helper, and the Stage 7 `backfill-lenovo-families` helper are implemented and tested. 525/525 tests pass. The live DB carries 56 products across all 4 Tier 1 vendors (Dell + HP + Lenovo + ASUS) after the Session 48 Stage 11 Phase 1+2 audit collapsed 76 source rows → 56 (`(product, year)` PK); the Session 39 refresh sprint and the Session 40 manual-review checkpoint (84 of 313 review_queue rows resolved across Dell + HP + ASUS; Lenovo's 229 deferred to next session). T6.1 closed partial at 6/8 — the HP first URL (OMEN Transcend 14 fb0023nr) is upstream-blocked in `scrapers-lib`, and the Lenovo second product is now unblocked by T7.0a merge ingest (re-ingest pending). T6.2 done. T6.7 captured 16 findings; T7.0b (Session 13) closed the actionable bridge + CLI fixes (#2, #4, #5, #8, #11, #12) and resolved three policy items (#6 → T7.1 doc, #7 → T7.0c, #9 → T7.0d); T7.0a (Session 15) shipped Lenovo merge ingest and subsumed Finding #3; T7.2 (Session 17) shipped end-to-end smoke — all 6 products refresh successfully across all 4 vendors, T7.0a family_code merge confirmed end-to-end on live PSREF, and surfaced a CLI URL template gap (the hard-coded `DEFAULT_*_URL_TMPL` constants in `cli/refresh.py` don't reach Dell Aurora / HP full-slug / ASUS Strix variants) filed as T7.4; T7.4 (Session 18) shipped `refresh --from-db` — reads each product's stored `source_url` from bundle provenance and bypasses the per-vendor URL templates entirely, closing the gap. Finding #1 (HP Transcend 14 upstream) remains deferred. Full list and design sketches live in `SESSION_LOG.md` Sessions 12, 13, 15, 17, and 18.

- All 16 field categories from the source 80-column Excel (`Competitor Columns.xlsx`) are mapped to a data shape.
- Schema connective tissue (catalog references, unknown-chip handling, provenance record format, naming, enum policy) is locked.
- Database engine: **SQLite (local).** One file on disk, managed via DB Browser for SQLite. Migration to hosted Postgres reserved for if/when team access becomes real.
- `scrapers-lib` Tier 2 fetchers exist for Dell, HP, Lenovo, ASUS; Acer and MSI deferred upstream. Installed editable from the sibling repo.
- Six Stage 2 follow-up decisions resolved (year handling, naming, cross-tile merge, adapter source, boards modeling, storage parity). See `SESSION_LOG.md` Session 5 for detail.
- Four Session 7 decisions resolved during the HP / Lenovo pause checkpoints (HP weight handling, HP USB-C ambiguous-rate flagging, Lenovo target substitution, Lenovo `tgp_max` = max-per-board). See `SESSION_LOG.md` Session 7.
- Five Session 8 decisions resolved during the ASUS pause checkpoint — most notably the amendment to the Session 3 stub-only catalog rule: vendors that publish chip-level specs on laptop spec pages (ASUS NPU TOPS, Lenovo cores/clocks/process-node, HP/Dell core counts) now seed the matching `cpu_catalog` columns, with cross-vendor disagreement routed to the existing `value_disagreement` queue. See `SESSION_LOG.md` Session 8.
- Three Session 9 format decisions locked at the Stage 4 mid-stage checkpoint: empty sections render as `Heading: [empty]` (not hidden); single-offering categories drop the redundant `Offering 1:` prefix; the identity title block always shows all six identity fields including `[empty]` for unset. View layer marker scheme and section conventions captured in `VIEWS.md`. See `SESSION_LOG.md` Session 9.
- Stage 5 (Session 10): four CLI helpers shipped (`find-conflicts`, `find-empty`, `manual-edit`, `resolve`). Each views module gained a `field_paths(product)` registry, exposed via `views/orchestrator.all_field_paths()`; `find-empty` reuses the section structure for grouped output. Path syntax for writes is dotted — `<column>` for scalars, `<offerings_column>.<idx>.<leaf_key>` for offering leaves; catalog cells are not editable via `manual-edit` (plain text, no provenance scaffolding). 18 new CLI happy-path tests landed under `tests/cli/`. See `SESSION_LOG.md` Session 10.

**Stage 9 (Filter UX polish) — open.** Opened Session 36 with T9.1 (value dropdown on the "Find products where…" screen — `ui/find.py` `_distinct_values_for_template` helper replaces the free-text Value input with a selectbox populated from distinct DB values per (section, field), numeric-then-alpha sort, empty-field info banner). T9.2 (display canonicalizer in `views/formatting.py` — `_CANONICAL_BY_FIELD` lookup + `canonicalize_display(field_path, rendered)` hook + opt-in `field_path` kwarg on `display_value`; one rule seeded: `display_offerings.*.panel_type` "IPS-level" → "IPS"; wired symmetrically into `ui/find.py` dropdown and cell-match so picking "IPS" matches every stored variant) shipped Session 37. §Next is empty — Stage 9 candidates surface as daily use reveals more dropdown variants or filter friction. Section views (browse / compare / inspect-product) are untouched by canonicalization — they pass no `field_path` and continue to show the raw stored value. Session 42 closed three deferred Stage 9 items: T9.5 (Dell CPU regex now preserves `(Series N)` parenthetical), T9.6 (`resolve` unwraps `{"value": ...}` bundle before writing catalog text), T9.3 (ASUS TUF multi-SKU rollup — `family_code` + `arch_marker` derivation in `bridge/asus.py` with zero per-product hardcoding). See `TASKS.md` Stage 9 row and `SESSION_LOG.md` Sessions 36–37, 42.

**Stage 10a (UI visual polish) — closed Session 43 (2026-05-19).** Eight-phase Streamlit redesign per locked editorial-spec-sheet direction (Notion / Stripe / Apple-spec feel; light palette, generous whitespace, descriptive card-based CTAs). Foundation: new `competitive_database/ui/theme.py` (`PALETTE` / `SPACE` / `RADIUS` / `TYPE` design tokens + `inject_global_css()`), `competitive_database/ui/_chrome.py` (`render_header(active)` top-bar nav with Browse / Compare / Find + `···` overflow, `render_footer()` thin divider), expanded `competitive_database/ui/_components.py` (`cascading_picker`, `identity_strip_html`, `spec_table_html`, `comparison_grid_html`, `marker_legend_inline_html`, `dot_marker`, `MARKER_LABELS`, `friendly_field_label`, `friendly_leaf_label`), and `.streamlit/config.toml` for light theme. All six per-screen modules (`hub.py`, `browse.py`, `compare.py`, `find.py`, `edit.py`, `refresh.py`) rewritten end-to-end against the new helpers. Plus two data-model extensions delivered mid-stream: `manual` is now a real third bundle status alongside `vouched` / `needs-review` (enforced Python-side in `db/helpers._MANUAL_STATUSES`; no schema migration — `status` is free-text JSON), and `manual-edit` persists a top-level `source_url` on the manual provenance bundle (new `--source-url` CLI flag). `edit.py` rebuilt as a bulk per-product editor (cascading picker → all fields listed vertically with `✎` inline expand → bottom Save bar with live change count); the legacy JSON-literal toggle was dropped entirely. `refresh.py` rebuilt with three-mode tabs (All products / By company / Selected products) and a slim in-progress card (`Refreshing K of N…` + `st.progress`) plus a post-run 4-tile result panel; Custom-URL mode dropped (and the 16 obsolete `tests/ui/test_refresh_helpers.py` cases with it). `triage.py` got a chrome-only cleanup carve-out — the full triage redesign is parked for Stage 10c. Tests 339 → 349 (peaked 364 mid-stream; settled 349 after Phase G's obsolete-test prune). See `SESSION_LOG.md` Session 43 for the full phase-by-phase narrative + 8 decisions.

**Stage 10b (Data display rollup) — FULLY CLOSED Session 46 (2026-05-20).** Browse / Compare / Find collapse every visible section to a single rolled-up line (I/O is the one exception — four sub-rows). Per-SKU detail is preserved in the DB and stays visible on the Edit screen. Closed across two batches:

- **Batch 1 (Session 44):** CPU + Graphics. CPU rollup deduplicates `architecture_code` values across `cpu_offerings` (comma-joined; e.g. `RPL-H R` / `HWK R`). Graphics rollup walks each board's `gpus`: NVIDIA contributes the catalog `board` (e.g. `MB1` / `MB2` / `MB3`), AMD / Intel contribute the brand name, `gpu_class = "integrated"` rows drop out entirely. Both carry one worst-status marker across per-SKU offerings (`needs-review > vendor-doesn't-publish > manual > verified`). Schema additions (idempotent `ALTER` migrations): `cpu_catalog` — renamed empty `architecture` → `architecture_code`, added `architecture_name` and `generation`; `gpu_catalog` — added `series`, `board`, `gpu_class` (existing `architecture` column kept for future curation). All six new columns are JSON provenance bundles, user-curated, not auto-seeded. Live DB carries 65 curated CPU rows and 13 GPU rows. Section heading `Boards` renamed to `Graphics` in the view registry; underlying `products.boards` column unchanged. Tests 349 → 364.

- **Batch 2 (Session 46):** the remaining 14 sections. Each section's `views/<name>.py` now exposes `rollup_value(product) -> (display, marker)` returning one collapsed line; I/O exposes `rollup_rows(product) -> list[(label, value, marker)]` for its four sub-rows (USB / HDMI / SD card / audio jack). Two sections are **hidden** from the visual rollup: **Keyboard** (free-text descriptions resist clean rollup) and **Thermals** (100% NULL across the DB today). Both stay editable. `views/orchestrator.py` adds a new `_VISUAL_SECTIONS` tuple alongside `_SECTION_REGISTRY` so Edit / `find-empty` continue to walk every section. CPU section heading was renamed `CPU` → **Processor**. Alongside the section work, Browse / Compare / Find were redesigned on top of the new rollup tables: **Series replaces Product as the picker rung** on Browse + Compare (verified `(vendor, sub_brand, series, year)` resolves to exactly one product across all 76); **strict cascade** (no auto-select at any level); Compare's `+` button restyled and dropped onto a faint horizontal rail; Find restructured around a Section → Feature → Match → Value cascade with horizontal **result cards** carrying an `Open →` button that jumps to Browse pre-loaded. Tests 364 → **479 green** (+115 net).

**Stage 11 (database hierarchy layer) — Phases 1–8 shipped Sessions 48–52 (2026-05-21 → 2026-05-26).** 5-level identity hierarchy locked Session 47: `Brand | Sub-brand | Series | Product | Year`. Sub-brand is the marketed-distinct premium gaming line (ROG / Alienware / OMEN-legacy / HyperX-2026+ / Legion / Predator-future); NULL for brand-level lines (TUF, Victus, LOQ, V-series). Series is populated only when the parent has multiple named sub-lines (Strix/Zephyrus/Flow under ROG; Area-51/Aurora under Alienware; Legion 5/7/9 under Legion). Tier modifiers (Pro, Essential, Max, Slim, Transcend, Scar, X) ride on Product, not Series. Echo-parent display rule (P6, shipped S51): when `sub_brand` or `series` is NULL on a rendered product, the nearest non-null ancestor renders in italic-faint at the empty slot — via `_echo_parent_for_leaf(key, product)` in `ui/_components.py`. Mixed-case in union strips (some rows populated, some NULL at the same rung) renders plain; Find result cards always emit three identity crumbs + year. **(Product, Year) is the PK** as of Session 48 — extends Lenovo's Stage-7 chassis-merge pattern to all brands; underlying SKU codes preserved in `source_model_codes`. **HP HyperX 2026 rebrand handling** baked in: pre-2026 = Sub-brand=OMEN, Series=∅; 2026+ = Sub-brand=HyperX, Series=OMEN. Per-brand audit lock: **76 source rows → 56 product rows** (20 cross-row merges, 19 year corrections). Browse + Compare picker reshape both shipped: Browse Session 49 (P3), Compare Session 50 (P5) — 3 dropdowns (Brand → Series → Product) + Year toggle button block (multi-select, default 2026) + Status toggle button block (Active/Discontinued, default Active) + union-sections view; Compare uses the same per-column. Find narrow-by reshape (P7, shipped S52): `_render_narrow_by` rewritten against the Phase 3 components (`brand_series_product_picker` + `year_toggle_block` + `status_toggle_block`) replacing the legacy 3-selectbox shape; partial picks narrow (Brand-only is valid — explicit user lock, not a strict cascade) and Status defaults to empty filter (different from Browse/Compare's Active default). 8-phase plan: P1 schema swap + P2 recurate (S48), P3 Browse picker + P4 union spec primitive (S49), P5 Compare adopts picker + union grid (S50), P6 echo-parent rule (S51), P7 Find narrow-by reshape (S52) — all shipped. P8 tests + docs slice + status curation pass landed S52; all 56 products curated via year rule (2025/2026 → Active, 2023/2024 → Discontinued); spot-checks for older-year products still on sale are the follow-up. **Stage 10c (review queue triage redesign) + small UI polish brainstorm both queued behind Stage 11.** See `SESSION_LOG.md` Sessions 47–52.

**Hub welcome modal (Session 45, 2026-05-20).** Side-quest off the Stage 10b/10c boundary, not a tracked stage. Added a one-time-per-Streamlit-session intro modal on the Hub: a hero block (live SVG density grid — one accent square per product — plus a `products × spec_categories = total_fields` math reveal in 48px type) over a three-column explanatory block (Problem / What this does / Who it's for — Product, Marketing, Competitive intel + use case per row). Vendor names in the body read live from `products.brand` via a new `_vendor_names(conn)` helper, sorted alphabetically with `, etc.` appended so Acer / MSI / future OEMs flow through automatically when seeded. Modal flag is set on dialog *open* (not on Got it click) so X-dismissal sticks. Surfaced one durable gotcha: `@st.dialog`-decorated bodies rerun on a Streamlit worker thread distinct from the main script thread that created `sqlite3.Connection`, so all DB-derived values must be computed in `render()` and passed into the dialog as primitives (never the connection itself). 4 new UI tests landed (all green); full suite at session close 366 passing / 2 failing where the 2 failures are pre-existing uncommitted edits in `views/cpu.py` unrelated to Session 45. See `SESSION_LOG.md` Session 45.

**Current phase:** Phase 2 (UI) — Stage 11 done (P1–P8 shipped S48–S52; status curation applied S52 via year rule with spot-checks as the follow-up). Stage 10c in progress — brainstorm locked + P1 friendly-label swap + P2 sidebar tree restructure shipped S53; P3 (filter chips + sort + search) + P4 (done-hides + counts) queued. **Stage 8 complete** (historical) — scoped Session 25 (T8.0–T8.8 substages: browse / compare / find / queue-triage screens, refresh trigger, polish); T8.0 (skeleton + `python -m competitive_database ui` launch + live-counts landing) shipped Session 26; T8.1 (browse one product — picker + colored-marker HTML render via `views.orchestrator.render_product`, hub → browse wired via `st.session_state["view"]`) shipped Session 27. T8.2 (dashboard hub: four-destination grid + days-since-refresh stat + stub routes for compare / find / queue) shipped Session 28. T8.3 (compare side-by-side: multiselect over `(model_code, year)` + vendor / segment / status filter bar + HTML grid rendered over the union of `views.orchestrator.all_field_paths`, section-grouped) shipped Session 29. T8.4 (find products where… — single-field filter playground: section → field cascade over the union of `all_field_paths` with offering indices collapsed to a `*` wildcard, comparator dropdown of `= / contains / ≥ / ≤ / is set / is empty / vendor doesn't publish`, per-product result blocks with every matching cell rendered inline with provenance marker) shipped Session 30; marker palette + path resolver promoted to `ui/_markers.py` at the rule-of-three threshold (third caller). T8.5 (review queue triage — sidebar + main-panel layout, existing-vs-candidate diff with provenance markers, four action buttons matching the `resolve` CLI verbs, manual-override form, `new_chip_unverified` rows show only the two valid actions) shipped Session 31; `cli/resolve.py` refactored to expose `resolve_row(conn, …)` as a pure-library handler so UI + CLI share one write path. **First UI write path** — the read-only invariant from T8.0–T8.4 ends here. T8.6 (manual-edit a cell — product selectbox + section/field cascade with offering-index picker + value text input with JSON-literal toggle + status radio + note + entered-by override; current-value preview line and post-save before/after banner) shipped Session 32; `cli/manual_edit.py` refactored to expose `manual_edit_cell(conn, …)` as a pure-library handler per the T8.5 precedent. Hub layout split into "Explore" (browse / compare / find) and "Curate" (review-queue triage / manual-edit + reserved slot for T8.7 refresh trigger). T8.7 (refresh trigger — mode radio for one-product / all-products; one-product offers a URL-source radio for `URL template` / `Custom URL` / `From DB stored source_url`; all-products shows the Eligible / Skipped / Total tiles + a will-refresh preview; progress streams live through `st.status` + an `on_step` callback) shipped Session 33; `cli/refresh.py` refactored to expose `refresh_product(conn, …)` + `refresh_all_products(conn, …)` as pure-library handlers per the T8.5 / T8.6 precedent. The CLI's `--all` flag, previously a "not implemented yet" SystemExit, is now live and loops every product whose brand bundle resolves to a supported vendor and whose row carries at least one stored `source_url`. T8.8 (polish — README "Launching the UI" Quick-start subsection in §Setup, Custom-URL host pre-flight check `_validate_url_brand` in `ui/refresh.py` rejecting brand/URL mismatches before the request leaves the UI, and the `streamlit.testing.v1.AppTest` harness under `tests/ui/` covering entry-point boot + view dispatcher + one read-only screen smoke + all three write screens' write-path interaction tests + the refresh error-pipeline) shipped Sessions 34–35: A README launch + D host pre-flight + B AppTest first cut Session 34; B per-screen AppTest write-path coverage over the 3 write screens (`triage` / `edit` / `refresh`) Session 35. T8.8 (c) `_enumerate_refresh_targets` ↔ `refresh_all_products` planning-loop dedup and (d) cross-product URL dedup in refresh `--all` move to TASKS §Deferred under their existing gates (rule-of-three / 3rd caller per Session 33 Decision #8; shared-URL-pattern emerging across products). T7.0d (keyboard structured offerings — Session 13 Finding #9) remains deferred from Stage 7; re-openable if filterable keyboard data becomes a real need. See `TASKS.md` Stage 8 row and `SESSION_LOG.md` Sessions 25–35.

---

## Setup

This is a personal project, not packaged for distribution. Steps assume Python 3.12+.

### Prerequisites

- Python 3.12 or newer.
- `scrapers-lib` cloned as a **sibling directory** to this repo. The bridge layer imports `scrapers_lib.tier2.*` for vendor fetchers; without it, `refresh` fails at import time.

  ```
  Workspace/
  ├── scrapers-lib/          # sibling — vendor scrapers
  └── competitive-database/  # this repo
  ```

- DB Browser for SQLite (optional) — spreadsheet-style spot checks against `competitive.db`.

### Install

From the repo root, in a fresh virtualenv:

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -e .
pip install -e ../scrapers-lib   # editable sibling install
pip install -e ".[ui]"           # optional: local browser UI (Streamlit) — see `ui` subcommand below
```

### Bootstrap the database

```bash
python -m competitive_database db-init
```

Creates `competitive.db` in the current directory with the full schema. Override the path with `--path`.

### First refresh

Fetch and ingest one product end-to-end:

```bash
python -m competitive_database refresh --brand dell --model alienware-area-51-aa18250-gaming-laptop
```

Inspect the resulting row:

```bash
python -m competitive_database inspect-product alienware-area-51-aa18250-gaming-laptop
```

See [CLI reference](#cli-reference) for the full subcommand surface.

### Launching the UI

Browse, compare, search, triage, manually edit, and refresh products from a local browser surface (Streamlit). Requires the optional `ui` extra (`pip install -e ".[ui]"`).

```bash
python -m competitive_database ui
```

Binds to `127.0.0.1` and opens the default browser automatically. Override the DB path with `--db competitive.db` and the port with `--port 8501`.

Landing page is the **hub** — hero line + three metric tiles (products / vendors / days since refresh) over three rounded CTA cards (**Browse**, **Compare**, **Find**) with primary `Open →` buttons. Top-bar nav carries Browse / Compare / Find directly; **Edit** and **Refresh** live under a `···` overflow. The visual direction (Stage 10a, Session 43) is editorial-spec-sheet: light palette, dotted dividers, rounded soft borders, colored `●` dot markers in place of bracketed text tokens. The triage screen is reachable through the CLI today and will be redesigned under Stage 10c.

The Edit and Refresh screens write through the same library handlers as the `resolve`, `manual-edit`, and `refresh` CLIs — so a UI write and a CLI write produce identical bundles + provenance. See the [`ui` subcommand reference](#ui) below for flags.

---

## Scope

### In scope
- Six brands: **Dell, HP, Lenovo, ASUS, Acer, MSI**.
- **US vendor sites only.**
- **Gaming laptops only.**
- **Data layer only:** scrape, clean, transform, store. The database is the deliverable for this phase.

### Out of scope (deferred or excluded)
- UI / dashboard / chatbot — separate later efforts after the DB is reliable.
- SKU-level configurations (e.g., "i9 + 5090 + 32GB / 1TB" as a row).
- Pricing.
- Operating system variants (Windows 11 Home vs Pro).
- Release dates.
- Color / finish options.
- History / audit log of changing values — deferred, not blocked.

---

## Architecture (high level)

Three tables:

1. **`cpu_catalog`** — chip-level data per CPU model (e.g., Core Ultra 9 285HX). Populated deterministically from Intel ARK and AMD spec pages, plus name-suffix rules.
2. **`gpu_catalog`** — chip-level data per GPU model (e.g., RTX 5070 Ti). Populated deterministically from NVIDIA and AMD spec pages.
3. **`products`** — one row per gaming-laptop product, identified by **(product, year)** (Stage 11 PK swap, Session 48 — generalizes Lenovo's chassis-merge pattern across all brands; `model_code` demoted to non-PK survivor slug, `source_model_codes` carries the vendor SKU array). References catalogs by model name string for chip data. Carries product-decided values directly (TGP, TDP max, board configuration, etc.).

Detailed schema: see [`DATA_MODEL.md`](docs/DATA_MODEL.md).

---

## Identity

- **A product = (product, year).** ASUS ROG Strix G16 2025 ≠ ASUS ROG Strix G16 2026. (Stage 11 PK swap, Session 48 — `product` is the new curated identity column, set during the per-brand audit.)
- The vendor-written full name is scraped as-is and stored.
- From the name + URL, the following are mechanically derived: brand, sub-brand, series, model code, year (when in the name). The `product` column is **curated** rather than derived — set during the Stage 11 audit and used as the PK component alongside `year`.
- `status` (active / discontinued) and `segment` (entry / premium / flagship) stay manual forever.

---

## Refresh model

- **Manual button only.** No scheduler.
- Real-world cadence expected: **~quarterly** once built.

---

## Provenance and confidence

Every cell carries a provenance record and a status flag. Scraped data is held to a *correctness bar*; manual data to a *vouched* bar.

### Scraped cells

| Field | Description |
|---|---|
| `source_url` | The page the value came from. |
| `captured_at` | Timestamp of extraction. |
| `scraper_id` | Which scraper produced it. |
| `status` | `verified` / `needs-review` / `vendor-doesn't-publish`. |

**Correctness bar:** scraped data must match the official US vendor page. If extraction is uncertain, the value is **not stored** — it routes to the review queue.

### Manual cells

| Field | Description |
|---|---|
| `entered_by` | Who entered it. |
| `entered_at` | Timestamp. |
| `source_note` | Free-form (URL, teardown reference, etc.). |
| `status` | `vouched` (default) / `needs-review`. |

`needs-review` on manual cells is a self-check tool — not a multi-reviewer workflow. Used when a value is thinly sourced and the user wants to revisit it.

---

## Conflict policy

When a scraper finds a value different from what's already stored — especially against a manually entered value — it **never silently overwrites**. The disagreement routes to a **review queue** for the user to resolve. Manual edits never silently lock either; both sides are visible until resolved.

---

## Catalog reference and unknown-chip handling

- Products reference CPU and GPU catalogs **by model name string** (e.g., `"Core Ultra 9 285HX"`).
- When a scraper encounters a chip model not yet in the catalog, the chip is **auto-added** with `status = needs-review`. The scrape proceeds without blocking. The user reviews catalog entries asynchronously.

---

## Locked policy decisions (summary)

- **Database engine:** SQLite (local). One-file storage, managed via DB Browser for SQLite. Migration to hosted Postgres reserved for if/when team access becomes real.
- **Sources:** Tier 2 manufacturer product pages only (via `scrapers-lib`). Tier 1 (mentions/feeds) and Tier 3 (retailer pages) are out of scope for this DB.
- **Vendor coverage rule:** Schema and tables built for all 6 brands. If `scrapers-lib` lacks a vendor, that vendor's products show empty rows until upstream catches up — not a project block.
- **Bridge-layer location:** All project-specific parsing and transformation lives in `competitive-database`. `scrapers-lib` is only extended when the change is universally useful.
- **No pre-locked manual fields:** Every DATA_MODEL field is scrape-eligible. The scraper extracts what it can; whatever's empty becomes the manual surface at runtime. The provenance + status flag system already handles "vendor doesn't publish" — we don't bake that into the schema.
- Catalogs only for CPU and GPU. Other commodities store specs directly on the product, no catalog.
- Multi-option fields (CPU offerings, GPU/board variants, displays, batteries, keyboards, cameras, adapters) stored as **lists of offerings**, not fixed slots.
- Motherboard variants are first-class on the product. Each board carries its own TPP cap, GPU TGP cap, and list of supported GPUs.
- Catalog references use the **model name string** as the foreign key (not a generated ID).
- Field naming: **snake_case** throughout.
- Categorical fields start as **open enums**; tighten as data accumulates.
- History deferred — current state only — but design preserves the option to add a history layer later.

---

## Repo layout (planned)

```
Workspace/
├── scrapers-lib/                 # sibling — vendor-specific scrapers
└── competitive-database/         # this repo
    ├── README.md                 # this file — overview, scope, policy
    └── docs/
        ├── PRD.md                # product requirements
        ├── DATA_MODEL.md         # full field-by-field schema reference
        ├── ARCHITECTURE.md       # detailed system design
        ├── SESSION_LOG.md        # decision log per session
        ├── TASKS.md              # work breakdown
        ├── VIEWS.md              # view-layer format choices and conventions
        └── POPULATION_QUEUE.md   # URL inventory + vendor navigation guide for adding products
```

---

## Vendor URL conventions

Each vendor's bridge expects a specific URL shape. Using the wrong shape produces silent or noisy failures.

- **Lenovo** — must be `psref.lenovo.com/l/Product/...` (the spec catalog). The consumer shop (`www.lenovo.com/...`) is rejected outright.
- **ASUS** — must include the `/spec/` subpath, e.g. `https://rog.asus.com/laptops/.../<model>/spec/`. The bare landing page returns no spec sections.
- **HP** — PDP URLs (`hp.com/us-en/shop/pdp/...`) work for most products. Some products (e.g. OMEN Transcend 14 fb0023nr) currently fail upstream in `scrapers-lib`; this is a known gap.
- **Dell** — `--brand dell --model <slug>` derives the URL automatically; or pass `--url https://www.dell.com/.../spd/<slug>` explicitly.

For step-by-step navigation from each vendor's home page to the target product URL (the "where do I start, where do I drill to" recipe per vendor), see [`POPULATION_QUEUE.md` § How to find a product URL per vendor](docs/POPULATION_QUEUE.md#how-to-find-a-product-url-per-vendor). The home URLs there are the single point of update if a vendor reorganizes their site.

---

## CLI reference

All subcommands run via `python -m competitive_database <command>`. `--db <path>` is accepted on every read/write subcommand (default `competitive.db`).

Under the Stage 11 PK swap (Session 48), `MODEL_CODE` positional / `--model` flag callsites still pass the legacy vendor slug; the `_normalize_products_pk` compat shim in `db/helpers.py` translates them to the new `(product, year)` PK so every pre-Stage-11 CLI signature continues to work unchanged.

### `db-init`

Bootstrap a fresh SQLite DB with the full schema, or apply pending column migrations to an existing DB (idempotent).

```
db-init [--path PATH]
```

- `--path` — DB file location. Default: `competitive.db`.

```bash
python -m competitive_database db-init
```

### `refresh`

Fetch a vendor product page, parse via the bridge, and ingest the result. Single SQLite transaction per product; cross-tile offerings are unioned.

```
refresh --brand BRAND (--model SLUG | --url URL | --from-db --model SLUG [--year YEAR])
        [--db DB] [--profiles-dir DIR]
```

- `--brand` — `dell` / `hp` / `lenovo` / `asus`. Required.
- `--model` — URL slug for the product (vendor-specific). Mutually exclusive with `--url`.
- `--url` — Full vendor URL. Recommended for Lenovo (`psref.lenovo.com/l/Product/...`) and ASUS (`/spec/` subpath required).
- `--from-db` — Read the product's stored `source_url(s)` from bundle provenance in the local DB instead of formatting via the per-vendor template. Recommended for refreshing an already-ingested product — the template-formatted URL doesn't always match the URL the product was originally ingested from (e.g. Dell Aurora line, HP full marketing slug, ASUS Strix no-`/us/`). See `SESSION_LOG.md` Sessions 17 + 18 for the full story. Requires `--model`; mutually exclusive with `--url`. For Lenovo Intel+AMD merged rows, refreshes from each stored URL once.
- `--year` — Disambiguator for `--from-db` when the same `model_code` has multiple yearly variants in `products`.
- `--all` — Refresh every product in the DB whose brand bundle resolves to a supported vendor and whose row carries at least one stored `source_url`. Loops via `--from-db` per product (Lenovo Intel+AMD rows fan out to both stored URLs). Brand is read per-product from the DB, so `--brand` is omitted with `--all`. Per-product errors are recorded and reported but do not stop the loop. Skip rules: brand bundle missing / malformed → skip; brand value not in `dell` / `hp` / `lenovo` / `asus` → skip; no scraped `source_url` on any bundle → skip. T8.7 / Session 33.
- `--profiles-dir` — Persistent browser profiles directory for the Playwright stealth context. Default: `.profiles`.

```bash
# First-time ingest — template-formatted URL.
python -m competitive_database refresh --brand dell --model xps-13-9315

# First-time ingest — explicit URL override.
python -m competitive_database refresh --brand asus --url https://rog.asus.com/laptops/rog-zephyrus/rog-zephyrus-g16-2026/spec/

# Returning refresh — read each stored URL out of the DB.
python -m competitive_database refresh --brand dell --model aa18250 --from-db

# Refresh every eligible product in the DB.
python -m competitive_database refresh --all
```

### `inspect-product`

Print the orchestrated, status-marked spec dump for one product.

```
inspect-product MODEL_CODE [--year YEAR] [--db DB]
```

- `MODEL_CODE` (positional) — Product slug. For Lenovo merged rows, this is the `family_code` (e.g. `legion-pro-7-16-gen-10`).
- `--year` — Disambiguator if the slug has multiple yearly variants.

```bash
python -m competitive_database inspect-product rog-zephyrus-g16-2026
```

### `find-empty`

List empty and `vendor-doesn't-publish` cells per product, grouped by the same 16 sections as `inspect-product`.

```
find-empty (--product MODEL_CODE [--year YEAR] | --all) [--db DB]
```

- `--product` — Product slug. Required unless `--all`.
- `--year` — Disambiguator.
- `--all` — Walk every product in the DB.

```bash
python -m competitive_database find-empty --all
```

### `find-conflicts`

List unresolved `review_queue` rows (id, product, conflict type, field path, existing-vs-candidate summary — one row per line).

```
find-conflicts [--product MODEL_CODE] [--db DB]
```

- `--product` — Filter to one product slug.

```bash
python -m competitive_database find-conflicts
```

### `manual-edit`

Write a manual cell at a dotted field path. Provenance scaffolding (`status`, `entered_by`, `entered_at`) is filled in automatically.

```
manual-edit --product MODEL_CODE --field PATH (--value VAL | --value-json JSON)
            [--year YEAR] [--note NOTE] [--status STATUS] [--entered-by USER]
            [--source-url URL] [--db DB]
```

- `--product` — Product slug. Required.
- `--field` — Dotted field path. `<column>` for scalars; `<offerings_column>.<idx>.<leaf_key>` for offering leaves. Required.
- `--value` — Cell value (coerced int → float → string).
- `--value-json` — Cell value as a JSON literal (use for `true` / `false` / `null` / lists). Mutually exclusive with `--value`.
- `--note` — Free-form source note (stored as bundle `source_note`).
- `--status` — Bundle status. Default `vouched`; alternatives `needs-review`, `manual` (Stage 10a / Session 43 — third real status, no longer aliases to `vouched`).
- `--entered-by` — Override the bundle `entered_by` field (default: `$USER` / `$USERNAME`).
- `--source-url` — Optional source URL (Stage 10a / Session 43); when set, persisted as a top-level `source_url` key on the manual provenance bundle, parallel to the scraped bundle's `source_url`.

```bash
python -m competitive_database manual-edit --product rog-zephyrus-g16-2026 --field audio_jack --value-json true
python -m competitive_database manual-edit --product alienware-m18-2026 --field display_offerings.0.nits_peak --value 500
```

Catalog cells aren't editable through `manual-edit` (the path syntax only addresses `products` columns). The Stage 10b curated columns (`cpu_catalog.architecture_code` / `architecture_name` / `generation`; `gpu_catalog.series` / `board` / `gpu_class`) carry JSON provenance bundles populated by hand directly via SQL or DB Browser, not by the bridge layer.

Plain-leaf offering paths (currently `boards.{idx}.arch_marker`) write plain scalars instead of bundles; bundle helpers refuse plain-leaf paths to keep the shape honest.

### `resolve`

Close one `review_queue` row in a single transaction.

```
resolve --id ID --action ACTION [--value VAL | --value-json JSON]
        [--note NOTE] [--entered-by USER] [--db DB]
```

- `--id` — `review_queue.id` of the row. Required.
- `--action` — One of `accept_candidate`, `kept_existing`, `manual_override`, `dropped`. Required.
- `--value` / `--value-json` — Required only with `--action manual_override`.
- `--note` — Resolver note; stored on the queue row, and used as the bundle `source_note` for `manual_override`.

```bash
python -m competitive_database resolve --id 42 --action accept_candidate
python -m competitive_database resolve --id 47 --action manual_override --value 16 --note "Verified from teardown"
```

For `new_chip_unverified` rows, `resolve` routes off the queue row's `candidate_value` payload (which encodes the catalog target as `{table, model, value}`) rather than `field_path`. `accept_candidate` flips the target catalog row's `catalog_status` from `needs-review` to `vouched`; `dropped` resolves the queue row without touching the catalog. `kept_existing` and `manual_override` are rejected for these rows.

### `audit-normalize`

Walk every product and surface paths where the same conceptual field carries 2+ distinct value strings (e.g. `Wi-Fi 7` vs `WiFi 7`). Operational tool for catching vocabulary drift.

```
audit-normalize [--all] [--strings-only] [--db DB]
```

- `--all` — Print every filled path with its values, not just the gaps.
- `--strings-only` — Skip numeric and boolean values. Strings are where normalization issues live.

```bash
python -m competitive_database audit-normalize --strings-only
```

### `backfill-lenovo-families`

One-time backfill for legacy Lenovo rows ingested before T7.0a. Reads rows with `family_code IS NULL`, re-derives family + arch from existing bundles, applies in-place updates for singletons or merges multi-row families (boards + offerings unioned; source machine codes preserved in `source_model_codes`). Idempotent.

```
backfill-lenovo-families [--db DB]
```

```bash
python -m competitive_database backfill-lenovo-families
```

### `ui`

Launch the local browser UI (Streamlit). Binds to `127.0.0.1`; the user's default browser opens automatically. Requires the optional `ui` extra (`pip install -e ".[ui]"`).

```
ui [--db DB] [--port PORT] [--base-path PATH]
```

- `--db` — DB file location. Default: `competitive.db`.
- `--port` — Streamlit server port. Default: `8501`.
- `--base-path` — Subpath under a reverse proxy (e.g. `competitive-database` for `https://host/competitive-database`). When set, also applies the reverse-proxy companion flags (`--server.headless=true`, `--server.enableCORS=false`, `--server.enableXsrfProtection=false`) so Streamlit emits asset URLs prefixed for the proxied subpath. Leave unset for local-only use.

```bash
python -m competitive_database ui
```

Stage 8 / Phase 2 complete (Session 35) — all seven Phase 2 screens (hub, browse, compare, find, triage, edit, refresh) live with `AppTest` harness coverage under `tests/ui/`. Stage 10a (Session 43) re-skinned the UI under one editorial design system: design tokens centralized in `competitive_database/ui/theme.py`, shared top-bar header + footer in `competitive_database/ui/_chrome.py`, cross-screen helpers in `competitive_database/ui/_components.py`; the six per-screen modules (hub, browse, compare, find, edit, refresh) rewritten against those helpers. Triage redesign is parked for Stage 10c.

---

## Upgrading

When you pull schema changes from git, **re-run `db-init` to apply column migrations** to your existing `competitive.db`:

```bash
python -m competitive_database db-init
```

This step is required: `db/connection.py::connect()` opens the SQLite handle but does **not** call `apply_schema()` — only the `db-init` subcommand does. Any CLI subcommand that touches a newly added column will fail with `sqlite3.OperationalError: no such column: <name>` on a pre-migration DB until `db-init` is run once.

`apply_schema()` is idempotent: existing tables are guarded by `PRAGMA table_info` checks and new columns added via `ALTER TABLE ... ADD COLUMN`. Existing rows are preserved. Data backfills that depend on new columns (e.g. `backfill-lenovo-families` for the T7.0a Lenovo family rollup) are exposed as their own CLI subcommands — run them after `db-init`.

---

## Normalization notes

### `resolution_label` — documented enum-pair

Vendors publish display resolution in two equivalent vocabularies — a marketing label and a resolution standard:

| Marketing label | Resolution standard |
|---|---|
| FHD | 1080p |
| WQXGA | 2.5K |
| UHD | 4K |

Either form may appear in `resolution_label` depending on the vendor (e.g. Lenovo publishes `WQXGA`; ASUS publishes `2.5K`). **Both are stored as-is with no normalization at ingest** — the open enum stays open at the storage layer. The companion `resolution_pixels` field carries the unambiguous pixel form (e.g. `2560×1600`) for filters and joins.

Per the Session 13 Finding #6 decision. `DATA_MODEL.md` cross-links here.

---

## Document conventions

- All docs are Markdown.
- Decisions are written in present tense; deferred items explicitly tagged.
- When a decision changes, update the relevant doc *and* note the change in `SESSION_LOG.md` (when that doc exists).
