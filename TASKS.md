# Tasks — Work Breakdown (Phase 1: Data Layer)

For project scope and policy, see [`README.md`](README.md). For system design, see [`ARCHITECTURE.md`](ARCHITECTURE.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

---

## Phasing principle

Foundation first, then the smallest end-to-end slice (one vendor working end-to-end), then expand to the other vendors, then the view layer, then operational helpers, then a structured validation pass, then polish. Each stage gates the next.

---

## Stage 1 — Foundation

| Task | Deliverable |
|---|---|
| T1.1 | Repo bootstrap: `pyproject.toml`, package skeleton, `.gitignore` (excludes `competitive.db`) |
| T1.2 | `db/schema.sql` — `CREATE TABLE` for `cpu_catalog`, `gpu_catalog`, `products`, `review_queue`. Add indexes on common filter paths. |
| T1.3 | `db/connection.py` — SQLite connection + transaction helper |
| T1.4 | `db/helpers.py` — read/write provenance bundles. Handles both scalar bundles and list-of-offerings (per-leaf bundles). The single point of truth for all DB writes. |
| T1.5 | `db-init` CLI command — bootstraps schema |

Stage exit criterion: empty DB file is initialized with the full schema; `db/helpers.py` round-trips a sample provenance bundle.

---

## Stage 2 — Dell end-to-end slice

The smallest path that proves the architecture: fetch one Dell product, parse, write to DB, read back.

| Task | Deliverable |
|---|---|
| T2.1 | `bridge/types.py` — `CandidateProduct` shape (mirrors DATA_MODEL with bundles attached) |
| T2.2 | `bridge/helpers.py` — shared utilities: unit parsing (`"8GB"` → `8`), vendor full name decomposition (→ brand / sub-brand / series / model code / year), tier flag derivation |
| T2.3 | Test fixtures — capture sample `ProductSnapshot` JSON from a Dell live page, save to `tests/fixtures/dell/` |
| T2.4 | `bridge/dell.py` — Dell parser (flat regex over techspecs payload) + unit tests against fixtures |
| T2.5 | `bridge/dispatcher.py` — route a `ProductSnapshot` to the right parser by `snapshot.source` |
| T2.6 | `ingest/catalog_resolve.py` — CPU/GPU stub auto-add (model + brand only; `status: needs-review`) and `new_chip_unverified` queue insert |
| T2.7 | `ingest/runner.py` — full diff + write-or-queue logic. Single SQLite transaction per snapshot. |
| T2.8 | `cli/refresh.py` + `__main__.py` wiring — CLI entry for `refresh --brand <brand> --model <model>` and `refresh --all` |
| T2.9 | Live smoke test — refresh one Dell product end-to-end against the live site; inspect the DB to verify shape |

Stage exit criterion: `python -m competitive_database refresh --brand dell --model alienware-area-51-aa18250-gaming-laptop` produces a valid DB row with provenance bundles on every populated cell.

---

## Stage 3 — Other vendor parsers

Add HP, Lenovo, ASUS to the bridge. Each is a contained add — dispatcher routes by `snapshot.source`, no other code changes needed.

**Status (Session 8, 2026-05-07):** Done. All three vendors shipped end-to-end. Session 8 also amended Session 3 Decision 4 — see SESSION_LOG.md — to allow vendor-published chip specs to seed the CPU catalog.

| Task | Deliverable | Status |
|---|---|---|
| T3.1 | `bridge/hp.py` — HP parser (multi-line spec values: line 0 → `tier: base`, additional lines → `tier: optional`) + tests against fixtures | Done — live capture: OMEN Transcend 14 |
| T3.2 | `bridge/lenovo.py` — Lenovo parser (walks hierarchical `level1 > level2 > level3` path keys) + tests | Done — live capture: Legion Pro 7 16AFR10H (AMD cousin; Intel Pro 7i Gen 10 not yet on PSREF) |
| T3.3 | `bridge/asus.py` — ASUS parser (section-grouped h2 titles; per-SKU variants newline-joined) + tests | Done — live capture: ROG Zephyrus G16 (2026) |

Stage exit criterion: refresh succeeds end-to-end for at least one product per vendor. **Met.**

---

## Stage 4 — View layer + `inspect-product`

Single source of truth for human-readable presentation. CLI uses it now; UI uses it later.

**Status (Session 9, 2026-05-07):** Done. View layer shipped end-to-end. Three user format decisions resolved at the mid-stage checkpoint (empty-section heading, single-offering label, identity-block always-show) plus one catalog-marker default — see `SESSION_LOG.md` Session 9.

| Task | Deliverable | Status |
|---|---|---|
| T4.1 | `views/formatting.py` — shared markers (`[verified]`, `[m]`, `[?]`, `[—]`, `[empty]`, `[partial]`), status aggregation helper | Done |
| T4.2 | One render function per category — 16 view modules: `cpu.py`, `boards.py`, `display.py`, `battery.py`, `memory.py`, `storage.py`, `network.py`, `io.py`, `adapter.py`, `camera.py`, `audio.py`, `keyboard.py`, `thermals.py`, `dimensions.py`, `weight.py`, `design.py`. Each takes `product` (and `catalogs` where needed) and returns a string. | Done |
| T4.3 | `views/orchestrator.py` — composes per-category views into a full product render | Done |
| T4.4 | `cli/inspect_product.py` — `inspect-product <model_code>` prints the orchestrated render | Done — wired into `__main__.py`; positional `model_code` arg + `--year` disambiguator + `--db` override |
| T4.5 | `VIEWS.md` — short doc capturing non-obvious format choices and why (so future sessions don't undo deliberate decisions) | Done |

Stage exit criterion: `inspect-product alienware-m18-2026` prints a readable, status-marked, catalog-enriched dump of the product. **Met** — validated against the live ROG Zephyrus G16 row (`inspect-product rog-zephyrus-g16-2026`); same shape applies to Alienware once an Alienware row is re-ingested.

---

## Stage 5 — Other CLI helpers

Operational surface for conflicts and manual entry. All thin wrappers over Python functions the future UI will call.

**Status (Session 10, 2026-05-07):** Done. All four CLI helpers shipped + wired into `__main__.py`. Each views module gained a `field_paths(product)` helper exposed via `views/orchestrator.all_field_paths()` so `find-empty` reuses the section structure. 18 new CLI tests; 166/166 tests passing.

| Task | Deliverable | Status |
|---|---|---|
| T5.1 | `cli/resolve.py` — single-transaction resolution of a `review_queue` row. Four actions: `accept_candidate`, `kept_existing`, `manual_override`, `dropped` | Done |
| T5.2 | `cli/manual_edit.py` — write a manual cell with provenance scaffolding handled automatically (`status`, `entered_by`, `entered_at`) | Done |
| T5.3 | `cli/find_empty.py` — list empty + `vendor-doesn't-publish` cells per product, using view-layer field labels for human-readable output | Done — section grouping mirrors `inspect-product` order |
| T5.4 | `cli/find_conflicts.py` — list unresolved review queue rows | Done — supports `--product` filter |

Stage exit criterion: a real conflict can be resolved end-to-end via `resolve`; a real manual cell can be written via `manual-edit`. **Met** — covered by `tests/cli/test_resolve.py` (all four actions roundtripped through a real SQLite DB) and `tests/cli/test_manual_edit.py` (scalar + offering-leaf writes verified). The three existing live `review_queue` rows on the ROG Zephyrus G16 row are `new_chip_unverified` over `boards.N.gpus.M` (4-level) paths — that's the catalog-vouching workflow, deferred to a later stage; `resolve` errors out on those with a clear message.

---

## Stage 6 — Validation pass

Structured validation, not eyeballing. Catches the bugs UI would otherwise inherit.

**Status (Session 12, 2026-05-08):** Audit phase complete. T6.1 partial-complete at 6/8 products (HP first URL upstream-blocked; Lenovo second deferred pending multi-URL merge ingest design). T6.2 done. T6.7 captures 16 findings — bridge bugs, CLI ergonomics, ingest policy, normalization, and one architectural addition (Lenovo merge ingest) — see `SESSION_LOG.md` Session 12 for full list and design sketches. Stage closes here; fixes scoped into Stage 7.

| Task | Deliverable | Status |
|---|---|---|
| T6.1 | Sample-audit — refresh 2 products per vendor; cross-check populated cells against the actual vendor pages by hand | Partial — 6/8 products refreshed (Dell 2/2, HP 1/2 upstream-blocked, Lenovo 1/2 deferred, ASUS 2/2). Manual cell-by-cell cross-check NOT done; deferred to Stage 7 alongside bridge fixes (no point auditing data we'll re-ingest). |
| T6.2 | Normalization audit | Done — 6 vocabulary findings (camera res, display res-label, boards.label, lighting residue, keyboard desc shape, anti_glare enum) rolled into T6.7. No Wi-Fi/DDR5/MT-s drift detected. |
| T6.3 | Conflict logic test | Validated (Session 11) |
| T6.4 | Low-confidence test | Validated (Session 11) |
| T6.5 | Manual-edit nested field test | Validated (Session 11) |
| T6.6 | HP tier test | Validated (Session 11) |
| T6.7 | Document any schema gaps surfaced during validation; update `DATA_MODEL.md` if needed | Done — 16 findings captured in `SESSION_LOG.md` Session 12. Notable: Lenovo multi-URL merge ingest (architectural addition; full design + slug-parser sketch in Session 12). DATA_MODEL.md unchanged; future `family_code` and `source_model_codes` additions land with the Stage 7 merge ingest work. |

Stage exit criterion: data layer is trusted enough to be the foundation for Phase 2 UI work. **Met.**

---

## Stage 7 — Polish

**Status (Session 16, 2026-05-11):** T7.1 shipped (docs polish — README Setup + Upgrading + Normalization notes sections + per-CLI CLI reference covering all 9 subcommands; DATA_MODEL.md `resolution_label` cross-link; PRD intentionally untouched per Session 15 sweep; doc-only, 242/242 tests unchanged). T7.0a shipped Session 15 (Lenovo multi-URL merge ingest — schema additions + slug parser + bridge integration + grouping coercion + runner premerge + backfill CLI + plain-leaf manual-edit shape; 198 → 242 tests across 7 commits). T7.0c shipped Session 14 (boards.label view-layer ordinal renumbering; 192 → 198 tests). T7.0e shipped Session 14 close (dropped `boards.{idx}.label` from manual-edit field_paths). T7.0b shipped Session 13 (7 actionable bridge + CLI fixes; 172 → 192 tests). T7.0d (keyboard structured offerings), T7.2 / T7.3 still open. Deferrals: Finding #1 HP upstream-blocked.

| Task | Deliverable | Status |
|---|---|---|
| T7.0a | Lenovo multi-URL merge ingest — slug parser + family-code detection + append-vs-new ingest path. Adds `family_code` and `source_model_codes` fields. Subsumes Finding #3 (consumer-shop URL acceptance). Design in `SESSION_LOG.md` Session 12; implementation walked through in Session 15. | Done — Session 15. Step 0: dropped `boards.{idx}.label` from manual-edit field_paths (T7.0e). M1: `products.family_code` + `products.source_model_codes` columns (plain TEXT/JSON-array-as-TEXT, idempotent ALTER on apply_schema). M2+M3: `bridge/lenovo.py::_derive_lenovo_family_and_arch` (compressed + verbose slug conventions, arch token map IRX/IAX/ADR/ARX/AFR, H suffix dropped from arch but kept in source_model_codes, `_LENOVO_FAMILY_LINE_PREFIXES` allowlist); `bridge/types.py` CandidateProduct gains `family_code` + `source_model_codes`; per-board plain `arch_marker`. M4: `cli/refresh.py` grouping coerces model_code → family_code when set; `ingest/runner.py::_merge_boards` keys by (label, arch_marker), `_merge_candidates` unions source_model_codes, new `_premerge_lenovo_existing_row` handles AMD-after-Intel append. M5: `cli/backfill_lenovo_families.py` one-time CLI for legacy Lenovo rows. M6: integration bug sweep (`views/load.py` `_PLAIN_PRODUCT_FIELDS` extended, `views/boards.py` exposes arch + `_BOARD_SCALAR_LEAVES`, backfill fallback for empty vendor_full_name). M7: plain-leaf manual-edit shape — `_PLAIN_OFFERING_LEAVES` set in `cli/_paths.py`, `is_plain_offering_leaf` + `write_plain_at_path` helpers; `cli/manual_edit.py` routes plain-leaf paths; `write_bundle_at_path` raises if called on a plain-leaf path. 198 → 242 tests. |
| T7.0b | Bridge bug sweep from Stage 6 findings — Dell Design VDP gap, ASUS auto-append `/spec/`, ASUS double-year suffix, Lenovo lighting residue + camera MP normalization, CLI slug-with-year tolerance. See `SESSION_LOG.md` Session 12 #2, #4, #5, #8, #11, #12 + Session 13 implementation notes. | Done — Session 13. Helpers `format_product_pk` + `parse_product_arg` added to `cli/_paths.py`; wired across find-empty, find-conflicts, inspect-product, manual-edit, resolve. Findings #1 (HP upstream) and #3 (Lenovo URL → T7.0a) deferred. |
| T7.0c | Boards.label per-product ordinal renumbering — view-layer rewrite (preserves bridge tier-merge semantics). Decoded: bridge keeps internal MB1/MB2/MB3 tier labels for cross-tile merge; view layer renames them to per-product ordinals at render time so an ac16251 with no top-tier SKU shows MB1 + MB2 instead of MB2 + MB3. | Done — Session 14. `views/boards.py:render` sorts offerings by tier (MB1 < MB2 < MB3, unmapped last) before assigning per-product ordinals; bridge / merge / `field_paths` unchanged. New `tests/views/test_boards.py` (+6 tests; 192 → 198). |
| T7.0d | Keyboard structured offerings — extract `backlight`, `copilot_key`, `layout`, `travel_mm` as discrete bundle leaves; `description` becomes vendor-doesn't-publish (or short normalized line). Touches all 4 bridges + schema additions. | New (Session 13 policy decision; Finding #9) |
| T7.0e | Drop `boards.{idx}.label` from `manual-edit` field_paths — addresses the Session 14 caveat (manual label edits were silently masked at render after T7.0c). | Done — Session 15 Step 0 of T7.0a. `views/boards.py::field_paths` no longer includes the label leaf. |
| T7.1 | Update `README.md` with setup instructions, common workflows, CLI reference. Also document the `resolution_label` enum-pair convention (WQXGA = 2.5K, FHD = 1080p, UHD = 4K) per Session 13 Finding #6 decision. | Done — Session 16. New README sections: **Setup** (prereqs / install / bootstrap / first refresh walkthrough), **Upgrading** (migration gotcha — re-run `db-init` after schema pulls; references `apply_schema()` idempotency), **Normalization notes** (`resolution_label` enum-pair table). "CLI commands" section expanded into a per-CLI **CLI reference** for all 9 subcommands (purpose, usage, args, example each). `DATA_MODEL.md` `resolution_label` row cross-links to README § Normalization notes. PRD reviewed and intentionally untouched (T7.0a / T7.1 are internal mechanics + reference material, not PRD-level claims) — Session 15 tail-point #4 stance reconfirmed. |
| T7.2 | End-to-end smoke test across all four vendors | |
| T7.3 | Update `SESSION_LOG.md` with implementation milestones as they land | Partial — Sessions 13, 14, 15 entries cover T7.0a–c closeouts; further milestones to follow. |

Stage exit criterion: a fresh clone plus the docs is enough for someone (or future-me) to set up the project, run a refresh, inspect data, and resolve a conflict without external help.

---

## Deferred — tracked, not scheduled

| Item | Reason |
|---|---|
| Acer / MSI parsers | Waiting on `scrapers-lib` Tier 2 upstream |
| Catalog chip-spec auto-fetch (Intel ARK / NVIDIA) | Stub-only auto-add chosen for Phase 1; chip-spec backlog filled manually or by a later job |
| Admin UI | Phase 2 — depends on validation pass completion. View layer ready for it. |
| History layer | Design preserves the option; no implementation in Phase 1 |
| Hosted Postgres migration | Reserved for if/when team access becomes real |
| Manual T6.1 cell-by-cell cross-check across 6 products | Tedious; deferred until after bridge fixes land in Stage 7 (no point auditing data we'll re-ingest) |
