"""Thermals section: design, material, TIM, fan count."""

from __future__ import annotations

from typing import Any

from .formatting import render_scalar_section


_FIELDS: list[tuple[str, str]] = [
    ("design", "thermal_design"),
    ("material", "thermal_material"),
    ("TIM", "tim"),
    ("fan count", "fan_count"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("Thermals", product, _FIELDS)
