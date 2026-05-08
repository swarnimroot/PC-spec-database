"""Audio section: speakers, tuning, subwoofer."""

from __future__ import annotations

from typing import Any

from .formatting import render_scalar_section


_FIELDS: list[tuple[str, str]] = [
    ("speaker count", "speaker_count"),
    ("tuning brand", "tuning_brand"),
    ("subwoofer", "has_subwoofer"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("Audio", product, _FIELDS)
