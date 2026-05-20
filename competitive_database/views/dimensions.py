"""Dimensions section: width, depth, min/max height (mm).

Stage 10b rollup: visual tables collapse to
``<w> × <d> × <h_min>-<h_max> mm``. When only the max height is set,
``<w> × <d> × <h_max> mm``. When both heights are NULL,
``<w> × <d> mm``. When width or depth is missing, the rollup is empty.
Numeric values trim trailing ``.0`` so 354.0 renders as ``354``.
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
    ("width (mm)", "width_mm"),
    ("depth (mm)", "depth_mm"),
    ("height min (mm)", "height_mm_min"),
    ("height max (mm)", "height_mm_max"),
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
    """Return ``(display_string, marker_token)`` for the Dimensions rollup cell.

    ``<w> × <d> × <h_min>-<h_max> mm`` when all four are present;
    falls back per the section docstring rules when heights are
    missing. When width or depth is missing the rollup is empty —
    those two are load-bearing for a dimensions display.
    """
    bundles = {key: product.get(key) for _label, key in _FIELDS}
    if all(b is None for b in bundles.values()):
        return "", MARKER_EMPTY

    marker = worst_marker(marker_for_bundle(b) for b in bundles.values())

    w = _fmt_num(_bundle_value(bundles["width_mm"]))
    d = _fmt_num(_bundle_value(bundles["depth_mm"]))
    h_min = _fmt_num(_bundle_value(bundles["height_mm_min"]))
    h_max = _fmt_num(_bundle_value(bundles["height_mm_max"]))

    if not w or not d:
        return "", marker

    if h_min and h_max:
        return f"{w} × {d} × {h_min}-{h_max} mm", marker
    if h_max:
        return f"{w} × {d} × {h_max} mm", marker
    if h_min:
        return f"{w} × {d} × {h_min} mm", marker
    return f"{w} × {d} mm", marker


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("Dimensions", product, _FIELDS)
