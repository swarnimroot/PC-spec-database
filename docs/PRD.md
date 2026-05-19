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
| 2 — UI / dashboard | Stage 8 functional UI complete (Session 35); Stage 10a visual redesign complete (Session 43); Stage 10b (per-field data display cleanup) next — see [Phase 2 — UI](#phase-2--ui-stage-8) below |
| 3 — Chatbot | Deferred |
| 4 — History / audit layer | Deferred |

---

## Phase 2 — UI (Stage 8)

The data layer is at a zero-issue baseline (314/314 tests, `review_queue` unresolved = 0, both catalog tables `needs-review` = 0). Phase 2 turns the DB into a tool the owner and team can drive without CLI fluency.

### Why a UI now

- Today every workflow (browse, query, refresh, resolve, manual-edit) is a `python -m competitive_database.cli.X` call. The owner is fluent; team members are not.
- The single-field filter queries enumerated in §Use cases require typing SQL or knowing dotted `--field` paths. The UI is the surface that makes those queries clickable.
- Provenance markers (`[verified] [?] [—] [m] [empty]`) are already a one-line scan in the `inspect-product` view. A real webpage renders them just as well — no display invention needed; the conventions in [`VIEWS.md`](VIEWS.md) carry over verbatim.

### What it covers

A dashboard hub as the landing screen, with four destinations:

1. **Browse one product** — the `inspect-product` output rendered as a webpage; same marker scheme and section order as `VIEWS.md`. Stage 10a (Session 43): Company → Product → Year cascading picker over a light identity strip + Section / Feature / Value spec table; colored `●` dot markers in place of bracketed text tokens; inline marker legend.
2. **Compare side-by-side** — Stage 10a (Session 43): N vertical picker columns (1–4 max) with `+` / `×`; per-column segment auto-shown read-only; comparison grid with a `▌` strict-majority (`max_count * 2 > N`) left-edge divergence cue on cells that disagree.
3. **Find products where…** — single-field filter playground covering the queries enumerated in §Use cases. Value input is a dropdown of distinct DB values for the chosen (section, field) since T9.1 (Session 36) — picking a filter guarantees a match against what's actually stored, no need to know the exact stored form. T9.2 (Session 37) adds per-field display canonicalization so duplicate-meaning string variants (today: `panel_type` "IPS-level" → "IPS") collapse to one dropdown entry, and picking the canonical form matches every stored variant. Stage 10a (Session 43): three-box query bar (Spec field / Match / Value) with plain-English ops + optional Company / Year narrow-by; rounded result cards with `Open →` cross-nav to Browse.
4. **Review queue triage** — existing-vs-candidate diff per row, action buttons matching the `resolve` CLI's verbs (`accept_candidate` / `kept_existing` / `dropped` / `manual_override`). Stage 10c (deferred) will redesign filter / sort / grouping for the 229 unresolved Lenovo rows; Stage 10a delivered only a chrome-cleanup carve-out on this screen.

Hub also surfaces top-line health. Stage 10a (Session 43): the editorial hub shows three metric tiles (products / vendors / days since refresh) over three rounded CTA cards (Browse / Compare / Find) with primary `Open →` buttons. Edit + Refresh live under a `···` overflow in the top-bar nav. Triage is reachable via CLI today; UI surfaces it via the existing route until 10c.

### Workflow shape

Full control. The UI handles the entire daily curation loop:

- **Resolve queue rows** — replaces `resolve` CLI as the primary path.
- **Manual-edit a cell** — replaces `manual-edit` CLI.
- **Refresh products** — replaces `refresh` CLI (one product or all), with progress streamed back so the user sees rows landing and queue rows enqueueing.

CLIs remain available as a scripting / power-user backstop; the UI is the new primary surface, not the only surface.

### Out of scope (Phase 2)

- Chatbot — Phase 3.
- History / audit trail browser — Phase 4.
- Hosted Postgres migration — out of scope indefinitely (local-first preference; previously rejected).
- Multi-user concurrency, auth, RBAC — single-user local tool.
- Mobile / responsive layouts — desktop browser only.
- Acer / MSI products — blocked on `scrapers-lib` Tier 2 upstream.
- New write actions or queue states beyond what the CLIs already support — the UI mirrors the CLIs, it does not extend them.
