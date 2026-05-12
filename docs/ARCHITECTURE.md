# Architecture — System Design

For project scope and policy, see [`README.md`](../README.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

---

## Overview

Four parts:

1. **SQLite database** — three core tables (`cpu_catalog`, `gpu_catalog`, `products`) plus one operational table (`review_queue`). Per-cell provenance is bundled with each value as JSON.
2. **Bridge layer** — Python modules that take `scrapers-lib`'s text output, decode each vendor's idioms, and emit candidate product records. One module per vendor.
3. **Ingestion runner** — orchestrates fetch → parse → catalog-resolve → diff → write-or-queue.
4. **CLI helpers** — the operational surface for refresh, conflict resolution, and manual entry. The Phase 2 UI (see [§UI layer](#ui-layer-phase-2)) sits on top of these helpers; the helpers are the only writers to the DB.

---

## Database

### Engine

SQLite, one file (`competitive.db`), inspected via DB Browser for SQLite. All writes go through Python helpers — DB Browser is for reading and ad-hoc SQL queries, not editing.

### Tables

#### `cpu_catalog`
One row per CPU model. Primary key: `model` (string).
Columns map directly to [`DATA_MODEL.md`](DATA_MODEL.md#cpu-catalog) — each column carries a provenance bundle (see below).

#### `gpu_catalog`
One row per GPU model. Primary key: `model` (string). Same provenance pattern.

#### `products`
One row per product. Composite primary key: `(model_code, year)`.

Each column corresponds to a DATA_MODEL field. Storage:

- **Scalar fields** (`memory_max_gb`, `wifi_standard`, `width_mm`, etc.) — stored as a JSON object: `{value, ...provenance}`.
- **List-of-offerings fields** (`cpu_offerings`, `boards`, `display_offerings`, etc.) — stored as a JSON array. Each element is itself a structured object whose leaf-cells each carry their own provenance bundle.
- **Plain-scalar identity columns** (`model_code`, `year`, plus the Lenovo merge columns `family_code` and `source_model_codes` — added Stage 7 T7.0a) — stored as plain TEXT/INTEGER, no provenance bundle. `family_code` is the canonical family identifier (e.g. `legion-pro-5-16-gen-10`); `source_model_codes` is a JSON-array-as-TEXT of the per-vendor machine codes that merged into this product (e.g. `["16IRX10H", "16AHP10"]`). Both NULL for non-Lenovo rows and for legacy Lenovo rows until backfilled via `backfill-lenovo-families`.

#### `review_queue`
Operational table for unresolved items.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `product_model_code` | TEXT | |
| `product_year` | INTEGER | |
| `field_path` | TEXT | Dot/index path: `memory_max_gb`, `boards.0.gpus`, `display_offerings.1.nits_peak`, or bare offering column (`camera_offerings`) for list-level value_disagreement |
| `conflict_type` | TEXT | `value_disagreement` / `low_confidence_extraction` / `new_chip_unverified` / `year_inferred` |
| `existing_value` | JSON | Nullable |
| `existing_provenance` | JSON | Nullable |
| `candidate_value` | JSON | |
| `candidate_provenance` | JSON | |
| `detected_at` | TIMESTAMP | |
| `resolved_at` | TIMESTAMP | Nullable — null = unresolved |
| `resolution` | TEXT | `kept_existing` / `accepted_candidate` / `manual_override` / `dropped` |
| `resolution_value` | JSON | Used when resolution = `manual_override` |
| `resolver_note` | TEXT | Free-form |

---

## Provenance shape

Every cell carries a provenance bundle. Two shapes.

**Scraped cell:**
```json
{
  "value": "Wi-Fi 7",
  "source_url": "https://www.dell.com/...",
  "captured_at": "2026-05-06T14:32:11Z",
  "scraper_id": "dell.fetch_dell_product",
  "status": "verified"
}
```

**Manual cell:**
```json
{
  "value": 600,
  "source_note": "DisplayMate review 2026-04",
  "entered_by": "swarnim",
  "entered_at": "2026-05-06T14:32:11Z",
  "status": "vouched"
}
```

**Status values:**
- Scraped: `verified` / `needs-review` / `vendor-doesn't-publish`
- Manual: `vouched` / `needs-review`

**For list-of-offerings fields**, each leaf within each offering carries its own bundle independently. Example: `display_offerings[1].nits_peak` and `display_offerings[1].refresh_rate_hz` can have different sources, timestamps, and statuses.

**Empty vs. vendor-doesn't-publish:**
- Empty (never written): the cell is absent. No bundle.
- Vendor-doesn't-publish: the cell carries a bundle with `value: null` and `status: "vendor-doesn't-publish"`. Records that the scraper checked.

---

## Bridge layer

One module per vendor — vendor structures are too divergent for a unified parser.

```
bridge/
├── dispatcher.py    # routes a ProductSnapshot to the right parser by snapshot.source
├── helpers.py       # shared utilities: unit parsing, name decomposition, tier derivation
├── types.py         # CandidateProduct (in-memory shape, mirrors DATA_MODEL with bundles attached)
├── dell.py
├── hp.py
├── lenovo.py
└── asus.py
```

### Per-vendor parser

Each parser:
1. Takes a `ProductSnapshot` from `scrapers-lib`.
2. Reads `snapshot.specs: dict[str, str]` and decodes that vendor's idioms:
   - **Dell** — flat regex extraction over the techspecs payload.
   - **HP** — multi-line spec values; line 0 → `tier: base`, additional lines → `tier: optional`.
   - **Lenovo** — walks hierarchical `level1 > level2 > level3` path keys.
   - **ASUS** — section-grouped h2 titles; per-SKU variants newline-joined.
3. Stamps each cell with a scraped provenance bundle derived from `snapshot.url`, `snapshot.fetched_at`, and the scraper ID.
4. Returns a `CandidateProduct` (in-memory only — no DB write).
5. If a cell cannot be extracted confidently, the parser emits it with `status: needs-review` so the runner can route it to the queue. Uncertain extractions never silently land in the DB.

### What the bridge does NOT do

- Touch the database.
- Resolve conflicts.
- Auto-add catalog rows.
- Decide what to overwrite.

Those are the runner's job.

---

## Ingestion runner

Single orchestrator: `ingest/runner.py`. CLI entry: `refresh`.

### Sequence

1. **Receive command** (e.g., `refresh --brand dell --model alienware-m18` or `refresh --all`).
2. **Fetch:** call `scrapers-lib`'s registered fetcher for the brand → `list[ProductSnapshot]`.
3. **For each snapshot:**
   1. Dispatch to vendor parser → `CandidateProduct`.
   2. **Catalog-resolve:**
      - Each CPU model name in `candidate.cpu_offerings` looked up in `cpu_catalog`. If missing → insert a stub row (model + brand parsed from name; remaining columns null) with `status: needs-review` and enqueue a `new_chip_unverified` review row.
      - Same flow for each GPU model name in `candidate.boards[*].gpus` against `gpu_catalog`.
      - **Stub-only as the default — amended Session 8.** When a laptop spec page surfaces chip-level data (e.g., ASUS publishes NPU TOPS, Lenovo publishes per-CPU cores/clocks/process-node), the bridge attaches them to `candidate.cpu_chip_specs` and the runner seeds the matching `cpu_catalog` cells. Per-cell rule: empty → write; `needs-review` row + match → no-op; `needs-review` row + diff → overwrite + queue `value_disagreement`; `vouched` row + diff → keep existing + queue `value_disagreement`. See DATA_MODEL.md §CPU Catalog for vendor coverage.
   3. **Diff against existing product row:**
      - No existing row → insert candidate.
      - Field empty in DB → write candidate cell.
      - Field matches candidate → refresh `captured_at`, no other change.
      - Field differs from candidate → enqueue `value_disagreement`; existing value untouched.
      - Candidate cell marked `needs-review` → enqueue `low_confidence_extraction`; do not write.
4. **Print summary:** refreshed N, conflicts M, new chips K, low-confidence L.

### Lenovo merge ingest (Stage 7 T7.0a)

Lenovo's PSREF gives each Intel / AMD architecture cousin its own machine code (e.g. `16IRX10H` vs `16AHP10`) under one underlying product family (`Legion Pro 5 16 Gen 10`). The merge ingest path collapses those into a single row keyed by `family_code`.

1. **Bridge** (`bridge/lenovo.py`): `_derive_lenovo_family_and_arch` parses the Lenovo title to derive `family_code` (canonical kebab slug, e.g. `legion-pro-5-16-gen-10`) and per-board `arch_marker` token (`IRX` / `IAX` / `ADR` / `ARX` / `AFR`). The H suffix (Hybrid / discrete-graphics indicator) is dropped from `arch_marker` but the original code is preserved in `source_model_codes`. The parser uses a known-line allowlist (`_LENOVO_FAMILY_LINE_PREFIXES`) — when Lenovo ships a new product line, the allowlist needs updating. Non-Lenovo bridges leave `family_code` and `source_model_codes` unset.
2. **Grouping coercion** (`cli/refresh.py`): when a candidate has `family_code`, the grouping layer coerces `model_code` to `family_code` so candidates from the same family group together regardless of source machine code. Non-Lenovo (and legacy Lenovo without `family_code`) take the legacy path.
3. **Multi-candidate merge** (`ingest/runner.py::_merge_candidates`): groups boards by `(label, arch_marker)` rather than label alone, unions `source_model_codes` across candidates, asserts all non-None `family_code`s agree.
4. **Existing-row premerge** (`ingest/runner.py::_premerge_lenovo_existing_row`): handles "AMD ingest arrives after Intel row already exists" — unions boards + `source_model_codes` into the existing row before the normal diff path runs, so the second architecture appends rather than queueing every cell as a `value_disagreement`.

Note: `products.model_code` has no FK references elsewhere — using `family_code` as the canonical PK value is safe.

### Atomicity

Each `(snapshot → diff → writes + queue inserts)` runs inside a single SQLite transaction. Crash mid-refresh = clean rollback.

---

## CLI helpers

All helpers under `cli/`. Each is a thin wrapper over an underlying Python function — the future UI calls those same functions, not the CLI. Single source of truth.

### `refresh`
Ingestion. See [Ingestion runner](#ingestion-runner).

Three URL-resolution modes: per-vendor `DEFAULT_*_URL_TMPL` (first-time ingest, slug as `--model`); explicit `--url` (first-time ingest, exact URL); `--from-db` (returning refresh — reads each product's stored `source_url` from bundle provenance, bypassing templates, and loops fetch across every distinct URL on the row so Lenovo Intel+AMD merged products refresh both sides).

```
python -m competitive_database refresh --brand dell --model alienware-m18
python -m competitive_database refresh --brand dell --model aa18250 --from-db
python -m competitive_database refresh --all
```

### `resolve`
Resolves a `review_queue` row in a single transaction.

```
python -m competitive_database resolve --id 17 --action accept_candidate
python -m competitive_database resolve --id 17 --action kept_existing
python -m competitive_database resolve --id 17 --action manual_override --value 600 --note "..."
python -m competitive_database resolve --id 17 --action dropped
```

Updates the products table (when applicable), marks the queue row resolved with timestamp + resolution, writes the resolver note.

For `new_chip_unverified` rows the dispatch routes off `candidate_value` (which carries `{"table", "model", "value"}` pointing at the catalog stub created at ingest time) rather than `field_path` — `accept_candidate` flips that row's `catalog_status` from `needs-review` to `vouched`; `dropped` resolves the queue row without touching the catalog. `kept_existing` and `manual_override` are rejected (`existing_value` is always NULL for these rows). This sidesteps the path parser entirely, handling both depth-3 `cpu_offerings.N.model` and depth-4 `boards.N.gpus.M` shapes uniformly.

### `manual-edit`
Writes a manual cell with provenance scaffolding handled automatically.

```
python -m competitive_database manual-edit \
  --product alienware-m18-2026 \
  --field display_offerings.0.nits_peak \
  --value 600 \
  --note "DisplayMate review 2026-04"
```

Sets value, `status: vouched`, `entered_by` from env, `entered_at` to now.

### `find-empty`
Lists empty and `vendor-doesn't-publish` cells per product — the manual-fill backlog surface.

```
python -m competitive_database find-empty --product alienware-m18-2026
python -m competitive_database find-empty --all
```

### `find-conflicts`
Lists unresolved review queue rows.

```
python -m competitive_database find-conflicts
python -m competitive_database find-conflicts --product alienware-m18-2026
```

### `db-init`
Bootstraps the SQLite file with schema + indexes.

### `inspect-product`
Prints the orchestrated, status-marked spec dump for one product. Implementation: `cli/inspect_product.py` calls `views/load.py` to decode the row + catalogs, then `views/orchestrator.py` to render the 16 category sections in fixed order. Read-only — touches `products`, `cpu_catalog`, `gpu_catalog`.

```
python -m competitive_database inspect-product alienware-m18-2026
python -m competitive_database inspect-product rog-zephyrus-g16-2026 --year 2026
```

### `audit-normalize`
Surfaces normalization gaps across products: walks every row in `products`, collects the distinct value strings written at each fillable cell path (via `views/orchestrator.all_field_paths`), and (by default) prints only paths where 2+ distinct values appear — e.g., `Wi-Fi 7` vs `WiFi 7`. Implementation: `cli/audit_normalize.py`. Read-only — touches `products` plus the `views/` read path.

```
python -m competitive_database audit-normalize
python -m competitive_database audit-normalize --all
python -m competitive_database audit-normalize --strings-only
```

### `backfill-lenovo-families`
One-time cleanup for legacy Lenovo rows ingested before T7.0a. Reads every Lenovo row with `family_code IS NULL`, re-derives `family_code` + per-board `arch_marker` from the bundles already on the row (`vendor_full_name`, falling back to brand/segment/status `source_url`), then either updates the row in place (singleton family) or merges multiple rows into one (multi-row family — reuses `_merge_boards` / `_merge_offerings` / `_enqueue` from `ingest/runner.py`, unions `source_model_codes`). Idempotent: rerunning after a clean run is a no-op. Implementation: `cli/backfill_lenovo_families.py`.

```
python -m competitive_database backfill-lenovo-families
python -m competitive_database backfill-lenovo-families --db path/to/competitive.db
```

---

## Repo layout

```
competitive-database/
├── README.md
├── docs/
│   ├── PRD.md
│   ├── DATA_MODEL.md
│   ├── ARCHITECTURE.md        # this file
│   ├── SESSION_LOG.md
│   ├── TASKS.md
│   └── VIEWS.md               # view-layer format choices
├── pyproject.toml
├── competitive_database/
│   ├── __init__.py
│   ├── __main__.py            # CLI dispatch
│   ├── db/
│   │   ├── schema.sql
│   │   ├── connection.py
│   │   └── helpers.py         # read/write provenance bundles
│   ├── bridge/
│   │   ├── dispatcher.py
│   │   ├── helpers.py
│   │   ├── types.py
│   │   ├── dell.py
│   │   ├── hp.py
│   │   ├── lenovo.py
│   │   └── asus.py
│   ├── ingest/
│   │   ├── runner.py
│   │   └── catalog_resolve.py
│   ├── views/
│   │   ├── __init__.py
│   │   ├── formatting.py        # shared markers + leaf helpers
│   │   ├── load.py              # per-product DB read path
│   │   ├── orchestrator.py      # composes per-category views
│   │   ├── cpu.py
│   │   ├── boards.py
│   │   ├── memory.py
│   │   ├── storage.py
│   │   ├── display.py
│   │   ├── keyboard.py
│   │   ├── camera.py
│   │   ├── audio.py
│   │   ├── network.py
│   │   ├── io.py
│   │   ├── battery.py
│   │   ├── adapter.py
│   │   ├── thermals.py
│   │   ├── dimensions.py
│   │   ├── weight.py
│   │   └── design.py
│   └── cli/
│       ├── _paths.py            # shared dotted-path helpers (incl. _PLAIN_OFFERING_LEAVES)
│       ├── db_init.py
│       ├── refresh.py
│       ├── inspect_product.py
│       ├── resolve.py
│       ├── manual_edit.py
│       ├── find_empty.py
│       ├── find_conflicts.py
│       ├── audit_normalize.py
│       └── backfill_lenovo_families.py   # one-time Lenovo family_code backfill
├── tests/
│   ├── fixtures/              # sample ProductSnapshot JSON per vendor
│   ├── bridge/
│   ├── ingest/
│   └── cli/
└── competitive.db             # gitignored
```

---

## View layer

Single source of truth for human-readable product presentation. The `inspect-product` CLI uses it today; the future admin UI sits on the same module. Detailed format choices are captured in `VIEWS.md`; this section is the architectural summary.

### Module layout

- **`views/formatting.py`** — six visible markers (`[verified]`, `[?]`, `[—]`, `[m]`, `[empty]`, `[partial]`), a `marker_for_bundle` mapper, an `aggregate_markers` collapser, a `display_value` stringifier, and a `format_leaf` one-line renderer. Plus `render_scalar_section` for the all-scalar categories.
- **`views/load.py`** — per-product DB read path. Decodes every column on the products row into either a bundle dict, a list-of-offerings, or a plain PK value. Plus bulk loaders for `cpu_catalog` and `gpu_catalog`. The view layer owns its own read path; the cell-bundle helpers in `db/helpers.py` work column-by-column and aren't shaped for whole-row reads.
- **`views/<category>.py`** — one render module per category (16 total). Each takes the decoded `product` dict (plus `cpu_catalog` / `gpu_catalog` for chip-enriched categories) and returns a string. Sections that are wholly empty render as `Heading: [empty]`. Each module also exposes `field_paths(product) -> list[(field_path, display_label)]` — the registry of fillable cells in that section, used by `find-empty` so the missing-cell output groups by the same 16 sections as `inspect-product`.
- **`views/orchestrator.py`** — composes the per-category renders in a fixed order: identity, then compute (CPU, boards), memory/storage, display, peripherals (keyboard, camera, audio), connectivity (network, I/O), power (battery, adapter), physical (thermals, dimensions, weight, design). Also exposes `all_field_paths(product) -> list[(section_name, field_path, display_label)]` — the central registry over all 16 section helpers (plus identity), in render order.
- **`cli/inspect_product.py`** — thin subcommand. Positional `model_code`, optional `--year` disambiguator (errors if a model_code has multiple yearly variants and `--year` is unset), `--db` override. Reconfigures `sys.stdout` to UTF-8 before printing so the em-dash marker `[—]` and the `×` in resolution strings render cleanly on Windows (default cp1252 mangles them).

### Section conventions (load-bearing)

- **Empty sections show their heading.** `Audio: [empty]` rather than hiding the section. Makes gap-spotting a one-line scan.
- **Single-offering categories drop the `Offering 1:` prefix.** A laptop with one CPU option inlines its CPU directly under `CPU:`. Categories with 2+ offerings keep numbered sub-headers and indent leaves one level deeper.
- **Identity block always shows all six identity fields.** Including `[empty]` for unset (`status` / `segment` are typical empties for vendors that don't publish them on the spec page). Confirmed against header-noise concerns; gap-spotting wins.
- **Catalog spec lines render without per-line markers.** `cpu_catalog` / `gpu_catalog` spec columns (cores, NPU TOPS, architecture, etc.) are plain TEXT — no per-cell provenance bundle. The row-level `catalog_status` is shown once per offering; the `brand` bundle (the only bundled catalog column) keeps its own marker.
- **`storage_slots` is offerings-shaped.** A list of slots, each with a `gen` leaf for PCIe generation. Lives in the `_OFFERINGS_FIELDS` set in `views/load.py` alongside `cpu_offerings`, `boards`, `display_offerings`, `battery_offerings`, `keyboard_offerings`, `adapter_offerings`, `camera_offerings`.

### How the marker logic works

`marker_for_bundle` decides each leaf's marker from one bundle dict (or `None`):

- `None` → `[empty]`. Cell never written.
- `entered_by` key present → `[m]`. Manual cell, regardless of `vouched`/`needs-review` sub-status.
- `status == "verified"` → `[verified]`.
- `status == "vendor-doesn't-publish"` → `[—]`.
- `status == "needs-review"` (or any unknown status) → `[?]`.

`aggregate_markers` collapses a list of leaf markers to one category-level marker — all-same → that marker, mixed → `[partial]`. Used sparingly; per-leaf markers are usually preferred over aggregating, since they preserve full information.

---

## UI layer (Phase 2)

Scoped Session 25 (2026-05-12). Phase 2 promotes the `inspect-product` view + the CLI write paths to a clickable surface. Same plumbing, browser front end. Scope and workflow shape live in [`PRD.md` §Phase 2 — UI](PRD.md#phase-2--ui-stage-8); this section covers how it's built.

### Runtime

Browser tab on localhost. A single launch command starts a local server bound to the loopback interface only; the user's default browser opens automatically. Nothing hosted, nothing leaves the machine. Bookmarkable but not exposed beyond `localhost`.

Standing preference: local-first. Supabase / hosted Postgres explicitly rejected.

### File layout (planned)

```
competitive_database/
└── ui/
    ├── __init__.py
    ├── __main__.py            # launch entry point
    ├── hub.py                 # dashboard landing
    ├── browse.py              # product profile view
    ├── compare.py             # side-by-side grid
    ├── find.py                # filter playground
    └── queue.py               # review-queue triage
```

One module per screen, mirroring the per-vendor module pattern in `bridge/`. No duplicate marker logic — shared rendering primitives live next to the existing `views/` helpers.

### What the UI reuses (no new write paths)

- **Read path:** `views/orchestrator.render_product`, `views/orchestrator.all_field_paths`, `views/load.py`. Markers, section order, and empty-section rules from `VIEWS.md` carry over unchanged.
- **Write path:** `ingest/runner.py` (refresh), `cli/resolve.py`'s underlying handlers (queue resolution dispatch, including the catalog-vouching dispatch off `candidate_value` shipped Session 23), `ingest/catalog_resolve.py` (catalog stub helpers), `cli/_paths.py` (dotted-path parsing for `manual-edit`).

The architectural invariant from §Forward compatibility holds: all writes route through helper functions. The UI calls those same functions. No DB-level coupling to a UI framework; swapping frameworks later is a rendering change, not a data change.

### Open implementation decisions (first Stage 8 coding session)

- **Web framework.** Local-first Python options: Streamlit (least code, opinionated layout), FastHTML / Flask + HTMX (more control, more code), Dash (data-app strong). Decide once the queue-triage screen is sketched against each.
- **Launch entry point.** Either follow today's CLI pattern (`python -m competitive_database.ui`) or wire `[project.scripts]` (`competitive-ui`, with a one-time `pip install -e .` re-run). Pick one and stay consistent.
- **Refresh progress streaming.** Server-sent events vs polling vs page-reload-after-done. Framework-dependent.
- **Testing strategy.** Action handlers reuse existing `ingest/*` modules, so the 273-test suite already covers writes; UI tests focus on rendering + form validation.

---

## Forward compatibility

Preserved without restructuring:

- **History layer.** Adding `products_history` (append-only) later is non-breaking. Provenance bundles already carry enough signal that a snapshot is reconstructable.
- **Hosted Postgres migration.** Schema is plain SQL; bundles are JSON (Postgres has native JSONB). Migration = export/import + type adjustment.
- **Admin UI.** All edits route through helper functions. UI calls the same functions. No DB-level coupling to a UI framework.
- **Catalog chip-spec auto-population.** A future job walks rows where `status = needs-review` and fetches from Intel ARK / NVIDIA. No schema change.
- **Acer / MSI bridges.** Drop in `bridge/acer.py` and `bridge/msi.py` once `scrapers-lib` supports them. Dispatcher routes by `snapshot.source`. No other changes.

---

## Trade-offs explicitly accepted

- **Provenance bundled as JSON per cell.** Plain-SQL queries on values require SQLite JSON functions (`json_extract`). Mitigated by all reads going through helpers, which decode bundles transparently.
- **DB Browser is read-only in practice.** Editing JSON-bundled cells in a spreadsheet view is ugly. CLI helpers are the editing surface.
- **CLI before UI.** Phase 1 has no UI. The CLI helpers are the manual surface; the UI is the same plumbing with a different front end, deferred.
- **Stub-only catalog auto-add (default).** New CPU/GPU rows are stubbed; chip specs filled manually or by a future job. Amended Session 8: where the laptop spec page itself surfaces chip-level fields (NPU TOPS, cores, clocks, architecture, process node), the bridge captures them and the runner seeds the matching `cpu_catalog` cells under a per-cell write/queue rule (see Ingestion runner §Catalog-resolve).
- **No history layer.** Resolved values overwrite. The surviving value's provenance bundle is preserved; the prior bundle is not. Adding history later is non-breaking but explicit work.

---

## Locked decisions (this session)

- **Provenance shape:** bundled with each value as JSON (one shape per cell).
- **Bridge layer:** one module per vendor + shared helpers. No universal parser.
- **Ingestion flow:** CLI command → fetch → vendor parse → catalog-resolve → diff → write-or-queue. Single transaction per snapshot.
- **Catalog auto-add:** stubs only. No Intel ARK / NVIDIA fetch in Phase 1.
- **Conflict resolution:** CLI helper (`resolve`) built from day one.
- **Manual entry:** CLI helpers (`manual-edit`, `find-empty`) built from day one.
- **All writes go through helpers.** Future UI sits on top of helpers — same plumbing.
