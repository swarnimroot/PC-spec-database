"""Memory section: 5 platform-capability scalars.

Special: ``memory_slots == 0`` is the project's convention for "soldered
(non-upgradable)" — render that explicitly so the user doesn't read it
as "missing".
"""

from __future__ import annotations

from typing import Any

from .formatting import (
    MARKER_EMPTY,
    format_leaf,
    marker_for_bundle,
    section_heading,
)


_FIELDS: list[tuple[str, str]] = [
    ("type", "memory_type"),
    ("max (GB)", "memory_max_gb"),
    ("speed (MT/s)", "memory_speed_mts"),
    ("slots", "memory_slots"),
    ("overclocking", "memory_overclocking"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def render(product: dict[str, Any]) -> str:
    bundles = [product.get(key) for _, key in _FIELDS]
    if all(b is None for b in bundles):
        return section_heading("Memory", MARKER_EMPTY)

    out = [section_heading("Memory")]
    for label, key in _FIELDS:
        bundle = product.get(key)
        if key == "memory_slots" and bundle and bundle.get("value") == 0:
            out.append(f"  slots: soldered (0) {marker_for_bundle(bundle)}")
        else:
            out.append(f"  {format_leaf(label, bundle)}")
    return "\n".join(out)
