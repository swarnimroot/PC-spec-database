# Tasks

For project scope and policy, see [`README.md`](../README.md). For system design, see [`ARCHITECTURE.md`](ARCHITECTURE.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

Phasing principle: foundation first, then the smallest end-to-end slice (one vendor working end-to-end), then expand to the other vendors, then the view layer, then operational helpers, then a structured validation pass, then polish. Each stage gates the next.

## Active
- T9.2 Display canonicalizer in `views/formatting.py` — per-field rule lookup + opt-in via `field_path` kwarg on `display_value`; one rule today (`panel_type` "IPS-level"→"IPS"); wired into `ui/find.py` dropdown + cell-match — Session 37

## Next
- (empty — Stage 9 candidates surface as daily use reveals more dropdown variants or filter friction)

## Deferred
- T9.3 ASUS `family_code` support — mirror Lenovo T7.0a/b cross-SKU merge for ASUS (F/A CPU variants, internal SKU codes like `fa608`). Without it, each ASUS URL becomes its own DB row; populate-sprint groupings in POPULATION_QUEUE.md (e.g. TUF 16 2025 = 1 product from F16+A16 URLs) won't actually union at refresh. Discovered Session 38 during populate sprint
- T7.0d Keyboard structured offerings split — Session 19
- T8.8 (c) Refresh-targets enumeration dedup (`ui/refresh.py:104-152` ↔ `cli/refresh.py:334-374` near-duplicate planning loops) — gated on a third caller surfacing per Session 33 Decision #8 (rule-of-three convention) — Session 35
- T8.8 (d) Cross-product URL dedup in refresh `--all` (`cli/refresh.py:709-715`'s `_collect_source_urls_from_product` dedups per-call only) — gated on a shared URL pattern emerging across products — Session 35
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

(Per-stage task detail: SESSION_LOG.md)
