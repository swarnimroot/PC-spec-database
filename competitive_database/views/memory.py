"""Memory section: 5 platform-capability scalars.

Special: ``memory_slots == 0`` is the project's convention for "soldered
(non-upgradable)" — render that explicitly so the user doesn't read it
as "missing".

Stage 10b rollup: visual tables collapse the four populated scalars to
``<type> <speed>MT/s · <slots> slots ; up to <max>GB``. Overclocking
drops from the rollup (still on the Edit screen).
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


_FIELDS: list[tuple[str, str]] = [
    ("type", "memory_type"),
    ("max (GB)", "memory_max_gb"),
    ("speed (MT/s)", "memory_speed_mts"),
    ("slots", "memory_slots"),
    ("overclocking", "memory_overclocking"),
]

# Scalars that feed the rollup cell. memory_overclocking drops.
_ROLLUP_FIELDS: tuple[str, ...] = (
    "memory_type",
    "memory_speed_mts",
    "memory_slots",
    "memory_max_gb",
)


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def rollup_value(product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Memory rollup cell.

    ``<type> <speed>MT/s · <slots> slots ; up to <max>GB``.

    ``slots == 0`` renders as ``soldered`` (project convention for
    non-upgradable RAM). Any missing leaf drops its segment but the
    sentence still composes from the remaining leaves.
    """
    bundles = {key: product.get(key) for key in _ROLLUP_FIELDS}
    if all(b is None for b in bundles.values()):
        return "", MARKER_EMPTY

    marker = worst_marker(marker_for_bundle(b) for b in bundles.values())

    type_v = _bundle_value(bundles["memory_type"])
    speed_v = _bundle_value(bundles["memory_speed_mts"])
    slots_v = _bundle_value(bundles["memory_slots"])
    max_v = _bundle_value(bundles["memory_max_gb"])

    head_tokens: list[str] = []
    if type_v:
        head_tokens.append(str(type_v))
    if speed_v is not None:
        head_tokens.append(f"{speed_v}MT/s")

    if slots_v is not None:
        slot_token = "soldered" if slots_v == 0 else f"{slots_v} slots"
    else:
        slot_token = None

    first_clause = " ".join(head_tokens)
    if slot_token:
        first_clause = (
            f"{first_clause} · {slot_token}" if first_clause else slot_token
        )

    if max_v is not None:
        max_clause = f"up to {max_v}GB"
        if first_clause:
            return f"{first_clause} ; {max_clause}", marker
        return max_clause, marker
    return first_clause, marker


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
