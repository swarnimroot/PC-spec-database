# React Rebuild — Build Plan

Status: APPROVED 2026-06-08; **COMPLETE 2026-06-09 (Session 55)** — all phases done; the
Streamlit UI has been retired. Replaces the Streamlit UI with a React frontend built
from the claude.ai/design prototypes, keeping the entire Python/SQLite layer as a
local backend. Goal: pixel-faithful to the prototypes + the real interactions
(drag-to-compare, year scrubber, ⌘K, keyboard queue commit), which Streamlit cannot do.

Source prototypes (our starting code, DO NOT delete):
`.tmp_design/comp-database/project/` — `directions/*.jsx`, `shared/{data.js,states.css,*-tokens.css}`.

## Architecture (plain language)

Two pieces, both running locally on your machine (still local-first — nothing leaves it):

- **Backend** — a small Python web server (**FastAPI**) that wraps the code you already
  have (`db/`, `views/`, the extracted query engine, `manual_edit_cell`, `resolve_row`,
  `refresh`). It speaks JSON. Same language as everything else, so it's the least-new part.
- **Frontend** — the **React** prototype code, moved into a real project (**Vite**), with
  its fake `data.js` swapped for calls to the backend. This is the part you see in the browser.

Your DB, scrapers, all 10 CLIs, and core logic are untouched — only the Streamlit `ui/`
layer is replaced (and, as of Session 55, deleted).

## What we keep from our current app (NOT the prototype's choices)

- **Our headers/sections** — schema is generated from our `_SECTION_REGISTRY` (16 categories
  + Identity), not the prototype's trimmed 10-category set.
- **Gen-level CPU/GPU** — keep our fields; the prototype's specific SKUs ("Ryzen AI 9 HX 370")
  are demo data only.
- **Advanced field+operator query** — the prototype's faceted Finder only filters a fixed
  handful of facets. We preserve our full power (query ANY field; operators incl. is-empty,
  marked-unavailable, numeric ≥/≤) as an "advanced" mode behind the facets. This is the one
  capability that would otherwise be lost.
- **Welcome guide modal** — ported to the Home screen. As shipped (S55) it fires
  **per-session** (persisted in sessionStorage). Revisited when we lighten the home page.

## Phases

> **Progress (Session 55, 2026-06-09): COMPLETE.** All phases done. Phase 1 (query engine)
> and Phase 2 (FastAPI backend + React Spec Finder) DONE (S54). Phase 3 — Compare Matrix +
> Review (formerly Curation Cockpit) DONE (S54); **Home + per-session welcome modal DONE (S55)**; **Refresh
> screen DONE (S55)**. Phase 4 cutover **DONE (S55)** — the Streamlit `ui/` package, the
> `ui-launch` CLI, and `tests/ui/` were deleted and the `ui` optional dependency dropped from
> `pyproject.toml`; the React frontend is the sole UI. A one-command launch
> (`cd frontend && npm run dev`) runs both halves (see §Running below). Tests: **499 passing**.

### Phase 1 — Backend API (the foundation) — DONE (S54)
1. **Extract the query engine** out of `ui/find.py` into `competitive_database/query/`
   (the 7 operators, `_union_templates`, `_find_matches`, distinct-values, narrow-by).
   Pure functions, unit-tested. De-risks Find regardless of frontend.
