# React Rebuild — Build Plan

Status: APPROVED 2026-06-08. Replaces the Streamlit UI with a React frontend built
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
layer is replaced.

## What we keep from our current app (NOT the prototype's choices)

- **Our headers/sections** — schema is generated from our `_SECTION_REGISTRY` (16 categories
  + Identity), not the prototype's trimmed 10-category set.
- **Gen-level CPU/GPU** — keep our fields; the prototype's specific SKUs ("Ryzen AI 9 HX 370")
  are demo data only.
- **Advanced field+operator query** — the prototype's faceted Finder only filters a fixed
  handful of facets. We preserve our full power (query ANY field; operators incl. is-empty,
  marked-unavailable, numeric ≥/≤) as an "advanced" mode behind the facets. This is the one
  capability that would otherwise be lost.
- **Welcome guide modal** — ported and upgraded to fire **once-ever** (persisted in
  localStorage) instead of once-per-session, with a "show guide again" link. Revisited when
  we lighten the home page.

## Phases

### Phase 1 — Backend API (the foundation)
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
   - `GET /api/queue` — curation queue (needs-review / blank / hand-entered tabs)
   - `POST /api/value` — write edited value+state+provenance (`manual_edit_cell`)
   - `POST /api/resolve` — triage resolution (`resolve_row`)
   - `POST /api/refresh` — real scrape/refresh (wraps `cli/refresh`) — replaces the
     prototype's mocked "Pull fresh data"
   - `GET /api/value/{id}/history` — provenance (see Open Decisions re: real audit log)

### Phase 2 — Frontend scaffold + FIRST screen end-to-end (prove the stack)
- Vite + React project under `frontend/`. Convert prototype globals → imports, swap
  `window.DB` for an API client of the same shape. Factor the triplicated primitives into
  a shared lib: `<StateDot>`, `<ValueCell>` (multi-option + blank handling), data helpers.
- **Build the Spec Finder first** — highest-value upgrade, and it forces `/catalog`,
  `/schema`, `/find`, and the advanced-query preservation early.
- Acceptance: real `competitive.db` (56 products), facets with live counts, advanced query
  (is-empty / marked-unavailable / numeric) all working, look matches the prototype.

### Phase 3 — remaining screens (each wired to real data, one at a time)
- **Compare Matrix** (→ our Spec Roster): drag-tray, per-column year scrubber, differences-only,
  using OUR sections/fields, gen-level CPU/GPU.
- **Curation Cockpit** (→ Edit + the parked Triage work): queue + editor + provenance; C/N/R
  commit → `/api/value`; "Pull fresh data" → `/api/refresh`; year-diff strip. **Responsive fix:**
  collapse the provenance pane to a slide-over below laptop width (the prototype's flagged
  density problem).
- **Home (lightened)** + welcome modal (once-ever).
- **Refresh** screen.

### Phase 4 — cutover & cleanup
- Run React to parity; keep Streamlit alive until then (never without a working app).
- Retire `ui/` (Streamlit) + its AppTest suite once parity is reached; keep & grow
  `db/`/`views/`/`query/` tests; add API + a few frontend tests.
- Docs: ARCHITECTURE (new two-tier), README run instructions, single dev-launch command.

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

## Running the Spec Finder (Phase 2 — shipped)

The first screen lives in `frontend/` (Vite + React, plain JSX) and renders
REAL `/api/catalog` + `/api/schema` data (no fake `data.js`). Two commands,
from the project root, in two terminals (Windows PowerShell):

```powershell
# 1) Backend — FRESH port 8011 (8000 is occupied by an unrelated process)
$env:COMPETITIVE_DB_PATH = "$PWD\competitive.db"
.venv\Scripts\python -m uvicorn competitive_database.api.app:app --port 8011
```

```powershell
# 2) Frontend
cd frontend
npm install   # first run only
npm run dev   # default http://localhost:5173/
```

The API base URL is configurable via `frontend/.env`
(`VITE_API_BASE`, default `http://localhost:8011`).

### Frontend layout
- `src/api.js` — API client (catalog / schema / model / find).
- `src/shared/` — reusable primitives: `StateDot` (5 value-states),
  `ValueCell` (lead + alt values, blank / not-published), `data.js` helpers
  (`latestYear`, `resolve`, `lead`, value parsers). Reused by later screens.
- `src/finder/` — facet rail with live counts, result cards (matched spec
  highlighted, year-change `→YY` markers), active-filter chips, sort,
  "Show data state" toggle, per-model detail slide-over, ⌘K command palette,
  and the **Advanced** query mode.

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
