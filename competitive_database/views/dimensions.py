"""Dimensions section: width, depth, min/max height (mm)."""

from __future__ import annotations

from typing import Any

from .formatting import render_scalar_section


_FIELDS: list[tuple[str, str]] = [
    ("width (mm)", "width_mm"),
    ("depth (mm)", "depth_mm"),
    ("height min (mm)", "height_mm_min"),
    ("height max (mm)", "height_mm_max"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("Dimensions", product, _FIELDS)
