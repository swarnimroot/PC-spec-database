"""JSON serializers that translate our DB shapes into the React prototype's
value / model / schema objects.

The React Spec Finder reuses these shapes verbatim (see
``.tmp_design/comp-database/project/shared/data.js``):

  - value object: ``{v, s, src, ts, note}``
  - model object: ``{id, brand, series, model, segment, years, updated,
    base, byYear}``
  - schema: ordered categories -> ordered fields (labels)

Only the visual (rollup) sections contribute spec-map fields, honoring the
"keep our sections + gen-level CPU/GPU" constraint. Per-SKU offering paths
are intentionally NOT surfaced here.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Optional

from ..db.helpers import list_all_product_identities
from ..views import (
    adapter,
    audio,
    battery,
    boards,
    camera,
    cpu,
    design,
    dimensions,
    display,
    io,
    memory,
    network,
    orchestrator,
    storage,
    weight,
)
from ..query.engine import resolve_path
from ..views.formatting import (
    MARKER_EMPTY,
    MARKER_MANUAL,
    MARKER_NEEDS_REVIEW,
    MARKER_PARTIAL,
    MARKER_VENDOR_NO_PUB,
    MARKER_VERIFIED,
)
from ..views.load import load_cpu_catalog, load_gpu_catalog, load_product

# ---------------------------------------------------------------------------
# State mapping — the single source of truth (6 stored statuses -> 5 display
# states, plus the marker-token mapping for rollup-derived cells).
# ---------------------------------------------------------------------------

#: Stored bundle ``status`` value -> display state used by the React UI.
STATUS_TO_STATE: dict[str, str] = {
    "verified": "confirmed",
    "vouched": "confirmed",
    "vendor-doesn't-publish": "not_published",
    "manual": "hand",
    "needs-review": "review",
}

#: View-layer marker token -> display state (for rollup cells, which expose a
#: marker rather than a raw status).
MARKER_TO_STATE: dict[str, str] = {
    MARKER_VERIFIED: "confirmed",
    MARKER_MANUAL: "hand",
    MARKER_VENDOR_NO_PUB: "not_published",
    MARKER_NEEDS_REVIEW: "review",
    MARKER_EMPTY: "blank",
    MARKER_PARTIAL: "review",
}

#: Display state for an absent / NULL bundle.
_BLANK_STATE = "blank"


def state_for_status(status: Optional[str]) -> str:
    """Map a stored bundle ``status`` (or None) to a display state."""
    if status is None:
        return _BLANK_STATE
    return STATUS_TO_STATE.get(status, "review")


def state_for_marker(marker: str) -> str:
    """Map a view-layer marker token to a display state."""
    return MARKER_TO_STATE.get(marker, "review")


# ---------------------------------------------------------------------------
# Value object builder
# ---------------------------------------------------------------------------


def value_object(bundle_or_plain: Any) -> dict[str, Any]:
    """Build a ``{v, s, src, ts, note}`` value object.

    Accepts a provenance bundle dict, a plain string leaf, or None. For a
    bundle, ``v`` is its value (string or list), ``s`` the display state,
    ``src`` the source_url or source_note, ``ts`` captured_at or entered_at,
    and ``note`` the source_note / note.
    """
    if bundle_or_plain is None:
        return {"v": None, "s": _BLANK_STATE, "src": None, "ts": None, "note": None}
    if not isinstance(bundle_or_plain, dict):
        # Plain string leaf — scraped/verified by construction.
        return {
            "v": bundle_or_plain,
            "s": "confirmed",
            "src": None,
            "ts": None,
            "note": None,
        }
    bundle = bundle_or_plain
    status = bundle.get("status")
    state = state_for_status(status)
    value = bundle.get("value")
    # vendor-doesn't-publish bundles carry value=None but are a known absence.
    src = bundle.get("source_url") or bundle.get("source_note")
    ts = bundle.get("captured_at") or bundle.get("entered_at")
    note = bundle.get("source_note") or bundle.get("note")
    return {"v": value, "s": state, "src": src, "ts": ts, "note": note}


def _rollup_value_object(value_str: str, marker: str) -> dict[str, Any]:
    """Build a value object from a rollup ``(value_str, marker)`` pair.

    Empty rollup strings collapse to ``v=None``. Multi-option rollups are
    kept as a single joined string (the view layer already deduped + joined);
    splitting back to a list would re-derive structure the rollup discarded.
    """
    v: Any = value_str if value_str else None
    state = state_for_marker(marker)
    return {"v": v, "s": state, "src": None, "ts": None, "note": None}


# ---------------------------------------------------------------------------
# Section -> rollup registry. Single-value sections expose ``rollup_value``;
# I/O exposes ``rollup_rows`` (multiple sub-rows). CPU and Graphics need the
# catalog dicts.
# ---------------------------------------------------------------------------

# field_key, section_label, rollup callable (product[, catalog]) -> (str, marker)
_SINGLE_SECTIONS: list[tuple[str, str, Callable[..., tuple[str, str]], str]] = [
    ("processor", "Processor", cpu.rollup_value, "cpu"),
    ("graphics", "Graphics", boards.rollup_value, "gpu"),
    ("display", "Display", display.rollup_value, ""),
    ("memory", "Memory", memory.rollup_value, ""),
    ("storage", "Storage", storage.rollup_value, ""),
    ("camera", "Camera", camera.rollup_value, ""),
    ("audio", "Audio", audio.rollup_value, ""),
    ("network", "Network", network.rollup_value, ""),
    ("battery", "Battery", battery.rollup_value, ""),
    ("adapter", "Adapter", adapter.rollup_value, ""),
    ("dimensions", "Dimensions", dimensions.rollup_value, ""),
    ("weight", "Weight", weight.rollup_value, ""),
    ("design", "Design", design.rollup_value, ""),
]

# I/O sub-row labels, in render order (see io.rollup_rows).
_IO_SUBROW_LABELS = ["USB", "HDMI", "SD card", "Audio jack"]


def _io_field_key(label: str) -> str:
    return "io_" + label.lower().replace(" ", "_")


def _spec_map(
    product: dict[str, Any],
    cpu_catalog: dict[str, dict[str, Any]],
    gpu_catalog: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build the spec map ``{fieldKey: value_object}`` for one loaded product.

    Keys are our visual section field keys; I/O contributes its sub-rows.
    """
    spec: dict[str, dict[str, Any]] = {}
    for field_key, _label, fn, catalog in _SINGLE_SECTIONS:
        if catalog == "cpu":
            value_str, marker = fn(product, cpu_catalog)
        elif catalog == "gpu":
            value_str, marker = fn(product, gpu_catalog)
        else:
            value_str, marker = fn(product)
        spec[field_key] = _rollup_value_object(value_str, marker)
    for label, value_str, marker in io.rollup_rows(product):
        spec[_io_field_key(label)] = _rollup_value_object(value_str, marker)
    return spec


