"""Weight section: min/max kg (varies by display panel weight, etc.).

Stage 10b rollup: visual tables collapse to ``<min>-<max> kg``. When
only one side is set the cell renders ``<value> kg min`` or
``<value> kg max``. All-NULL → empty.
"""

from __future__ import annotations

from typing import Any

from .formatting import (
    MARKER_EMPTY,
    marker_for_bundle,
    render_scalar_section,
    worst_marker,
)


_FIELDS: list[tuple[str, str]] = [
    ("min (kg)", "weight_kg_min"),
    ("max (kg)", "weight_kg_max"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def _fmt_num(value: Any) -> str | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f == int(f):
        return str(int(f))
    return str(f)


def rollup_value(product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Weight rollup cell.

    Both → ``<min>-<max> kg``. Min-only → ``<v> kg min``. Max-only →
    ``<v> kg max``. All-NULL → empty.
    """
    min_b = product.get("weight_kg_min")
    max_b = product.get("weight_kg_max")
    if min_b is None and max_b is None:
        return "", MARKER_EMPTY

    marker = worst_marker(marker_for_bundle(b) for b in (min_b, max_b))

    min_v = _fmt_num(_bundle_value(min_b))
    max_v = _fmt_num(_bundle_value(max_b))

    if min_v and max_v:
        return f"{min_v}-{max_v} kg", marker
    if min_v:
        return f"{min_v} kg min", marker
    if max_v:
        return f"{max_v} kg max", marker
    return "", marker


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("Weight", product, _FIELDS)
