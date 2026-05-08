"""Adapter section: zero or more adapter offerings + a connector scalar."""

from __future__ import annotations

from typing import Any

from .formatting import MARKER_EMPTY, format_leaf, section_heading


_LEAVES: list[tuple[str, str]] = [
    ("wattage (W)", "wattage_w"),
    ("tier", "tier"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("adapter_offerings") or []):
        for _label, key in _LEAVES:
            out.append((f"adapter_offerings.{idx}.{key}", f"offering {idx} - {key}"))
    out.append(("adapter_connector", "adapter_connector"))
    return out


def render(product: dict[str, Any]) -> str:
    offerings = product.get("adapter_offerings") or []
    connector = product.get("adapter_connector")

    if not offerings and connector is None:
        return section_heading("Adapter", MARKER_EMPTY)

    out = [section_heading("Adapter")]

    if not offerings:
        out.append(f"  Offerings: {MARKER_EMPTY}")
    else:
        total = len(offerings)
        for idx, offering in enumerate(offerings, 1):
            if total > 1:
                out.append(f"  Offering {idx}")
                indent = "    "
            else:
                indent = "  "
            for label, key in _LEAVES:
                out.append(f"{indent}{format_leaf(label, offering.get(key))}")

    out.append(f"  {format_leaf('connector', connector)}")
    return "\n".join(out)
