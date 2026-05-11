# Competitive Database — Gaming Laptop Spec Catalog

A persistent, queryable database of competitor gaming-laptop specs from Dell, HP, Lenovo, ASUS, Acer, and MSI. Most fields auto-populate from public US vendor pages; the rest are manual. Every cell carries provenance and a status flag.

---

## Status

**Phase: Data layer + view layer + operational CLI — Stages 1–7 complete. Stage 6 (validation pass) closed in Session 12 (2026-05-08); Stage 7 (polish) closed in Session 19 (2026-05-11) — T7.0a, T7.0b, T7.0c, T7.0e, T7.1, T7.2, T7.3, T7.4 shipped; T7.0d deferred.** Foundation, schema, provenance helpers, all four Stage 3 vendor bridges, the Stage 4 view layer + `inspect-product` CLI, the Stage 5 operational helpers (`find-conflicts`, `find-empty`, `manual-edit`, `resolve`), the Stage 6 `audit-normalize` helper, and the Stage 7 `backfill-lenovo-families` helper are implemented and tested. 253/253 tests pass. The live DB carries 6 products across all 4 vendors (Dell ×2, HP ×1, Lenovo ×1, ASUS ×2). T6.1 closed partial at 6/8 — the HP first URL (OMEN Transcend 14 fb0023nr) is upstream-blocked in `scrapers-lib`, and the Lenovo second product is now unblocked by T7.0a merge ingest (re-ingest pending). T6.2 done. T6.7 captured 16 findings; T7.0b (Session 13) closed the actionable bridge + CLI fixes (#2, #4, #5, #8, #11, #12) and resolved three policy items (#6 → T7.1 doc, #7 → T7.0c, #9 → T7.0d); T7.0a (Session 15) shipped Lenovo merge ingest and subsumed Finding #3; T7.2 (Session 17) shipped end-to-end smoke — all 6 products refresh successfully across all 4 vendors, T7.0a family_code merge confirmed end-to-end on live PSREF, and surfaced a CLI URL template gap (the hard-coded `DEFAULT_*_URL_TMPL` constants in `cli/refresh.py` don't reach Dell Aurora / HP full-slug / ASUS Strix variants) filed as T7.4; T7.4 (Session 18) shipped `refresh --from-db` — reads each product's stored `source_url` from bundle provenance and bypasses the per-vendor URL templates entirely, closing the gap. Finding #1 (HP Transcend 14 upstream) remains deferred. Full list and design sketches live in `SESSION_LOG.md` Sessions 12, 13, 15, 17, and 18.

- All 16 field categories from the source 80-column Excel (`Competitor Columns.xlsx`) are mapped to a data shape.
- Schema connective tissue (catalog references, unknown-chip handling, provenance record format, naming, enum policy) is locked.
- Database engine: **SQLite (local).** One file on disk, managed via DB Browser for SQLite. Migration to hosted Postgres reserved for if/when team access becomes real.
- `scrapers-lib` Tier 2 fetchers exist for Dell, HP, Lenovo, ASUS; Acer and MSI deferred upstream. Installed editable from the sibling repo.
- Six Stage 2 follow-up decisions resolved (year handling, naming, cross-tile merge, adapter source, boards modeling, storage parity). See `SESSION_LOG.md` Session 5 for detail.
- Four Session 7 decisions resolved during the HP / Lenovo pause checkpoints (HP weight handling, HP USB-C ambiguous-rate flagging, Lenovo target substitution, Lenovo `tgp_max` = max-per-board). See `SESSION_LOG.md` Session 7.
- Five Session 8 decisions resolved during the ASUS pause checkpoint — most notably the amendment to the Session 3 stub-only catalog rule: vendors that publish chip-level specs on laptop spec pages (ASUS NPU TOPS, Lenovo cores/clocks/process-node, HP/Dell core counts) now seed the matching `cpu_catalog` columns, with cross-vendor disagreement routed to the existing `value_disagreement` queue. See `SESSION_LOG.md` Session 8.
- Three Session 9 format decisions locked at the Stage 4 mid-stage checkpoint: empty sections render as `Heading: [empty]` (not hidden); single-offering categories drop the redundant `Offering 1:` prefix; the identity title block always shows all six identity fields including `[empty]` for unset. View layer marker scheme and section conventions captured in `VIEWS.md`. See `SESSION_LOG.md` Session 9.
- Stage 5 (Session 10): four CLI helpers shipped (`find-conflicts`, `find-empty`, `manual-edit`, `resolve`). Each views module gained a `field_paths(product)` registry, exposed via `views/orchestrator.all_field_paths()`; `find-empty` reuses the section structure for grouped output. Path syntax for writes is dotted — `<column>` for scalars, `<offerings_column>.<idx>.<leaf_key>` for offering leaves; catalog cells are not editable via `manual-edit` (plain text, no provenance scaffolding). 18 new CLI happy-path tests landed under `tests/cli/`. See `SESSION_LOG.md` Session 10.

**Immediate next phase:** Phase 2 (UI) is the next horizon and is currently unscoped. Stage 8 is not yet planned. T7.0d (keyboard structured offerings — Session 13 Finding #9) was deferred at Stage 7 close-out; re-openable if filterable keyboard data becomes a real need. See `TASKS.md` Stage 7 row T7.0d and `SESSION_LOG.md` Session 19.

---

## Setup

This is a personal project, not packaged for distribution. Steps assume Python 3.12+.

### Prerequisites

- Python 3.12 or newer.
- `scrapers-lib` cloned as a **sibling directory** to this repo. The bridge layer imports `scrapers_lib.tier2.*` for vendor fetchers; without it, `refresh` fails at import time.

  ```
  Workspace/
  ├── scrapers-lib/          # sibling — vendor scrapers
  └── competitive-database/  # this repo
  ```

- DB Browser for SQLite (optional) — spreadsheet-style spot checks against `competitive.db`.

### Install

From the repo root, in a fresh virtualenv:

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -e .
pip install -e ../scrapers-lib   # editable sibling install
```

### Bootstrap the database

```bash
python -m competitive_database db-init
```

Creates `competitive.db` in the current directory with the full schema. Override the path with `--path`.

### First refresh

Fetch and ingest one product end-to-end:

```bash
python -m competitive_database refresh --brand dell --model alienware-area-51-aa18250-gaming-laptop
```

Inspect the resulting row:

```bash
python -m competitive_database inspect-product alienware-area-51-aa18250-gaming-laptop
```

See [CLI reference](#cli-reference) for the full subcommand surface.

---

## Scope

### In scope
- Six brands: **Dell, HP, Lenovo, ASUS, Acer, MSI**.
- **US vendor sites only.**
- **Gaming laptops only.**
- **Data layer only:** scrape, clean, transform, store. The database is the deliverable for this phase.

### Out of scope (deferred or excluded)
- UI / dashboard / chatbot — separate later efforts after the DB is reliable.
- SKU-level configurations (e.g., "i9 + 5090 + 32GB / 1TB" as a row).
- Pricing.
- Operating system variants (Windows 11 Home vs Pro).
- Release dates.
- Color / finish options.
- History / audit log of changing values — deferred, not blocked.

---

## Architecture (high level)

Three tables:

1. **`cpu_catalog`** — chip-level data per CPU model (e.g., Core Ultra 9 285HX). Populated deterministically from Intel ARK and AMD spec pages, plus name-suffix rules.
2. **`gpu_catalog`** — chip-level data per GPU model (e.g., RTX 5070 Ti). Populated deterministically from NVIDIA and AMD spec pages.
3. **`products`** — one row per gaming-laptop product, identified by **(model code, year)**. References catalogs by model name string for chip data. Carries product-decided values directly (TGP, TDP max, board configuration, etc.).

Detailed schema: see [`DATA_MODEL.md`](DATA_MODEL.md).

---

## Identity

- **A product = (model code, year).** ASUS ROG Strix G16 2025 ≠ ASUS ROG Strix G16 2026.
- The vendor-written full name is scraped as-is and stored.
- From the name + URL, the following are mechanically derived: brand, sub-brand, series, model code, year (when in the name).
- `status` (active / discontinued) and `segment` (entry / premium / flagship) stay manual forever.

---

## Refresh model

- **Manual button only.** No scheduler.
- Real-world cadence expected: **~quarterly** once built.

---

## Provenance and confidence

Every cell carries a provenance record and a status flag. Scraped data is held to a *correctness bar*; manual data to a *vouched* bar.

### Scraped cells

| Field | Description |
|---|---|
| `source_url` | The page the value came from. |
| `captured_at` | Timestamp of extraction. |
| `scraper_id` | Which scraper produced it. |
| `status` | `verified` / `needs-review` / `vendor-doesn't-publish`. |

**Correctness bar:** scraped data must match the official US vendor page. If extraction is uncertain, the value is **not stored** — it routes to the review queue.

### Manual cells

| Field | Description |
|---|---|
| `entered_by` | Who entered it. |
| `entered_at` | Timestamp. |
| `source_note` | Free-form (URL, teardown reference, etc.). |
| `status` | `vouched` (default) / `needs-review`. |

`needs-review` on manual cells is a self-check tool — not a multi-reviewer workflow. Used when a value is thinly sourced and the user wants to revisit it.

---

## Conflict policy

When a scraper finds a value different from what's already stored — especially against a manually entered value — it **never silently overwrites**. The disagreement routes to a **review queue** for the user to resolve. Manual edits never silently lock either; both sides are visible until resolved.

---

## Catalog reference and unknown-chip handling

- Products reference CPU and GPU catalogs **by model name string** (e.g., `"Core Ultra 9 285HX"`).
- When a scraper encounters a chip model not yet in the catalog, the chip is **auto-added** with `status = needs-review`. The scrape proceeds without blocking. The user reviews catalog entries asynchronously.

---

## Locked policy decisions (summary)

- **Database engine:** SQLite (local). One-file storage, managed via DB Browser for SQLite. Migration to hosted Postgres reserved for if/when team access becomes real.
- **Sources:** Tier 2 manufacturer product pages only (via `scrapers-lib`). Tier 1 (mentions/feeds) and Tier 3 (retailer pages) are out of scope for this DB.
- **Vendor coverage rule:** Schema and tables built for all 6 brands. If `scrapers-lib` lacks a vendor, that vendor's products show empty rows until upstream catches up — not a project block.
- **Bridge-layer location:** All project-specific parsing and transformation lives in `competitive-database`. `scrapers-lib` is only extended when the change is universally useful.
- **No pre-locked manual fields:** Every DATA_MODEL field is scrape-eligible. The scraper extracts what it can; whatever's empty becomes the manual surface at runtime. The provenance + status flag system already handles "vendor doesn't publish" — we don't bake that into the schema.
- Catalogs only for CPU and GPU. Other commodities store specs directly on the product, no catalog.
- Multi-option fields (CPU offerings, GPU/board variants, displays, batteries, keyboards, cameras, adapters) stored as **lists of offerings**, not fixed slots.
- Motherboard variants are first-class on the product. Each board carries its own TPP cap, GPU TGP cap, and list of supported GPUs.
- Catalog references use the **model name string** as the foreign key (not a generated ID).
- Field naming: **snake_case** throughout.
- Categorical fields start as **open enums**; tighten as data accumulates.
- History deferred — current state only — but design preserves the option to add a history layer later.

---

## Repo layout (planned)

```
Workspace/
├── scrapers-lib/                 # sibling — vendor-specific scrapers
└── competitive-database/         # this repo
    ├── README.md                 # this file — overview, scope, policy
    ├── DATA_MODEL.md             # full field-by-field schema reference
    ├── PRD.md                    # product requirements
    ├── SESSION_LOG.md            # decision log per session
    ├── ARCHITECTURE.md           # detailed system design
    ├── TASKS.md                  # work breakdown
    ├── VIEWS.md                  # view-layer format choices and conventions
    └── TESTING.md                # (future) test strategy
```

---

## Vendor URL conventions

Each vendor's bridge expects a specific URL shape. Using the wrong shape produces silent or noisy failures.

- **Lenovo** — must be `psref.lenovo.com/l/Product/...` (the spec catalog). The consumer shop (`www.lenovo.com/...`) is rejected outright.
- **ASUS** — must include the `/spec/` subpath, e.g. `https://rog.asus.com/laptops/.../<model>/spec/`. The bare landing page returns no spec sections.
- **HP** — PDP URLs (`hp.com/us-en/shop/pdp/...`) work for most products. Some products (e.g. OMEN Transcend 14 fb0023nr) currently fail upstream in `scrapers-lib`; this is a known gap.
- **Dell** — `--brand dell --model <slug>` derives the URL automatically; or pass `--url https://www.dell.com/.../spd/<slug>` explicitly.

---

## CLI reference

All subcommands run via `python -m competitive_database <command>`. `--db <path>` is accepted on every read/write subcommand (default `competitive.db`).

### `db-init`

Bootstrap a fresh SQLite DB with the full schema, or apply pending column migrations to an existing DB (idempotent).

```
db-init [--path PATH]
```

- `--path` — DB file location. Default: `competitive.db`.

```bash
python -m competitive_database db-init
```

### `refresh`

Fetch a vendor product page, parse via the bridge, and ingest the result. Single SQLite transaction per product; cross-tile offerings are unioned.

```
refresh --brand BRAND (--model SLUG | --url URL | --from-db --model SLUG [--year YEAR])
        [--db DB] [--profiles-dir DIR]
```

- `--brand` — `dell` / `hp` / `lenovo` / `asus`. Required.
- `--model` — URL slug for the product (vendor-specific). Mutually exclusive with `--url`.
- `--url` — Full vendor URL. Recommended for Lenovo (`psref.lenovo.com/l/Product/...`) and ASUS (`/spec/` subpath required).
- `--from-db` — Read the product's stored `source_url(s)` from bundle provenance in the local DB instead of formatting via the per-vendor template. Recommended for refreshing an already-ingested product — the template-formatted URL doesn't always match the URL the product was originally ingested from (e.g. Dell Aurora line, HP full marketing slug, ASUS Strix no-`/us/`). See `SESSION_LOG.md` Sessions 17 + 18 for the full story. Requires `--model`; mutually exclusive with `--url`. For Lenovo Intel+AMD merged rows, refreshes from each stored URL once.
- `--year` — Disambiguator for `--from-db` when the same `model_code` has multiple yearly variants in `products`.
- `--all` — Refresh every configured product. **Not yet implemented.**
- `--profiles-dir` — Persistent browser profiles directory for the Playwright stealth context. Default: `.profiles`.

```bash
# First-time ingest — template-formatted URL.
python -m competitive_database refresh --brand dell --model xps-13-9315

# First-time ingest — explicit URL override.
python -m competitive_database refresh --brand asus --url https://rog.asus.com/laptops/rog-zephyrus/rog-zephyrus-g16-2026/spec/

# Returning refresh — read each stored URL out of the DB.
python -m competitive_database refresh --brand dell --model aa18250 --from-db
```

### `inspect-product`

Print the orchestrated, status-marked spec dump for one product.

```
inspect-product MODEL_CODE [--year YEAR] [--db DB]
```

- `MODEL_CODE` (positional) — Product slug. For Lenovo merged rows, this is the `family_code` (e.g. `legion-pro-7-16-gen-10`).
- `--year` — Disambiguator if the slug has multiple yearly variants.

```bash
python -m competitive_database inspect-product rog-zephyrus-g16-2026
```

### `find-empty`

List empty and `vendor-doesn't-publish` cells per product, grouped by the same 16 sections as `inspect-product`.

```
find-empty (--product MODEL_CODE [--year YEAR] | --all) [--db DB]
```

- `--product` — Product slug. Required unless `--all`.
- `--year` — Disambiguator.
- `--all` — Walk every product in the DB.

```bash
python -m competitive_database find-empty --all
```

### `find-conflicts`

List unresolved `review_queue` rows (id, product, conflict type, field path, existing-vs-candidate summary — one row per line).

```
find-conflicts [--product MODEL_CODE] [--db DB]
```

- `--product` — Filter to one product slug.

```bash
python -m competitive_database find-conflicts
```

### `manual-edit`

Write a manual cell at a dotted field path. Provenance scaffolding (`status`, `entered_by`, `entered_at`) is filled in automatically.

```
manual-edit --product MODEL_CODE --field PATH (--value VAL | --value-json JSON)
            [--year YEAR] [--note NOTE] [--status STATUS] [--entered-by USER] [--db DB]
```

- `--product` — Product slug. Required.
- `--field` — Dotted field path. `<column>` for scalars; `<offerings_column>.<idx>.<leaf_key>` for offering leaves. Required.
- `--value` — Cell value (coerced int → float → string).
- `--value-json` — Cell value as a JSON literal (use for `true` / `false` / `null` / lists). Mutually exclusive with `--value`.
- `--note` — Free-form source note (stored as bundle `source_note`).
- `--status` — Bundle status. Default `vouched`; alternative `needs-review`.
- `--entered-by` — Override the bundle `entered_by` field (default: `$USER` / `$USERNAME`).

```bash
python -m competitive_database manual-edit --product rog-zephyrus-g16-2026 --field audio_jack --value-json true
python -m competitive_database manual-edit --product alienware-m18-2026 --field display_offerings.0.nits_peak --value 500
```

Plain-leaf offering paths (currently `boards.{idx}.arch_marker`) write plain scalars instead of bundles; bundle helpers refuse plain-leaf paths to keep the shape honest.

### `resolve`

Close one `review_queue` row in a single transaction.

```
resolve --id ID --action ACTION [--value VAL | --value-json JSON]
        [--note NOTE] [--entered-by USER] [--db DB]
```

- `--id` — `review_queue.id` of the row. Required.
- `--action` — One of `accept_candidate`, `kept_existing`, `manual_override`, `dropped`. Required.
- `--value` / `--value-json` — Required only with `--action manual_override`.
- `--note` — Resolver note; stored on the queue row, and used as the bundle `source_note` for `manual_override`.

```bash
python -m competitive_database resolve --id 42 --action accept_candidate
python -m competitive_database resolve --id 47 --action manual_override --value 16 --note "Verified from teardown"
```

### `audit-normalize`

Walk every product and surface paths where the same conceptual field carries 2+ distinct value strings (e.g. `Wi-Fi 7` vs `WiFi 7`). Operational tool for catching vocabulary drift.

```
audit-normalize [--all] [--strings-only] [--db DB]
```

- `--all` — Print every filled path with its values, not just the gaps.
- `--strings-only` — Skip numeric and boolean values. Strings are where normalization issues live.

```bash
python -m competitive_database audit-normalize --strings-only
```

### `backfill-lenovo-families`

One-time backfill for legacy Lenovo rows ingested before T7.0a. Reads rows with `family_code IS NULL`, re-derives family + arch from existing bundles, applies in-place updates for singletons or merges multi-row families (boards + offerings unioned; source machine codes preserved in `source_model_codes`). Idempotent.

```
backfill-lenovo-families [--db DB]
```

```bash
python -m competitive_database backfill-lenovo-families
```

---

## Upgrading

When you pull schema changes from git, **re-run `db-init` to apply column migrations** to your existing `competitive.db`:

```bash
python -m competitive_database db-init
```

This step is required: `db/connection.py::connect()` opens the SQLite handle but does **not** call `apply_schema()` — only the `db-init` subcommand does. Any CLI subcommand that touches a newly added column will fail with `sqlite3.OperationalError: no such column: <name>` on a pre-migration DB until `db-init` is run once.

`apply_schema()` is idempotent: existing tables are guarded by `PRAGMA table_info` checks and new columns added via `ALTER TABLE ... ADD COLUMN`. Existing rows are preserved. Data backfills that depend on new columns (e.g. `backfill-lenovo-families` for the T7.0a Lenovo family rollup) are exposed as their own CLI subcommands — run them after `db-init`.

---

## Normalization notes

### `resolution_label` — documented enum-pair

Vendors publish display resolution in two equivalent vocabularies — a marketing label and a resolution standard:

| Marketing label | Resolution standard |
|---|---|
| FHD | 1080p |
| WQXGA | 2.5K |
| UHD | 4K |

Either form may appear in `resolution_label` depending on the vendor (e.g. Lenovo publishes `WQXGA`; ASUS publishes `2.5K`). **Both are stored as-is with no normalization at ingest** — the open enum stays open at the storage layer. The companion `resolution_pixels` field carries the unambiguous pixel form (e.g. `2560×1600`) for filters and joins.

Per the Session 13 Finding #6 decision. `DATA_MODEL.md` cross-links here.

---

## Document conventions

- All docs are Markdown.
- Decisions are written in present tense; deferred items explicitly tagged.
- When a decision changes, update the relevant doc *and* note the change in `SESSION_LOG.md` (when that doc exists).
