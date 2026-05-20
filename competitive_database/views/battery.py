"""Battery section: zero or more battery offerings (wattage / cells / tier).

Stage 10b rollup: visual tables collapse each offering to a
``<Wh>Wh <cells>-cell`` triple, joined by ``" · "``. When ``cells`` is
NULL on an offering, that offering renders as just ``<Wh>Wh``. The
``tier`` leaf is dropped from the rollup.
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
    ("wattage (Wh)", "wattage_wh"),
    ("cell count", "cell_count"),
    ("tier", "tier"),
]

# Leaves consumed by the Stage 10b rollup (tier drops).
_ROLLUP_LEAVES: tuple[str, ...] = ("wattage_wh", "cell_count")


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("battery_offerings") or []):
        for _label, key in _LEAVES:
            out.append((f"battery_offerings.{idx}.{key}", f"offering {idx} - {key}"))
    return out


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def _fmt_wh(value: Any) -> str | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return f"{value}Wh"
    if f == int(f):
        return f"{int(f)}Wh"
    return f"{f}Wh"


def rollup_value(product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Battery rollup cell.

    Single offering → ``99Wh 6-cell``. Multi-offering →
    ``99Wh 6-cell · 70Wh 4-cell`` (dedupe first-occurrence). Offerings
    with NULL ``cell_count`` render as just ``<Wh>Wh``.
    """
    offerings = product.get("battery_offerings") or []
    if not offerings:
        return "", MARKER_EMPTY

    markers: list[str] = []
    parts: list[str] = []
    for offering in offerings:
        wh_bundle = offering.get("wattage_wh")
        cells_bundle = offering.get("cell_count")
        markers.append(marker_for_bundle(wh_bundle))
        markers.append(marker_for_bundle(cells_bundle))

        wh = _fmt_wh(_bundle_value(wh_bundle))
        cells = _bundle_value(cells_bundle)
        tokens: list[str] = []
        if wh:
            tokens.append(wh)
        if cells is not None:
            tokens.append(f"{cells}-cell")
        if tokens:
            part = " ".join(tokens)
            if part not in parts:
                parts.append(part)

    marker = worst_marker(markers)
    return " · ".join(parts), marker


def render(product: dict[str, Any]) -> str:
    offerings = product.get("battery_offerings") or []
    if not offerings:
        return section_heading("Battery", MARKER_EMPTY)

    out = [section_heading("Battery")]
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
