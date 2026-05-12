# Tasks

For project scope and policy, see [`README.md`](../README.md). For system design, see [`ARCHITECTURE.md`](ARCHITECTURE.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

Phasing principle: foundation first, then the smallest end-to-end slice (one vendor working end-to-end), then expand to the other vendors, then the view layer, then operational helpers, then a structured validation pass, then polish. Each stage gates the next.

## Active
- Stage 8 / Phase 2 UI — scope locked Session 25, T8.0 shipped Session 26, T8.1 shipped Session 27, T8.2 shipped Session 28; see [`PRD.md` §Phase 2](PRD.md#phase-2--ui-stage-8) + [`ARCHITECTURE.md` §UI layer](ARCHITECTURE.md#ui-layer-phase-2)
  - T8.0 — Skeleton + launch — framework + entry-point lock; localhost page proves server → DB read — **done Session 26**
  - T8.1 — Browse one product — picker over `(model_code, year)` + `inspect-product` rendered as colored HTML (markers wrapped in spans); hub → browse wired via `st.session_state["view"]` — **done Session 27**
  - T8.2 — Dashboard hub — 4 destination buttons + 4th health stat (days-since-refresh) + stub routes wired — **done Session 28**
  - T8.3 — Compare side-by-side — multiselect → grid + vendor / segment / status filter bar
  - T8.4 — Find products where… — single-field filter playground covering PRD §Use cases
  - T8.5 — Review queue triage — existing-vs-candidate diff + `resolve` action buttons; **first write path**
  - T8.6 — Manual-edit a cell — product → field → value → status → note; replaces `manual-edit` CLI
  - T8.7 — Refresh trigger — one product / all + progress streamed back to the page
  - T8.8 — Polish — README / launch instructions, smoke tests, anything that surfaces during use

## Next
- (none — Stage 8 in flight)

## Deferred
- T7.0d Keyboard structured offerings split — Session 19
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

(Per-stage task detail: SESSION_LOG.md)
