"""Camera section: zero or more camera offerings."""

from __future__ import annotations

from typing import Any

from .formatting import MARKER_EMPTY, format_leaf, section_heading


_LEAVES: list[tuple[str, str]] = [
    ("resolution", "resolution"),
    ("IR supported", "ir_supported"),
    ("privacy shutter", "privacy_shutter"),
    ("tier", "tier"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("camera_offerings") or []):
        for _label, key in _LEAVES:
            out.append((f"camera_offerings.{idx}.{key}", f"offering {idx} - {key}"))
    return out


def render(product: dict[str, Any]) -> str:
    offerings = product.get("camera_offerings") or []
    if not offerings:
        return section_heading("Camera", MARKER_EMPTY)

    out = [section_heading("Camera")]
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
