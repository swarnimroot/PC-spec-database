"""Design section: cover materials, thermal shelf, lighting.

Stage 10b rollup: visual tables surface only A-cover and D-cover
materials. ``c_cover_material`` (always NULL in practice),
``thermal_shelf`` and ``lighting`` drop from the rollup but stay on the
Edit screen.

Rollup shapes:
* A and D set to the same material → ``<material> (A + D)``
* A and D set to different materials → ``<m1> (A) · <m2> (D)``
* Only A set → ``<material> (A)`` (and the mirror for D)
* All NULL → empty
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
    ("A-cover material", "a_cover_material"),
    ("C-cover material", "c_cover_material"),
    ("D-cover material", "d_cover_material"),
    ("thermal shelf", "thermal_shelf"),
    ("lighting", "lighting"),
]

# Cover-material scalars consumed by the Stage 10b rollup.
_ROLLUP_FIELDS: tuple[str, ...] = ("a_cover_material", "d_cover_material")


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def rollup_value(product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Design rollup cell."""
    a_b = product.get("a_cover_material")
    d_b = product.get("d_cover_material")
    if a_b is None and d_b is None:
        return "", MARKER_EMPTY

    marker = worst_marker(marker_for_bundle(b) for b in (a_b, d_b))
    a_v = _bundle_value(a_b)
    d_v = _bundle_value(d_b)

    if a_v and d_v:
        if str(a_v) == str(d_v):
            return f"{a_v} (A + D)", marker
        return f"{a_v} (A) · {d_v} (D)", marker
    if a_v:
        return f"{a_v} (A)", marker
    if d_v:
        return f"{d_v} (D)", marker
    return "", marker


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("Design", product, _FIELDS)