# ---------------------------------------------------------------------------
# Schema builder
# ---------------------------------------------------------------------------


def schema() -> dict[str, Any]:
    """Return ``{categories: [...]}`` — ordered categories + fields.

    Each visual section is one category. Single-rollup sections expose a
    single field (the section value); I/O exposes its four sub-rows.
    """
    categories: list[dict[str, Any]] = []
    for field_key, label, _fn, _catalog in _SINGLE_SECTIONS:
        categories.append(
            {
                "id": field_key,
                "label": label,
                "fields": [{"key": field_key, "label": label}],
            }
        )
    io_fields = [
        {"key": _io_field_key(label), "label": label} for label in _IO_SUBROW_LABELS
    ]
    categories.append({"id": "io", "label": "I/O", "fields": io_fields})
    return {"categories": categories}


# ---------------------------------------------------------------------------
# Model object builder
# ---------------------------------------------------------------------------


def load_identity_rows(
    conn: sqlite3.Connection,
    brand: str,
    series: Optional[str],
    product_name: str,
) -> list[dict[str, Any]]:
    """Load every (product, year) row for one identity, DESC by year.

    Uses ``json_extract(series, '$.value')`` for the series predicate to stay
    consistent with ``list_all_product_identities`` (which reads the stored
    ``$.value``). ``db.helpers.load_product_rows`` instead filters series via a
    SQL ``IS NULL`` check, which misses rows whose series column holds a JSON
    bundle of ``{"value": null, ...}`` rather than a SQL NULL — the documented
    series=None zero-rows bug. This loader sidesteps it; ``db/`` is out of
    scope for edits, so the fix lives here in the API layer.
    """
    if series is None:
        sql = (
            "SELECT model_code, year FROM products "
            "WHERE json_extract(brand, '$.value') = ? "
            "AND json_extract(series, '$.value') IS NULL "
            "AND product = ? ORDER BY year DESC"
        )
        params: tuple = (brand, product_name)
    else:
        sql = (
            "SELECT model_code, year FROM products "
            "WHERE json_extract(brand, '$.value') = ? "
            "AND json_extract(series, '$.value') = ? "
            "AND product = ? ORDER BY year DESC"
        )
        params = (brand, series, product_name)
    rows = conn.execute(sql, params).fetchall()
    return [load_product(conn, r["model_code"], r["year"]) for r in rows]


