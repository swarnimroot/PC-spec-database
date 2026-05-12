# Session Log

Append-only log of brainstorming and design sessions. Each entry captures what was discussed, what was decided, where we left off, and pickup pointers for the next session.

Newest sessions at the top.

---

## Session 21 — 2026-05-12 (Stage 5 CLI gap closed: column-level offering paths now resolvable)

**Goal:** Close the Session 20 carryforward — extend the `resolve` CLI to accept column-level offering paths (e.g. `camera_offerings`) so runner-emitted list-level conflicts are resolvable end-to-end. Unblocks row #18 architecturally.

**Outcome:** New `ParsedPath` kind `products_offering_list` added; `resolve` CLI now handles column-level paths for `accept_candidate` / `kept_existing` / `dropped` (writes / leaves the whole offerings list); `manual_override` rejected at this shape with a redirect to leaf-level `manual-edit`. Runner left unchanged — the "offerings list is a unit of disagreement" semantic in `ingest/runner.py::_diff_offerings` (line 730–732 comment: collapse-to-list-level diff is intentional for Stage 2) is preserved. **Tests 255 → 263** (8 new — 4 in `test_paths.py`, 4 in `test_resolve.py`).

### Approach decision

Three options laid out for closing the gap: (A) extend resolver to accept column-only paths, runner unchanged; (B) change runner to emit `<column>.<idx>.<leaf>` representative paths; (C) introduce a new `conflict_type` like `offerings_list_disagreement`. **User approved A.** Rationale: B fights the deliberate list-level diff semantic and is lossy when multiple leaves differ; C is cleaner semantically but touches schema + runner + resolver + every test — disproportionate blast radius for a one-row unblock.

### Code changes

- `cli/_paths.py` — module docstring lists four path forms instead of three; `ParsedPath.kind` comment extended; `parse_path` accepts a 1-part offering column path and returns `kind="products_offering_list"`; `read_at_path` adds a branch that returns the whole offerings list. Error message for 2-part / 4-part offering paths now reads `'<column>' or '<column>.<idx>.<leaf>'`.
- `cli/resolve.py` — new `write_offerings` import. `_apply_action`:
  - `accept_candidate` on `products_offering_list`: decode `candidate_value` (the full offerings list with embedded per-leaf provenance bundles — `candidate_provenance` is NULL for this shape, see `runner._enqueue` list-level branch where `existing_bundle` / `candidate_bundle` are None) and call `write_offerings`.
  - `manual_override` on `products_offering_list`: reject with a `SystemExit` that redirects to `manual-edit` on a leaf path.
  - `kept_existing` and `dropped` unchanged (no write to target).

### Test changes

- `tests/cli/test_paths.py` — `parse_path` was previously untested (the file only covered `format_product_pk` / `parse_product_arg`). Added 4 tests: column-only returns the new kind; offering leaf still returns leaf kind; 2-part and 4-part paths rejected with the contract message.
- `tests/cli/test_resolve.py` — added 4 column-level offering tests (one per action). Each seeds a row mirroring `runner._enqueue`'s list-level shape (`existing_value` / `candidate_value` carry the full offerings list; both `*_provenance` columns NULL).

### Doc changes

- `ARCHITECTURE.md` L50 — `field_path` examples row extended with the column-only form.
- `DATA_MODEL.md` not touched — L25's `cpu_catalog.<model>.<column>` is catalog-scope, not products offerings; column-only offering paths don't belong there.

### What this does NOT change

- The runner's list-level diff strategy is preserved. Per-leaf offering diffs remain finicky and out of scope (Stage 2 design intent).
- Row #18 (`legion-pro-7-16-gen-10` `camera_offerings`) is now CLI-resolvable but is **not** resolved in this session — that belongs in the next review-queue cleanup pass.

### Decisions made this session

1. **Option A taken.** Resolver widened; runner untouched.
2. **`manual_override` for column-level rejected, not supported.** Constructing a full list-of-offerings JSON via CLI is not a sensible contract; redirect users to leaf-level `manual-edit`.
3. **`DATA_MODEL.md` L25 unchanged.** Catalog-conflict scope; offering paths don't belong there. ARCHITECTURE.md L50 (canonical `field_path` examples) is the right place to surface the new form.

### Where we left off (pickup pointers)

- **263/263 tests green** (255 pre-session + 8 new).
- Stage 5 CLI gap from Session 20 closed; Deferred item removed from `TASKS.md`.
- Working tree at session close: **clean** after two commits — code+tests+contract doc, then session-docs.
- **Carryforward:** 23 unresolved review_queue rows still open. Row #18 is now CLI-resolvable; pick it up in the next review-queue cleanup pass.
- **Phase 2 (UI) is unscoped.** Stage 8 not yet planned.

---

## Session 20 — 2026-05-11 (Carryforward sweep: fb0023nr retired, camera resolution Option A executed, Stage 5 CLI gap surfaced)

