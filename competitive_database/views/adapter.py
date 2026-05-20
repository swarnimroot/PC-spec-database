"""Adapter section: zero or more adapter offerings + a connector scalar.

Stage 10b rollup: visual tables collapse offerings to a list of
wattages joined by ``" · "`` followed by ``; <connector>`` when the
scalar ``adapter_connector`` is set. The ``tier`` per-offering leaf is
dropped from the rollup.
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
    ("wattage (W)", "wattage_w"),
    ("tier", "tier"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("adapter_offerings") or []):
        for _label, key in _LEAVES:
            out.append((f"adapter_offerings.{idx}.{key}", f"offering {idx} - {key}"))
    out.append(("adapter_connector", "adapter_connector"))
    return out


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def rollup_value(product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Adapter rollup cell.

    Wattages list (per-offering, deduped first-occurrence) joined by
    ``" · "`` then ``; <connector>`` when the scalar
    ``adapter_connector`` is set. Marker is worst across each offering's
    ``wattage_w`` bundle plus the connector bundle.
    """
    offerings = product.get("adapter_offerings") or []
    connector_bundle = product.get("adapter_connector")

    if not offerings and connector_bundle is None:
        return "", MARKER_EMPTY

    markers: list[str] = []
    wattages: list[str] = []
    for offering in offerings:
        bundle = offering.get("wattage_w")
        markers.append(marker_for_bundle(bundle))
        value = _bundle_value(bundle)
        if value is None:
            continue
        token = f"{value}W"
        if token not in wattages:
            wattages.append(token)

    if connector_bundle is not None:
        markers.append(marker_for_bundle(connector_bundle))

    marker = worst_marker(markers)

    wattage_clause = " · ".join(wattages)
    connector_value = _bundle_value(connector_bundle)
    if wattage_clause and connector_value:
        return f"{wattage_clause} ; {connector_value}", marker
    if wattage_clause:
        return wattage_clause, marker
    if connector_value:
        return str(connector_value), marker
    return "", marker


def render(product: dict[str, Any]) -> str:
    offerings = product.get("adapter_offerings") or []
    connector = product.get("adapter_connector")

    if not offerings and connector is None:
        return section_heading("Adapter", MARKER_EMPTY)

    out = [section_heading("Adapter")]

    if not offerings:
        out.append(f"  Offerings: {MARKER_EMPTY}")
    else:
        total = len(offerings)
        for idx, offering in enumerate(offerings, 1):
            if total > 1:
                out.append(f"  Offering {idx}")
                indent = "    "
            else:
                indent = "  "
            for label, key in _LEAVES:
                out.append(f"{indent}{format_leaf(label, offering.get(key))}")

    out.append(f"  {format_leaf('connector', connector)}")
    return "\n".join(out)
