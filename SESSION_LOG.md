# Session Log

Append-only log of brainstorming and design sessions. Each entry captures what was discussed, what was decided, where we left off, and pickup pointers for the next session.

Newest sessions at the top.

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
