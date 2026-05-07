# Session Log

Append-only log of brainstorming and design sessions. Each entry captures what was discussed, what was decided, where we left off, and pickup pointers for the next session.

Newest sessions at the top.

---

## Session 3 — 2026-05-07

**Goal:** Outline `ARCHITECTURE.md`. Walk through the open design questions. Propose `TASKS.md`.

**Outcome:** `ARCHITECTURE.md` and `TASKS.md` written. Six design questions resolved (the original five plus a sixth — view layer — surfaced mid-session). View layer added as a first-class concern of the data layer, not deferred to UI.

### What we covered

**Six design decisions locked:**

- **Provenance shape — bundled JSON per cell.** Every cell stores `{value, source_url|source_note, captured_at|entered_at, scraper_id|entered_by, status}` together. List-of-offerings fields carry per-leaf bundles. Trade-off accepted: plain-SQL queries on values require SQLite JSON functions; mitigated by all reads going through helpers.
- **Bridge layer — one module per vendor.** Vendor structures (Dell flat regex, HP multi-line line-0-is-base, Lenovo hierarchical path keys, ASUS section-grouped) are too divergent for a unified parser. Per-vendor module + shared helpers.
- **Ingestion flow.** CLI command → scrapers-lib fetch → vendor parse → catalog stub auto-add → diff → write-or-queue. Single SQLite transaction per snapshot.
- **Catalog auto-add — stub only.** New CPU/GPU rows get `model + brand` + `status: needs-review`. No Intel ARK / NVIDIA chip-spec fetch in Phase 1; deferred.
- **Resolution + manual entry — CLI helpers from day one.** `resolve`, `manual-edit`, `find-empty`, `find-conflicts`. Future UI sits on top of the same helper functions.
- **View layer — separate `views/` module, first-class.** One render function per category. `inspect-product` CLI renders through views. UI later renders through the same views (string render now; structured-record render added when UI lands). Single source of truth for human-readable presentation.

**Phasing locked.** Data layer (full) → structured validation pass → UI (Phase 2). The view layer's specific value: validation surfaces what UI will eventually show, so visual-layer bugs surface during validation, not after UI is built.

**TASKS.md stages — seven stages:** foundation → Dell end-to-end → other vendor parsers → view layer + `inspect-product` → other CLI helpers → validation pass → polish. Each stage gates the next.

### Course corrections worth remembering

- **UI was missing from the original task plan.** User noticed only "admin UI" was tagged deferred — no UI surface in Phase 1 at all. Confirmed phasing intent: data layer first, validate via CLI + DB Browser, THEN UI. The user's reasoning ("UI on bad data papers over the bug") is the correct architectural justification. Don't apologize for the deferral; it's the right order.
- **View layer was almost missed as a concept.** The user surfaced it: `inspect-product` should show what the UI eventually shows (e.g., "DDR5 5600 MT/s, 2 slots, max 64 GB" instead of three raw rows). Architectural concern, not a CLI ergonomic concern. Result: views are now a first-class module, with a planned promotion path from string-render today to structured-record-render when UI lands. Same module, additional functions, no rewrite.
- **`scrapers-lib` audit memory was partially stale.** Live verification confirmed Tier 2 fetchers return `list[ProductSnapshot]` (not single — vendors expose multiple tiles/variants per page). Bridge handles fan-out. Snapshot carries `url`, `fetched_at`, `raw` blob; per-cell provenance is bridge's responsibility. HP coverage figure of "~12 fields" was a snapshot of an older state — current is 23–26 via async PDP merge.
- **Helpers are a discipline, not a convenience.** Resolution, manual entry, view rendering — all go through helper functions. The future UI calls those same functions. Bypassing the helpers (even for "small" cases) breaks the single-source-of-truth promise that makes UI cheap later.

### Open at end of session

- Stage-by-stage implementation. Stage 1 (foundation) is the natural starting point.
- `VIEWS.md` (or section appended to `ARCHITECTURE.md`) — non-obvious format choices documented as the views are written. Created during Stage 4.
- Acer / MSI parsers and catalog chip-spec auto-fetch remain deferred; not blocking.

### Where we left off (pickup pointers for next session)

- `README.md`, `PRD.md`, `DATA_MODEL.md`, `ARCHITECTURE.md`, `TASKS.md`, `SESSION_LOG.md` are all updated and consistent.
- **Recommended next-session priority:** Stage 1 (foundation). Bootstrap the repo, write `db/schema.sql`, build the provenance-bundle read/write helpers in `db/helpers.py`. No more design discussion — straight to implementation. Unless the user wants to revisit a locked decision, the design is settled.
- Memory updated: architecture decisions saved as a project memory.

---

## Session 2 — 2026-05-06

**Goal:** Lock the DB engine; audit `scrapers-lib`; close outstanding policy on vendor coverage, bridge-layer location, and source scope.

**Outcome:** Engine locked (SQLite). `scrapers-lib` audited (architecture + Tier 2 output ground-truthed). Four new policies locked. Schema unchanged. Ready to outline `ARCHITECTURE.md`.

### What we covered