2. **JSON mapping layer:** map our value bundles → prototype value shape `{v, s, src, ts, note}`;
   map our 6 stored statuses → the 5 display states (verified+vouched→confirmed,
   vendor-doesn't-publish→not_published, manual→hand, needs-review→review, empty→blank).
3. **Endpoints** (thin wrappers over existing callables, bound to localhost):
   - `GET /api/catalog` — all models as `{id,brand,series,model,segment,years,base,byYear}`
   - `GET /api/schema` — our categories+fields (from `all_field_paths`)
   - `GET /api/model/{id}?year=` — one decoded product (`load_product`)
   - `POST /api/find` — `{field_path, operator, value, narrow_by}` → matches (extracted engine).
     Powers BOTH facets and advanced query.
   - `GET /api/queue` — review queue (Conflicts / Unverified / Missing / Manual buckets)
   - `POST /api/value` — write edited value+state+provenance (`manual_edit_cell`)
   - `POST /api/resolve` — triage resolution (`resolve_row`)
   - `POST /api/refresh` — real scrape/refresh (wraps `cli/refresh`) — replaces the
     prototype's mocked "Pull fresh data"
   - `GET /api/value/{id}/history` — provenance (see Open Decisions re: real audit log)

### Phase 2 — Frontend scaffold + FIRST screen end-to-end (prove the stack) — DONE (S54)
- Vite + React project under `frontend/`. Convert prototype globals → imports, swap
  `window.DB` for an API client of the same shape. Factor the triplicated primitives into
  a shared lib: `<StateDot>`, `<ValueCell>` (multi-option + blank handling), data helpers.
- **Build the Spec Finder first** — highest-value upgrade, and it forces `/catalog`,
  `/schema`, `/find`, and the advanced-query preservation early.
- Acceptance: real `competitive.db` (56 products), facets with live counts, advanced query
  (is-empty / marked-unavailable / numeric) all working, look matches the prototype.

### Phase 3 — remaining screens (each wired to real data, one at a time)
- **Compare Matrix** (→ our Spec Roster) — **DONE (S54)**: drag-shelf + typeahead to add
  columns (≤4), per-column year scrubber, differences-only toggle, using OUR sections/fields,
  gen-level CPU/GPU. Reuses shared `StateDot` / `ValueCell`.
- **Review** (formerly Curation Cockpit; → Edit + the parked Triage work) — **DONE (S54;
  renamed S55)**: UNIFIED queue with **Conflicts / Unverified / Missing / Manual** buckets,
  adaptive center editor (resolve-conflict vs edit-value) with keyboard commit →
  `/api/value` / `/api/resolve`; responsive provenance slide-over; `/api/refresh` wired.
  Intended to replace Edit + Triage. (Route id / `src/curation/` folder unchanged.)
- **Home (lightened)** + welcome modal (per-session, sessionStorage) — **DONE (S55)**: `src/home/`
  — hero, live counts (Products / Vendors / Conflicts / Unverified from
  `/api/catalog` + `/api/queue/counts`), clickable stat cards (Products/Vendors → Spec Finder;
  Conflicts/Unverified → Review), clickable screen cards, per-session welcome modal. Default
  screen; brandmark routes here.
- **Refresh** screen (React) — **DONE (S55)**: `src/refresh/` — "All eligible products"
  (`POST /api/refresh {all:true}`) or "One product" (catalog dropdown + year → `from_db`
  re-scrape) modes, confirm step, running spinner, results rollup (stat grid, errors/skipped
  lists, conflict callout to Review).

### Phase 4 — cutover & cleanup — DONE (S55)
- React reached parity; the Streamlit app was retired in this cutover.
- Deleted `competitive_database/ui/` (Streamlit) + its AppTest suite (`tests/ui/`) + the
  `cli/ui_launch.py` launcher; removed the `ui_launch` subparser from `__main__.py` and the
  `ui = ["streamlit>=1.40"]` optional dependency from `pyproject.toml`. `db/`/`views/`/`query/`/
  `api/` tests retained; suite now **499 passing**. The `refresh` CLI + `POST /api/refresh`
  remain as the non-UI refresh path.
- Docs: ARCHITECTURE (two-tier), README run instructions, single dev-launch command — updated.

## Open decisions (small, not blocking the plan)
1. **Visual identity** — prototype used a different accent per direction. A single app needs
   one. Default: neutral Dell-base + one accent; confirm when we see the first screen live.
2. **Audit history** — we have provenance fields but NO per-field edit log today. The Cockpit
   shows a history pane. Either (a) scope history to existing provenance now, or (b) add a
   lightweight history table later. Recommend (a) now, (b) later.
3. **Which fields become facets** in the Finder (Brand, segment, GPU gen, refresh, Wi-Fi, …) —
   a short curation step; everything else stays reachable via advanced query.

## Honest costs / risks
- New dependencies: FastAPI + uvicorn (Python), Node + Vite + React (frontend). Approved.
- More moving parts for a solo non-technical maintainer (two pieces instead of one Streamlit app).
- The ~514 Streamlit AppTest tests largely become obsolete; backend/logic test coverage grows.
- Our schema (16+ categories) is larger than the prototype's (10) — layouts must handle more
  rows/fields gracefully (esp. the compare matrix and which facets to expose).

## Running the app (Home | Spec Finder | Compare | Review | Refresh — all shipped)

The frontend lives in `frontend/` (Vite + React, plain JSX) and renders REAL data
from the FastAPI backend (no fake `data.js`). **One command** starts both halves
together — `concurrently` runs the backend (uvicorn) and the Vite dev server, with
`cross-env` injecting `COMPETITIVE_DB_PATH=../competitive.db`:

```powershell
cd frontend
npm install   # first run only
npm run dev
```

This opens the app at **http://localhost:8501/competitive-database/** (Vite `base`
`/competitive-database/` + `strictPort` 8501) backed by uvicorn on **:8011**. CORS on
the backend allows the localhost dev origins (3000 / 5173 / 8501). The backend reads
the **real `competitive.db`** in the project root.

