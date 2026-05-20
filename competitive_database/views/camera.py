"""Camera section: zero or more camera offerings.

Stage 10b rollup: visual tables surface only the per-offering
``resolution`` value, deduped first-occurrence and joined by ``" · "``.
IR / privacy_shutter / tier are dropped from the rollup (still on Edit).
"""

from __future__ import annotations

from typing import Any

from .formatting import (
    MARKER_EMPTY,
    format_leaf,
    marker_for_bundle,
    section_heading,
    worst_marker,
)


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


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def rollup_value(product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Camera rollup cell.

    Single offering → ``1080p``. Multi-offering → ``1080p · 720p``
    (dedupe first-occurrence). Marker is worst across each offering's
    ``resolution`` bundle.
    """
    offerings = product.get("camera_offerings") or []
    if not offerings:
        return "", MARKER_EMPTY

    markers: list[str] = []
    parts: list[str] = []
    for offering in offerings:
        bundle = offering.get("resolution")
        markers.append(marker_for_bundle(bundle))
        value = _bundle_value(bundle)
        if value is None:
            continue
        text = str(value)
        if text and text not in parts:
            parts.append(text)

    return " · ".join(parts), worst_marker(markers)


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