**DB engine — locked: SQLite.**
- Reasoning: solo use, manual quarterly refresh, hundreds of products max — well within SQLite's lane. Zero setup, one file, DB Browser for SQLite for spreadsheet-style cell editing.
- Trade-off accepted: JSON-shaped fields edit as JSON text in dev tools; small admin UI is the eventual fix, deferred.
- Rejected: Supabase (cloud), Postgres-local (setup friction without offsetting benefit), MongoDB (weak SQL filters), Airtable/Notion (can't store nesting or per-cell provenance).

**`scrapers-lib` audit — done.** Two passes: architecture summary + Tier 2 ground-truth.
- Implemented in scrapers-lib: Tier 1 (Reddit, RSS, articles, YouTube, BestBuy API — *not relevant* to this DB), Tier 2 (Dell, HP, Lenovo, ASUS), Tier 3 (BestBuy, Amazon retailer — *not relevant*).
- Deferred upstream: Acer, MSI Tier 2 scrapers.
- Output shape: `ProductSnapshot` with `specs: dict[str, str]` — text per category. No structured sub-objects, no per-cell provenance, no catalog FKs. Bridge layer required.
- Per-vendor format observed at audit time: Dell formal / regex-friendly (~20 fields). HP gaming PDPs reach 20+ fields after a recent async-reliability update (audit's "12-only" figure was stale). Lenovo hierarchical 3-level path keys (40+ fields). ASUS semi-structured (~20 fields).
- HP convention: multi-line spec values where line 0 = configured default, rest = upgrade options. Bridge must preserve ordering — maps to `tier: base/optional`.
- Granularity differs: Dell/HP per-tile (3 SKUs/page), Lenovo/ASUS per model family. Reconciliation = bridge-layer responsibility.

**Policies locked this session:**
- **Vendor coverage rule.** Build for all 6 brands. Missing scraper coverage = empty rows for that brand. Not a project block.
- **Bridge-layer location.** All project-specific parsing and transformation lives in `competitive-database`. `scrapers-lib` is only extended when the change is universally useful.
- **Source scope.** Tier 2 manufacturer pages only. Tier 1 (mentions) and Tier 3 (retailer pages) ignored for this DB.
- **No pre-locked manual fields.** Every DATA_MODEL field is scrape-eligible. Scraper extracts what it can; whatever's empty is the manual surface at runtime. Avoids locking out future scraper improvements.

### Course corrections worth remembering

- **Local-only, not Supabase.** Supabase pitched (admin-UI ergonomics were the appeal); user rejected — "must be local to begin with." Future engine recommendations should default to local-first unless cloud is invited.
- **HP coverage mis-stated.** I quoted the audit's "HP ~12 categories" figure; user corrected — recent `scrapers-lib` async-reliability update lifts HP gaming PDPs to 20+. The audit was a snapshot of an older state. Don't re-cite specific coverage numbers without verifying current.
- **Don't pre-lock fields as "manual-only."** I proposed marking brightness/HDR/thermals as manual-only based on the audit's "structurally absent" finding. User pushed back: those are runtime states, not design-time decisions. The provenance + status flag system already handles "vendor doesn't publish." Pre-locking creates technical debt against future scraper improvements and conflates runtime state with schema labels.

### Open at end of session

- `ARCHITECTURE.md` not yet written. Bridge-layer design is the meatiest piece (cell-provenance shape: embedded JSON vs. sidecar table; vendor-keyed parsing modules; ingestion + review-queue mechanics).
- `TASKS.md` not yet written.
- `scrapers-lib` Acer/MSI Tier 2 — upstream deferral; track but don't block.

### Where we left off (pickup pointers for next session)

- README, DATA_MODEL, PRD, SESSION_LOG updated and consistent. Memory updated: SQLite engine, four new policies, two new feedback memories (`local_first`, `no_premanual_fields`).
- **Recommended next-session priority:** Outline `ARCHITECTURE.md`. Topics: SQLite schema (cell-provenance design choice — embedded JSON vs. sidecar table), bridge-layer module structure (per-vendor parsers + universal extractors), ingestion flow (manual button → scrapers-lib fetch → bridge parse → review queue or DB), review-queue mechanics, manual-entry surface for fields the scraper didn't fill.

---

## Session 1 — 2026-05-05 to 2026-05-06

**Goal:** Kickoff. Define the data layer for the competitive gaming-laptop spec database — scope, data model, policy, schema, initial docs.

**Outcome:** Schema-ready. Project docs `README.md`, `DATA_MODEL.md`, `PRD.md`, and `SESSION_LOG.md` created.

### What we covered

**Foundational scope (locked):**
- Six brands: Dell, HP, Lenovo, ASUS, Acer, MSI. US sites only. Gaming laptops only.
- Data layer first; UI / chatbot are explicitly separate later efforts.
- No SKU-level configurations, no pricing, no OS variants, no release dates, no color / finish options, no history layer (current state only).

**Data model — load-bearing decisions:**
- Row = product, identified by **(model code, year)**. Vendor full name scraped as-is and decomposed into brand / sub-brand / series / model code / year.
- Multi-option fields stored as **lists of offerings**, not fixed slots — correcting the original Excel's CPU 1/2/3 / Display 1/2 fixed-column pattern.
- Two **catalog tables**: CPU and GPU only. Other commodities store specs directly on the product.
- Catalogs populated **deterministically** from Intel ARK / AMD / NVIDIA spec pages (LLM-derivation rejected as unreliable).
- Catalog references by **model name string** as the foreign key.
- Unknown chips → **auto-add to the catalog with `needs-review`** status; scrape proceeds.
- **Motherboard variants are first-class entities** on the product. Each board carries TPP cap, GPU TGP cap, and a list of supported GPUs. Boards are 1:N with GPUs (one board supports multiple GPUs at a shared power class).

**Policy (locked):**
- Refresh = **manual button only**, ~quarterly cadence expected.
- **Per-cell provenance + status flag**, with separate shapes for scraped vs. manual cells.
- Scraped cells: `verified` / `needs-review` / `vendor-doesn't-publish`. Hard correctness bar — if extraction is uncertain, don't store; route to review queue.
- Manual cells: `vouched` (default) / `needs-review`. Self-check tool, not a multi-reviewer workflow.
- Conflicts route to a **review queue**, never silent overwrite, never silent manual-lock.

**Field walkthrough — all 16 categories locked.** Full schema is in `DATA_MODEL.md`. Categories: CPU, GPU + Power (boards), Display, Battery, Memory, Storage, Network, I/O, Adapter, Camera, Audio, Keyboard, Thermals, Dimensions, Weight, Design.

**Trade-offs explicitly accepted (named so future sessions can re-evaluate if they bite):**
- No per-CPU TDP variance tracked — single `cpu_tdp_max` per product.
- One `tgp_max` per board collapses per-GPU TGP variance within a single board.
- Display panels not catalog'd — vendors rarely publish panel models, so panels stored as spec bundles.
- `adapter_connector` is product-level, assuming uniform connector across adapter offerings.

### Course corrections worth remembering

These are moments where the user pushed back and the model was refined. Future sessions should remember:

- **CPU 1/2/3 as fixed slots → list of offerings.** User initially modeled CPUs as fixed columns. We surfaced the foot-guns (position is arbitrary; reorders look like data changes; queries become disjunctive over column variants) and switched to list-shaped storage. Display/visualization can still render as CPU 1/2/3 columns.
- **Motherboards are 1:N with GPUs, not 1:1.** Initial assumption was each board hosts a single GPU. User corrected: MB1 supports e.g. RTX 5070 Ti / 5080 / 5090 at one shared power class. The GPU + Power model was reshaped around this.
- **GPU TGP per (board, GPU) collapsed to per board.** Realistic per-GPU TGPs within a board (e.g., RTX 5090 at 175W vs RTX 5070 Ti at 140W on the same board) are NOT captured. Trade-off accepted in service of simplicity.
- **TASKS readiness — wrong direction.** Originally claimed `TASKS.md` was more ready than `PRD.md`. User correctly pointed out tasks flow FROM the PRD (what + why) and ARCHITECTURE (how). Right order: `SESSION_LOG` → `PRD` → `ARCHITECTURE` → `TASKS`.
- **DB engine implications for manual entry.** When proposing manual entry via JSON / CSV editing, user pushed back: we're building a real DB, so manual entry is a DB tooling decision (form UI / admin panel / GUI like DBeaver), not a file-editing operation. That makes it an architecture concern.

### Open at end of session

- **DB engine selection.** Recommended **PostgreSQL** (locally, then Supabase / Neon / AWS RDS for cloud). Not yet locked by the user.
- **`scrapers-lib` field coverage** — unknown until an audit pass.
- **Per-vendor publishability** — unknown until research across the six US vendor sites.

### Where we left off (pickup pointers for next session)

- `README.md`, `DATA_MODEL.md`, `PRD.md`, `SESSION_LOG.md` — written and committed as source of truth.
- `ARCHITECTURE.md` and `TASKS.md` — deferred. They depend on:
  1. DB engine choice locked.
  2. `scrapers-lib` audit complete.
- **Recommended next-session priorities, in order:**
  1. **Confirm DB engine + setup.** PostgreSQL recommended; Supabase suggested for non-technical setup with a built-in spreadsheet-style admin UI.
  2. **`scrapers-lib` audit** — Explore agent. Map current extractor coverage per vendor against the locked field list. Identifies gaps requiring new scrapers.
  3. **Per-vendor publishability research** — research agent across the six US vendor sites. Mark per field which vendors publish vs. require manual entry. Feeds the per-cell `vendor-doesn't-publish` status.
  4. Once 1–3 are done, write `ARCHITECTURE.md` and `TASKS.md`.

### Memory state

- `MEMORY.md` index lists three memories: user profile, project overview, data model decisions.
- `project_overview.md` carries scope and locked policy.
- `data_model_decisions.md` carries the full field-shape map and connective tissue.
- These memory files are **backups / pointers** — `README.md` and `DATA_MODEL.md` and `PRD.md` in this repo are the source of truth.
