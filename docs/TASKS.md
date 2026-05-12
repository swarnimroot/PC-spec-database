# Tasks

For project scope and policy, see [`README.md`](../README.md). For system design, see [`ARCHITECTURE.md`](ARCHITECTURE.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

Phasing principle: foundation first, then the smallest end-to-end slice (one vendor working end-to-end), then expand to the other vendors, then the view layer, then operational helpers, then a structured validation pass, then polish. Each stage gates the next.

## Active
- Stage 8 / Phase 2 UI — scope locked Session 25, T8.0 shipped Session 26, T8.1 shipped Session 27, T8.2 shipped Session 28, T8.3 shipped Session 29, T8.4 shipped Session 30, T8.5 shipped Session 31, T8.6 shipped Session 32; see [`PRD.md` §Phase 2](PRD.md#phase-2--ui-stage-8) + [`ARCHITECTURE.md` §UI layer](ARCHITECTURE.md#ui-layer-phase-2)
  - T8.0 — Skeleton + launch — framework + entry-point lock; localhost page proves server → DB read — **done Session 26**
  - T8.1 — Browse one product — picker over `(model_code, year)` + `inspect-product` rendered as colored HTML (markers wrapped in spans); hub → browse wired via `st.session_state["view"]` — **done Session 27**
  - T8.2 — Dashboard hub — 4 destination buttons + 4th health stat (days-since-refresh) + stub routes wired — **done Session 28**
  - T8.3 — Compare side-by-side — multiselect over `(model_code, year)` + vendor / segment / status filter bar; HTML grid (products as columns, fields as rows) over the union of `views.orchestrator.all_field_paths` across selected products, section-grouped — **done Session 29**
  - T8.4 — Find products where… — single-field filter playground: section → field cascade over union of `all_field_paths` (offering indices collapsed to `*`); operators `= / contains / ≥ / ≤ / is set / is empty / vendor doesn't publish`; per-product result blocks listing every matching cell with provenance marker; marker palette + path resolver promoted to `ui/_markers.py` at rule-of-three — **done Session 30**
  - T8.5 — Review queue triage — sidebar list + main-panel detail; existing-vs-candidate diff with provenance markers + four action buttons (`accept_candidate` / `kept_existing` / `manual_override` / `dropped`); `new_chip_unverified` rows show only the valid actions; manual-override form gated behind expander with optional JSON-literal mode. `cli/resolve.py` refactored to expose `resolve_row(conn, …)` as a pure-library handler; UI + CLI now share one write path. **First UI write path** — read-only invariant from T8.0–T8.4 ends here — **done Session 31**
  - T8.6 — Manual-edit a cell — product selectbox + section/field cascade over the union of `all_field_paths` (offering indices collapsed to `*`, with an offering-index selectbox when applicable) + value text input (with JSON-literal toggle) + status radio + note + entered-by override; current-value preview line + post-save before/after diff banner. `cli/manual_edit.py` refactored to expose `manual_edit_cell(conn, …)` per the T8.5 precedent; UI + CLI share one write path. Hub split into "Explore" (3 read screens) + "Curate" (review queue + manual-edit, with the third slot reserved for T8.7 refresh trigger) — **done Session 32**
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
