# VIEWS.md

Format choices and conventions for the Stage 4 view layer (the
`inspect-product` CLI). For the why-behind-the-architecture see
`ARCHITECTURE.md`; this file only covers the *display* layer.

---

## Marker scheme

Every leaf cell is rendered as `label: value [marker]`. The marker
encodes provenance and confidence at a glance:

| Marker      | Meaning                                                                                  |
|-------------|------------------------------------------------------------------------------------------|
| `[verified]` | Scraped from the vendor's spec page; bundle status `verified`.                          |
| `[?]`       | Scraped, bundle status `needs-review` (e.g. catalog rows auto-added during ingestion).   |
| `[—]`       | Scraped, bundle status `vendor-doesn't-publish`. The scraper checked; the field is not exposed by the vendor. |
| `[m]`       | Manually entered (any status — `vouched` or `needs-review`). Distinguished from scraped by the bundle's `entered_by` key. |
| `[empty]`   | Cell never written (no bundle). Distinct from `[—]`: empty means we haven't tried.       |
| `[partial]` | Aggregate marker for a category with mixed leaf statuses. Currently only used by `formatting.aggregate_markers`; per-leaf markers are usually preferred over aggregating. |

---

## Section layout choices

### Empty sections show their heading with `[empty]`

Confirmed at the Stage 4 checkpoint. Hiding empty sections looks
cleaner, but it makes "we never captured this" indistinguishable from
"the section doesn't exist." Showing `Audio: [empty]` keeps gap-spotting
as a one-line scan.

### Single-offering categories drop the "Offering 1" prefix

If a category has only one entry in its offerings list (typical for
laptops with a single CPU/display/keyboard option), the renderer skips
the redundant `Offering 1:` sub-header and inlines the leaves directly
under the section heading. Multi-offering categories keep the numbered
sub-headers (`Offering 1` / `Offering 2`) and indent leaves one level
deeper for clarity.

### Identity block always shows all six fields

`vendor`, `brand`, `sub-brand`, `series`, `status`, `segment` are
always printed, even when `[empty]`. This was a deliberate trade-off
against header noise: the user wanted to spot which identity fields a
vendor doesn't expose at a glance. (Body-category empties already work
this way; consistency wins.)

### Catalog spec lines render without per-line markers

Inside the CPU and Boards (GPU) sections, after each catalog hit the
view prints a `catalog status: <status>` line, then the catalog spec
columns (`cores`, `NPU TOPS`, `architecture`, etc.) as plain
`label: value` rows — no `[marker]` suffix.

The reason: catalog spec columns are stored as plain text in
`cpu_catalog` / `gpu_catalog` (no per-cell provenance bundle). The
row-level `catalog_status` already tells the user whether the chip
specs are vouched or pending review; repeating that on every line would
be noise. The exception is `brand`, which *is* bundled — it carries its
own marker.

---

## Project conventions surfaced by the view

### Memory: `slots = 0` means soldered

Rendered as `slots: soldered (0)` rather than the bare `0`. Without the
explicit "soldered" gloss, `0` reads like missing data. The bundle's
marker is preserved.

### Storage: `storage_slots` is a list

Initially read as a scalar; it's actually a list-of-slot offerings
(each slot has a `gen` leaf for its PCIe generation). Caught and fixed
in Stage 4 — the loader's `_OFFERINGS_FIELDS` set now correctly groups
it with the other offering columns.

### Boards: per-board GPU options nested under each board

A board offering has scalar leaves (`label`, `tgp_max`, `tpp_max`,
plus the Lenovo-only `arch_marker` added in T7.0a) plus a `gpus`
array of model-name bundles. The view lists each GPU model with its
own `[marker]`, then drops one indent and runs catalog enrichment
under it. Board configurations that ship with multiple GPU SKUs
(e.g. Zephyrus G16 MB1 → either RTX 5070 Ti or RTX 5080) all show
under the same board.

