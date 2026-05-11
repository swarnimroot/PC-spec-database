# Tasks

For project scope and policy, see [`README.md`](README.md). For system design, see [`ARCHITECTURE.md`](ARCHITECTURE.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

Phasing principle: foundation first, then the smallest end-to-end slice (one vendor working end-to-end), then expand to the other vendors, then the view layer, then operational helpers, then a structured validation pass, then polish. Each stage gates the next.

## Active
- (none — Stage 7 closed 2026-05-11)

## Next
- Stage 8 / Phase 2 UI — not yet scoped

## Deferred
- T7.0d Keyboard structured offerings split — Session 19
- Acer / MSI parsers — waiting on `scrapers-lib` Tier 2 upstream
- Catalog chip-spec auto-fetch (Intel ARK / NVIDIA / AMD) — Phase 2
- Admin UI — Phase 2
- History layer — Phase 2
- Hosted Postgres migration — if/when team access becomes real
- Manual T6.1 cell-by-cell cross-check across 6 products — low payoff post-T7.0a/b
- `camera_offerings.0.resolution` unit mismatch (Lenovo MP vs others' video res) — future camera-leaf shape conversation

## Closed stages
- Stage 1 — Foundation — 2026-05-07 (5)
- Stage 2 — Dell end-to-end slice — 2026-05-07 (9)
- Stage 3 — Other vendor parsers — 2026-05-07 (3)
- Stage 4 — View layer + `inspect-product` — 2026-05-07 (5)
- Stage 5 — Other CLI helpers — 2026-05-07 (4)
- Stage 6 — Validation pass — 2026-05-08 (7, T6.1 Partial)
- Stage 7 — Polish — 2026-05-11 (9, T7.0d Def)

(Per-stage task detail: SESSION_LOG.md)
