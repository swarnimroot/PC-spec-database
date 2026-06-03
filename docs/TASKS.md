# Tasks

For project scope and policy, see [`README.md`](../README.md). For system design, see [`ARCHITECTURE.md`](ARCHITECTURE.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

Phasing principle: foundation first, then the smallest end-to-end slice (one vendor working end-to-end), then expand to the other vendors, then the view layer, then operational helpers, then a structured validation pass, then polish. Each stage gates the next.

## Active
- T9.2 Display canonicalizer in `views/formatting.py` — per-field rule lookup + opt-in via `field_path` kwarg on `display_value`; one rule today (`panel_type` "IPS-level"→"IPS"); wired into `ui/find.py` dropdown + cell-match — Session 37
- Stage 11 — Database hierarchy layer — **Phase 1+2+3+4+5+6+7+8 shipped** (S48: schema migration + 76→56 row audit + helpers compat shim; S49: Browse picker reshape — 3-rung Brand→Series→Product + Year/Status toggles + union spec table primitive; S50: Compare adopts per-column picker + multi-column union grid at ≥1 column; S51: echo-parent display rule across Browse + Compare + Find with mixed-case-stays-plain lock and Find card always-3-crumbs lock; S52: Find narrow-by reshape onto picker + pill toggles, Brand-only narrow locked + status curation rule applied across all 56 products (2025/2026 → Active, 2023/2024 → Discontinued); Policy B `·`-join union format locked; NULL-status-as-Active locked; tests 479 → 525 green) — Session 52

## Next
- UI rework — Spec Roster — **Browse + Compare merged into single `ui/spec_roster.py` screen DONE S54** (browse.py/compare.py + their tests deleted; spec_roster.py + test_spec_roster.py added; 3 mockups under docs/; 514 tests green); remaining rework screens (Find / Edit / Refresh / Triage) pending — Session 54
- Stage 11 Phase 8 spot-checks — year-rule curation applied S52 (2025/2026 → Active 24+20; 2023/2024 → Discontinued 3+9); walk older-year Discontinued rows for products still on sale and correct as needed — Session 52
- Stage 10c — Review queue triage redesign — **brainstorm locked S53**; P1 friendly-label swap + P2 sidebar tree restructure SHIPPED S53; **P3 (filter chips + sort + product search) + P4 (done-hides + counts) PARKED — post-commit user feedback S53 flagged the tree shape itself as too click-heavy ("very difficult to understand, involves a lot of clicks and steps before being able to take any action"); queued phases don't fix the underlying problem**; fresh triage UX brainstorm needed anchored on minimizing clicks to act on a row — Session 53
- Small UI polish brainstorm — enumerate paper cuts user has been noticing across Browse / Compare / Find / Edit / Hub; user-flagged at S46 close, never enumerated — Session 53

## Deferred
- Stage 11 Phase 1.5 (optional cleanup) — strict callsite rename to `{"product": ..., "year": ...}` pk dicts everywhere; remove the `_normalize_products_pk` compat shim in `db/helpers.py`. ~34 mechanical callsites + bridges populating `product` per the new naming convention. Tests stay green throughout — Session 48
- T9.4 Dell `snapshot.options` consumption — bridge to surface scrapers-lib v1.5.0 configurator options (CPU/GPU/RAM/Storage/Display/Keyboard/Battery/Adapter/OS) as additional offering rows; fetcher flag wired Session 39 but bridge doesn't read the field yet
- ASUS GPU regex over-matching — `bridge/asus.py` (or upstream `scrapers-lib`) captures clock-speed / wattage / VRAM strings as GPU model values (e.g. `"6GB GDDR6"`, `"1595 MHz* at 115W (...)"`). Cleaned out of 6 affected products on 2026-05-20; will re-pollute on next refresh until the GPU regex is tightened — Session 44
- ASUS TUF URL template in `cli/refresh.py` — `refresh --from-db` on `asus-tuf-gaming-*` model_codes won't auto-build URLs (no `www.asus.com/.../tuf-gaming/{slug}/techspec/` template); gated on user adding first TUF product to DB — Session 42
- T7.0d Keyboard structured offerings split — Session 19
- T8.8 (c) Refresh-targets enumeration dedup (`ui/refresh.py` ↔ `cli/refresh.py` near-duplicate planning loops) — gated on a third caller surfacing per Session 33 Decision #8 (rule-of-three convention) — Session 35
- T8.8 (d) Cross-product URL dedup in refresh `--all` (`cli/refresh.py::collect_source_urls_from_product` dedups per-call only) — gated on a shared URL pattern emerging across products — Session 35
- Triage / `__init__.py` historical-scope docstring cleanup — module-level docstrings in `ui/triage.py` + `ui/__init__.py` still reference T8.X scope; cosmetic only, fold into Stage 10c — Session 43
- Edit annotation-only boolean round-trip — annotation-only edits on bool fields render the existing value as `"yes"`/`"no"` in the text input, then re-coerce on save (lossy for `True`/`False`); audit when 10b touches the field-type map — Session 43
- Acer / MSI parsers — waiting on `scrapers-lib` Tier 2 upstream
- Catalog chip-spec auto-fetch (Intel ARK / NVIDIA / AMD) — future enrichment job
- History layer — Phase 4
- Hosted Postgres migration — if/when team access becomes real
- Manual T6.1 cell-by-cell cross-check across 6 products — low payoff post-T7.0a/b

## Closed stages
- Stage 1 — Foundation — 2026-05-07 (5)
- Stage 2 — Dell end-to-end slice — 2026-05-07 (9)
- Stage 3 — Other vendor parsers — 2026-05-07 (3)
- Stage 4 — View layer + `inspect-product` — 2026-05-07 (5)
- Stage 5 — Other CLI helpers — 2026-05-07 (4)
- Stage 6 — Validation pass — 2026-05-08 (7, T6.1 Partial)
- Stage 7 — Polish — 2026-05-11 (9, T7.0d Def)
- Stage 8 — Phase 2 UI — 2026-05-12 (9, T8.8(c)+T8.8(d) Def)
- Stage 10a — UI visual polish — 2026-05-19 (8 phases A–H; +2 data-model extensions: `manual` real third status, `source_url` on manual bundles)
- Stage 10b — Data display rollup — FULLY CLOSED 2026-05-20 across two batches: Batch 1 Session 44 (CPU + Graphics — schema migration + view rewrites + 65 CPU / 13 GPU curated rows; 349 → 364 tests), Batch 2 Session 46 (remaining 14 sections rolled up + I/O multi-row + Keyboard/Thermals hidden + Browse/Compare/Find redesigns with Series rung + strict cascade + Find result cards; 364 → 479 tests)

(Per-stage task detail: SESSION_LOG.md)
