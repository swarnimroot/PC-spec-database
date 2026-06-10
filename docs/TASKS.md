# Tasks

For project scope and policy, see [`README.md`](../README.md). For system design, see [`ARCHITECTURE.md`](ARCHITECTURE.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

Phasing principle: foundation first, then the smallest end-to-end slice (one vendor working end-to-end), then expand to the other vendors, then the view layer, then operational helpers, then a structured validation pass, then polish. Each stage gates the next.

## Active
- T9.2 Display canonicalizer in `views/formatting.py` — per-field rule lookup + opt-in via `field_path` kwarg on `display_value`; one rule today (`panel_type` "IPS-level"→"IPS"); wired into `query/engine.py` (Find dropdown + cell-match, live) — Session 37 — DONE S60 (extended to the Compare detail accordion via `api/serializers.py::_detail_rows`; verified end-to-end on real DB — raw `IPS-level` now served as `IPS`)
- Stage 11 — Database hierarchy layer — **Phase 1+2+3+4+5+6+7+8 shipped** (S48: schema migration + 76→56 row audit + helpers compat shim; S49: Browse picker reshape — 3-rung Brand→Series→Product + Year/Status toggles + union spec table primitive; S50: Compare adopts per-column picker + multi-column union grid at ≥1 column; S51: echo-parent display rule across Browse + Compare + Find with mixed-case-stays-plain lock and Find card always-3-crumbs lock; S52: Find narrow-by reshape onto picker + pill toggles, Brand-only narrow locked + status curation rule applied across all 56 products (2025/2026 → Active, 2023/2024 → Discontinued); Policy B `·`-join union format locked; NULL-status-as-Active locked; tests 479 → 525 green) — Session 52

## Next
- React rebuild Phase 1+2 — query engine → `competitive_database/query/` + FastAPI `competitive_database/api/` (health/schema/catalog/model/find/queue/counts/value/resolve/history/refresh) + `frontend/` Vite+React Spec Finder (facets + advanced query, 37 models on real DB) — DONE S54 (`docs/REACT_REBUILD_PLAN.md`)
- React Compare Matrix (`frontend/src/compare/`) — rows = our sections, ≤4 columns via drag-shelf + typeahead, per-column year scrubber, differences-only — DONE S54
- React Review screen (`frontend/src/curation/`; renamed from Curation Cockpit S55) — unified queue (conflicts + field-state review/missing/hand) + adaptive editor (resolve-vs-edit) + keyboard commit + provenance slide-over; backend on `api/app.py` + `competitive_database/curation/queue.py` — DONE S54
- React one-command launch — `cd frontend && npm run dev` (concurrently+cross-env: uvicorn :8011 + Vite :8501; app at http://localhost:8501/competitive-database/) — DONE S54
- React Refresh screen (`frontend/src/refresh/`) — "All eligible products" / "One product" modes over `POST /api/refresh`, confirm step + running spinner + results rollup with conflict callout to Review — DONE S55
- React Home (`frontend/src/home/`) — hero + live counts (Products/Vendors/Conflicts/Unverified) + clickable stat cards + clickable screen cards + per-session welcome modal (sessionStorage); default screen, brandmark routes home — DONE S55
- React Phase 4 cutover — Streamlit retired: deleted `competitive_database/ui/`, `cli/ui_launch.py`, `tests/ui/`; removed `ui_launch` from `__main__.py` + `ui` extra from `pyproject.toml`; React is the sole UI; tests 499 passed — DONE S55
- React same-origin API + Tailscale Funnel exposure — `api.js` BASE defaults to `import.meta.env.BASE_URL` (no hardcoded host); `vite.config.js` `server.allowedHosts: ['.ts.net']` + proxy `/competitive-database/api`→`localhost:8011` (`VITE_API_TARGET`); `.env` `VITE_API_BASE` unset — DONE S55
- Curation→Review rename + bucket relabel — nav/Home/welcome say "Review" (route id unchanged); queue buckets Conflicts / Unverified (was Needs review) / Missing / Manual (was Hand-entered); `shared/data.js` state labels review→Unverified, hand→Manual — DONE S55
- Home clickable stat cards (Products/Vendors → Spec Finder; Conflicts/Unverified → Review) + per-session welcome modal (sessionStorage, was once-ever localStorage) — DONE S55
- Parked hiccup — Compare empty-state bug: removing all columns blanked the area + broke drag/select of a first product — DONE S56 (add-column search+drop zone factored into a shared `addDropZone`, now rendered in both the empty state and the header)
- Parked hiccup — Finder repeated row-label names ("V V16", "Strix Strix G16", "Area-51 Area-51 16"): DB `product` already includes the series word — DONE S56 (display-only `modelTail(series, model)` helper in `shared/data.js` strips the redundant prefix at every label site; no DB change)
- Parked hiccup — Review left queue flat-list readability: needs groupings + field-importance prioritization (Curation→Review rename shipped S55) — DONE S57 (queue grouped by spec category in importance order, top group expanded + rest collapsed, j/k traverses visible only; Conflicts tab gained a "Correct value" edit box routing to `manual_override`, off catalog-vouch rows; frontend-only, `resolve_row` already supported override)
- Compare per-leaf detail drill-down — new read-only `GET /api/model/{id}/detail?year=` (year required; per-leaf values grouped by Compare section, one row per leaf, multi-offering leaves as lists + synthetic Graphics GPU row) + `GET /api/schema/detail`; `serializers.model_detail`/`detail_schema` + `_FRIENDLY_LEAF`; only Processor/Graphics/I/O → collapsible accordions (collapsed = rollup summary, expand fetches real values stacked per line, cached per model·year), other sections plain rows + ☰ Fields drawer (left of control bar) + `api.js` `getModelDetail`/`getDetailSchema`; refinements: `.drow`→`.detrow` global-CSS fix, ~31px midway density + left breathing room, uniform-font no-dot options (I/O keeps dots); tests 499 → 505 — DONE S58
- UI rework (Streamlit, legacy) — Browse + Compare merged into `ui/spec_roster.py` + Find checkbox-pick handoff DONE S54; remaining rework screens (Edit / Refresh / Triage) superseded by the React rebuild — Session 54
- Stage 11 Phase 8 spot-checks — year-rule curation applied S52 (2025/2026 → Active 24+20; 2023/2024 → Discontinued 3+9); walk older-year Discontinued rows for products still on sale and correct as needed — Session 52
- Stage 10c — Review queue triage redesign — **brainstorm locked S53**; P1 friendly-label swap + P2 sidebar tree restructure SHIPPED S53; **P3 (filter chips + sort + product search) + P4 (done-hides + counts) PARKED — post-commit user feedback S53 flagged the tree shape itself as too click-heavy ("very difficult to understand, involves a lot of clicks and steps before being able to take any action"); queued phases don't fix the underlying problem**; fresh triage UX brainstorm needed anchored on minimizing clicks to act on a row — Session 53
- Small UI polish brainstorm — enumerate paper cuts user has been noticing across Browse / Compare / Find / Edit / Hub; user-flagged at S46 close, never enumerated — Session 53

## Deferred
- Stage 11 Phase 1.5 (optional cleanup) — strict callsite rename to `{"product": ..., "year": ...}` pk dicts everywhere; remove the `_normalize_products_pk` compat shim in `db/helpers.py`. ~34 mechanical callsites + bridges populating `product` per the new naming convention. Tests stay green throughout — Session 48
- T9.4 Dell `snapshot.options` consumption — bridge to surface scrapers-lib v1.5.0 configurator options as additional offering rows; fetcher flag wired Session 39 — DONE S60 (`bridge/dell.py` consumes CPU/GPU/RAM/Storage/Display: selectable option labels append to the tile spec text and run through the existing builders; RAM/storage raise the `*_max_gb` ceiling; `unavailable` skipped; `selected` deduped against tile via merge + new `_build_boards` GPU dedup; `_build_cpu_chip_specs` guarded so configurator CPUs don't inherit the tile core count; +7 tests. VERIFIED ON SYNTHETIC OPTIONS ONLY — no live Dell fetch with real `.options` yet; first real refresh is the live check. Keyboard/Battery/Adapter/OS modules NOT consumed — out of scope this pass. S61: code-reviewed (no bugs) + 4 real-label hardening tests added — GPU ®/™/VRAM dedup, RAM `32 GB, 2 x 16 GB` → 32, `ComponentOption` object path, malformed/None options; +4 tests → 519. Live refresh now only needs to confirm real module key names)
- ASUS GPU regex over-matching — `bridge/asus.py` captured clock-speed / wattage / VRAM strings as GPU model values (e.g. `"6GB GDDR6"`, `"1595 MHz* at 115W (...)"`). Cleaned out of 6 affected products on 2026-05-20 — Session 44 — DONE S60 (root cause was the `else` branch recording non-GPU pieces; added `_GPU_BRAND_RE` guard so a piece must carry a GPU brand token to be recorded — branded-but-unmapped models still surface as needs-review, pure spec prose is skipped; +2 tests. No longer re-pollutes on refresh)
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
