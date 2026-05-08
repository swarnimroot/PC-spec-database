"""Storage section: per-slot offerings (PCIe gen) + platform max."""

from __future__ import annotations

from typing import Any

from .formatting import (
    MARKER_EMPTY,
    format_leaf,
    section_heading,
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
