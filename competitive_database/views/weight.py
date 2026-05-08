"""Weight section: min/max kg (varies by display panel weight, etc.)."""

from __future__ import annotations

from typing import Any

from .formatting import render_scalar_section


_FIELDS: list[tuple[str, str]] = [
    ("min (kg)", "weight_kg_min"),
    ("max (kg)", "weight_kg_max"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("Weight", product, _FIELDS)