def _identity_for_model_code(
    conn: sqlite3.Connection, model_code: str
) -> Optional[dict[str, Any]]:
    """Find the (brand, series, product) identity owning ``model_code``."""
    row = conn.execute(
        "SELECT json_extract(brand, '$.value') AS b, "
        "json_extract(series, '$.value') AS s, product AS p "
        "FROM products WHERE model_code = ?",
        (model_code,),
    ).fetchone()
    if row is None:
        return None
    return {"brand": row[0], "series": row[1], "product": row[2]}


def _updated_date(product: dict[str, Any]) -> Optional[str]:
    """Latest captured_at / entered_at across all bundles, as YYYY-MM-DD."""
    best: Optional[str] = None
    for val in product.values():
        if not isinstance(val, dict):
            continue
        ts = val.get("captured_at") or val.get("entered_at")
        if ts and (best is None or ts > best):
            best = ts
    if best is None:
        return None
    return best[:10]


def model_object(conn: sqlite3.Connection, model_code: str) -> dict[str, Any]:
    """Build one model object for the identity owning ``model_code``.

    A "model" is one (brand, series, product) identity spanning one or more
    year rows. ``base`` is the LATEST year's spec map; ``byYear`` holds only
    the fields whose value differs from base for each other year, so the
    prototype's ``resolve(base, override)`` merge reproduces every year.
    ``id`` is the latest year's model_code.
    """
    identity = _identity_for_model_code(conn, model_code)
    if identity is None:
        raise LookupError(f"no product with model_code={model_code!r}")
    brand = identity["brand"]
    series = identity["series"]
    product_name = identity["product"]

    rows = load_identity_rows(conn, brand, series, product_name)
    if not rows:
        raise LookupError(
            f"no rows for identity brand={brand!r} series={series!r} "
            f"product={product_name!r}"
        )
    cpu_catalog = load_cpu_catalog(conn)
    gpu_catalog = load_gpu_catalog(conn)

    # rows are DESC by year (load_product_rows orders year DESC).
    rows_by_year = {int(r["year"]): r for r in rows}
    years = sorted(rows_by_year.keys())
    latest_year = years[-1]

    base_spec = _spec_map(rows_by_year[latest_year], cpu_catalog, gpu_catalog)

    by_year: dict[str, dict[str, Any]] = {}
    for year in years:
        if year == latest_year:
            continue
        full = _spec_map(rows_by_year[year], cpu_catalog, gpu_catalog)
        override = {
            key: val
            for key, val in full.items()
            if val.get("v") != base_spec.get(key, {}).get("v")
        }
        by_year[str(year)] = override

    latest_row = rows_by_year[latest_year]
    segment_bundle = latest_row.get("segment") or latest_row.get("sub_brand")
    segment = None
    if isinstance(segment_bundle, dict):
        segment = segment_bundle.get("value")

    return {
        "id": latest_row.get("model_code"),
        "brand": brand,
        "series": series,
        "model": product_name,
        "segment": segment,
        "years": years,
        "updated": _updated_date(latest_row),
        "base": base_spec,
        "byYear": by_year,
    }


# ---------------------------------------------------------------------------
# Detail (accordion "expand") — raw leaf values, not the rollup codes.
#
# The visual spec map (``_spec_map``) collapses each section to one rollup
# string (e.g. CPU "ARL-HX R", Graphics "MB1"). The Compare accordion needs
# the underlying RAW leaves: actual CPU model names, display specs, GPU model
# strings, etc. Those come from ``orchestrator.all_field_paths`` (the canonical
# per-field walk) resolved against the loaded product via ``resolve_path``.
# ---------------------------------------------------------------------------

