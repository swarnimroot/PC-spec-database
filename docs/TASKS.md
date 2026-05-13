# Tasks

For project scope and policy, see [`README.md`](../README.md). For system design, see [`ARCHITECTURE.md`](ARCHITECTURE.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

Phasing principle: foundation first, then the smallest end-to-end slice (one vendor working end-to-end), then expand to the other vendors, then the view layer, then operational helpers, then a structured validation pass, then polish. Each stage gates the next.

## Active
- T9.1 Value dropdown in `ui/find.py` — replace free-text value input with selectbox populated from distinct DB values per (section, field) — Session 36

## Next
- T9.2 Display canonicalizer in `views/formatting.py` — per-field canonical naming for the variant gaps `audit-normalize` surfaces (e.g., `panel_type` "IPS" vs "IPS-level"); scope locked after T9.1 dropdown reveals real-world inconsistencies

## Deferred
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