`arch_marker` renders inline as `arch: <value>` per board (no marker
suffix — it's a plain-shape leaf, not a bundle).

---

## Encoding note (Windows console)

The em-dash marker `[—]` and the `×` character in resolution strings
(`2560×1600`) are not in cp1252, the default Windows console encoding.
`cli/inspect_product.py:main()` calls `sys.stdout.reconfigure(encoding="utf-8")`
before printing so these characters render cleanly on PowerShell. The
call is wrapped in a try/except so it's a no-op on platforms where it
doesn't apply.

---

## Section order

The orchestrator emits sections in a fixed order:

1. **Identity** (header rule + 6 identity fields)
2. **CPU** → **Boards** (compute)
3. **Memory** → **Storage** (RAM/disk)
4. **Display**
5. **Keyboard** → **Camera** → **Audio** (input/output peripherals)
6. **Network** → **I/O** (connectivity)
7. **Battery** → **Adapter** (power)
8. **Thermals** → **Dimensions** → **Weight** → **Design** (physical)

The order roughly tracks how a user mentally categorizes a laptop spec
sheet. It's not load-bearing — re-arrange if a future workflow benefits
from a different grouping.

---

## `field_paths(product)` — the fillable-cell registry

Stage 5 added a `field_paths(product) -> list[(field_path, display_label)]`
helper to every per-category view module, plus an `_identity_field_paths`
in `orchestrator.py`. Each helper returns the dotted paths to every
fillable bundle the section currently exposes on the loaded product:

- Scalar columns emit one entry per column: `(audio_jack, audio_jack)`.
- Offerings columns walk the product's existing offerings list and emit
  per-leaf paths: `(display_offerings.0.nits_peak, "offering 0 - nits_peak")`.
- If an offerings list is empty / `None`, that section contributes zero
  paths (the section is a "no offerings recorded" issue, not a "fill the
  cell" issue — `find-empty` correctly skips such sections).
- Catalog leaves on `cpu_catalog` / `gpu_catalog` are NOT included.
  Those live on the catalog rows, not the products row, and aren't
  fillable via per-product `manual-edit`. CPU and Boards therefore
  expose only the product-level leaves (the `model` bundles, the board
  scalars, `cpu_tdp_max`).
- The Boards section excludes the per-board `gpus` array. Its 4-level
  path shape (`boards.N.gpus.M`) isn't supported by `manual-edit` /
  `resolve` yet.
- The Boards section also excludes `boards.{idx}.label` (T7.0e,
  Session 15). After T7.0c the display value is always the synthesized
  per-product ordinal `MB{ordinal}`, so manual edits to the stored
  label were silently masked at render. Dropping the leaf from
  `field_paths` keeps `manual-edit` honest. The label is still stored
  in the bundle (load-bearing for cross-tile merge); just not user-editable.
- Plain-shape offering leaves (registry: `cli/_paths.py::_PLAIN_OFFERING_LEAVES`,
  today `{("boards", "arch_marker")}`) are included in `field_paths`
  but go through `write_plain_at_path` rather than `write_bundle_at_path`
  in `manual-edit`. The view renders them inline with no `[marker]`
  suffix — same shape as the catalog spec lines.

`views/orchestrator.all_field_paths(product)` aggregates across the 16
sections (plus identity) in render order, returning
`list[(section_name, field_path, display_label)]`. That's the spine
`find-empty` walks: classify each path's value (empty / vendor-doesn't-
publish / filled), group the misses by `section_name`, print.

**Why per-module helpers, not a central registry module?** The labels
already live next to the per-category render code. Adding a separate
registry module would either duplicate or be a parallel structure that
could drift out of sync. The orchestrator's `_SECTION_REGISTRY` is the
only central piece — it's a small list of `(section_name, callable)`
pairs that mirrors `render_product`'s call order. A drift between the
registry and `render_product` is loud (it'd `AttributeError` on import
or skip a section in find-empty's output, both visible immediately).
