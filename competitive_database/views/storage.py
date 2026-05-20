"""Storage section: per-slot offerings (PCIe gen) + platform max.

Stage 10b rollup: visual tables collapse the per-slot list to
``N× GenX [+ M× GenY] ; up to <max>TB``. Slots are bucketed by
``gen`` value, descending (Gen5 listed before Gen4). The platform
``storage_max_gb`` value always renders in TB on the rollup, with one
decimal place trimmed when zero.
"""

from __future__ import annotations

from typing import Any

from .formatting import (
    MARKER_EMPTY,
    format_leaf,
    marker_for_bundle,
    section_heading,
    worst_marker,
)


_SLOT_LEAVES: list[tuple[str, str]] = [
    ("PCIe gen", "gen"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("storage_slots") or []):
        for _label, key in _SLOT_LEAVES:
            out.append((f"storage_slots.{idx}.{key}", f"slot {idx} - {key}"))
    out.append(("storage_max_gb", "storage_max_gb"))
    return out


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def _fmt_tb(gb_value: Any) -> str | None:
    if gb_value is None:
        return None
    try:
        tb = float(gb_value) / 1000.0
    except (TypeError, ValueError):
        return None
    rounded = round(tb, 1)
    if rounded == int(rounded):
        return f"{int(rounded)}TB"
    return f"{rounded}TB"


def rollup_value(product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Storage rollup cell.

    ``N× GenX [+ M× GenY] ; up to <max>TB``. Slots are grouped by gen
    and ordered descending (Gen5 first). When ``storage_max_gb`` is set
    the cell appends ``; up to <max>TB``; when only the max is set the
    cell renders just that clause; when only slots are present the cell
    renders just the slot list.
    """
    slots = product.get("storage_slots") or []
    max_bundle = product.get("storage_max_gb")

    if not slots and max_bundle is None:
        return "", MARKER_EMPTY

    slot_bundles = [s.get("gen") for s in slots]
    markers = [marker_for_bundle(b) for b in slot_bundles]
    if max_bundle is not None:
        markers.append(marker_for_bundle(max_bundle))
    marker = worst_marker(markers)

    # Bucket slots by gen value, preserving insertion of distinct gens.
    counts_by_gen: dict[Any, int] = {}
    for bundle in slot_bundles:
        gen = _bundle_value(bundle)
        if gen is None:
            continue
        counts_by_gen[gen] = counts_by_gen.get(gen, 0) + 1

    # Sort by gen descending — numeric when possible, falling back to
    # string compare so unexpected values still produce stable output.
    def _sort_key(item: tuple[Any, int]) -> tuple[int, Any]:
        gen = item[0]
        try:
            return (0, -int(gen))
        except (TypeError, ValueError):
            return (1, str(gen))

    slot_clause = " + ".join(
        f"{count}× Gen{gen}"
        for gen, count in sorted(counts_by_gen.items(), key=_sort_key)
    )

    max_str = _fmt_tb(_bundle_value(max_bundle))
    max_clause = f"up to {max_str}" if max_str else ""

    if slot_clause and max_clause:
        return f"{slot_clause} ; {max_clause}", marker
    if slot_clause:
        return slot_clause, marker
    if max_clause:
        return max_clause, marker
    return "", marker


def render(product: dict[str, Any]) -> str:
    slots = product.get("storage_slots") or []
    max_gb = product.get("storage_max_gb")

    if not slots and max_gb is None:
        return section_heading("Storage", MARKER_EMPTY)

    out = [section_heading("Storage")]

    if not slots:
        out.append(f"  Slots: {MARKER_EMPTY}")
    else:
        out.append(f"  Slots: {len(slots)}")
        for idx, slot in enumerate(slots, 1):
            for label, key in _SLOT_LEAVES:
                out.append(f"    Slot {idx} {format_leaf(label, slot.get(key))}")

    out.append(f"  {format_leaf('max (GB)', max_gb)}")
    return "\n".join(out)
