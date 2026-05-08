"""Battery section: zero or more battery offerings (wattage / cells / tier)."""

from __future__ import annotations

from typing import Any

from .formatting import MARKER_EMPTY, format_leaf, section_heading


_LEAVES: list[tuple[str, str]] = [
    ("wattage (Wh)", "wattage_wh"),
    ("cell count", "cell_count"),
    ("tier", "tier"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("battery_offerings") or []):
        for _label, key in _LEAVES:
            out.append((f"battery_offerings.{idx}.{key}", f"offering {idx} - {key}"))
    return out


def render(product: dict[str, Any]) -> str:
    offerings = product.get("battery_offerings") or []
    if not offerings:
        return section_heading("Battery", MARKER_EMPTY)

    out = [section_heading("Battery")]
    total = len(offerings)
    for idx, offering in enumerate(offerings, 1):
        if total > 1:
            out.append(f"  Offering {idx}")
            indent = "    "
        else:
            indent = "  "
        for label, key in _LEAVES:
            out.append(f"{indent}{format_leaf(label, offering.get(key))}")
    return "\n".join(out)