**Goal:** Sweep parked carryforward items in simplicity order, smallest first. Item 1: re-examine "HP Transcend 14 fb0023nr upstream-blocked" (Session 19 L46 / Session 12 Finding #1). Item 2: settle the long-deferred `camera_offerings.0.resolution` unit-mismatch shape question (Session 17 L184, L195; parked since Stage 6).

**Outcome:** Two carryforward items retired, one new architectural finding raised. **(1)** `fb0023nr` confirmed as a phantom SKU (absent from HP's current shop catalog), not upstream-blocked — carryforward retired (no code / DB / test changes for this item). **(2)** Camera resolution shape settled via Option A: vendor megapixels normalized to canonical p-form (`720p / 1080p / 1440p / 4K`) per a 5-value table shared between Lenovo and ASUS bridges. ASUS bridge tightened (was a latent contract violation), Lenovo refactored to use the shared helper (behavior-preserving), MP table lifted to `bridge/helpers.py`. **(3)** New finding: the review_queue resolver CLI requires leaf-level paths (`<column>.<idx>.<leaf>`) but the runner produces column-level offering conflicts (e.g. `camera_offerings`) — row #18 cannot be resolved through the current CLI; deferred as a Stage 5 follow-up. **Tests 253 → 255** (2 new ASUS MP-normalization tests; full suite green; Lenovo refactor confirmed behavior-preserving).

### Investigation

1. **Direct URL probe** (PowerShell `Invoke-WebRequest` from this environment) timed out for both the suspect URL and the known-working `16t-ah100` URL. Inconclusive — environment-level slowness / rate-limiting, not a per-URL signal.
2. **Site-restricted web search of `hp.com` for `fb0023nr`:** zero direct hits — the SKU is absent from HP's current shop, support, and product-family pages.
3. **Open web search for `"fb0023nr" HP OMEN Transcend 14 specs`:** all retailer references (Best Buy, Micro Center, Consumer Reports, Tom's Guide) point to **`fb0023dx`**, the Best Buy / retail-exclusive variant (`dx` suffix). The `nr` variant is unattested anywhere.
4. **Current HP Transcend 14 family on hp.com:**
   - `fb0097nr` — current HP-direct retail variant (32 GB / 2 TB), live at `/shop/pdp/omen-transcend-laptop-14-fb0097nr`.
   - `14t-fb100` — current CTO (configurable) page, live at `/shop/pdp/omen-transcend-14-inch-gaming-laptop-pc-pdk-a88y7av-1`.
   - `fb0023dx` — Best Buy / Micro Center channel, never on hp.com shop.
5. **Re-attribution of the original error.** The Session 12 Finding #1 attribution ("scrapers-lib needs an updated HP PDP handler") was an honest reading of the error message at the time. With the SKU now confirmed phantom, the parsimonious explanation is: HP returned a non-PDP page (landing / redirect / 404-ish HTML), which legitimately lacks the `pdpCTOConfiguration.configurations` JSON block the parser searches for. The parser is functioning as designed — it refuses to coerce a non-PDP into a PDP.

### Camera resolution shape decision — Option A executed

Doc contract in `DATA_MODEL.md` L235 already locked `resolution` as the p-form enum (`720p / 1080p / 1440p / 4K`). Audit confirmed code drift: Dell / HP regex emit p-form only (matches the contract); Lenovo regex accepts MP and normalizes 5 known values to p-form via a local `_MP_TO_P_FORM` table (unknowns fall to `needs-review`); **ASUS regex accepts MP with no normalization at all** — a latent contract violation that would silently write a raw `NMP` string to the DB on any future ASUS PDP that publishes MP. DB state matched the doc for 5/6 products; only `legion-pro-7-16-gen-10` still held `5.0MP` (pre-mapping capture from 2026-05-08); the 2026-05-11 refresh produced candidate `1440p` and the resulting conflict sits in review_queue row #18.

Three options were laid out via output-mockup previews — (A) normalize MP→p, (B) add a sibling `megapixels` leaf for lossless capture, (C) keep MP raw with `needs-review`. **User chose A.** Rationale: doc contract already on p-form, no downstream consumer reads resolution semantically (`views/camera.py` renders strings as-is; `ingest/runner.py` does opaque value-equality), and Option B (sibling leaf) is more surface than YAGNI justifies until something queries on sensor megapixels.

Code changes:
- `bridge/helpers.py` — added `CAMERA_MP_TO_P_FORM` (lifted from Lenovo) and `normalize_camera_resolution(label) -> (value, status)`. Single source of truth for the policy; both bridges call it. Camera section is the third helpers cluster (after unit parsing and chip-brand inference).
- `bridge/lenovo.py` — removed the local `_MP_TO_P_FORM` dict and the inline FHD/HD/UHD/4K/MP branching in `_build_camera_offerings`; replaced with a one-line call to `h.normalize_camera_resolution(m.group(1))`. Byte-identical table; preserved unknown-MP `needs-review` fallthrough; status flag still threaded into `_maybe_bundle`. Refactor only — no behavior delta.
- `bridge/asus.py` — same refactor: inline FHD/HD/UHD/4K/MP branching replaced with the helper call; the `resolution` bundle now takes `status=res_status` so unknown-MP rows can flag `needs-review` (previously ASUS never set status on the resolution leaf — that's the latent-bug fix).
- `tests/bridge/test_asus.py` — added two synthetic-fixture tests mirroring Lenovo's existing camera tests: `test_parse_synthetic_camera_known_mp_value_normalized_to_p_form` (verifies `"2.0MP IR camera"` → `1080p`, `verified`) and `test_parse_synthetic_camera_unknown_mp_value_flags_needs_review` (verifies `"3.0MP IR camera"` → `3.0MP`, `needs-review`).

Doc change:
- `DATA_MODEL.md` L235 — added one-line policy note to the `resolution` row Notes column: `(vendor MP normalized via bridge/helpers.CAMERA_MP_TO_P_FORM; unknown MP → status="needs-review")`.

Test count: **253 → 255**. Both new tests pass; existing 253 unchanged including Lenovo's MP-related tests (`test_parse_synthetic_camera_unknown_mp_value_flags_needs_review`, `test_parse_synthetic_camera_ir_supported`), confirming the Lenovo refactor is behavior-preserving.

### Stage 5 resolver CLI gap (new finding)

Discovered while attempting to resolve review_queue row #18 — the natural follow-through of the camera shape decision. The CLI `python -m competitive_database resolve --id 18 --action accept_candidate` errored:

```
resolve: queue row id=18 has a field_path shape not supported by Stage 5 (offering path must be '<column>.<idx>.<leaf>', got 'camera_offerings').
```

Inspection: row #18's `field_path` is `camera_offerings` (column-level). The runner's conflict detector (`ingest/runner.py`) treats the offerings JSON as opaque value-equality during merge — `_camera_id` aligns offerings by identity but the conflict itself fires at the column level when the resulting JSON arrays differ. The resolver CLI's `accept_candidate` path was built for the per-leaf model (write one provenance Bundle to one leaf inside the JSON) and hard-rejects column-level paths.

Three resolution paths existed: (A) direct SQL bypass — write the candidate JSON to `products.camera_offerings` and mark row #18 resolved manually; (B) defer + document — leave row #18 open as a Stage 5 architectural finding; (C) widen the resolver in this session — extend `accept_candidate` to handle column-level offering paths by writing the full JSON blob. **User chose B.** Rationale: the mismatch is architectural, not row-specific — any future column-level offering conflict (display_offerings, keyboard_offerings, etc.) will hit the same wall — and bypassing the gap with SQL would paper over the right fix. A proper resolver-design pass belongs in a future session, ideally when Phase 2 needs the review_queue workflow live.

Row #18 remains open. The 1440p candidate sits unresolved in queue; DB still holds `5.0MP` on `legion-pro-7-16-gen-10`'s camera_offerings[0].resolution. The shape question is settled (bridge code now enforces p-form across all four vendors), but the specific DB row will only flip to `1440p` once the resolver supports column-level offering paths — or when the user is willing to bypass with SQL.

Added one row to TASKS.md Deferred: `review_queue resolver CLI doesn't accept column-level offering paths (e.g. \`camera_offerings\`) — Stage 5 follow-up (Session 20)`.

### Decisions made this session

1. **fb0023nr retired from carryforward.** Phantom SKU, not an upstream blocker.
2. **Earlier session entries left unchanged.** Session 12 (first report) and Session 13 (deferral) record what we believed at the time; rewriting them would break the append-only / honest-log convention.
3. **No Transcend 14 row added.** Whether to ever ingest one (using a real SKU — `fb0097nr` retail or the `14t-fb100` CTO URL) is a separate scope decision, not in this session.
4. **Camera resolution policy = p-form.** Vendor MP normalized via a shared 5-value table; unknown MP flagged `needs-review`. Option A chosen over Option B (sibling `megapixels` leaf — YAGNI deferred) and Option C (keep MP raw — violates doc contract).
5. **`CAMERA_MP_TO_P_FORM` lifted to `bridge/helpers.py`.** Two-vendor reuse of identical normalization logic justified extraction (matches the existing helpers.py convention for cross-vendor parsing primitives). Lenovo refactor is behavior-preserving (existing tests prove it).
6. **ASUS latent-bug fix:** the resolution bundle now carries `status=res_status` so unknown MP values flag `needs-review` (previously dropped to default `"verified"`).
7. **review_queue row #18 deferred, not resolved.** Stage 5 CLI gap for column-level offering paths surfaced as a new architectural finding (TASKS.md Deferred). Direct-SQL bypass declined.

### Where we left off (pickup pointers)

- Stage 7 closed. Stages 1–7 done; T7.0d deferred.
- **255/255 tests green** (253 pre-session + 2 new ASUS MP normalization tests). Full suite confirms Lenovo refactor is behavior-preserving.
- Working tree at session close: **clean** after two commits — code+tests+contract doc commit, then session-docs commit (see git log for SHAs).
- **Carryforward (updated):** 23 unresolved review_queue rows still open. The `camera_offerings.0.resolution` unit-mismatch **shape question is settled** (Option A executed; bridge code now enforces p-form across all four vendors), but row #18 itself remains open due to the Stage 5 CLI gap (below). **HP fb0023nr retired** (Session 20: phantom SKU; not upstream-blocked).
- **New deferred item:** review_queue resolver CLI doesn't accept column-level offering paths (e.g. `camera_offerings`) — the runner emits these but the resolver requires `<column>.<idx>.<leaf>`. Symptom: row #18 cannot be resolved via CLI. Logged in TASKS.md under Deferred as a Stage 5 follow-up.
- **Phase 2 (UI) is unscoped.** Stage 8 not yet planned.
- **Open question (non-blocking):** whether to ever add a Transcend 14 DB row using `fb0097nr` (retail) or `14t-fb100` CTO. Not currently in scope.

---

## Session 19 — 2026-05-11 (Stage 7 close-out: T7.0d deferred, T7.3 final milestone)

**Goal:** Close Stage 7. Two decisions: (1) defer T7.0d (keyboard structured offerings) rather than implement it; (2) write the final T7.3 milestone so the rolling SESSION_LOG can stop rolling. Doc-only session.

**Outcome:** Stage 7 declared closed. T7.0d marked Deferred in TASKS.md; T7.3 marked Done with this entry as the final milestone. No code changes this session. **Tests unchanged at 253/253 (no source touched, no test run needed).** Working tree dirty on TASKS.md + SESSION_LOG.md (+ a minimal README drift fix) only.

### T7.0d — deferred (reversed from Session 13 Finding #9)

Session 13 Finding #9 scoped the work: split `keyboard_offerings.<idx>.description` into four discrete bundle leaves (`backlight`, `copilot_key`, `layout`, `travel_mm`) across all four bridges (Dell, HP, Lenovo, ASUS), with schema additions and the matching field-paths registry update. T7.0a / T7.0b experience shows that's a ~4-bridge + schema + ingest + ~253-test surface to touch. Payoff would be filterable keyboard data ("which products have a per-key RGB backlight?", "which products ship a Copilot key?"). Reversing here because the payoff isn't clearly real yet — no Phase 2 UI scope locked, no concrete query I want to run today that the free-text `description` blob blocks. Keep keyboard as a single `description` blob for now. Re-openable if/when filterable keyboard data becomes a real need — the Finding #9 scope in `SESSION_LOG.md` Session 13 stands as the restart sketch.

### T7.3 — final milestone (rolling SESSION_LOG closed)

T7.3 was rolling across Sessions 13, 14, 15, 17, 18 — one entry per landed task. This entry is the final milestone: Stage 7 closes here, so the rolling task closes here. Marked Done in TASKS.md.

### Decisions made this session

1. **T7.0d deferred, not done.** Keyboard structured split shelved; `description` blob stays. Reverses Session 13 Finding #9 design intent.
2. **Stage 7 closed.** All remaining tasks either Done (T7.0a, T7.0b, T7.0c, T7.0e, T7.1, T7.2, T7.3, T7.4) or explicitly Deferred (T7.0d).

### TASKS.md compact restructure

Audit caught drift: Stages 1–3 rows were clean (Task / Deliverable / Status one-liners), Stage 4 introduced a Status column, and by Stage 7 the rows had bloated into multi-paragraph entries (80–150 words per row, with rationale + cross-refs + sub-bullets repeating what already lives in SESSION_LOG). User authorized a compact-bullet restructure: **Active / Next / Deferred / Closed stages** instead of per-stage tables. Each closed stage collapses to one line with the close date pulled from the relevant SESSION_LOG heading (Stages 1–5 → 2026-05-07, Stage 6 → 2026-05-08, Stage 7 → 2026-05-11). Phasing principle compressed to one line. **150 → 32 lines, zero info loss** — every rationale already lived in SESSION_LOG, which is the authoritative per-stage detail source (the new closing line `(Per-stage task detail: SESSION_LOG.md)` makes that explicit).

### ASUS `tpp_max` / `tgp_max` verification + DATA_MODEL.md L131 rewrite

`DATA_MODEL.md` L131 carried stale "to be re-verified during the Stage 7 bridge sweep" phrasing for `tpp_max` / `tgp_max`. Verified the ASUS path against the code: `bridge/asus.py::_build_boards()` calls `_extract_asus_tgp()`, which runs `_TGP_MANUAL_RE` first (Manual-mode wattage — the unlocked ceiling) with fallback to `_TGP_TURBO_RE` (Turbo-mode wattage). Per-GPU values are collapsed via `max()` into `tgp_max_by_label` and emitted as a verified bundle per board. `tpp_max` stays `vendor-doesn't-publish` across all four vendors (no vendor exposes board-level TPP). Live test `test_parse_live_boards_merge_by_static_label_max_per_gpu_tgp` confirms the math on real ASUS fixtures. L131 rewritten to credit the Stage 7 T7.0b sweep and name ASUS's Manual-mode + Turbo-mode fallback explicitly; mirrors the Session 7 Lenovo `tgp_max = max-per-board` convention.

### docs/ folder reorganization

Six markdown files moved via `git mv` from repo root → `docs/`: `PRD.md`, `VIEWS.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `SESSION_LOG.md`, `TASKS.md`. **`README.md` stays at root** — GitHub landing-page convention; it's the first file a visitor reads. Six cross-references updated across the moved files: `README.md` retargets to `docs/<file>.md`; intra-`docs/` references go bare (same-dir) or to `../README.md`. The ASCII repo-layout tree inside `ARCHITECTURE.md` (and the matching one in `README.md`) was updated to show the new `docs/` subfolder. No code files reference doc paths at runtime — verified by grep. Two commits landed this session: **`154a9bd`** (Stage 7 close + content fixes — TASKS restructure, DATA_MODEL L131 rewrite, README Status bump) and **`495c879`** (docs/ reorg — `git mv` + cross-ref retargets + tree-diagram updates).

### Where we left off (pickup pointers)

- Stage 7 closed. Stages 1–7 done; T7.0d deferred.
- 253/253 tests green (no code changes this session — no test run needed).
- Working tree at session close: **clean** after both commits (`154a9bd`, `495c879`). All 7 docs cleanly organized: `README.md` at root, the other six under `docs/`.
- TASKS.md now in compact-bullet form (32 lines) and lives at `docs/TASKS.md`.
- **Carryforward (unchanged):** 23 unresolved review_queue rows from Session 17 live drift — Dell aa18250 `storage_slots` 2→1 + `keyboard_offerings` tier consolidation, Lenovo lighting + camera `value_disagreement`, 4 `year_inferred` re-fires across Lenovo + Dell aa18250 + Dell ac16251 + HP 16t-ah100. `camera_offerings.0.resolution` unit mismatch still parked. HP Transcend 14 fb0023nr still upstream-blocked.
- **Phase 2 (UI) is unscoped.** Stage 8 not yet planned.

---

## Session 18 — 2026-05-11 (Stage 7 T7.4: `refresh --from-db` CLI flag)

**Goal:** Close the URL-template gap surfaced by Session 17 — let `refresh` read each product's stored `source_url` directly from the local DB instead of formatting via the hard-coded `DEFAULT_*_URL_TMPL` constants. Removes the "remember the full marketing slug" trap for any product already ingested.

**Outcome:** T7.4 shipped. `cli/refresh.py` gains `--from-db` and `--year` flags. When `--from-db` is set, the CLI loads the product row by `(model_code, year)`, walks every JSON-encoded bundle column on that row, collects the distinct scraped `source_url` values, and loops the existing fetch + ingest path across each URL. Mutually exclusive with `--url`. Manual-only products (no `source_url` anywhere on the row) error with a helpful message. Multi-URL products — specifically Lenovo Intel+AMD merged rows that carry distinct `source_url`s on the per-arch leaves — are handled naturally by fetching each distinct URL once; the existing PK-grouping + `_premerge_lenovo_existing_row` path unions the candidates downstream as it already did at original ingest time. 11 new tests in `tests/cli/test_refresh.py` (5 walker, 6 DB collector). **242 → 253 tests, all passing.** Working tree dirty, no commit.

### What the new flag does

```
refresh --brand <brand> --model <model_code> --from-db [--year <year>]
```

- Skips the per-vendor `DEFAULT_*_URL_TMPL` constants entirely; reads source_url(s) out of `products.<col>` JSON.
- Mutually exclusive with `--url` (the manual-override path is still there for first-time ingests).
- `--year` is required only when the same `model_code` has multiple yearly variants in `products`.
- Errors clearly when the product isn't in DB, has multiple year variants and no `--year`, or has only manual cells (no `source_url` anywhere).

### Implementation shape (all in `cli/refresh.py`)

- **`_walk_source_urls(payload, sink)`** — pure recursive walker over a JSON-decoded column value; appends every non-empty `source_url` string it finds. Caller dedupes. Handles scalar bundles (top-level dict with `source_url`) and offering lists (list of dicts whose values are leaf bundles).
- **`_collect_source_urls_from_product(conn, model_code, year)`** — `SELECT * FROM products WHERE model_code = ? [AND year = ?]`, JSON-decodes each non-null column (plain TEXT columns like `family_code`, `arch_marker`, and `source_model_codes` fall through `json.JSONDecodeError` / `TypeError`), walks each, dedupes preserving order. Raises `SystemExit` with a helpful message on missing product or ambiguous year.
- **`main()`** — branches before the existing `_resolve_url` call. From-db path: opens a short-lived connection, calls the collector, prints `[from-db] fetching <url>` per URL, loops `_fetch_snapshots(brand, url, slug, profiles_dir)` and accumulates snapshots. Slug is derived per URL the same way the existing `--url` path derives it (rightmost path segment after stripping trailing slash). Downstream PK-grouping + ingest loop is untouched.

### Why the walker is schema-blind rather than column-aware

The product row has 50+ columns of mixed shapes — scalar bundle JSONs (`brand`, `audio_jack`, ...), offering-list JSONs (`cpu_offerings`, `display_offerings`, ...), and plain TEXT (`family_code`, `arch_marker`, `source_model_codes`). A column-aware reader would enumerate columns and dispatch on shape. The walker just probes `json.loads` per column and recurses on dicts/lists. Two reasons it's the right call here: (1) shape changes are routine (T7.0a added two plain columns recently), and a schema-blind walker keeps working through future column additions without edits; (2) `source_url` only appears in scraped-bundle dicts — there's no risk of false positives because no other JSON shape in the row uses that key. The plain-TEXT fall-through (`try` / `except (json.JSONDecodeError, TypeError)`) is cheap and explicit; `TypeError` covers the integer `year` column which `json.loads` rejects.

### Lessons and notes

- **Dry-run verification against the live DB:** ran `_collect_source_urls_from_product` against `competitive.db` for all 6 ingested products. Each returns exactly the URL that succeeded in Session 17's manual `--url` override:
  - `aa18250` → `…/alienware-18-area-51-gaming-laptop/spd/alienware-area-51-aa18250-gaming-laptop`
  - `ac16251` → `…/alienware-16x-aurora-gaming-laptop/spd/alienware-aurora-ac16251-gaming-laptop`
  - `16t-ah100` → `…/shop/pdp/hyperx-omen-max-gaming-laptop-16t-ah100-16-cn3g9av-1`
  - `legion-pro-7-16-gen-10` → `…/psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec`
  - `rog-strix-g16-2026` → `https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2026/spec/` (no `/us/`)
  - `rog-zephyrus-g16-2026` → `https://rog.asus.com/us/laptops/rog-zephyrus/rog-zephyrus-g16-2026/spec/` (with `/us/`)

  All 4 Session-17 template-mismatch cases are closed at the read layer.
- **End-to-end live smoke (session-end):** ran `refresh --brand dell --model aa18250 --from-db` against the live Dell page. Output: `[from-db] fetching …/alienware-area-51-aa18250-gaming-laptop`; `3 snapshots; inserted=0 refreshed=48 conflicts=2 low_confidence=0 year_inferred=1`; one note `year=2026 inferred from fetched_at; vendor_full_name flagged needs-review`. The 2 conflicts are the same drift surfaced by Session 17 (`storage_slots` 2→1 + `keyboard_offerings` tier consolidation), untouched by T7.4. **Shortcut confirmed working fetch-to-ingest on Session 17's worst template-mismatch product.**
- Lenovo `legion-pro-7-16-gen-10` currently has only one stored URL (AMD-only ingest); the Intel variant isn't ingested yet (README notes "re-ingest pending" for the Lenovo second product). The multi-URL merge code path is covered by `test_collect_source_urls_multi_url_lenovo_pattern` rather than by live data — it will exercise live once the Intel ingest lands.
- Session 17's `feedback_url_template_check.md` lesson — "verify refresh URL matches DB-stored source_url before claiming scrapers-lib regression" — now has a CLI affordance: `refresh --from-db` *is* that verification step for already-ingested products.
- 23 unresolved review_queue rows still open from Session 17 drift (Dell aa18250 `storage_slots` + `keyboard_offerings`, Lenovo lighting + camera `value_disagreement`, 4 `year_inferred` re-fires). Untouched by T7.4 — side track.
- `camera_offerings.0.resolution` unit mismatch (Lenovo MP vs others' video res) still deferred from Session 17.
- No schema changes, no bridge changes, no ingest changes. All edits localized to `cli/refresh.py` (+ tests).

### Stage 7 status snapshot

- **Done:** T7.0a, T7.0b, T7.0c, T7.0e, T7.1, T7.2, **T7.4 (this session)**.
- **Open:** T7.0d (keyboard structured offerings — bridge-heavy, largest remaining task).
- **Rolling:** T7.3 (SESSION_LOG milestones — this entry counts).

### Pickup pointer for next session

T7.0d. Scope from Session 13 Finding #9: extract `backlight`, `copilot_key`, `layout`, `travel_mm` as discrete bundle leaves across all four bridges (Dell, HP, Lenovo, ASUS); `description` becomes vendor-doesn't-publish or a short normalized line. Schema additions needed. Re-read Session 13 Finding #9 before scoping the bridge work — the `description` policy decision shapes which existing leaf gets retired.

---

## Session 17 — 2026-05-11 (Stage 7 T7.2: end-to-end smoke test across all 4 vendors)

**Goal:** Run live refreshes for all 6 products across all 4 vendor bridges; verify pipeline holds end-to-end; surface drift via `find-conflicts` and `audit-normalize`; document findings.

**Outcome:** T7.2 closed. Pipeline verified healthy end-to-end across all 4 vendors. **All 6 products refresh successfully** when invoked with their correct URLs. Initial run failed 4 of 6 with "page structure may have changed" parser errors; I attributed those to `scrapers-lib` parser regressions and wrote them up as such. User pushed back ("scrapers-lib was working on all these vendor URLs — maybe we are giving incorrect URLs?"). Investigation by reading the stored `source_url` out of DB provenance (`products.brand` bundle JSON) showed the failures were caused by the CLI's hard-coded URL templates in `cli/refresh.py` emitting URLs that differ from what was originally ingested. **Re-running the 4 failures with `--url` overrides using the DB-stored URLs succeeded for all 4.** Scrapers-lib is not regressed. Real T7.2 finding: URL template gap in competitive-database. 242/242 tests unchanged. 15 → 23 unresolved review_queue rows (+8 from live drift across Lenovo + Dell aa18250 + year_inferred refresh re-fires).

### Refresh outcomes (final, after URL correction)

| Product | URL used | Result |
|---|---|---|
| Dell aa18250 | `.../alienware-18-area-51-gaming-laptop/spd/alienware-area-51-aa18250-gaming-laptop` | ✅ 3 snapshots; inserted=5 refreshed=43 conflicts=2 year_inferred=1 (real drift on `storage_slots` and `keyboard_offerings`) |
| Dell ac16251 | `.../alienware-16x-aurora-gaming-laptop/spd/alienware-aurora-ac16251-gaming-laptop` | ✅ 3 snapshots; inserted=0 refreshed=49 conflicts=0 year_inferred=1 |
| HP 16t-ah100 | `.../shop/pdp/hyperx-omen-max-gaming-laptop-16t-ah100-16-cn3g9av-1` | ✅ 3 snapshots; inserted=0 refreshed=45 conflicts=0 year_inferred=1 |
| Lenovo Legion Pro 7 | `Legion_Pro_7_16AFR10H` (template) | ✅ 1 snapshot; refreshed=47 conflicts=2 year_inferred=1; family_code merge confirmed end-to-end |
| ASUS Zephyrus G16 | `rog-zephyrus-g16-2026` (template) | ✅ 1 snapshot; refreshed=51 conflicts=0; clean |
| ASUS Strix G16 | `https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2026/spec/` (no `/us/` prefix) | ✅ 1 snapshot; refreshed=51 conflicts=0; clean |

### The URL template gap (real finding)

`cli/refresh.py` defines four `DEFAULT_*_URL_TMPL` constants. Three of them work only for the *original* product they were designed around:

- **`DEFAULT_DELL_URL_TMPL`** = `…/alienware-18-area-51-gaming-laptop/spd/{slug}` — hard-coded to the Alienware Area-51 line. Bare model code (`aa18250`) doesn't redirect to the full-slug PDP, and the segment is wrong for any non-Area-51 Alienware product. `ac16251` lives at `alienware-16x-aurora-gaming-laptop` with the full slug `alienware-aurora-ac16251-gaming-laptop`.
- **`DEFAULT_HP_URL_TMPL`** = `…/shop/pdp/{slug}` — accepts bare slugs but the landing page returned by `16t-ah100` doesn't carry the same `pdpCTOConfiguration` JSON shape as the full marketing slug PDP (`hyperx-omen-max-gaming-laptop-16t-ah100-16-cn3g9av-1`).
- **`DEFAULT_LENOVO_URL_TMPL`** = `…/Legion/{slug}?tab=spec` — PSREF accepts the bare ProductKey, works as-is.
- **`DEFAULT_ASUS_URL_TMPL`** = `…/us/laptops/rog-zephyrus/{slug}/spec/` — hard-coded to the Zephyrus line *and* with a `/us/` regional prefix. The stored Strix URL doesn't carry `/us/`; whether that's deliberate or vendor-side ambiguity is unclear.

The fix surface: ingest already stores each product's working `source_url` in bundle provenance. A "refresh by stored source_url" CLI subcommand (or a `--from-db` flag) would let returning users refresh existing products without remembering the full marketing slug. Filed as **T7.4 (new)**.

### What the live drift on aa18250 caught

Dell appears to have updated the aa18250 PDP between Session 12's ingest (2026-05-08) and today (2026-05-11):

- **`storage_slots`** existing = 2 slots (Gen4 + Gen5); candidate = 1 slot (Gen4 only). Either a real product change or page restructure.
- **`keyboard_offerings`** existing = 2 tiers (base RGB + CherryMX optional); candidate = 1 tier (base only). Tier consolidation or page restructure.

Both flagged for manual review. Healthy conflict-detection signal — exactly the point of `value_disagreement`.

### Audit-normalize findings (unchanged from initial run)

48 paths flagged with >1 distinct value across the 6 products. Most are genuinely-per-product noise. Two real normalization candidates:

1. **`display_offerings.0.resolution_label`** — 3 products use `WQXGA` (Dell aa18250, Dell ac16251, Lenovo), 3 use `2.5K` (HP, ASUS Strix, ASUS Zephyrus). Both halves of the T7.1 enum-pair, each vendor preserves its own form. **Decision deferred:** keep vendor-preserved form; T7.1 enum-pair doc is the equivalence record.
2. **`camera_offerings.0.resolution`** — 4 products store video resolution (`1080p`), Lenovo stores sensor megapixels (`5.0MP`, now `1440p` after this refresh). Different units, same field. **Deferred:** future camera-leaf shape conversation, not scoped into T7.2.

### Lenovo merge verification (positive signal)

The Lenovo refresh exercised the T7.0a merge path end-to-end against live PSREF: slug `Legion_Pro_7_16AFR10H` (AMD machine code) → bridge derived `family_code = legion-pro-7-16-gen-10`, `source_model_codes = ["16AFR10H"]`, board `arch_marker = amd-radeon` → refresh runner coerced `model_code → family_code` at grouping (`[legion-pro-7-16-gen-10-2026 tiles=Legion_Pro_7_16AFR10H]`) → ingest applied 47 cell refreshes against the existing merged row, captured 2 new value_disagreement rows (PSREF updated lighting label punctuation and camera resolution), re-fired the year_inferred flag. No data loss, no PK collision, no duplicate row. **This is the headline T7.0a verification.**

### Decisions made this session

1. **T7.2 is closed.** Pipeline verified across all 4 vendors with all 6 products refreshing successfully. Conflict detection, family merge, year-inferred flagging, and queue insertion all confirmed end-to-end against live vendor data. Real-page drift captured on Dell aa18250.
2. **URL template gap is filed as T7.4, not retrofitted into T7.2.** The clean fix is a "refresh by stored source_url" CLI subcommand (reads `products.<bundle>.source_url` and uses that, bypassing templates). Templates remain as a convenience for first-time ingests.
3. **`resolution_label` stays vendor-preserved.** No canonicalization. T7.1 enum-pair doc is the equivalence record.
4. **`camera_offerings.0.resolution` unit mismatch deferred.** Future camera-leaf shape conversation.

### Process lesson (saved as feedback memory)

I initially attributed the 4 refresh failures to scrapers-lib parser regressions and wrote that into SESSION_LOG + TASKS.md Deferred without verifying my own URL construction. The user caught it: scrapers-lib had worked on these URLs before, so the regression claim was the wrong default hypothesis. The correct first step was to read each product's stored `source_url` out of DB provenance and compare. The wrong claims were rolled back this session. Saved as `feedback_url_template_check.md` to avoid repeating the mistake.

### Where we left off (pickup pointers)

- T7.2 closed; pipeline declared healthy.
- T7.3 still **Partial** — Session 17 entry adds a milestone; final stage-close milestone pending T7.0d.
- Stage 7 remaining: **T7.0d** (keyboard structured offerings; the largest task left) and **T7.4** (new, small — refresh-by-stored-source_url CLI).
- 242/242 tests green (no code touched this session).
- Live DB state: 6 products, 23 unresolved review_queue rows (+8 from live drift this session — 2 value_disagreement on Lenovo lighting + camera, 2 value_disagreement on Dell aa18250 storage_slots + keyboard_offerings, 4 year_inferred re-fires across Lenovo + Dell aa18250 + Dell ac16251 + HP 16t-ah100). 5 new cells inserted on Dell aa18250.

---

## Session 16 — 2026-05-11 (Stage 7 T7.1: docs polish + Session 15 leftovers)

**Goal:** Close T7.1 (README setup + CLI reference + `resolution_label` enum-pair doc) and fold in the two Session 15 leftovers — PRD doc-sweep status and migration-gotcha surface. Doc-only session.

**Outcome:** T7.1 shipped. 242/242 tests unchanged (doc-only, no code touched). README gained Setup, Upgrading, and Normalization notes sections; CLI commands expanded into a per-CLI CLI reference covering all 9 subcommands. DATA_MODEL.md cross-links `resolution_label` to the README enum-pair table. PRD intentionally untouched — Session 15 tail-point #4 sweep already evaluated and skipped (T7.0a/T7.1 are internal mechanics / reference material, not PRD-level user-visible claims); reconfirmed for T7.1. Migration gotcha (`connect()` does not auto-apply schema; re-run `db-init` after schema pulls) now surfaced in README Upgrading, not only in memory + `apply_schema()` docstring.

### Doc edits that landed

- `README.md` — new sections:
  - **Setup** (after Status): prerequisites (Python 3.12+, `scrapers-lib` sibling layout, optional DB Browser), install (venv + editable installs, PowerShell + POSIX variants), bootstrap (`db-init`), first-refresh + inspect walkthrough.
  - **CLI reference** (replaces brief "CLI commands"): per-CLI subsection (purpose, usage signature, args, example) for all 9 subcommands — `db-init`, `refresh`, `inspect-product`, `find-empty`, `find-conflicts`, `manual-edit`, `resolve`, `audit-normalize`, `backfill-lenovo-families`.
  - **Upgrading**: surfaces the `connect()` non-auto-migrate gotcha; explains the idempotent `apply_schema()` path and the one-time data-backfill CLI pattern.
  - **Normalization notes**: `resolution_label` enum-pair table (FHD ↔ 1080p, WQXGA ↔ 2.5K, UHD ↔ 4K) per Session 13 Finding #6 decision.
- `README.md` — Status headline updated to include T7.0b + T7.1 in shipped list (T7.0b was already in the body but missing from the headline; corrected in-line while updating for T7.1).
- `DATA_MODEL.md` — Display section: `resolution_label` row now carries the enum-pair note and cross-links to README § Normalization notes.

### Session 15 leftovers — resolution

1. **PRD doc-sweep — confirmed skip.** Per Session 15 tail point #4, the doc-alignment agent's judgment that T7.0a is an internal ingestion mechanic, not a PRD-level user-visible feature claim, still holds for T7.1. The PRD scope (goals, target users, success criteria, phase definition) doesn't move when reference material (Setup walkthrough, CLI reference, normalization table) lands. No PRD edit this session.
2. **Migration gotcha — surfaced in README.** Previously documented only in `db/connection.py::apply_schema` docstring and the memory record `migration_gotcha.md`. New users reading the README now see the re-run-`db-init`-after-pull rule before they hit a `no such column` error. The Session 15 decision to leave the auto-migrate gap as-is is preserved — the doc surfaces the boundary, doesn't change it.

### Decisions made this session

- **Setup goes after Status, near the top.** User-first ordering: a reader hitting the README wants to know "what is this" → "how do I run it" before architecture. The project-history Status block stays at the top because it's already structured as the project-state header.
- **CLI reference uses per-CLI subsections, not a single table.** `manual-edit` and `resolve` carry enough flag complexity that a row-per-CLI table would be cramped; per-CLI subsections give room for the usage / args / example block without compressing critical detail.
- **Enum-pair table stays minimal — three confirmed pairs only.** Session 13 Finding #6 named FHD / WQXGA / UHD specifically. Tempting to add QHD+ / UHD+ rows but the canonical list is what's locked; speculative pairs would be premature. Future entries land when a vendor case forces them.

### Where we left off (pickup pointers)

- T7.1 closed. Both Session 15 leftovers folded in and closed.
- 242/242 tests green (doc-only — no code touched, no tests added).
- Memory `project_overview.md` updated: 8 → 9 CLIs; T7.1 moved from open to shipped; Session 16 status header. `MEMORY.md` index line updated.
- Stage 7 still open: **T7.0d** (keyboard structured offerings — bridge-heavy, touches all 4 vendors + schema additions; largest remaining task), **T7.2** (end-to-end smoke test across all 4 vendors), **T7.3** (rolling SESSION_LOG closeout milestones — Session 16 counts as a partial bump but the final stage-close milestone is still pending).
- Next likely task: **T7.0d** if a coding session, **T7.2** if a verification session.
- Uncommitted Session 16 doc edits at session close.

---

## Session 15 — 2026-05-08 (Stage 7 T7.0a: Lenovo multi-URL merge ingest)

**Goal:** Land the Lenovo per-architecture merge ingest design from Session 12 — one `family_code`-keyed product row collapses the Intel / AMD machine-code cousins PSREF publishes separately. Plus the Step 0 caveat fix from Session 14 (drop `boards.{idx}.label` from manual-edit field_paths) on the way in.

**Outcome:** Shipped across 7 commits. 198 → 242 tests (+44 across the chain). T7.0a closed end-to-end: schema migration → bridge parser + arch tagging → runner merge path → one-time backfill CLI → integration bug sweep → plain-leaf manual-edit shape fix.

### Code that landed (commit-by-commit)

- `b4b8b75` **Step 0** (T7.0e) — `views/boards.py::field_paths` no longer includes `boards.{idx}.label`. Addresses the Session 14 caveat: after T7.0c, manual edits to `label` were silently masked at render because the view always synthesizes `MB{ordinal}` from tier-sorted presence order. Dropping the leaf from `field_paths` keeps `manual-edit` honest.
- `04abc56` **M1 — schema migration.** `db/schema.sql` + `db/connection.py::apply_schema` add `products.family_code TEXT` and `products.source_model_codes TEXT` (JSON-array-as-TEXT). Both plain scalars, no bundles. Idempotent ALTER on apply.
- `3bb4b62` **M2+M3 — slug parser + bridge integration.** `bridge/lenovo.py::_derive_lenovo_family_and_arch` parses both compressed (`16IRX10H`) and verbose (`Legion Pro 5 16 Gen 10`) slug conventions, maps the arch token (`IRX` / `IAX` / `ADR` / `ARX` / `AFR`) per board, drops the trailing `H` (Hybrid / discrete-graphics indicator) from `arch_marker` but preserves the original code in `source_model_codes`. New `_LENOVO_FAMILY_LINE_PREFIXES` line allowlist. `bridge/types.py::CandidateProduct` gains `family_code: Optional[str] = None` and `source_model_codes: Optional[list[str]] = None`. Each board dict optionally carries a plain-string `arch_marker`.
- `4ef3544` **M4 — merge runner.** `cli/refresh.py` grouping layer coerces `model_code` → `family_code` when set (legacy path otherwise). `ingest/runner.py::_merge_boards` keys by `(label, arch_marker)`; `_merge_candidates` unions `source_model_codes`; new `_premerge_lenovo_existing_row` handles "AMD ingest arrives after Intel row already exists" by unioning boards + `source_model_codes` into the existing row before the diff path runs. Confirmed no FK references to `products.model_code` exist — using `family_code` as the canonical PK is safe.
- `61c2c84` **M5 — backfill CLI.** New `cli/backfill_lenovo_families.py` subcommand registered in `__main__.py`. Reads Lenovo rows with `family_code IS NULL`, re-derives family + arch from existing bundles, applies in-place updates for singletons or merges multi-row families. Reuses `_merge_boards` + `_merge_offerings` + `_enqueue` from `ingest/runner.py`. Idempotent.
- `ca75ebf` **M6 — integration bug sweep from live smoke.** 4 fixes: `views/load.py::_PLAIN_PRODUCT_FIELDS` extended with the M1 columns (`source_model_codes` gets a JSON-decode arm); `views/boards.py::_BOARD_SCALAR_LEAVES` adds `arch_marker` so `field_paths` exposes it; `views/boards.py::render` surfaces `arch: <value>` per board; `backfill_lenovo_families::_read_lenovo_title_and_url` falls back to brand / segment / status bundle source_urls when `vendor_full_name` is empty.
- `c14b05e` **M7 — arch_marker manual-edit shape.** Direction C: `arch_marker` is parser-derived metadata, peer of `family_code` / `source_model_codes`, kept as a plain string (no bundle). New `_PLAIN_OFFERING_LEAVES` frozenset in `cli/_paths.py` (currently `{("boards", "arch_marker")}`) with `is_plain_offering_leaf` + `write_plain_at_path` helpers; `cli/manual_edit.py` routes plain-leaf paths to `write_plain_at_path`; `write_bundle_at_path` now raises if called on a plain-leaf path (loud-fail). Closes "Direction A vs B vs C" debate.

### Decisions locked this session

1. **`model_code = family_code` for merged Lenovo rows.** PSREF assigns machine codes per architecture (`16IRX10H` vs `16AHP10`); the family is one product. Since `products.model_code` has no FK targets, swapping the PK value to the family slug at grouping time is safe and keeps the merged row addressable by its family identity.
2. **Plain-vs-bundle rule for offering leaves.** Most offering leaves are vendor-published spec values with full provenance bundles; parser-derived identifiers / metadata leaves are plain scalars with no bundle. The registry is `cli/_paths.py::_PLAIN_OFFERING_LEAVES`. Today that's `{("boards", "arch_marker")}`; future parser-derived leaves go in the same set. Peer to the plain-scalar identity columns (`model_code`, `year`, `family_code`, `source_model_codes`).
3. **H suffix is dropped from `arch_marker` but kept in `source_model_codes`.** The H token is metadata about discrete-graphics inclusion, not the architecture itself. Dropping it from `arch_marker` makes the merge key `(label, arch_marker)` correctly collapse cousins; preserving it in `source_model_codes` keeps the source machine code lossless.
4. **Lenovo line allowlist over open parsing.** `_LENOVO_FAMILY_LINE_PREFIXES` is a hard-coded allowlist (Legion Pro 5, Legion Pro 7, etc.). When Lenovo ships a new gaming line, the allowlist needs updating — chosen over open-ended parsing to avoid silent mis-merges on unfamiliar shapes.
5. **Backfill policy is cleanup-now via one-time CLI, not wait-for-next-refresh.** Confirms the design preference from Session 12. The one Lenovo row already in the live DB gets `family_code` populated immediately via `backfill-lenovo-families`, not on the next ingest.
6. **`arch_marker` is editable via manual-edit.** Closes Direction B/C debate. The plain-leaf path machinery (`write_plain_at_path` + `_PLAIN_OFFERING_LEAVES`) makes it a peer-shape edit alongside other parser-derived columns.

### Known follow-ups (not addressed this session)

- **Lenovo line allowlist maintenance burden.** New product lines silently slip through with `family_code = None` unless the allowlist is updated. Acceptable today (Lenovo ships gaming lines slowly) but worth revisiting if the allowlist grows.
- **T7.0d** — keyboard structured offerings; touches all 4 bridges + schema. Still open.
- **T7.1 / T7.2 / T7.3** — README setup + smoke test + rolling SESSION_LOG. Stage 7 close-out.

### Live verification + post-commit tail

After `60fa4c2`, user ran live verification on the production DB:

1. **Migration gotcha discovered.** `python -m competitive_database backfill-lenovo-families` failed against the user's pre-T7.0a DB with `sqlite3.OperationalError: no such column: family_code`. Root cause: `db/connection.py::connect()` opens the SQLite handle but does NOT call `apply_schema()` — only the `db-init` subcommand does. The M6 smoke agent had incorrectly claimed otherwise. Any CLI subcommand that touches the new M1 columns will fail on a pre-T7.0a DB until the user runs `db-init` once.
2. **Decision: leave the auto-migrate gap as-is.** Proposed making `connect()` auto-call `apply_schema()` (one-line fix, ~2 regression tests). User chose to leave the explicit `db-init` step as the migration boundary. The manual step is a known one-time gotcha for upgrading users; the migration itself is already idempotent (`PRAGMA table_info` guard + `ALTER TABLE ADD COLUMN`).
3. **Backfill proof-of-feature.** User then ran `python -m competitive_database db-init` (initialized fine) followed by `python -m competitive_database backfill-lenovo-families`. Output: `16AFR10H -> family legion-pro-7-16-gen-10, arch amd-radeon`. One product updated, zero deleted, zero unchanged. The live DB's Lenovo row is now in the merged shape.
4. **PRD untouched in the docs sweep.** Doc-alignment agent's judgment: T7.0a is an internal ingestion mechanic, not a PRD-level user-visible feature claim. User accepted; no PRD edit this session.

### Where we left off (pickup pointers)

- T7.0a is committed across the 7 SHAs above plus the `60fa4c2` docs sweep plus a Session 15 tail commit. 242/242 tests green.
- Live DB: the existing Lenovo row (`16AFR10H`) was migrated this session to `legion-pro-7-16-gen-10` with board `arch_marker = amd-radeon`. The deferred Lenovo second product can now be re-ingested via the merge path.
- Doc-alignment sweep ran this session — README / ARCHITECTURE / DATA_MODEL / TASKS / SESSION_LOG / VIEWS updated to reflect T7.0a state.
- Next likely task: T7.0d (keyboard structured offerings) or T7.1 (README setup + CLI reference + resolution_label enum-pair doc). T7.0d is bridge-heavy; T7.1 is doc-only.

---

## Session 14 — 2026-05-08 (Stage 7 T7.0c: boards.label per-product ordinal renumbering)

**Goal:** Land Session 13's `boards.label` policy decision as a view-layer rewrite — bridges keep tier labels (MB1/MB2/MB3) for cross-tile merge, view layer renames to per-product ordinals at render time so a product without the top tier shows MB1 + MB2 instead of MB2 + MB3.

**Outcome:** Shipped. 192 → 198 tests. No bridge / ingest / `field_paths` changes; one view module + one test file touched.

### Code that landed

- `views/boards.py` — `render()` now sorts offerings by underlying label tier ascending (MB1 < MB2 < MB3, unmapped `label.value=None` entries last) before assigning ordinals. The label leaf is synthesized as `MB{ordinal} {marker}` for mapped entries; unmapped entries fall back to default `format_leaf` rendering (shows `label:  [?]` from the bundle's needs-review marker, no ordinal consumed). New helper `_label_tier_sort_key` documents the rationale (`_merge_boards` preserves tile-iteration order across candidates, which isn't tier-ascending).
- `tests/views/__init__.py` + `tests/views/test_boards.py` — new test module (first tests targeting view layer directly; previously only exercised via CLI tests). 6 cases: empty, single-board, three-board identity, gap (the ac16251 case), out-of-tier-order bridge emission, and unmapped-board edge case.

### Decisions made this session

- **Sort by tier before renumbering.** Session 13 said "presence order at render time"; literal interpretation breaks if `_merge_boards` lands boards out of tier-ascending order (which can happen since merge preserves tile-iteration order across candidates). Sort-by-tier guarantees the example outcome ("ac16251 shows MB1 + MB2") regardless of upstream emission order. Output is identical when the bridge already emits tier-ordered.
- **Unmapped boards (label.value=None) sort last and don't consume an ordinal slot.** Preserves the "we don't know its tier" semantic — claiming MB1 for an unclassified GPU would falsely imply tier knowledge.

### Caveat surfaced (not addressed)

- `views/boards.py:field_paths()` still includes `boards.{idx}.label` so `manual-edit` lets a user set the label. After this change, any manual label edit is silently masked at render (display always uses synthesized `MB{ordinal}`). Options for next session: (a) drop label from field_paths so manual-edit no longer exposes it; (b) leave as-is on the principle that bridge/refresh always overwrites manual edits next refresh anyway. Not blocking.

### Where we left off (pickup pointers)

- T7.0c committable: 2 files modified / 2 files created (1 empty `__init__.py`), 198/198 tests green. User has not committed yet.
- TASKS.md updated this turn (T7.0c row marked Done; Stage 7 Status line bumped to Session 14).
- README.md "Status" section (lines 6–23) still drifts — folded into T7.1 sweep.
- Next likely task: T7.0a (Lenovo multi-URL merge — schema addition, one bridge) or T7.0d (keyboard structured offerings — schema addition, all 4 bridges). T7.0a is more contained.

---

## Session 13 — 2026-05-08 (Stage 7 T7.0b: bridge bug sweep + CLI ergonomics + 3 policy decisions)

**Goal:** Execute the actionable bridge + CLI fixes from Session 12's 16-finding list (T7.0b), surface the policy items that block remaining fixes, and capture the resulting new tasks.

**Outcome:** T7.0b complete — 7 fixes shipped across ASUS / Dell / Lenovo bridges and 5 CLIs. 172 → 192 tests passing. Three policy decisions resolved (resolution_label, boards.label, keyboard shape) → fold into T7.1 plus two new tasks T7.0c / T7.0d. Two findings deferred (#1 HP upstream-blocked; #3 Lenovo www→psref rolled into T7.0a).

### Code that landed

**Bridges:**

- `bridge/dell.py` — `_populate_design` now marks all 5 Design fields as `vendor-doesn't-publish` when Dell omits the Chassis / Materials section (Area-51 case, Finding #2). NULL meant "we never looked"; VDP means "we looked and Dell didn't publish".
- `bridge/lenovo.py` — Camera resolution: introduced `_MP_TO_P_FORM` mapping (0.9MP→720p, 2.0MP→1080p, 5.0MP→1440p, 8.0MP→4K) so Lenovo's MP form aligns with the p-form Dell / HP / ASUS publish (Finding #5); unknown MP values fall back to raw form with `status="needs-review"`. Lighting field now strips straight + curly double-quote variants via `_clean_lighting()` (Finding #8).

**CLIs:**

- `cli/_paths.py` — added `format_product_pk(model_code, year)` (collapses redundant year suffix; `rog-strix-g16-2026 + 2026 → rog-strix-g16-2026`) and `parse_product_arg(conn, arg, year_arg=None)` (accepts both bare slug and `slug-YYYY` paste form; falls back to whole-arg for ASUS-style baked-in-year slugs).
- `cli/refresh.py` — added `_coerce_vendor_url()` that auto-appends `/spec/` to ASUS URLs (Finding #4); display line uses `format_product_pk` (Finding #12).
- `find-empty`, `find-conflicts`, `inspect-product`, `manual-edit` — all now accept `slug-YYYY` paste form (Finding #11). Scope was `find-empty` + `find-conflicts` only; extended to inspect-product + manual-edit for UX consistency.
- `find-conflicts`, `manual-edit`, `resolve` — display lines use `format_product_pk` (Finding #12 follow-up across CLIs that print product PK).

**Tests:** +20 across `tests/cli/test_paths.py` (new, 11 tests for both helpers), `tests/cli/test_refresh.py` (new, 6 tests), `tests/bridge/test_dell.py` (+1 synthetic Design VDP test), `tests/bridge/test_lenovo.py` (2 updated for normalized output, +2 synthetic for MP fallback + curly-quote stripping).

### Findings status after this session

**Closed:**

- #2 Dell Design gap — fixed.
- #4 ASUS `/spec/` requirement — fixed.
- #5 Lenovo camera MP form — fixed.
- #8 Lenovo lighting quote residue — fixed.
- #11 CLI slug-with-year tolerance — fixed across 4 CLIs.
- #12 ASUS double-year suffix in display — fixed across 4 CLIs.

**Spawned new tasks:**

- #6 display resolution_label drift → T7.1 README enum-pair documentation (decision: accept WQXGA / 2.5K / FHD / 1080p / UHD / 4K as documented synonyms; no bridge normalization).
- #7 boards.label MB tier vs ordinal → T7.0c (decision: switch view-layer to per-product ordinals; bridge tier semantics stay for merge logic).
- #9 keyboard description shape → T7.0d (decision: structure as discrete offerings — `backlight`, `copilot_key`, `layout`, `travel_mm`; description → VDP).

**Deferred:**

- #1 HP `scrapers_lib.tier2.hp.parse_hp_product_page` `RuntimeError` on OMEN Transcend 14 PDP — upstream issue, not a bridge bug. Awaits scrapers-lib fix.
- #3 Lenovo `www.lenovo.com` consumer-shop URL rejection — folds into T7.0a Lenovo merge ingest. Tracked as part of T7.0a scope.

**Still open from Session 12:**

- #10 `year_inferred` cross-contamination in review queue — not addressed this session.
- #13 `anti_glare` enum confirmation — not addressed.
- #14 vendor URL conventions documentation — folds into T7.1.
- #15 keyboard structured offerings — same as #9, now T7.0d.
- #16 Lenovo merge ingest architectural addition — T7.0a.

### Decisions locked this session

1. **resolution_label is a documented enum-pair, not a normalized one.** Vendors publish either form (`WQXGA` / `2.5K`); both stay in the DB as-is. `T7.1` README adds the pair table so consumers know `WQXGA = 2.5K = 2560 × 1600` etc. Rationale: lossless preservation of vendor copy; easier than picking one canonical form and making both vendor camps wrong.
2. **boards.label switches to per-product ordinals at the view layer.** Bridges keep internal MB1/MB2/MB3 tier labels (load-bearing for cross-tile merge — runner unions boards by matching label across tiles). View layer (orchestrator or boards renderer) walks the product's actual boards and renumbers MB1 / MB2 by presence order. Outcome: a Dell ac16251 with no RTX 5070 Ti+ SKU shows MB1 (RTX 5070) + MB2 (RTX 4050) instead of MB2 + MB3, matching naive expectation. Bridge tests stay unchanged.
3. **keyboard description structures into discrete offerings.** Schema gains leaves `backlight`, `copilot_key`, `layout`, `travel_mm`; free-text marketing blob becomes vendor-doesn't-publish (or a short normalized one-liner). Touches all 4 vendor bridges. Resolves the "200-char Copilot legal disclaimer" outlier without truncation.

### Where we left off (pickup pointers)

- T7.0b is committable: 13 files modified / created, 192/192 tests green. User opted to pause for git review + commit.
- TASKS.md and SESSION_LOG.md updated this turn (T7.0b closeout + T7.0c / T7.0d entries + this session entry).
- README.md "Status" section (lines 6–23) still drifts on Stage 7 progress — flagged for next-session sweep alongside T7.1.
- Next likely task: T7.0c (smaller — view-layer rewrite, no schema change) before T7.0d (larger — bridge rework + schema additions). User has not chosen yet.

---

## Session 12 — 2026-05-08 (Stage 6 audit pass + Lenovo multi-URL merge design)

**Goal:** Execute the T6.1 + T6.2 audit pass end-to-end across all 4 vendors. Surface every bridge bug, CLI ergonomic issue, ingest-policy gap, and normalization drift. Close Stage 6 by capturing findings in T6.7; scope fixes into Stage 7.

**Outcome:** Audit phase complete. T6.1 partial-complete at 6/8 products (HP first URL upstream-blocked; Lenovo second deferred pending merge ingest). T6.2 done. T6.7 captures 16 findings spanning bridge bugs, CLI ergonomics, ingest policy, normalization, and one architectural addition (Lenovo's per-architecture model code structure → multi-URL merge ingest). Stage 6 closes here; fixes scoped into Stage 7.

### Refreshes attempted

| Vendor | URL | Result |
|---|---|---|
| Dell | `alienware-area-51-aa18250-gaming-laptop` | ✓ aa18250-2026 |
| Dell | `alienware-aurora-ac16251-gaming-laptop` | ✓ ac16251-2026 |
| HP | `omen-transcend-14-inch-laptop-pc-14-fb0023nr` | ✗ upstream `scrapers-lib` regression on this PDP |
| HP | `hyperx-omen-max-gaming-laptop-16t-ah100-16-cn3g9av-1` | ✓ 16t-ah100-2026 |
| Lenovo | `Legion_Pro_7_16AFR10H` (PSREF, from Stage 3) | ✓ 16AFR10H-2026 |
| Lenovo | `www.lenovo.com/.../len101g0041` (consumer shop) | ✗ bridge requires PSREF host |
| ASUS | `rog-zephyrus-g16-2026/spec/` (Stage 4 row) | ✓ rog-zephyrus-g16-2026 |
| ASUS | `rog-strix-g16-2026/` (no /spec/) | ✗ ASUS bridge needs `/spec/` subpath |
| ASUS | `rog-strix-g16-2026/spec/` | ✓ rog-strix-g16-2026-2026 |

DB final: 6 products, all 4 vendors covered. T6.1 partial-complete at 6/8 (HP first URL upstream-blocked; Lenovo second deferred pending merge ingest).

### 16 findings → T6.7

**Bridge bugs (code fix):**
1. **HP bridge URL-specific PDP regression** — `scrapers_lib.tier2.hp.parse_hp_product_page` raises `RuntimeError: hp: no pdpCTOConfiguration.configurations` on the OMEN Transcend 14 PDP. Other HP URLs parse fine. HP has shifted PDP structure on some products; scrapers-lib needs an updated handler.
2. **Dell Design section gap** — Dell Area-51 has 6 empty Design fields (a/c/d cover materials, thermal_shelf, lighting). Lenovo classifies equivalents as `vendor-doesn't-publish`. Dell bridge isn't reaching the Design section.
3. **Lenovo bridge accepts only `psref.lenovo.com`** — rejects `www.lenovo.com` consumer shop URLs. Either add a shop-page parser or document the constraint loudly in README.
4. **ASUS bridge requires `/spec/` subpath** — landing-page URLs (`rog.asus.com/.../rog-strix-g16-2026/`) fail with zero spec-section matches; `/spec/` URLs parse cleanly. Either auto-append `/spec/` in the bridge or document as URL convention.
5. **Camera resolution unit drift** — Lenovo emits `5.0MP`; Dell/HP/ASUS emit `1080p`/etc. Lenovo bridge stores raw scrape; needs unit-normalization to vertical-pixel form.
6. **Display resolution_label drift** — `WQXGA` vs `2.5K` for the same 2560×1600 panel. Either normalize to one form or accept both as a documented enum.
7. **boards.label off-by-one on Dell ac16251** — labels start at `MB2` instead of `MB1`. Dell parser numbering bug.
8. **lighting field has scrape residue** — embedded quotes in Lenovo `lighting` value (e.g., `"Legion" logo with RGB...`). Bridge isn't stripping quotes.
9. **keyboard description shape inconsistency** — free-text marketing blobs of wildly varying verbosity (one is a 200-char Copilot legal disclaimer). Either cap length, structure as offerings, or accept free-text and document.

**Ingest policy:**
10. **`year_inferred` cross-contamination** — when ingestion infers year from `fetched_at`, *non-conflicting* string fields (e.g., `vendor_full_name`) get routed to review queue alongside the year cell. Confirmed 2/2 on first-touch HP + Dell-2nd refreshes. Pattern: queue should only hold the actually-conflicted cell, not its siblings.

**CLI ergonomics:**
11. **`find-conflicts` and `find-empty` reject `<slug>-<year>`** — they require bare slug. Refresh stdout prints `[<slug>-<year>]`, so users naturally copy that and either get silent empty results (find-conflicts) or a hard error (find-empty). Either accept both forms or print the bare slug at refresh-end.
12. **Model_code double-year suffix** — `rog-strix-g16-2026` slug already contains the year, but the year-suffix logic appends another → `rog-strix-g16-2026-2026`. Suffix logic should detect existing year in slug.

**Enum / schema policy:**
13. **anti_glare values:** `matte` vs `glossy`. Confirm intended enum: `matte | glossy | none`?

**Documentation:**
14. **Vendor URL conventions** — each vendor has a non-obvious URL constraint:
    - Lenovo: must be `psref.lenovo.com`, not `www.lenovo.com`
    - ASUS: must include `/spec/` subpath
    - HP: PDP URLs work, but some products have drifted structurally
    - Dell: `--model <slug>` works against `dell.com/.../spd/<slug>`
    Belongs in README under "Refreshing products."

**Architecture / design (deferred):**
15. **`year_inferred` confidence vs cell-level routing** — see #10. Deserves a separate ingest-flow review.
16. **Lenovo multi-URL merge ingest** — full design captured below. Defer to Stage 7+.

### Lenovo multi-URL merge design (T6.7 finding #16)

Lenovo splits per chip-architecture, with each architecture published as its own PSREF model code. To represent "Legion Pro 5 Gen 10" as a single product (matching user's mental model), need to merge multiple PSREF URLs into one product row. Schema *can* hold this (boards array supports cross-architecture variants); ingest is the missing piece.

**Slug parser (right-to-left scan, regex):**

```text
PSREF slug pattern:  <Line>_<Size><Arch><Gen>[Suffix]

  Trailing digits   → gen
  Letters before    → architecture (IRX = Intel+RTX, ADR = AMD+Radeon-discrete,
                                    IAX = Intel+AMD-GPU, ARX = AMD+RTX, AFR = ?, ...)
  Digits before     → screen size
  Everything before → product line

Family code:  <line>-<size>-gen-<gen>  (lowercase, hyphens)

Examples:
  Legion_Pro_5_16IRX10  → family: legion-pro-5-16-gen-10  arch: intel-rtx
  Legion_Pro_5_16ADR10  → family: legion-pro-5-16-gen-10  arch: amd-radeon
  Legion_Pro_5_16IAX10  → family: legion-pro-5-16-gen-10  arch: intel-amd-gpu
  Legion_Pro_5_16ARX8   → family: legion-pro-5-16-gen-8   arch: amd-rtx  ← gen 8, separate family
```

**Two slug conventions exist:** compressed (`Legion_Pro_5_16IRX10`) and verbose (`Legion_Pro_7i_Gen_10`). Verbose splits cleanly on `_Gen_`. Parser handles both.

**Trailing letter suffixes** (e.g., `H` in `Legion_Pro_7_16AFR10H`) — meaning unknown without sampling. Default: treat as part of architecture marker until catalog sampling clarifies.

**Append flow:**

```text
refresh --brand lenovo --url <url> [--year <yyyy>]
  ↓
parse slug → derive family_code + arch
  ↓
does a product row with this family_code exist?
  ├─ yes → append new URL's snapshot to existing row
  │         · boards.append (with arch attribution)
  │         · display_offerings, memory_offerings, etc. = union (deduped)
  │         · dimensions, weight, etc. usually identical (same chassis); conflict→queue
  │         · year already set; no re-prompt
  └─ no  → create new product row
            · prompt for year if not passed (or auto if URL has gen→year hint)
```

**Schema additions:**

```text
products
  + family_code:        TEXT   (e.g., 'legion-pro-5-16-gen-10')
  + source_model_codes: JSON   (array, e.g., ['16IRX10', '16ADR10', '16IAX10'])

boards (already array)
  + arch_marker:        TEXT   (e.g., 'intel-rtx', 'amd-radeon') — within-family attribution
```

**First-time UX:** CLI prints derived family code + existing-row contents and asks "append? [y/N]" before merging. Avoids silent surprises while the rule beds in.

**Validation gate:** sample ~30 PSREF slugs across Legion / IdeaPad / ThinkPad lines and validate the regex covers them. Edge cases fall back to a manual `--family` flag.

**Effort:** 1–2 sessions. Slug parsing: ~half a session (regex + tests). Merge ingest + conflict policy + CLI ergonomics: bulk of remaining time.

**Scope:** Lenovo only. Other vendors stay on the existing single-URL ingest path.

### Decisions locked this session

1. **T6.1 declared partial-complete at 6/8.** HP first URL upstream-blocked (scrapers-lib regression); Lenovo second product deferred pending merge ingest. T6.1's job is bug-hunting, not collection completeness.
2. **T6.2 done.** No vocabulary drift on Wi-Fi / DDR5 / MT-s fields; 6 normalization issues surfaced (#5–9, #13) and rolled into T6.7.
3. **Lenovo multi-URL merge ingest deferred to Stage 7.** Design captured here. Schema *can* hold it; ingest is the missing piece. Not the right call mid-Stage 6.
4. **`family_code`** to be added to product schema as part of merge ingest work. Lowercase, hyphenated form.
5. **Audit phase exit criterion:** Stage 6 closes once T6.7 captures findings (this session). T6.7 is "documented gaps," not "fixed gaps" — fixes happen in Stage 7+.

### Next session recommendation

Move to Stage 7 with two priority items: (1) Lenovo multi-URL merge ingest (design above), (2) bridge bug sweep across findings #1-9, #11-12. Remaining Stage 7 polish (T7.1 README, T7.2 smoke test, T7.3 milestones) follows naturally.

---

## Session 11 — 2026-05-08 (validation map + Stage 6 kickoff)

**Goal:** Open Stage 6 — validation pass per `TASKS.md` §Stage 6. Identify which T6 deliverables are already covered by existing unit tests vs which need new live work; build any automation gap; hand off the live portion as a concrete checklist.

**Outcome:** Stage 6 partially closed. T6.3 / T6.4 / T6.5 / T6.6 cross-checked against the existing test suite — all four are validated by tests that pre-date Stage 6, so they need no new code. T6.2 helper (`audit-normalize` CLI) shipped; runs after T6.1 lands more products. T6.1 (live sample-audit) is genuinely manual work, prepared as a refresh checklist below for the user to drive at their pace. T6.7 (DATA_MODEL.md gap doc) waits on T6.1 + T6.2 findings — current `DATA_MODEL.md` is up to date through Session 8 chip-spec seeding. 166 → 172 tests passing.

### What was built / changed

- **`cli/audit_normalize.py` (new)**, wired into `__main__.py`. Walks every product in the DB, collects per-path distinct value sets via `views/orchestrator.all_field_paths`, and (by default) prints only paths with 2+ distinct value strings — the gap surface. `--all` prints every filled path. `--strings-only` filters out numeric/boolean values (normalization issues live in strings). `vendor-doesn't-publish` bundles are skipped (they don't carry a real value). Output groups by path; for each path, sorts values by descending product count and lists which products carry each value.
- **`tests/cli/test_audit_normalize.py` (new, 6 tests)**. Covers: gap detection (`Wi-Fi 7` vs `WiFi 7` → flagged), uniform-data short-circuit (no gaps message), `--all` mode, offering-leaf aggregation across products at the same index, `vendor-doesn't-publish` exclusion, empty-DB short-circuit.
- **`TASKS.md` §Stage 6**. Marked T6.3 / T6.4 / T6.5 / T6.6 as Validated with explicit references to the existing tests covering each. Status line at the top of the stage describing the Session 11 audit. T6.1 / T6.2 / T6.7 remain Pending with succinct status.

### Stage 6 coverage map (Session 11 audit)

Recon evaluated each T6 deliverable against the existing test suite. Findings:

- **T6.3 — Conflict logic.** Covered. `tests/ingest/test_runner.py::test_ingest_value_disagreement_enqueues` exercises the full path: existing `memory_max_gb=32` cell + candidate `=64` snapshot → the existing value is preserved on `products`, a `review_queue` row is created with `conflict_type='value_disagreement'`, `field_path='memory_max_gb'`, candidate bundle attached. Catalog conflict path covered separately by `tests/ingest/test_catalog_resolve.py::test_chip_specs_overwrite_and_queue_when_needs_review_cell_disagrees` for the chip-spec seeding flow (Session 8 amendment to Decision 4). The Stage 5 `resolve` CLI pulls from this same `review_queue` shape.
- **T6.4 — Low-confidence routing.** Covered. `tests/ingest/test_runner.py::test_ingest_needs_review_candidate_skips_db_and_queues` verifies `status='needs-review'` candidates do NOT write to `products` (post-write `read_scalar` returns `None`) and DO insert a `review_queue` row with `conflict_type='low_confidence_extraction'`. Offering-list variant (`::test_ingest_product_keeps_needs_review_offering_separate`) covers the case where a single needs-review leaf inside an offerings list pushes the entire list to queue-only.
- **T6.5 — Manual-edit nested field.** Covered by Stage 5: `tests/cli/test_manual_edit.py::test_manual_edit_writes_offering_leaf` writes `display_offerings.0.nits_peak` on a tmp DB and verifies the bundle lands at the right offering index, the sibling leaf is untouched, the `entered_by` provenance is set.
- **T6.6 — HP tier base/optional.** Covered. `tests/bridge/test_hp.py::test_parse_live_keyboard_tier_flags_base_and_optional` asserts `[0]["tier"]["value"] == "base"` and `[1:]` are `"optional"` against the live OMEN Transcend 14 fixture. Synthetic counterpart at `::test_parse_synthetic_keyboard_first_line_is_base_rest_optional`. The implementation routes through `bridge/helpers.py:tier_for_index(idx)` which is `"base" if idx == 0 else "optional"`.

### T6.1 live-refresh handoff (user drives)

Stage 6's T6.1 says "refresh 2 products per vendor; cross-check populated cells against the actual vendor pages by hand." The live DB currently has 1 product (ROG Zephyrus G16 2026). To meet T6.1 we need 1 additional product per vendor refreshed, then the populated cells cross-checked against the vendor's actual spec page.

Suggested second products per vendor (pick whichever current model is easiest to find on the vendor's site — these are starting points, not constraints):

- **Dell.** Already has Alienware Area-51 (the Stage 2 / fixture target) but no product currently sits in the live DB. Refresh it once to seed the DB. Then add one more Dell gaming laptop — typical candidates: Alienware m18, Alienware m16, or another Alienware Area family SKU.
  ```
  python -m competitive_database refresh --brand dell --model alienware-area-51-aa18250-gaming-laptop
  python -m competitive_database refresh --brand dell --url <full URL of second Dell product>
  ```
- **HP.** OMEN Transcend 14 is the existing target. Refresh it first to seed live DB; then a second OMEN product (OMEN 17, OMEN MAX 16, or another current OMEN gaming laptop).
  ```
  python -m competitive_database refresh --brand hp --url https://www.hp.com/us-en/shop/pdp/omen-transcend-14-inch-laptop-pc-14-fb0023nr
  python -m competitive_database refresh --brand hp --url <full URL of second HP product>
  ```
  (Use `--url` rather than `--model` — HP slugs are not stable enough to predict.)
- **Lenovo.** Legion Pro 7 16AFR10H (the AMD cousin captured in Session 7) is the existing target. Refresh it; then a second Legion product. Carry-over: the Intel Pro 7i Gen 10 may now be on PSREF — if it is, capture it as the second product. Otherwise pick a Legion Pro 5 or Legion Slim variant.
  ```
  python -m competitive_database refresh --brand lenovo --model Legion_Pro_7_16AFR10H
  python -m competitive_database refresh --brand lenovo --url <PSREF URL of second Lenovo product>
  ```
- **ASUS.** ROG Zephyrus G16 2026 is already in the DB — second ASUS product is the new one. Typical candidates: ROG Strix G16 / G18 2026, ROG Flow Z13, ROG Zephyrus G14 2026.
  ```
  python -m competitive_database refresh --brand asus --url <full URL of second ASUS product>
  ```
  (Use `--url` because the line segment in the path varies — `rog-zephyrus`, `rog-strix`, `rog-flow`.)

After each refresh, sanity-check with the Stage 4 / 5 helpers:

```
python -m competitive_database inspect-product <model_code>
python -m competitive_database find-empty --product <model_code>
python -m competitive_database find-conflicts --product <model_code>
```

Cross-check is the manual part. For each populated cell on each product:

1. Open the vendor spec page in a browser side-by-side with `inspect-product` output.
2. For every `[verified]` cell, eyeball-confirm the value matches the page. Look especially at: CPU model name, GPU model name(s), TGP/TDP wattages, RAM speed (MT/s), display resolution + nits + refresh rate, port counts, weight + dimensions.
3. Note any disagreement. If the cell on the page matches what's stored, it's good. If it differs, that's a real bug — either bridge parsing or scrapers-lib upstream. Open a SESSION_LOG.md note in the next session covering it.
4. Pay attention to `[?]` (needs-review) markers — those are the scraper saying "I'm not confident here." For each, decide whether to vouch (use `manual-edit`) or downgrade to `vendor-doesn't-publish` if the page truly omits it.

Then run T6.2:
```
python -m competitive_database audit-normalize
```
Any gaps surfaced (paths with 2+ distinct value strings) likely point to a bridge inconsistency between vendors — e.g. `wifi_standard` written as `"Wi-Fi 7"` by one bridge and `"WiFi 7"` by another. Fixes go in the per-vendor bridge module, not in a normalization layer (no schema lock-in for surface variants).

T6.7 follows: any DATA_MODEL.md gaps surfaced during T6.1 / T6.2 cross-checks get documented before declaring Stage 6 closed.

### Course corrections worth remembering

- **Stage 6 is mostly already-validated.** First reflex was to plan new automated tests for every T6 task. The recon agent found that T6.3 / T6.4 / T6.5 / T6.6 are all already covered by tests that pre-date Stage 6. Stage 6 is fundamentally a *manual* validation pass against real vendor pages — the unit tests prove the logic is right, the manual pass proves the data the logic produces is right. Future stages with similarly-named "validation" tasks should start with a coverage audit before authoring new tests, since a lot of the behavior is already exercised by the lower-level test suites.
- **Helper-vs-script for one-off audits.** `audit-normalize` is technically a one-off (run after T6.1 lands more products, then maybe again quarterly). But the helper is cheap (~140 LOC including subparser + tests) and reuses the existing `views/orchestrator.all_field_paths` registry, so it's a consistent shape with the other Stage 5 helpers (`find-empty`, `find-conflicts`). The future admin UI gets the same surface for free. Defaulted to "build the helper, don't write a one-off script."
- **`audit-normalize` defaults to gaps-only, not `--all`.** First sketch was to print every filled path with its values. With 8+ products that's a wall of output and the gap signal drowns. Defaulted to printing only paths with 2+ distinct values. `--all` is the escape hatch when the user wants the full distribution. Important because the noise-to-signal ratio of an audit tool determines whether the user actually runs it.

### Where we left off (pickup pointers for next session)

- **T6.1 — user-driven.** When the user runs the second-product refreshes per the checklist above, the next session can do the cross-check pass + run `audit-normalize` + collect any DATA_MODEL.md gaps for T6.7.
- **`audit-normalize`** ready to run now (will print "no gaps across 1 product"; not useful until T6.1 lands more products).
- **Three live `review_queue` rows on `competitive.db`** (unchanged from Session 10) — still unresolved, still 4-level `boards.N.gpus.M` paths. Stage 5's `resolve` errors out cleanly on those; their resolution is the "catalog-vouching" workflow deferred past Stage 6.
- **`scrapers-lib` ASUS display gap** still open upstream (refresh rate / HDR cert / nits / VRR / response time / DCI-P3 / sRGB live in marketing-highlights `<ul>`, not the structured `Display` h2). Visible via `find-empty` on the ROG row as `[—]` markers. Decision deferred: chase upstream or fill manually. Not a Stage 6 blocker — `find-empty` already surfaces it.
- **DATA_MODEL.md** confirmed current through Session 8. T6.7 will revisit only if T6.1 / T6.2 surface a real schema gap.

---

## Session 10 — 2026-05-07 (implementation)

**Goal:** Close Stage 5 — operational CLI helpers (`find-conflicts`, `find-empty`, `manual-edit`, `resolve`). All four are thin wrappers over Python functions the future UI will call (Decision 5 from Session 3). One open architectural call from Session 9: expose the per-category `(label, key)` tuples as a public registry so `find-empty` doesn't duplicate them.

**Outcome:** Stage 5 closed. All four CLI helpers shipped + wired into `__main__.py`. Each views module gained a `field_paths(product)` helper, exposed centrally via `views/orchestrator.all_field_paths()`. 18 new happy-path tests under `tests/cli/`; total suite 148 → 166 passing. One user format decision resolved: `find-empty` output is grouped-by-section (mirroring `inspect-product`'s 16-section structure), not a flat path list. No schema changes. No DB writes against the live `competitive.db`.

### What was built / changed

- **`views/<category>.field_paths(product)`** in all 16 view modules + an `_identity_field_paths` in `views/orchestrator.py`. Each returns `list[(field_path, display_label)]`. Offerings sections walk the existing offerings list and emit per-leaf paths (`display_offerings.0.nits_peak`, `boards.0.tgp_max`, etc.); scalar sections emit one entry per column. Boards excludes the `gpus` array (its 4-level path shape isn't yet supported by `manual-edit`/`resolve`); CPU and Boards both exclude catalog leaves (those live in `cpu_catalog` / `gpu_catalog` and aren't fillable on the products row).
- **`views/orchestrator.all_field_paths(product) -> list[(section_name, field_path, display_label)]`.** Iterates a `_SECTION_REGISTRY` whose order mirrors `render_product`. The single source of truth for "every fillable cell on a product, in inspect-product order."
- **`cli/_paths.py`** (new). Shared dotted-path helpers for `manual-edit` and `resolve`. `parse_path()` recognizes three forms: products scalar (`audio_jack`), products offering leaf (`display_offerings.0.nits_peak`), and catalog text (`cpu_catalog.<model>.architecture`). PK columns and malformed paths raise `ValueError`. `write_bundle_at_path()` reuses `db/helpers.write_scalar` / `write_offerings`. `write_catalog_text_at_path()` runs an `INSERT ... ON CONFLICT(model) DO UPDATE` for catalog tables.
- **`cli/find_empty.py`.** `--product <slug>` (with `--year` disambiguator) or `--all`. Loads the product, walks `all_field_paths`, classifies each leaf as `empty` (None) / `vendor doesn't publish` (bundle status) / filled, prints only the missing ones grouped by section. Summary line at the bottom: `N missing across M section(s)`. Live test against the ROG Zephyrus G16 row found 23 missing (3 empty, 20 vendor-doesn't-publish) — mostly the ASUS display gap (refresh rate / HDR cert / nits / VRR / response time / DCI-P3 / sRGB) plus design / thermals fields ASUS doesn't publish on the structured spec page.
- **`cli/find_conflicts.py`.** `--product <slug>` filter, otherwise lists every unresolved row. Output is one block per row: id, product PK, conflict type, field path, existing/candidate one-line summaries, detected_at. Live test surfaced the three existing rows (all `new_chip_unverified` over `cpu_offerings.0.model`, `boards.0.gpus.0`, `boards.0.gpus.1`).
- **`cli/manual_edit.py`.** Required: `--product`, `--field`, and exactly one of `--value` / `--value-json`. Optional: `--year`, `--note`, `--status` (default `vouched`), `--entered-by` (default `$USER` / `$USERNAME`). Builds a manual-provenance bundle via `db.helpers.make_manual_bundle`, writes it via `_paths.write_bundle_at_path`, prints a before/after diff. Catalog paths rejected with a clear message (catalog cells are plain text, no provenance scaffolding to apply).
- **`cli/resolve.py`.** `--id` (review_queue.id) and `--action` (one of `accept_candidate` / `kept_existing` / `manual_override` / `dropped`). All four actions run inside a single `transaction(conn)`. `accept_candidate` decodes `candidate_provenance` and writes it as the new bundle (or for catalog paths, decodes `candidate_value` and writes it as plain text). `manual_override` builds a fresh manual bundle (or plain text for catalog) from `--value` / `--value-json`. `kept_existing` and `dropped` don't touch the target cell. The queue row update sets `resolved_at`, `resolution`, `resolution_value`, `resolver_note`. Errors out cleanly on missing id, already-resolved rows, missing `--value` for `manual_override`, and 4-level paths from `new_chip_unverified` rows (catalog-vouching workflow, deferred).
- **`__main__.py`.** Removed the four-helper placeholder comment; wired `find_empty.add_subparser`, `find_conflicts.add_subparser`, `manual_edit.add_subparser`, `resolve.add_subparser`.
- **`tests/cli/`** (new directory). Four test modules covering happy paths and rejection paths:
  - `test_find_empty.py` (2 tests) — grouped output + clean-product short-circuit.
  - `test_find_conflicts.py` (3 tests) — unresolved-only, product filter, empty queue.
  - `test_manual_edit.py` (6 tests) — scalar write, int coercion, JSON-bool, offering-leaf write, catalog-path rejection, PK-path rejection.
  - `test_resolve.py` (7 tests) — all four actions roundtripped, already-resolved rejection, missing-id rejection, manual-override-without-value rejection.

### Decisions resolved this session

- **`find-empty` output format = grouped by section.** Two output mockups framed (flat dotted-path list / grouped by inspect-product section). User chose grouped — matches the mental model of `inspect-product` and prioritizes scannability over copy-paste-into-`manual-edit` ergonomics. Trade-off accepted: users reconstructing the full path for `manual-edit` need to combine the section's offerings-column name with the displayed `offering N - <key>` label.
- **`(label, key)` tuples → per-module `field_paths(product)` registry.** The Session 9 carry-over question. Picked the per-module-helper option over a centralized registry module: keeps labels colocated with the per-category render code and avoids a new module that would have to be kept in sync. The orchestrator's `_SECTION_REGISTRY` is the only central thing — and it's just a list of `(section_name, callable)` pairs that mirror `render_product`'s order, so editing one without the other is loud (a missing module would `AttributeError` in tests on import).
- **Boards `gpus` array excluded from `field_paths`.** The path shape `boards.N.gpus.M` is 4 levels deep (column → board idx → array key → bundle idx), not the 3-level pattern `parse_path` recognizes. Adding 4-level support is a Stage 6+ extension; for now `field_paths` skips the `gpus` array and `manual-edit`/`resolve` reject the path with an explicit "deferred to a later stage" SystemExit. The three existing `new_chip_unverified` queue rows on `competitive.db` are exactly this shape.

### Course corrections worth remembering

- **The harness's "did-you-Read-this-file" check is per-Claude-instance, not per-codebase.** When sub-agents read a file and report verbatim, that read is in the agent's context, not the parent's. Edits in the parent then fail with "File has not been read yet." Workaround: parent re-reads each file before editing, even if a delegated agent has already returned its content. Bit of duplicated I/O cost, but it's the rule. Not a project decision — just a workflow note for future implementation sessions that lean on Explore agents for bulk recon.
- **CLI test convention = call `main(argparse.Namespace(...))` directly, not subprocess.** Avoids the cold-start cost and gives clean stdout capture via `capsys`. Each Stage 5 test constructs the Namespace with all fields the parser would have set — including the ones a CLI user would normally not set explicitly (e.g., `value_json=None` when passing `--value`). Required because `mutually_exclusive_group` doesn't auto-default the unset side. Cheap enough that the explicit `Namespace` is fine.
- **Exit criterion language vs reality.** Stage 5's exit criterion says "a real conflict can be resolved end-to-end via `resolve`." The 3 live conflicts on `competitive.db` are all `new_chip_unverified` over 4-level paths — that's the *catalog-vouching* flow, not the *value_disagreement* flow Stage 5 was scoped for. The criterion is met by the test suite (synthetic value_disagreement row resolved through all four actions), not against the live DB rows. The user can produce a live value_disagreement by editing a cell manually then re-running `refresh` (Stage 6 task T6.3 is exactly this).

### Where we left off (pickup pointers for next session)

- **Stage 6 — validation pass.** Per `TASKS.md` §Stage 6: T6.1 sample-audit (refresh 2 products per vendor, cross-check by hand), T6.2 normalization audit (distinct values per categorical field), T6.3 conflict-logic test (manual edit + re-refresh produces a real `value_disagreement` queue row), T6.4 low-confidence test, T6.5 manual-edit nested field test (Stage 5 `manual-edit` already covers this — re-validate against live data), T6.6 HP tier test, T6.7 update `DATA_MODEL.md` with any schema gaps surfaced. T6.3 will produce the first live value_disagreement queue row, giving an end-to-end live test of `resolve --action accept_candidate`.
- **Catalog-vouching flow (4-level paths)** stays deferred. Three live `new_chip_unverified` rows currently can't be resolved via `resolve`. Either extend `parse_path` + `field_paths` to support 4-level paths (boards.N.gpus.M as a top-level bundle in an array), or build a separate `vouch-chip` helper that targets `cpu_catalog` / `gpu_catalog` directly. Lean toward the second — the catalog-vouching workflow is conceptually distinct (decision is "is this chip real / is its name canonical" rather than "is this value correct").
- **Live `competitive.db` state unchanged.** No DB writes in Session 10 — all Stage 5 validation went through `tests/cli/` against tmp DBs. The single ROG Zephyrus G16 2026 row + 3 unresolved chip-stub queue rows from Session 8 still stand. Carry-over Lenovo Intel Pro 7i Gen 10 refresh and `scrapers-lib` ASUS display gap unchanged from Session 9.

---

## Session 9 — 2026-05-07 (implementation)

**Goal:** Close Stage 4 — view layer + `inspect-product` CLI per `TASKS.md` Stage 4. Mid-stage checkpoint cadence (Session 8 recommendation): pause after the orchestrator + 2–3 representative views land, lock format choices with the user, then bulk-roll out the remaining 13 categories.

**Outcome:** Stage 4 closed. View layer shipped end-to-end; `inspect-product rog-zephyrus-g16-2026` prints the full status-marked, catalog-enriched dump of the live ASUS Zephyrus G16 row. 148/148 tests still pass (no regressions). Three user format decisions plus one catalog-marker default resolved at the mid-stage checkpoint. One integration-time bug caught (`storage_slots` was offerings-shaped, not scalar). One Windows-specific encoding fix landed. `VIEWS.md` written; `ARCHITECTURE.md` gained a §View layer section.

### What was built / changed

- **`views/formatting.py`.** Six-marker scheme: `[verified]` (scraped + verified), `[?]` (scraped + needs-review), `[—]` (vendor-doesn't-publish), `[m]` (manual, any sub-status — `vouched` or `needs-review`), `[empty]` (cell never written), `[partial]` (aggregate marker for mixed leaves). Distinguishes scraped vs manual bundles by presence of `entered_by` key (manual) vs `scraper_id` key (scraped). Helpers: `marker_for_bundle`, `aggregate_markers`, `display_value` (handles `vendor-doesn't-publish` placeholder text + boolean `yes/no` rendering), `format_leaf` (one-line `label: value [marker]` or `label: [empty]`), `section_heading`, plus `render_scalar_section` for the all-scalar categories.
- **`views/load.py`.** Per-product DB read path. Decodes every column on the products row into bundle / offerings-list / plain PK value. `_OFFERINGS_FIELDS` enumerates the 8 offerings columns (cpu_offerings, boards, display_offerings, battery_offerings, keyboard_offerings, **storage_slots**, adapter_offerings, camera_offerings). `resolve_year` disambiguates when one model_code has multiple yearly variants. Plus `load_cpu_catalog` / `load_gpu_catalog` (bulk reads keyed by `model`); only `brand` is decoded as a bundle, other catalog spec columns are plain TEXT.
- **`views/orchestrator.py`.** Composes 16 per-category renders in a fixed order: identity, CPU, boards, memory, storage, display, keyboard, camera, audio, network, I/O, battery, adapter, thermals, dimensions, weight, design.
- **16 per-category render modules.** `cpu.py` and `boards.py` carry catalog enrichment (cpu_catalog / gpu_catalog lookups; brand bundle marked, plain catalog spec cells unmarked). `memory.py` carries the soldered-RAM `slots = 0` → `"soldered (0)"` rendering. `display.py` / `battery.py` / `keyboard.py` / `camera.py` / `adapter.py` are offerings-list renderers. `storage.py` is offerings-list (per-slot PCIe gen) plus a scalar `storage_max_gb`. The seven all-scalar categories (`network`, `io`, `audio`, `thermals`, `dimensions`, `weight`, `design`) reuse `render_scalar_section`.
- **`cli/inspect_product.py`.** Thin subcommand wired into `__main__.py`. Positional `model_code` argument; `--year` disambiguator; `--db` override. Calls `sys.stdout.reconfigure(encoding="utf-8")` (try/except for cross-platform safety) before printing so the em-dash `[—]` and the `×` in resolution strings render cleanly on Windows (default cp1252 mangles them).
- **`__main__.py`.** Removed the `inspect-product` placeholder comment; wired the new subparser via `inspect_product.add_subparser(sub)`. `resolve` / `manual-edit` / `find-empty` / `find-conflicts` remain on the placeholder list for Stage 5.
- **`VIEWS.md`.** Captures the marker scheme, section-layout choices, the `storage_slots` offerings-shape gotcha, and the Windows-encoding fix.
- **`ARCHITECTURE.md` §View layer.** New section between `Repo layout` and `Forward compatibility`. Module layout, load-bearing section conventions, the marker-decision logic, CLI summary. Repo layout tree also updated to include the new `views/` package and `cli/inspect_product.py`. Top-level doc list updated to include `VIEWS.md`.
- **Live verification.** `python -m competitive_database inspect-product rog-zephyrus-g16-2026` produces a 16-section dump with markers on every leaf. Identity block shows all 6 fields including `[empty]` for `status` / `segment`. CPU section enriches Core Ultra 9 386H from the catalog (cores=16, npu_tops=50, brand=Intel `[?]` from row's needs-review state). Boards section enriches RTX 5070 Ti and RTX 5080 (both `[verified]` model names + brand=NVIDIA `[?]` per catalog row). Display section shows the 13-leaf shape clearly: panel/resolution_label/resolution_pixels/anti-glare/tier all `[verified]`, every quality leaf `[—]` because ASUS doesn't publish them on the structured `Display` h2.

### Decisions resolved this session

- **Empty section default = show heading + `[empty]`.** Two options framed (show heading with `[empty]` / hide the section entirely). User chose show. Gap-spotting at a glance beats cleaner output. Applies uniformly to body categories; identity block extends the same rule.
- **Single-offering categories drop the `Offering 1:` prefix.** Two options framed (skip when total == 1 / always label). User chose skip. The redundant `Offering 1:` line was noise on a typical product with one CPU option / one display SKU. Multi-offering categories (laptops with 2+ display SKUs, 2+ board configs, etc.) still get numbered sub-headers and a deeper indent.
- **Identity title block always shows all six fields.** Two options framed (hide empty title fields / show every title field with `[empty]` when missing). User chose show all. Mirrors the body-category rule and surfaces "this vendor doesn't expose `status` / `segment`" without a separate audit pass. Slightly noisier title block, accepted.
- **Catalog spec lines render unmarked.** Two options framed (leave unmarked / put the catalog row's status on every spec line). User chose unmarked. Catalog `cores` / `npu_tops` / `architecture` etc. are plain TEXT (no per-cell provenance), and the row-level `catalog_status` is already shown once per offering. Repeating the marker on every line would be noise. The `brand` bundle (the only bundled catalog column) keeps its own marker.

### Course corrections worth remembering

- **Stale agent reports about DB state.** The Explore agent's first pass reported "Alienware M18 2026" was the live product — it inferred from older test fixtures (`tests/fixtures/dell/snapshot_aa18250_synthetic.json` etc.) rather than querying `competitive.db`. Live DB state was the post-Session-8 ROG Zephyrus G16 2026 row from Session 8's smoke test. User caught the contradiction immediately ("we changed Alienware product to Alienware Area 51 18 — why is it still showing stale data?"). Corrected by querying the DB directly. **Lesson:** when an agent's report names a specific product/row, verify against `SELECT * FROM products` before treating it as ground truth — fixture filenames are not row state.
- **`storage_slots` is offerings-shaped, not scalar.** First integration run crashed because `views/storage.py` treated `storage_slots` as a scalar bundle — it's actually a list of slot entries with a `gen` leaf each. Schema (`schema.sql:83`) carries it as TEXT, like every other JSON-stored column, but `DATA_MODEL.md:182` documents the offerings shape ("Length = number of physical slots. Mixed-gen configs preserved."). The loader's `_OFFERINGS_FIELDS` set was missing it; fixed before bulk rollout. **Lesson:** when reading a column-shape question off DATA_MODEL.md, check the "Each ... entry" sub-table — that's the giveaway for an offerings field. Also: the count of offerings columns (8) in the products table doesn't match the count of `*_offerings`-suffixed names (7) — `storage_slots` doesn't follow the naming convention and is easy to miss on a name-suffix scan.
- **Windows console encoding bites Unicode markers.** Default Windows `cp1252` can't render the em-dash `—` or the `×` in `2560×1600`. They print as `?` (with the cp1252 replacement byte). Fix is `sys.stdout.reconfigure(encoding="utf-8")` in `inspect_product.main()`, wrapped in try/except for cross-platform safety. The fix is local to the CLI (not in `views/` or `db/`) since only the print path needs the reconfigure. Documented in `VIEWS.md` and `ARCHITECTURE.md` §View layer.
- **Plain-language framing matters with this user.** First mid-stage checkpoint dump was too technical — questions about subcommand wiring vs standalone module, marker behavior on whole-empty categories. User asked for simpler framing ("all of this is too technical. ask me questions simply"). Reformulated with output previews and concrete examples instead of structural questions; user answered immediately. **Lesson:** for this user, frame questions about user-visible output (what the printout looks like), not about implementation paths. The `AskUserQuestion` `preview` field rendered side-by-side mockups of each option — that landed best.
- **Catalog brand bundle marker `[?]` reflects row-level catalog state, not value uncertainty.** When the inspect-product output shows `brand: Intel [?]` for the Core Ultra 9 386H catalog row, that's because the row's `brand` bundle was written with `status='needs-review'` (auto-add from ASUS scrape, not yet vouched). It is NOT saying "we're unsure the brand is Intel" — it's saying "this catalog row hasn't been confirmed by the user yet." Easy to misread on first glance. The `catalog status: needs-review` line above it is the explanation; this is a feature of the user's manual catalog-vouching flow, not a parser problem.

### Where we left off (pickup pointers for next session)

- **Stage 5 — operational CLI helpers.** Per `TASKS.md` §Stage 5: `cli/resolve.py` (single-transaction queue resolution, four actions: `accept_candidate` / `kept_existing` / `manual_override` / `dropped`), `cli/manual_edit.py` (manual cell write with provenance scaffolding handled — `status` / `entered_by` / `entered_at` auto-populated), `cli/find_empty.py` (list empty + `vendor-doesn't-publish` cells per product, using view-layer field labels for human-readable output), `cli/find_conflicts.py` (list unresolved review queue rows). All thin wrappers over Python functions a future UI will call. No new schema work expected. The view layer's field-label structure (`(label, key)` tuples in each per-category module) is the natural source for `find-empty`'s human-readable output — consider exposing those tuples as a public registry to avoid duplication.
- **Lenovo Intel Pro 7i Gen 10 refresh** — opportunistic, carry-over from Session 7. Re-run `refresh --brand lenovo --url <new URL>` once PSREF indexes the Intel variant. No code change.
- **`scrapers-lib` ASUS display gap** — refresh rate / HDR cert / nits / VRR aren't captured (live in marketing-highlights `<ul>`, not the structured `Display` h2). Upstream `scrapers-lib` issue, not blocking Stage 5. The `inspect-product` output now makes this gap visible: every quality leaf shows `[—]` (`vendor doesn't publish`). User can decide whether to chase upstream or fill manually.
- **`competitive.db`** carries the post-Session-8 state (one ROG Zephyrus G16 2026 row, three chip stubs with seeded chip-spec values). No DB writes in Session 9 — view layer is read-only. Wipe before the next live refresh if you want a clean slate.
- **`ARCHITECTURE.md` §Trade-offs entry "CLI before UI"** is still accurate post-Stage-4; the view layer being shipped doesn't change the "Phase 1 has no UI" framing.

---

## Session 8 — 2026-05-07 (implementation)

**Goal:** Close Stage 3 — ASUS / ROG Zephyrus G16 bridge, then apply the follow-up decisions surfaced during the per-vendor pause-and-review checkpoint.

**Outcome:** Stage 3 closed. ASUS bridge shipped end-to-end (live capture clean, 51 fields inserted, 0 conflicts, 0 low-confidence, 3 expected `new_chip_unverified` queue rows). Five user decisions resolved during the checkpoint review. One of those decisions (#2 below) is a deliberate amendment to the Session 3 "stub-only catalog" architecture decision and applies to all four vendor parsers, not just ASUS. 140 → 148 tests passing.

### What was built / changed

- **Bridge — ASUS.** `competitive_database/bridge/asus.py` mirrors the HP / Lenovo pattern. ASUS-specific quirks absorbed: (a) single-line space-separated I/O ports with `Nx` count anchors (e.g. `"1x HDMI 2.1 FRL 2x USB 3.2 Gen 2 Type-A 1x Thunderbolt™ 4 …"`) — neither HP's per-line nor Lenovo's `\n`-joined shape applies, so a private `_split_asus_ports` tokenizer anchors on `\b\d+x\b`; (b) per-GPU TGP comes from marketing prose (`"Manual mode: 1497MHz at 140W"`) rather than a structured attribute — Manual-mode wattage feeds `tgp_max` per board (max), mirroring Lenovo; (c) memory speed published as a bare number after the type token (`"LPDDR5X 8533"`, no unit), so an ASUS-specific regex anchored on the type token is required; (d) battery published as `"90WHrs"` (plural Hrs, no separator) — normalize `WHrs` → `Wh` before parsing; (e) dimensions in cm with `~` height range (`"35.4 x 24.6 x 1.49 ~ 1.79 cm"`) — convert to mm (×10) with the tilde as the range separator; (f) NPU prose appended to the CPU line via `;` separator — `_is_npu_only` filters it out of CPU offerings and routes it to chip-spec extraction instead. Identity helpers private to the module. `SCRAPER_ID = "asus.fetch_asus_product"`.
- **Dispatcher.** `bridge/dispatcher.py` now routes `"dell"` / `"hp"` / `"lenovo"` / `"asus"`. All four Stage 3 vendors registered.
- **CLI refresh.** `cli/refresh.py` adds `DEFAULT_ASUS_URL_TMPL` (`https://rog.asus.com/us/laptops/rog-zephyrus/{slug}/spec/`), registers `"asus"` in `_VENDOR_TEMPLATES`, and adds an `asus` branch to `_fetch_snapshots` that lazy-imports `from scrapers_lib.tier2.asus import fetch_asus_product` (called with just `url` + `anchors` — ASUS uses neither Playwright profiles nor a curl_cffi warm-up).
- **Chip-spec catalog seeding (all four vendors).** New optional `cpu_chip_specs: dict[str, dict[str, Optional[str]]]` field on `CandidateProduct`, mapping CPU model name → cpu_catalog column name → string value. Bridges populate where the vendor publishes:
  - **ASUS:** `npu_tops` (from `Neural Processor` h2), `cores` (from Processor prose).
  - **Lenovo:** `cores`, `base_clock`, `boost_clock`, `process_node`, `architecture` (from PSREF `Att: AttV` rows).
  - **HP:** `cores` (from the combined PG&M parenthetical).
  - **Dell:** `cores` (from the Processor parenthetical, `24-Core` → `"24"`).
  `ingest/catalog_resolve.py` gains `_apply_cpu_chip_specs` + `_enqueue_catalog_disagreement`. Per-cell rule: empty cell → write; needs-review row + match → no-op; needs-review row + diff → overwrite + queue `value_disagreement`; vouched row + diff → keep existing + queue. No new conflict_type. Catalog spec columns stay plain TEXT (no provenance bundle — catalog is a reference table, not primary data).
- **Adapter connector enum.** Added `rectangle` value alongside `USB-C PD` / `barrel` / `slim-tip`. ASUS's `"Rectangle Conn, 250W AC Adapter"` lands as `rectangle` (verified). DATA_MODEL.md updated.
- **Tests.** `tests/bridge/test_asus.py` (29 cases — 17 live + 12 synthetic). New chip-spec extraction cases on each of `test_dell.py`, `test_hp.py`, `test_lenovo.py`, `test_asus.py`. Four new cases in `tests/ingest/test_catalog_resolve.py` covering the four seed/conflict rule branches. Fixtures: 2 in `tests/fixtures/asus/` (1 live ROG Zephyrus G16 2026 + 1 synthetic).
- **Live verification.** ASUS / ROG Zephyrus G16 (`rog-zephyrus-g16-2026`): 1 snapshot, 51 fields inserted. `cpu_catalog` row for `Core Ultra 9 386H` carries `cores='16'` and `npu_tops='50'` (catalog_status: needs-review; brand: Intel) — first chip-spec seed applied. `products.adapter_connector = rectangle` (verified). Queue: 3 `new_chip_unverified` rows (1 CPU + 2 GPUs); zero `value_disagreement`, zero `low_confidence_extraction`, zero `year_inferred`.

### Decisions resolved this session

- **Adapter connector enum gains `rectangle`.** Three options framed (keep as `barrel` / new `rectangle` / merge with Lenovo `slim-tip`). User chose new `rectangle` — most accurate cross-vendor compare; ASUS's flat plug is genuinely a different shape from Dell's round-pin barrel and Lenovo's narrower slim-tip. Small enum extension; no schema migration needed (column is plain TEXT).
- **CPU catalog seeding from vendors — amends Session 3 Decision 4.** Original decision was "stub-only catalog auto-add — no chip-spec fetch in Phase 1." User amended this: when the laptop vendor publishes chip-level specs on the laptop spec page, the bridge captures them and seeds the matching `cpu_catalog` columns. Per-cell rule (above). Phase 2 chip-spec auto-fetch (Intel ARK / NVIDIA / AMD) is still deferred — this amendment only opens the door for vendor-as-fallback. Cross-vendor disagreement is expected; queue path covers it.
- **AniMe Matrix → verbatim in `lighting`.** Three options framed (verbatim text / new `lid_lighting` enum field / yes-no `has_lid_display` flag). User chose verbatim. ASUS-specific marketing feature; structured filterability not worth a new column for a single-vendor case. Keeps schema small.
- **ASUS `model_code` = full URL slug.** Three options framed (full slug `rog-zephyrus-g16-2026` / strip year `rog-zephyrus-g16` / hunt for ASUS internal SKU like `GU605CX`). User chose full slug. Year shows up in both the slug and the `year` column — redundant but works; readability of the slug outweighs the cosmetic redundancy. Different visual shape from Dell `aa18250` / HP `14t-fb100` / Lenovo `16AFR10H`, accepted.
- **Soldered RAM → `memory_slots = 0`.** Two options framed (factually-zero / treat-as-missing). User confirmed `memory_slots = 0`. Preserves filterability (`WHERE memory_slots > 0` for replaceable RAM). Matches HP convention. ASUS's `"on board"` keyword now triggers this branch.

### Course corrections worth remembering

- **Grep the schema before asking "should we add a column?".** I almost asked the user "should we add an NPU column?" — the schema already had `cpu_catalog.npu_tops` (schema.sql:12), DATA_MODEL.md:27 documented it, and PRD.md:82 even listed `"NPU TOPS ≥ 40"` as a target query. The first ASUS subagent had silently dropped NPU prose because *its* framing said the schema didn't carry NPU. Same Session 7 lesson recurring: subagents over-default to "drop" or "vendor-doesn't-publish" when the schema actually wants the value. Lesson: always grep the schema and DATA_MODEL.md before treating a vendor's published value as a "should we capture this?" question.
- **One subagent, two related implementation passes, sequential.** Both Decision 1 (rectangle enum) and Decision 2 (chip-spec seeding) touched `bridge/asus.py` plus a four-vendor sweep for #2. Bundling them in one subagent run avoided file-conflict and gave the agent a coherent task; total time was tighter than two parallel runs would have been. Worth the cadence default for "small enum + cross-cutting policy change" pairs.
- **Catalog spec columns stay plain TEXT (no provenance bundles).** When opening the door to vendor-as-fallback chip-spec source, the temptation was to wrap catalog cells in the same `{value, source_url, captured_at, scraper_id, status}` bundle the products table uses. Resisted: the catalog is a reference table, the provenance question is "where does the canonical chip spec come from?" which is owned by Phase 2 ARK/AMD/NVIDIA fetch, not by per-vendor laptop pages. The conflict-queue path covers cross-vendor disagreement without needing per-cell provenance. Keep this distinction load-bearing for any future "should X carry a bundle?" question.
- **The five-decision walkthrough was per-vendor checkpoint cadence working as designed.** Session 7 surfaced four decisions across HP and Lenovo; Session 8 surfaced five for ASUS alone (one of which retroactively amended a Session 3 decision). The pause-after-each-vendor structure forced each into its own framing. Without it, the chip-spec seeding amendment would have been buried inside an end-of-Stage-3 summary and likely missed.
- **`Memory > "on board"` and the soldered-slots convention is now load-bearing across HP and ASUS.** When a fifth vendor (Acer / MSI eventually) publishes soldered RAM, the parser must follow this same `memory_slots = 0` convention, not `vendor-doesn't-publish`. Documented the call in DATA_MODEL.md is sufficient, but worth flagging.

### Where we left off (pickup pointers for next session)

- **Stage 4 — view layer + `inspect-product` CLI.** Single source of truth for human-readable presentation. CLI uses it now; UI uses it later. Per `TASKS.md` Stage 4: `views/formatting.py`, 16 per-category render modules, `views/orchestrator.py`, `cli/inspect_product.py`, `VIEWS.md`. Architectural intent is in `ARCHITECTURE.md` §View layer. Suggest delegating render-function implementation per category to subagents (each is small and self-contained); pause after the orchestrator + 2–3 representative views land for a checkpoint before bulk-rolling out the remaining 13.
- **Lenovo Intel Pro 7i Gen 10 TODO** — carry-over from Session 7. Once PSREF lists `Legion_Pro_7i_16IRX10H` (or whatever the Intel Pro 7i Gen 10's product key turns out to be), re-run `refresh --brand lenovo --url <new URL>`. Parser is already built against the Intel-variant shape via the synthetic fixture.
- **`scrapers-lib` ASUS display gap.** The ASUS extractor only pulls the structured `Display` h2 block, which on ROG marketing pages is sparse (size/res/panel/aspect/anti-reflection only). Refresh rate, HDR cert, peak nits, VRR live in the marketing-highlights `<ul>` and aren't captured today. Tracked as a `scrapers-lib` upstream issue, not a competitive-database parser change. Not blocking Stage 4.
- **Dell live test asserts `cores='24'`.** Whichever Core Ultra HX SKU is in the current Dell live snapshot has 24 cores. If the Dell live fixture is later refreshed to a different chip with a different core count, that test will need a small tweak. Not load-bearing.
- **`competitive.db`** carries the post-ASUS state from this session's smoke test (one ROG Zephyrus G16 2026 row, 3 chip stubs with `Core Ultra 9 386H` carrying seeded `cores='16'` + `npu_tops='50'`). Wipe before the next live refresh if you want a clean slate.

---

## Session 7 — 2026-05-07 (implementation)

**Goal:** Execute the Session 6 plan — Stage 3 vendor parsers, sequential, pause-and-review checkpoint after each vendor. Started cold with HP, then Lenovo. ASUS deferred per user pause-and-update-log decision.

**Outcome:** HP and Lenovo parsers shipped end-to-end. 111/111 tests pass (83 after HP, 111 after Lenovo). Live captures for both vendors landed cleanly. Four user decisions resolved during the two checkpoint reviews. ASUS is the only remaining Stage 3 vendor. One TODO carried forward: re-run Lenovo against the Intel Pro 7i Gen 10 once Lenovo PSREF indexes it (live capture currently uses the AMD cousin as a placeholder, parser is built against the right shape).

### What was built / changed

- **Bridge — HP.** `competitive_database/bridge/hp.py` mirrors the Dell pattern. HP-specific quirks absorbed: (a) the combined `"Processor, graphics & memory"` key splits on `+` per option then per-component; (b) RAM speed/type/OC stay `vendor-doesn't-publish` (HP gaming PDPs structurally don't publish them); (c) USB-C version inferred from signaling rate labels (`40Gbps` / `10Gbps` / `5Gbps` → USB4 / Gen 2 / Gen 1, all `verified`); (d) `20Gbps` and `80Gbps` attach a best-guess version with `status: needs-review` per the Session 7 user decision; (e) HP series naming = family + screen-size token (e.g., "Transcend 14"); (f) HP's single-value weight publishes as `weight_kg_min` only, `weight_kg_max` stays `vendor-doesn't-publish`; (g) storage gen falls back to HP's `(4x4 SSD)` shorthand when no explicit `PCIe Gen N`. Identity helpers private to the module (`_derive_hp_model_code` / `_derive_hp_sub_brand` / `_derive_hp_series`) — kept out of the generic `helpers.py`. `SCRAPER_ID = "hp.fetch_hp_product"`.
- **Bridge — Lenovo.** `competitive_database/bridge/lenovo.py` mirrors the HP pattern but absorbs Lenovo's hierarchical 3-level path keys (`"Performance > Processor > Processor"` etc.). Per-row `Att: AttV; Att: AttV` strings are parsed via a private `_row_attrs` helper; intra-row `;` separators are kept distinct from inter-row separators by a private `_split_alternatives` helper that splits only on `\n` and the literal word `or`. Per-GPU TGP attribute (`"TGP: 140W"` / `"TGP: 175W"`) collapses to `tgp_max = max` per board per the Session 7 user decision (initial subagent default was `vendor-doesn't-publish`; corrected on review — the schema column is literally named `tgp_max`, so the highest TGP is the right value to store). Lenovo's spec pages publish 40+ fields, the richest of the three, so most live assertions key off attribute names rather than free-text regex. Identity helpers private to the module. `SCRAPER_ID = "lenovo.fetch_lenovo_product"`.
- **Dispatcher.** `bridge/dispatcher.py` now routes `"dell"` / `"hp"` / `"lenovo"`. ASUS slot reserved.
- **CLI refresh.** `cli/refresh.py` replaced its hardcoded Dell-only check with `_VENDOR_TEMPLATES` carrying `dell` / `hp` / `lenovo` URL templates and a vendor-aware fetch dispatcher (lazy imports preserved per Stage 2 pattern).
- **Tests.** `tests/bridge/test_hp.py` (22 cases — 12 live + 9 synthetic + 1 ambiguous-USB-C-rate flag check) and `tests/bridge/test_lenovo.py` (28 cases — 17 live + 11 synthetic). Fixtures: 4 in `tests/fixtures/hp/` (3 live tiles + 1 synthetic) and 2 in `tests/fixtures/lenovo/` (1 live + 1 synthetic).
- **Live verification.** HP / OMEN Transcend 14 (`pdk-a88y7av-1`): 3 tiles → 1 product `(14t-fb100, 2026)`, 50 fields inserted, queue = 5 `new_chip_unverified` + 1 `year_inferred`. Lenovo / Legion Pro 7 (`16AFR10H`, AMD cousin): 1 snapshot, 50 fields inserted, queue = 4 `new_chip_unverified` + 1 `year_inferred`. Both clean — no `value_disagreement`, no `low_confidence_extraction`.

### Decisions resolved this session

- **HP weight handling — keep current behavior.** HP publishes one weight figure (e.g., 3.6 lb on the Transcend 14). Parser stores it as `weight_kg_min`; `weight_kg_max` stays `vendor-doesn't-publish`. Conservative — matches the convention that single-value weights are the starting weight. User chose this from a three-option framing.
- **HP USB-C signaling rate handling — translate, but flag for review when uncertain.** Unambiguous rates (`40Gbps` → USB4, `10Gbps` → USB 3.2 Gen 2, `5Gbps` → USB 3.2 Gen 1) and explicit Gen wording land `verified`. `20Gbps` and `80Gbps` attach best-guess versions (`USB 3.2 Gen 2x2`, `USB4`) with `status: needs-review` so the runner queues them for human review. Mechanical change: `_extract_usbc_version` now returns `Optional[tuple[value, status]]` and the populate-step builds the bundle accordingly. One synthetic test case locks the new behavior.
- **Lenovo target substitution accepted.** Intel Legion Pro 7i Gen 10 (the user-chosen target from Session 6) isn't yet on Lenovo PSREF, the only source `scrapers-lib` accepts. AMD cousin (`Legion Pro 7, 16AFR10H`) used as a placeholder live capture. Synthetic fixture is still keyed to the Intel Pro 7i shape, so the parser is built against the right product. TODO: re-run against the Intel variant once PSREF indexes it.
- **Lenovo per-GPU TGP collapses to `max` per board.** Lenovo publishes per-GPU TGPs (e.g., RTX 5070 Ti at 140W and RTX 5080 at 175W on the same board). Schema column name (`tgp_max`) was always the original Session 1 intent — the subagent's default of `vendor-doesn't-publish` was over-cautious. Corrected on review: the highest per-board TGP lands as `verified`. Lenovo Pro 7's MB1 → `tgp_max = 175`. Dell and HP boards stay blank (those vendors don't publish per-GPU TGP at all).

### Course corrections worth remembering

- **Subagent's "play safe" defaults can override schema intent.** The Lenovo subagent left `tgp_max` as `vendor-doesn't-publish` to avoid silently picking a number — but the column is literally named `tgp_max` and the schema was designed for exactly the highest-per-board case. Lesson: when a subagent reports "I picked the conservative path because two values won't fit one slot," cross-check the schema's naming intent, not just the abstract trade-off. The user picked up on this immediately ("the schema is set up to have the highest power per board, right? that was the plan") — confirmed and corrected.
- **PSREF can lag the actual product release by weeks.** Lenovo's structured spec mirror only carries products that have been on the market long enough to land in their internal database. Brand-new flagships (e.g., the Intel Pro 7i Gen 10) may not appear for some time. For Lenovo specifically, the AMD/Intel cousin pattern means an AMD variant often lands earlier and works as a stand-in for parser validation. Don't burn cycles guessing PSREF product keys for unreleased SKUs.
- **Vendor-by-vendor checkpoint cadence is paying off.** HP surfaced two real decisions (weight, ambiguous USB-C labels). Lenovo surfaced two more (target substitution, per-GPU TGP collapse). Bundling all three vendors into one subagent run would have buried these in a single 1000-word report; the per-vendor pause-and-review forced each decision into its own framing. Worth keeping for ASUS.
- **HP's single combined `"Processor, graphics & memory"` key is unique to HP.** Dell uses three distinct keys; Lenovo uses three distinct keys (under hierarchical paths). HP's combined-key handling does not need to generalize. If ASUS shows a similar combined key, treat that as a separate decision rather than reusing HP's `+`-split logic blindly.
- **`(value, status)` return-tuple pattern for ambiguous extractions is the new norm.** Introduced in HP's `_extract_usbc_version`; carried forward into Lenovo. Future vendor parsers should use the same shape for any field where the parser has a best-guess value but uncertain confidence.

### Where we left off (pickup pointers for next session)

- **Stage 3, vendor 3 — ASUS / ROG Zephyrus G16.** Same shape as HP / Lenovo: capture live snapshots → `tests/fixtures/asus/`, write `bridge/asus.py` (mirror `bridge/hp.py` and `bridge/lenovo.py`), write `tests/bridge/test_asus.py`, register in `bridge/dispatcher.py`, add `asus` template + lazy `fetch_asus_product` to `cli/refresh.py`, run live smoke test. Use the `(value, status)` tuple pattern for any ambiguous extraction. Then Stage 3 is fully done.
- **Lenovo Intel variant TODO.** Once PSREF lists `Legion_Pro_7i_16IRX10H` (or whatever the Intel Pro 7i Gen 10's product key turns out to be), re-run `refresh --brand lenovo --url <new URL>`. The parser is already built against the Intel-variant shape (synthetic fixture confirms), so this is a data refresh, not a code change.
- **Stage 4 (view layer + `inspect-product`)** comes after ASUS.
- **`competitive.db`** carries the post-Lenovo state from this session's smoke test (one AMD Legion Pro 7 row, 4 chip stubs, 1 year-inferred queue entry). Wipe before the next live refresh if you want a clean slate.

---

## Session 6 — 2026-05-07 (planning)

**Goal:** Pre-flight for Stage 3 (HP / Lenovo / ASUS parsers). Confirm fixture targets, fixture pattern, execution order, and checkpoint cadence before any code is written.

**Outcome:** No code written. Four operational decisions locked. Next session opens cold with HP parser implementation and pauses at HP for review before Lenovo / ASUS.

### Decisions locked this session

- **Live fixture targets.** HP → OMEN Transcend 14. Lenovo → Legion Pro 7i Gen 10. ASUS → ROG Zephyrus G16. All chosen as current-gen gaming flagships; user-confirmed picks.
- **Fixture pattern — mirror Dell.** At least 1 synthetic fixture (full-coverage edge cases) plus 1–2 live captures per vendor. Live captures land in `tests/fixtures/{hp,lenovo,asus}/`.
- **Execution order — sequential, not parallel.** HP first. Reason: if HP exposes a missing helper or a broken structural assumption, we find it on vendor 1 rather than having three subagents collide on `bridge/helpers.py` simultaneously. Slower wall-clock; acceptable for a solo project.
- **Checkpoint after HP.** Pause once HP parser + tests + dispatcher registration + live smoke test all pass. User reviews the pattern before Lenovo / ASUS proceed. Avoids burning context across three vendors if the shape needs adjustment.

### Recon performed (Explore agent)

Confirmed Stage 3 is purely additive against the existing codebase:

- `bridge/dispatcher.py` registers only `"dell"`; HP / Lenovo / ASUS source strings need to be added to `_PARSERS`.
- `cli/refresh.py` is hardcoded Dell-only (the brand check at lines 73–76 raises on anything else); needs a vendor → fetcher map.
- No fixtures yet for HP / Lenovo / ASUS.
- `bridge/types.py`, `bridge/helpers.py`, `ingest/runner.py`, and the `db/` layer are all vendor-agnostic and untouched by Stage 3.
- scrapers-lib import path: `from scrapers_lib.tier2.{vendor} import fetch_{vendor}_product` (lazy import, mirroring the Dell pattern).

No contradictions against `ARCHITECTURE.md` or the project memory.

### Where we left off (pickup pointers for next session)

- **Stage 3, vendor 1 — HP / OMEN Transcend 14.** Capture live snapshot → `tests/fixtures/hp/`, write `bridge/hp.py` (line-0 → `tier: base`, rest → `tier: optional`), write `tests/bridge/test_hp.py`, register in dispatcher, extend `cli/refresh.py` to dispatch `--brand hp`, run a live smoke test against the OMEN Transcend 14 PDP. Pause for user review.
- **After HP review:** Lenovo (Legion Pro 7i Gen 10) → ASUS (ROG Zephyrus G16), same shape. Then Stage 4 (view layer + `inspect-product`).
- **No design questions outstanding.** Stage 3 is implementation-only.

---

## Session 5 — 2026-05-07 (implementation)

**Goal:** Stage 2 (Dell end-to-end slice) implementation + six follow-up decisions applied on top of the subagent's first pass.

**Outcome:** Stage 2 complete and verified. Live refresh against the Alienware Area-51 PDP succeeded end-to-end through the full pipeline: scrapers-lib fetch → Dell bridge → catalog auto-add → cross-tile merge → diff → write/queue. All six user-locked decisions are applied and reflected in code, docs, and tests. 58/58 tests pass (42 baseline + 16 new). Ready for Stage 3 (drop in `bridge/{hp,lenovo,asus}.py`).

### What was built / changed

- **Bridge layer.**
  - `bridge/types.py` — `CandidateProduct` gains a `year_was_inferred: bool` flag (Decision 1). Not stored in the DB; threads through to the runner so the queue type can be picked correctly.
  - `bridge/helpers.py` — added the static `GPU_TO_BOARD` map and `lookup_board(gpu_model)` (Decision 5). Vendor prefix stripping + case-insensitive matching baked in.
  - `bridge/dell.py` — `_build_boards` rewritten: groups GPUs in a tile by `lookup_board(...)` instead of emitting one MB# per array index. Unmapped GPUs surface with `label: null` and the GPU bundle marked `needs-review`. Sets `cand.year_was_inferred` from `derive_year`'s second return. (Decision 4 confirmed already correct — the adapter wattage fallback to "Dimensions & Weight" was already present.)
- **Ingest.**
  - `ingest/runner.py` — new `ingest_product(conn, candidates)` entry point that merges N candidates sharing one PK, then calls `ingest()` against the merged result (single transaction). Cross-tile merge unions the eight list-of-offerings columns by per-column identity keys (CPU model name, GPU label+name set, display res+panel+refresh+size, etc.). `boards` has its own special-case unioning that collapses same-label entries and dedupes their GPU lists. `IngestReport` gains a `year_inferred` counter; `_diff_scalar` checks `year_was_inferred` when the field is `vendor_full_name` and routes to the new `year_inferred` queue type instead of `low_confidence_extraction`.
  - `cli/refresh.py` — switched from per-snapshot `ingest()` to `ingest_product()` after grouping snapshots by PK. Per-product print line lists the contributing tiles.
- **Docs.**
  - `ARCHITECTURE.md` — `review_queue.conflict_type` enum extended with `year_inferred`.
  - `DATA_MODEL.md` — new "GPU → Board mapping (static)" subsection documenting the table and the unmapped-GPU rule.
- **Tests.**
  - `tests/bridge/test_helpers.py` — six `lookup_board` cases (all three tiers, vendor-prefix stripping, case insensitivity, unmapped fallback to None).
  - `tests/bridge/test_dell.py` — three new cases: boards label coming from the static map (live snapshot), `year_was_inferred=True` set on live snapshots, two-GPU 'or' string in one tile collapsing into one MB1 entry. The synthetic test now asserts `boards[0]["label"]["value"] == "MB1"`.
  - `tests/ingest/test_runner.py` — six new cases: `year_inferred` routing for inferred-year candidates, the same shape with `year_was_inferred=False` still routes to `low_confidence_extraction`, cross-tile CPU union, cross-tile boards union with dedupe, needs-review offerings stay separate from verified ones, single-candidate fallthrough, mismatched-PK error.
- **Live verification.** Wiped `competitive.db`, re-ran `db-init`, re-ran the live `refresh` against the Alienware Area-51 URL. Three snapshots returned, merged into one product row, results below.
- **Late-day addition: `storage_max_gb`.** Storage section was asymmetric with Memory (Memory had `memory_max_gb` ceiling + slot info; Storage had only `storage_slots`). Added a `storage_max_gb` scalar column on `products` to mirror Memory's shape. Bridge extracts the maximum capacity from Dell's "Storage" spec (parses TB/GB tokens; 1 TB → 1000 GB, no silent unit conversion on raw GB). Cross-tile merge for this field uses `max()` rather than last-writer-wins — three live tiles publishing 1 TB / 2 TB / 2 TB merge to 2000 GB. Stage 6 ceiling-merge candidates list (`memory_max_gb`, `storage_max_gb`, `memory_speed_mts`) noted in `ingest/runner.py` next to `_CEILING_MERGE_SCALARS` as a forward-compat hook; only `storage_max_gb` uses the new path today. Schema, types, bridge, runner, DATA_MODEL.md, and tests updated; 61/61 tests pass; live smoke against Area-51 confirmed `storage_max_gb=2000` (verified) with queue counts unchanged (4 `new_chip_unverified` + 1 `year_inferred`).

### Implementation decisions resolved this session

- **Decision 1 — `year_inferred` queue type.** Implemented as a dedicated conflict_type. `CandidateProduct.year_was_inferred` flows from the Dell parser into the runner, which routes the `vendor_full_name` review row to `year_inferred` instead of the generic low-confidence bucket. The cell-level status on `vendor_full_name` stays `needs-review` as required.
- **Decision 2 — Alienware naming (no change).** Confirmed: `sub_brand = "Alienware"`, `series = "Area-51"`. Existing helper tests already assert this; live refresh produces the same.
- **Decision 3 — Cross-tile merge for option-list fields.** New `ingest_product` entry point unions all eight offerings columns by identity key. Scalars stay one-per-snapshot (first wins). Needs-review offerings are NOT collapsed with verified ones — they stay separate in the merged list. Single-tile callers can keep using plain `ingest()`.
- **Decision 4 — Adapter wattage source (no change).** Confirmed: `bridge/dell.py` already extracts adapter wattage from "Dimensions & Weight" when "Power Supply" is missing. Logic intact, no edit.
- **Decision 5 — Static GPU → board map.** `GPU_TO_BOARD` and `lookup_board` live in `bridge/helpers.py`. Dell parser groups GPUs by board label per tile; cross-tile merge collapses same-label boards across tiles. Unmapped GPUs route through the existing `low_confidence_extraction` queue (and `new_chip_unverified` via catalog auto-add) — no new queue type per the user's explicit "keep it simple" rule.
- **Decision 6 — N/A.** Resolved by Decision 1.

### Live re-verification (Alienware Area-51 AA18250)

Pre-state (before this session's changes, from prior smoke test):
- `value_disagreement: 4`, `low_confidence_extraction: 3`, `new_chip_unverified: 4`. Three boards entries (one per tile). Two of three were `MB2` from the per-tile counter, one was `MB1`. CPU offerings were not unioned.

Post-state (after Decisions 1–5):
- `value_disagreement: 0`, `low_confidence_extraction: 0`, `year_inferred: 1`, `new_chip_unverified: 4`.
- `boards`: ONE entry, `label: "MB1"`, `gpus: [RTX 5070 Ti, RTX 5090]` — both GPUs unioned across tiles.
- `cpu_offerings`: 2 unique CPUs (`Core Ultra 9 290HX Plus`, `Core Ultra 9 275HX`).
- Catalog auto-add fired 4 times (2 CPUs + 2 GPUs), as expected.

**Note on the `year_inferred` count.** The user's expectation was `~3` (one per snapshot). Got `1`. That is the correct behavior under cross-tile merge: three tiles for one product collapse into a single ingest, so `vendor_full_name` is enqueued once. Three would have meant we were still doing per-snapshot writes, which Decision 3 explicitly moves us off.

### Course corrections worth remembering

- **The original Stage 2 subagent emitted "one board per tile, label = MB{idx+1}".** That choice surfaces here as a bug: three live tiles produced `MB1` / `MB2` / `MB3` with the same GPU on each, which is meaningless. The static-map fix (Decision 5) is the right shape, and it was also a re-ask — the user had already said in Session 1 that motherboards are 1:N with GPUs at a *power class*, and the per-tile counter quietly broke that. Lesson: when a "stage" subagent's output doesn't match an earlier locked decision, treat it as a regression, not a new design question.
- **`value_disagreement` was masking a category error.** The 4 pre-state value_disagreement rows weren't real conflicts; they were three Dell tiles each writing their own version of the same offerings list and the runner index-wise diffing. Decision 3 (cross-tile merge) made the category error vanish. The diff path itself is fine — the input to it just wasn't the right shape.
- **`year_inferred` is intentionally per-product, not per-snapshot.** Easy to mis-spec as "one entry per tile." The right semantic is: the *product*'s year is suspect. One row per product is the correct cardinality once cross-tile merge is in place.
- **No new queue type for unmapped GPUs.** The user explicitly rejected adding an `unmapped_gpu` queue type. The existing `low_confidence_extraction` plus `new_chip_unverified` paths cover the case without proliferating queue types. Worth remembering when Lenovo/HP add their own GPU lookups.
- **`ingest_product` vs `ingest`.** Both are kept. `ingest()` stays as the per-candidate primitive (used heavily by tests and by anything that genuinely has one snapshot). `ingest_product()` is the right entry point for the CLI and any future caller that wants atomic cross-tile semantics. Don't deprecate `ingest()` — it's the simplest thing that could possibly work.

### Where we left off (pickup pointers for next session)

- **Stage 3 — drop in `bridge/{hp,lenovo,asus}.py`.** The dispatcher routes by `snapshot.source`, so adding a new vendor parser is a single file plus a registry entry in `bridge/dispatcher.py`. No other code changes needed. HP's "line 0 = base / rest = optional" convention is already documented in `ARCHITECTURE.md`.
- **`scrapers-lib` Acer/MSI Tier 2** — still upstream-deferred; not blocking.
- **Stage 4 — view layer + `inspect-product` CLI** comes after Stage 3.
- **Live competitive.db** — current state from this session's smoke test. Not gitignore'd; carries the verified Area-51 row plus 5 queue entries (4 catalog stubs + 1 year_inferred). Wipe before the next live refresh if you want a clean slate.

---

## Session 4 — 2026-05-07 (implementation)

**Goal:** Begin Stage 1 implementation per `TASKS.md` — foundation: repo bootstrap, schema, connection layer, provenance-bundle helpers, `db-init` CLI.

**Outcome:** Stage 1 complete. Empty DB initializes cleanly via `python -m competitive_database db-init`; helpers round-trip both scalar bundles and list-of-offerings bundles. 5/5 tests pass. Ready for Stage 2 (Dell end-to-end slice).

### What was built

- **`pyproject.toml`** — Python 3.12+, no runtime deps, `pytest>=8` as the only dev dep.
- **`.gitignore`** — excludes `competitive.db` (and `-shm`/`-wal`), `__pycache__`, virtualenvs, build artifacts.
- **Package skeleton** — only Stage 1 modules (`db/`, `cli/db_init.py`, `__main__.py`); `bridge/`, `ingest/`, `views/`, and other CLI modules deferred to Stage 2+.
- **`db/schema.sql`** — four tables (`cpu_catalog`, `gpu_catalog`, `products`, `review_queue`) + 10 indexes. `IF NOT EXISTS` throughout, so re-running is safe.
- **`db/connection.py`** — `connect()`, `transaction()` context manager, `apply_schema()`.
- **`db/helpers.py`** — three bundle factories (scraped / manual / vendor-doesn't-publish) + scalar read/write + offerings read/write. Single write gateway for the rest of the project.
- **`db-init` CLI** — wired through `competitive_database/__main__.py`; other subcommands are stubbed-out comments awaiting Stage 2.
- **`tests/db/test_roundtrip.py`** — 5 tests covering schema apply, scraped scalar bundle, manual scalar bundle, two-offering `display_offerings` list, and `None` returns for missing/unwritten cells.

### Implementation decisions resolved this session

- **Identity-field shape — Option A.** `products.model_code` (TEXT) and `products.year` (INTEGER) are plain columns forming the composite primary key. Every other identity field — `vendor_full_name`, `brand`, `sub_brand`, `series`, `status`, `segment` — keeps a JSON provenance bundle. The two PK columns are mechanically derived from the vendor full name, so the meaningful provenance still lives on `vendor_full_name`. User chose A after a plain-language framing of the alternatives (skip provenance on labels only / skip on all identity / duplicate the PK columns).
- **I/O fields split into separate scalar columns.** Instead of a single structured `usbc_thunderbolt: {count, version}` column, the schema uses `usbc_thunderbolt_count` and `usbc_thunderbolt_version` as separate scalar bundle columns. Same for `usbc_non_thunderbolt`, `usba`, `hdmi`. Keeps the "scalar bundle" pattern uniform across the table; avoids needing a third storage shape; makes "all laptops with TB5" trivial to filter.
- **Catalog row-level status.** `cpu_catalog` and `gpu_catalog` each carry a plain `catalog_status TEXT NOT NULL DEFAULT 'needs-review'` column. Per-cell statuses still live inside the JSON bundles; `catalog_status` is the row-level state for stub-vs-vouched (per the catalog auto-add policy).
- **pytest version range left open (`>=8`).** No upper cap. Pytest is famously stable across major versions; capping is busywork on a solo project. (Currently resolves to pytest 9.0.3.)
- **Manual bundles keep `source_note: null` when unset.** Predictable shape across every manual cell, easier on future code (manual-edit CLI, view layer). Tradeoff (slightly larger storage when no note) is invisible in practice.

### Course corrections worth remembering

- **The user is non-technical — frame option questions in outcomes, not mechanics.** First Option A/B/C explanation leaned on the "primary key" word; user pushed back ("too technical"). Reframed in terms of "do you want the system to remember when/why you marked something discontinued" — that landed. Same lesson for the pytest-cap and bundle-shape questions: lead with the day-to-day impact, mechanics are an aside.
- **Delegate implementation to subagents to save context.** User asked explicitly. The general-purpose agent ran the full Stage 1 build + tests and returned a 250-word report. Continue this pattern for Stage 2+ (each stage is a clean self-contained delegation target).

### Where we left off (pickup pointers for next session)

- **Recommended next-session priority: Stage 2 — Dell end-to-end slice** per `TASKS.md`. Smallest path that proves the architecture: fetch one Dell product via `scrapers-lib` → parse via `bridge/dell.py` → write to DB via the helpers → read back. Deliverables: `bridge/types.py`, `bridge/helpers.py`, Dell test fixtures, `bridge/dell.py`, `bridge/dispatcher.py`, `ingest/catalog_resolve.py`, `ingest/runner.py`, `cli/refresh.py` + `__main__.py` wiring, live smoke test.
- **scrapers-lib will need to be installed/imported in Stage 2.** Decide install strategy (sibling-repo path install vs. PyPI vs. submodule) at the start of Stage 2.
- Stage 1 exit criterion: empty DB initialized; helpers round-trip both bundle shapes. **Met.**

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
