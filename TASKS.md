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

**Status (Session 7, 2026-05-07):** T3.1 and T3.2 done; T3.3 pending.

| Task | Deliverable | Status |
|---|---|---|
| T3.1 | `bridge/hp.py` — HP parser (multi-line spec values: line 0 → `tier: base`, additional lines → `tier: optional`) + tests against fixtures | Done — live capture: OMEN Transcend 14 |
| T3.2 | `bridge/lenovo.py` — Lenovo parser (walks hierarchical `level1 > level2 > level3` path keys) + tests | Done — live capture: Legion Pro 7 16AFR10H (AMD cousin; Intel Pro 7i Gen 10 not yet on PSREF) |
| T3.3 | `bridge/asus.py` — ASUS parser (section-grouped h2 titles; per-SKU variants newline-joined) + tests | Pending — target: ROG Zephyrus G16 |

Stage exit criterion: refresh succeeds end-to-end for at least one product per vendor.

---

## Stage 4 — View layer + `inspect-product`

Single source of truth for human-readable presentation. CLI uses it now; UI uses it later.

| Task | Deliverable |
|---|---|
| T4.1 | `views/formatting.py` — shared markers (`[verified]`, `[m]`, `[?]`, `[—]`, `[empty]`, `[partial]`), status aggregation helper |
| T4.2 | One render function per category — 16 view modules: `cpu.py`, `boards.py`, `display.py`, `battery.py`, `memory.py`, `storage.py`, `network.py`, `io.py`, `adapter.py`, `camera.py`, `audio.py`, `keyboard.py`, `thermals.py`, `dimensions.py`, `weight.py`, `design.py`. Each takes `product` (and `catalogs` where needed) and returns a string. |
| T4.3 | `views/orchestrator.py` — composes per-category views into a full product render |
| T4.4 | `cli/inspect_product.py` — `inspect-product --product <model-year>` prints the orchestrated render |
| T4.5 | `VIEWS.md` — short doc capturing non-obvious format choices and why (so future sessions don't undo deliberate decisions) |

Stage exit criterion: `inspect-product alienware-m18-2026` prints a readable, status-marked, catalog-enriched dump of the product.

---

## Stage 5 — Other CLI helpers

Operational surface for conflicts and manual entry. All thin wrappers over Python functions the future UI will call.

| Task | Deliverable |
|---|---|
| T5.1 | `cli/resolve.py` — single-transaction resolution of a `review_queue` row. Four actions: `accept_candidate`, `kept_existing`, `manual_override`, `dropped` |
| T5.2 | `cli/manual_edit.py` — write a manual cell with provenance scaffolding handled automatically (`status`, `entered_by`, `entered_at`) |
| T5.3 | `cli/find_empty.py` — list empty + `vendor-doesn't-publish` cells per product, using view-layer field labels for human-readable output |
| T5.4 | `cli/find_conflicts.py` — list unresolved review queue rows |

Stage exit criterion: a real conflict can be resolved end-to-end via `resolve`; a real manual cell can be written via `manual-edit`.

---

## Stage 6 — Validation pass

Structured validation, not eyeballing. Catches the bugs UI would otherwise inherit.

| Task | Deliverable |
|---|---|
| T6.1 | Sample-audit — refresh 2 products per vendor; cross-check populated cells against the actual vendor pages by hand |
| T6.2 | Normalization audit — distinct values per categorical field across all products; surface gaps like `"Wi-Fi 7"` vs `"WiFi 7"` |
| T6.3 | Conflict logic test — manually edit a cell, re-run refresh, verify queue catches it |
| T6.4 | Low-confidence test — verify uncertain extractions skip the DB and route to queue |
| T6.5 | Manual-edit nested field test — verify helper handles nested paths cleanly (e.g., `display_offerings.0.nits_peak`) |
| T6.6 | HP tier test — verify line-0-base / rest-optional logic on real HP products |
| T6.7 | Document any schema gaps surfaced during validation; update `DATA_MODEL.md` if needed |

Stage exit criterion: data layer is trusted enough to be the foundation for Phase 2 UI work.

---

## Stage 7 — Polish

| Task | Deliverable |
|---|---|
| T7.1 | Update `README.md` with setup instructions, common workflows, CLI reference |
| T7.2 | End-to-end smoke test across all four vendors |
| T7.3 | Update `SESSION_LOG.md` with implementation milestones as they land |

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
