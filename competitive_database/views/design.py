"""Design section: cover materials, thermal shelf, lighting."""

from __future__ import annotations

from typing import Any

from .formatting import render_scalar_section


_FIELDS: list[tuple[str, str]] = [
    ("A-cover material", "a_cover_material"),
    ("C-cover material", "c_cover_material"),
    ("D-cover material", "d_cover_material"),
    ("thermal shelf", "thermal_shelf"),
    ("lighting", "lighting"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("Design", product, _FIELDS)