#: ``all_field_paths`` section_label -> compare schema section key. Built from
#: ``_SINGLE_SECTIONS`` (which already pairs field_key with its render label)
#: plus the I/O special case. Sections NOT in this map (Identity, Keyboard,
#: Thermals) are intentionally skipped — they don't surface on Compare.
_LABEL_TO_SECTION_KEY: dict[str, str] = {
    label: field_key for field_key, label, _fn, _catalog in _SINGLE_SECTIONS
}
_LABEL_TO_SECTION_KEY["I/O"] = "io"

#: Compare section order (the order the accordion renders sections in).
_DETAIL_SECTION_ORDER: list[str] = [field_key for field_key, _l, _f, _c in _SINGLE_SECTIONS]
_DETAIL_SECTION_ORDER.append("io")



#: Display-state precedence for the worst-state rollup across a leaf group.
#: review (most urgent) > not_published > hand > confirmed; anything else
#: (e.g. blank) loses to all of these and leaves the group state blank.
_STATE_PRECEDENCE: dict[str, int] = {
    "review": 4,
    "not_published": 3,
    "hand": 2,
    "confirmed": 1,
}

#: Friendly display label per leaf id (the last path segment). Detail rows are
#: grouped by leaf id (so all CPU offerings collapse into one "CPU model" row),
#: and this maps the snake_case id to a clean label. Anything missing falls
#: back to a generic prettifier (_friendly_leaf).
_FRIENDLY_LEAF: dict[str, str] = {
    "model": "CPU model",
    "cpu_tdp_max": "Max TDP",
    "gpu": "GPU",
    "tgp_max": "TGP",
    "tpp_max": "TPP",
    "arch_marker": "Architecture",
    "size_inches": "Size",
    "panel_type": "Panel",
    "resolution_label": "Resolution",
    "resolution_pixels": "Resolution (px)",
    "refresh_rate_hz": "Refresh rate",
    "nits_peak": "Brightness (nits)",
    "hdr_certification": "HDR",
    "dci_p3_pct": "DCI-P3 %",
    "srgb_pct": "sRGB %",
    "response_time_ms": "Response time",
    "vrr": "VRR",
    "anti_glare": "Anti-glare",
    "tier": "Tier",
    "memory_type": "Type",
    "memory_max_gb": "Max capacity",
    "memory_speed_mts": "Speed (MT/s)",
    "memory_slots": "Slots",
    "memory_overclocking": "Overclocking",
    "storage_max_gb": "Max capacity",
    "gen": "Slot gen",
    "resolution": "Resolution",
    "ir_supported": "IR camera",
    "privacy_shutter": "Privacy shutter",
    "speaker_count": "Speakers",
    "tuning_brand": "Tuning",
    "has_subwoofer": "Subwoofer",
    "wifi_standard": "Wi-Fi",
    "ethernet": "Ethernet",
    "bluetooth_version": "Bluetooth",
    "wattage_wh": "Capacity (Wh)",
    "cell_count": "Cells",
    "wattage_w": "Wattage",
    "adapter_connector": "Connector",
    "width_mm": "Width (mm)",
    "depth_mm": "Depth (mm)",
    "height_mm_min": "Height min (mm)",
    "height_mm_max": "Height max (mm)",
    "weight_kg_min": "Weight min (kg)",
    "weight_kg_max": "Weight max (kg)",
    "a_cover_material": "A-cover",
    "c_cover_material": "C-cover",
    "d_cover_material": "D-cover",
    "thermal_shelf": "Thermal shelf",
    "lighting": "Lighting",
    "description": "Description",
    "has_numpad": "Numpad",
    "usbc_thunderbolt_count": "Thunderbolt ports",
    "usbc_thunderbolt_version": "Thunderbolt version",
    "usbc_non_thunderbolt_count": "USB-C ports",
    "usbc_non_thunderbolt_version": "USB-C version",
    "usba_count": "USB-A ports",
    "usba_version": "USB-A version",
    "hdmi_count": "HDMI ports",
    "hdmi_version": "HDMI version",
    "sd_card": "SD card",
    "sd_card_speed": "SD card speed",
    "audio_jack": "Audio jack",
}