**Same-origin API / deployment story.** The browser calls the API **same-origin** under
the base path (`/competitive-database/api/...`) — `src/api.js` defaults its base to
`import.meta.env.BASE_URL`, and the Vite dev server proxies `/competitive-database/api`
→ `http://localhost:8011` (target overridable via `VITE_API_TARGET`). Because no host is
baked into the bundle, the same build serves both localhost and a reverse proxy: the
existing **Tailscale Funnel** mapping (`/competitive-database` → `localhost:8501/competitive-database/`)
exposes the app publicly with no code change. `vite.config.js` sets
`server.allowedHosts: ['.ts.net']` so the Funnel host can load the dev server.
`VITE_API_BASE` in `frontend/.env` is an optional override (left unset → same-origin default).
For a backend-only run:
`.venv\Scripts\python -m uvicorn competitive_database.api.app:app --reload --port 8011`
(set `COMPETITIVE_DB_PATH` first).

### Frontend layout
- `src/api.js` — API client (catalog / schema / model / find / queue / value / resolve / refresh / history).
- `src/shared/` — reusable primitives: `StateDot` (5 value-states),
  `ValueCell` (lead + alt values, blank / not-published), `data.js` helpers
  (`latestYear`, `resolve`, `lead`, value parsers). Reused by every screen.
- `src/home/` — Home dashboard: hero, live counts (Products / Vendors / Conflicts /
  Unverified), clickable stat cards (Products/Vendors → Spec Finder; Conflicts/Unverified
  → Review), clickable screen cards, and a per-session welcome modal (sessionStorage).
  Default screen; the brandmark routes here.
- `src/finder/` — Spec Finder: facet rail with live counts, result cards (matched spec
  highlighted, year-change `→YY` markers), active-filter chips, sort,
  "Show data state" toggle, per-model detail slide-over, ⌘K command palette,
  and the **Advanced** query mode.
- `src/compare/` — Compare Matrix: rows = our sections, ≤4 columns via drag-shelf +
  typeahead, per-column year scrubber, differences-only toggle. Sections are collapsible
  accordions (S58): collapsed = rollup summary, expand fetches `/api/model/{id}/detail`
  for the real per-leaf values (cached per model·year); ☰ Fields drawer toggles
  fields/sections on/off.
- `src/curation/` — Review (route id / folder unchanged): unified queue with
  Conflicts / Unverified / Missing / Manual buckets → adaptive editor (resolve-conflict
  vs edit-value, keyboard commit) → responsive provenance slide-over. Queue groups by
  spec category in importance order (S57); Conflicts tab has a "Correct value" box →
  `manual_override`.
- `src/refresh/` — Refresh: "All eligible products" / "One product" modes over
  `POST /api/refresh`, confirm step, running spinner, results rollup with conflict
  callout to Review.

Top nav (`App.jsx`): **Home | Spec Finder | Compare | Review | Refresh**.

## Parked hiccups
1. **Compare empty-state bug.** ~~Removing all columns blanks the compare area and breaks
   drag/select of a first product.~~ **FIXED S56** — the add-column search box + drop zone
   lived inside the `<table>` that the empty state replaced; factored into a shared
   `addDropZone` element now rendered in both the empty state and the header.
2. **Finder repeated names in row labels.** ~~Duplicated tokens ("V V16", "Strix Strix G16").~~
   **FIXED S56** — the DB `product` name already includes the series word; added a display-only
   `modelTail(series, model)` helper in `frontend/src/shared/data.js` that strips the redundant
   prefix at every label site (dim-series + bold-model look). No data change.
3. **Review queue readability.** ~~The Curation Cockpit's left-rail queue is a hard-to-read flat
   list — needs groupings + field-importance prioritization.~~ **FIXED S57** — the left queue now
   groups by spec category in importance order (Graphics → Processor → … → Identity), top group
   expanded and the rest collapsed, with `j`/`k` traversing visible items only. The Conflicts tab
   also gained a "Correct value" edit box (routes resolution through `manual_override`, off
   catalog-vouch rows). (The Curation→Review rename itself shipped S55.)

### Facets vs. real fields
Kept: Brand, Sub-brand (segment), Wi-Fi (network rollup), Display = OLED,
Graphics (board listed vs not), Memory (≥64/128 GB parsed), Refresh rate
(max Hz parsed), Ports (HDMI / card reader), Weight slider (kg parsed).
Dropped: IPS panel + Touchscreen — the rollup display string only cleanly
exposes OLED, and there is no touch field in the visual rollup sections.

### Advanced query (locked requirement)
Field + operator + value → `POST /api/find`, using the REAL granular DB field
paths (e.g. `weight_kg_min`, `memory_max_gb`, `wifi_standard`,
`battery_offerings.*.wattage_wh`) — not the section rollups — so `is_empty`,
`vendor_unavailable`, and numeric `gte`/`lte` work on any field.
