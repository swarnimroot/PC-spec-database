# Competitive Database — Gaming Laptop Spec Catalog

A persistent, queryable database of competitor gaming-laptop specs from Dell, HP, Lenovo, ASUS, Acer, and MSI. Most fields auto-populate from public US vendor pages; the rest are manual. Every cell carries provenance and a status flag.

---

## Status

**Phase: Data layer — Stages 1–3 complete; Stage 4 (view layer + `inspect-product`) next.** Foundation, schema, provenance helpers, and all four Stage 3 vendor bridges are implemented and tested. 148/148 tests pass. Live refresh has been validated against the Alienware Area-51 (Dell), the OMEN Transcend 14 (HP), the Legion Pro 7 16AFR10H (Lenovo, AMD cousin used as a placeholder for the Intel Pro 7i Gen 10), and the ROG Zephyrus G16 2026 (ASUS).

- All 16 field categories from the source 80-column Excel (`Competitor Columns.xlsx`) are mapped to a data shape.
- Schema connective tissue (catalog references, unknown-chip handling, provenance record format, naming, enum policy) is locked.
- Database engine: **SQLite (local).** One file on disk, managed via DB Browser for SQLite. Migration to hosted Postgres reserved for if/when team access becomes real.
- `scrapers-lib` Tier 2 fetchers exist for Dell, HP, Lenovo, ASUS; Acer and MSI deferred upstream. Installed editable from the sibling repo.
- Six Stage 2 follow-up decisions resolved (year handling, naming, cross-tile merge, adapter source, boards modeling, storage parity). See `SESSION_LOG.md` Session 5 for detail.
- Four Session 7 decisions resolved during the HP / Lenovo pause checkpoints (HP weight handling, HP USB-C ambiguous-rate flagging, Lenovo target substitution, Lenovo `tgp_max` = max-per-board). See `SESSION_LOG.md` Session 7.
- Five Session 8 decisions resolved during the ASUS pause checkpoint — most notably the amendment to the Session 3 stub-only catalog rule: vendors that publish chip-level specs on laptop spec pages (ASUS NPU TOPS, Lenovo cores/clocks/process-node, HP/Dell core counts) now seed the matching `cpu_catalog` columns, with cross-vendor disagreement routed to the existing `value_disagreement` queue. See `SESSION_LOG.md` Session 8.

**Immediate next phase:**
1. Stage 4 — view layer + `inspect-product` CLI per `TASKS.md`. Single source of truth for human-readable presentation; UI later renders through the same module.
2. Stages 5–7 follow per `TASKS.md`. Setup instructions and CLI reference land in Stage 7 (polish).

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
    └── TESTING.md                # (future) test strategy
```

---

## Document conventions

- All docs are Markdown.
- Decisions are written in present tense; deferred items explicitly tagged.
- When a decision changes, update the relevant doc *and* note the change in `SESSION_LOG.md` (when that doc exists).
