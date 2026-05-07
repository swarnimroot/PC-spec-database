# Architecture — System Design

For project scope and policy, see [`README.md`](README.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

---

## Overview

Four parts:

1. **SQLite database** — three core tables (`cpu_catalog`, `gpu_catalog`, `products`) plus one operational table (`review_queue`). Per-cell provenance is bundled with each value as JSON.
2. **Bridge layer** — Python modules that take `scrapers-lib`'s text output, decode each vendor's idioms, and emit candidate product records. One module per vendor.
3. **Ingestion runner** — orchestrates fetch → parse → catalog-resolve → diff → write-or-queue.
4. **CLI helpers** — the operational surface for refresh, conflict resolution, and manual entry. A future UI sits on top of these helpers; the helpers are the only writers to the DB.

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

#### `review_queue`
Operational table for unresolved items.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `product_model_code` | TEXT | |
| `product_year` | INTEGER | |
| `field_path` | TEXT | Dot/index path: `memory_max_gb`, `boards.0.gpus`, `display_offerings.1.nits_peak` |
| `conflict_type` | TEXT | `value_disagreement` / `low_confidence_extraction` / `new_chip_unverified` |
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
      - **Stub-only:** chip specs (cores, NPU TOPS, etc.) are not auto-fetched. Manual or future job.
   3. **Diff against existing product row:**
      - No existing row → insert candidate.
      - Field empty in DB → write candidate cell.
      - Field matches candidate → refresh `captured_at`, no other change.
      - Field differs from candidate → enqueue `value_disagreement`; existing value untouched.
      - Candidate cell marked `needs-review` → enqueue `low_confidence_extraction`; do not write.
4. **Print summary:** refreshed N, conflicts M, new chips K, low-confidence L.

### Atomicity

Each `(snapshot → diff → writes + queue inserts)` runs inside a single SQLite transaction. Crash mid-refresh = clean rollback.

---

## CLI helpers

All helpers under `cli/`. Each is a thin wrapper over an underlying Python function — the future UI calls those same functions, not the CLI. Single source of truth.

### `refresh`
Ingestion. See [Ingestion runner](#ingestion-runner).

```
python -m competitive_database refresh --brand dell --model alienware-m18
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

---

## Repo layout

```
competitive-database/
├── README.md
├── PRD.md
├── DATA_MODEL.md
├── ARCHITECTURE.md            # this file
├── SESSION_LOG.md
├── TASKS.md                   # next deliverable
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
│   └── cli/
│       ├── refresh.py
│       ├── resolve.py
│       ├── manual_edit.py
│       ├── find_empty.py
│       └── find_conflicts.py
├── tests/
│   ├── fixtures/              # sample ProductSnapshot JSON per vendor
│   ├── bridge/
│   ├── ingest/
│   └── cli/
└── competitive.db             # gitignored
```

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
- **Stub-only catalog auto-add.** New CPU/GPU rows are stubbed; chip specs filled manually or by a future job. Backlog accepted for simplicity.
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
