# Product Requirements Document — Competitive Gaming-Laptop Spec Database

For project scope, architecture, and policy details, see [`README.md`](../README.md). For full schema, see [`DATA_MODEL.md`](DATA_MODEL.md).

---

## Overview

A persistent, queryable database tracking the publicly published specifications of gaming laptops from Dell, HP, Lenovo, ASUS, Acer, and MSI. The database is the deliverable for the current phase. It exists to be consumed — by the owner directly, by a small team, and eventually by a UI and a chatbot built on top of it.

---

## Problem statement

Competitive intelligence on gaming-laptop specs is currently scattered:

- Vendor websites are the authoritative source for what's offered, but each vendor publishes specs differently — different fields, different terminology, different formats.
- Reviewer / press / teardown sources fill gaps but disagree with each other and with vendors.
- Spreadsheets go stale fast and don't capture *why* a value is what it is — no provenance, no source link, no last-confirmed timestamp.
- There is no single place that says: *"As of today, this product offers these CPUs, these GPUs at these power classes, this set of displays — and here's where each value came from."*

This DB is the answer to that gap.

---

## Target users

| User | How they use it |
|---|---|
| **Owner (independent researcher)** | Curates the data, reviews scraped values, fills manual entries, queries directly for analysis. |
| **Team members** | Consume the data — raw queries, future UI dashboards, future chatbot interactions. |
| **(Future) UI users** | Browse and filter via a visual interface — separate later effort. |
| **(Future) chatbot users** | Ask natural-language questions answered against the DB — separate later effort. |

This phase serves the **owner** and **team** directly. UI and chatbot are deferred.

---

## Goals

1. **Coverage parity with vendor pages.** If a vendor publishes a value on its US product page, that value must be in the DB. No silent omissions.
2. **Per-cell provenance.** Every value can be traced — to a source URL (scraped) or to a human entry note (manual), with a captured-at timestamp.
3. **Correctness for scraped data.** Scraped values must match the vendor page exactly. Uncertain extractions route to a review queue, not into the DB.
4. **Manual fill for the rest.** Fields vendors don't publish (TIM, A/C/D-cover materials, internal motherboard layout, etc.) can be filled by the owner or team with provenance.
5. **Clean comparison across vendors.** The schema supports apples-to-apples comparison — list-of-offerings, motherboard variants, status flags — so a query like *"which products offer Wi-Fi 7"* returns honest, comparable results.
6. **Queryable today, extensible tomorrow.** The DB supports single-field filter queries now. Schema preserves the option to add history, UI, and chatbot layers later without restructuring.

---

## Non-goals

- **SKU-level fidelity.** Combinations like "i9 + RTX 5090 + 32GB / 1TB" are not tracked. The DB answers *"what's offered on this product"*, not *"what specific configurations can be ordered."*
- **Pricing.** Out of scope.
- **OS variants** (Windows 11 Home / Pro), **release dates**, **color / finish options** — out of scope.
- **History / audit trail** of changing values — deferred. The design preserves the option to add it later; no history features in this phase.
- **UI / dashboard / chatbot** — separate later efforts after the DB is reliable.
- **Brands outside the six listed**, **non-US vendor pages**, **non-gaming laptops** — out of scope.

---

## Success criteria

The DB is "ready for UI / chatbot" when:

1. **Coverage rule met.** For every product tracked, every field that the vendor publishes on its US product page is filled in. Coverage *percentage* will vary by product and vendor — it's the *rule* that's the bar, not a fixed percentage. Vendors that publish more get higher coverage; vendors that publish less get lower coverage; both are expected.
2. **No incorrect values.** No scraped cell holds a value that doesn't match the vendor page. Uncertain values live in the review queue, not in the DB.
3. **Provenance is complete.** Every cell carries a source (URL for scraped, note for manual) and a status flag.
4. **Manual fill is current.** All fields the owner or team committed to maintaining manually are populated and marked `vouched`.
5. **Queries return honest results.** Filter queries return product sets that match what a manual cross-check of the vendor pages would produce.

---

## Use cases (this phase)

Single-field filter queries are the primary mode. Examples:

- *"Which products offer the RTX 5070 Ti?"*
- *"Which products have OLED displays at 240Hz or higher?"*
- *"Which products support Wi-Fi 7?"*
- *"Which products use vapor-chamber thermals?"*
- *"Which vendors publish memory speed on their US product pages?"*
- *"Which products offer a CPU with NPU TOPS ≥ 40?"*
- *"Which products are listed as `discontinued` but still have active vendor pages?"*

Multi-field aggregation (e.g., *"rank products by total Thunderbolt + USB-C port count"*) is not a goal for this phase, but the schema does not preclude it.

---

## Constraints

- **Brands:** Dell, HP, Lenovo, ASUS, Acer, MSI. (Locked.)
- **Geography:** US vendor sites only.
- **Form factor:** Gaming laptops only.
- **Refresh model:** Manual button only — no scheduled scraping. Real-world cadence expected ~quarterly.
- **Scrapers:** Use the sibling Python package `scrapers-lib`. Tier 2 manufacturer product pages only — Tier 1 (mentions/feeds) and Tier 3 (retailer pages) excluded for this DB.
- **Sources of truth:**
  - Vendor product pages are authoritative for scraped data.
  - Reviewer sources, teardowns, OEM marketing material are acceptable for manual cells, with provenance noted.

---

## Stakeholders

- **Owner / curator:** the user (independent researcher).
- **Consumers:** team members (data + future UI + future chatbot).
- No external stakeholders, no employer dependencies.

---

## Phase definition

| Phase | Status |
|---|---|
| 1 — Data layer (this PRD) | In progress, schema-ready |
| 2 — UI / dashboard | Deferred |
| 3 — Chatbot | Deferred |
| 4 — History / audit layer | Deferred |