_LEAF_ACRONYMS = {"hdr", "vrr", "usb", "sd", "io"}


def _friendly_leaf(leaf_id: str) -> str:
    """Friendly label for a leaf id, via the override map or a generic prettify."""
    if leaf_id in _FRIENDLY_LEAF:
        return _FRIENDLY_LEAF[leaf_id]
    words = leaf_id.split("_")
    return " ".join(w.upper() if w in _LEAF_ACRONYMS else w.capitalize() for w in words)


def _gpu_value_objects(product: dict[str, Any]) -> list[dict[str, Any]]:
    """One value object per GPU on every board.

    ``all_field_paths`` for Graphics yields only tgp_max / tpp_max /
    arch_marker — never the GPU name. The GPU model lives in
    ``product["boards"][n]["gpus"][m]`` where each entry is either a
    provenance bundle (``{"value": ...}``) or a plain string (see
    ``views.boards._bundle_value``). ``value_object`` already handles both
    shapes, so pass each raw entry straight through.
    """
    out: list[dict[str, Any]] = []
    for board in product.get("boards") or []:
        for gpu in board.get("gpus") or []:
            out.append(value_object(gpu))
    return out


def _merge_group(value_objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse a leaf group's value objects into one ``{v, s, src, ts, note}``.

    ``v`` is the distinct non-null values joined by " · " (None if all empty);
    ``s`` is the worst display-state by ``_STATE_PRECEDENCE`` (blank if none of
    the precedence states are present); ``src`` / ``ts`` / ``note`` come from
    the first value object that carries each.
    """
    parts: list[str] = []
    for vo in value_objects:
        v = vo.get("v")
        if v is None:
            continue
        if isinstance(v, list):
            pieces = [str(x) for x in v if x is not None and str(x) != ""]
        else:
            pieces = [str(v)] if str(v) != "" else []
        for piece in pieces:
            if piece not in parts:
                parts.append(piece)

    best_state = ""
    best_rank = 0
    for vo in value_objects:
        rank = _STATE_PRECEDENCE.get(vo.get("s", ""), 0)
        if rank > best_rank:
            best_rank = rank
            best_state = vo["s"]

    src = next((vo.get("src") for vo in value_objects if vo.get("src")), None)
    ts = next((vo.get("ts") for vo in value_objects if vo.get("ts")), None)
    note = next((vo.get("note") for vo in value_objects if vo.get("note")), None)

    return {
        # Multiple distinct values -> a list so the UI renders them on
        # separate lines (ValueCell stacks list items); single -> scalar.
        "v": parts if len(parts) > 1 else (parts[0] if parts else None),
        "s": best_state,
        "src": src,
        "ts": ts,
        "note": note,
    }


def _detail_rows(product: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build ``{section_key: [row, ...]}`` of raw detail leaves for a product.

    Walks ``all_field_paths``, mapping each section_label to a compare section
    key (skipping unmapped sections), grouping leaves by (section_key,
    leaf_label) in first-seen order. The Graphics GPU synthetic leaf is
    prepended so the actual GPU model names surface on expand.
    """
    # (section_key, leaf_label) -> list[value object], first-seen order kept by
    # ``order`` so dict insertion order = render order per section.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    order: dict[str, list[str]] = {}

    def _add(section_key: str, leaf_label: str, vo: dict[str, Any]) -> None:
        gkey = (section_key, leaf_label)
        if gkey not in groups:
            groups[gkey] = []
            order.setdefault(section_key, []).append(leaf_label)
        groups[gkey].append(vo)

    # Graphics GPU synthetic leaf — PREPENDED (registered before the walk so
    # it sorts first within the graphics section).
    gpu_objs = _gpu_value_objects(product)
    if gpu_objs:
        for vo in gpu_objs:
            _add("graphics", "gpu", vo)

    # Group by LEAF ID (the last path segment) so every offering / board of a
    # given attribute collapses into one row (all CPUs → one "CPU model" row),
    # rather than one ragged row per offering index.
    for section_label, field_path, _leaf_label in orchestrator.all_field_paths(product):
        section_key = _LABEL_TO_SECTION_KEY.get(section_label)
        if section_key is None:
            continue
        leaf_id = field_path.split(".")[-1]
        bundle, plain = resolve_path(product, field_path)
        if plain is not None:
            vo = value_object(plain)
        else:
            vo = value_object(bundle)
        _add(section_key, leaf_id, vo)

    sections: dict[str, list[dict[str, Any]]] = {}
    for section_key in _DETAIL_SECTION_ORDER:
        leaf_ids = order.get(section_key)
        if not leaf_ids:
            continue
        rows = []
        for leaf_id in leaf_ids:
            merged = _merge_group(groups[(section_key, leaf_id)])
            rows.append(
                {
                    "key": f"{section_key}.{leaf_id}",
                    "label": _friendly_leaf(leaf_id),
                    "value": merged,
                }
            )
        sections[section_key] = rows
    return sections


def model_detail(
    conn: sqlite3.Connection, model_code: str, year: int
) -> dict[str, Any]:
    """Raw detail leaves for one (model_code, year), grouped by compare section.

    Resolves the identity the same way ``model_object`` does (a missing
    model_code raises ``LookupError``), loads the row for ``year``, then walks
    every fillable cell to surface the actual underlying values (CPU model
    names, GPU names, display specs, ...) the rollup hides.

    Returns ``{id, year, sections: {section_key: [rows...]}}`` with only the
    sections that have at least one row, in compare section order.
    """
    identity = _identity_for_model_code(conn, model_code)
    if identity is None:
        raise LookupError(f"no product with model_code={model_code!r}")
    product = load_product(conn, model_code, year)
    return {
        "id": model_code,
        "year": year,
        "sections": _detail_rows(product),
    }


def detail_schema(conn: sqlite3.Connection) -> dict[str, Any]:
    """Union of every possible detail leaf per compare section, across all models.

    Scans every product, collecting the DISTINCT (section_key, leaf_label) set
    in first-seen order per section (same grouping + Graphics GPU synthetic
    leaf as ``model_detail``). Feeds the field-visibility panel, so it lists
    every leaf any model could expose even if a given model lacks it.

    Returns ``{sections: {section_key: [{key, label}, ...]}}`` covering every
    compare section, in compare section order.
    """
    # section_key -> ordered list of {key, label} (first-seen across all models),
    # deduped by key.
    seen: dict[str, list[dict[str, str]]] = {}
    seen_keys: dict[str, set[str]] = {}

    rows = conn.execute("SELECT model_code, year FROM products").fetchall()
    for row in rows:
        product = load_product(conn, row["model_code"], row["year"])
        for section_key, leaves in _detail_rows(product).items():
            bucket = seen.setdefault(section_key, [])
            keyset = seen_keys.setdefault(section_key, set())
            for leaf in leaves:
                if leaf["key"] not in keyset:
                    keyset.add(leaf["key"])
                    bucket.append({"key": leaf["key"], "label": leaf["label"]})

    sections: dict[str, list[dict[str, str]]] = {
        section_key: seen.get(section_key, []) for section_key in _DETAIL_SECTION_ORDER
    }
    return {"sections": sections}


def catalog(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Build a model object for every distinct identity in the DB.

    One model per (brand, series, product) identity. The identity's latest
    year row supplies the ``id`` model_code.
    """
    identities = list_all_product_identities(conn)
    out: list[dict[str, Any]] = []
    for ident in identities:
        if ident["series"] is None:
            sql = (
                "SELECT model_code FROM products "
                "WHERE json_extract(brand, '$.value') = ? "
                "AND json_extract(series, '$.value') IS NULL "
                "AND product = ? ORDER BY year DESC LIMIT 1"
            )
            params: tuple = (ident["brand"], ident["product"])
        else:
            sql = (
                "SELECT model_code FROM products "
                "WHERE json_extract(brand, '$.value') = ? "
                "AND json_extract(series, '$.value') = ? "
                "AND product = ? ORDER BY year DESC LIMIT 1"
            )
            params = (ident["brand"], ident["series"], ident["product"])
        latest = conn.execute(sql, params).fetchone()
        if latest is None:
            continue
        out.append(model_object(conn, latest["model_code"]))
    return out
