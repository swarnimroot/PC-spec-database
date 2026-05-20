"""CPU section (Stage 10b rollup).

The product carries one or more CPU SKU offerings (``cpu_offerings``).
Each offering's ``model`` value keys into ``cpu_catalog``, where curated
columns ``architecture_code`` / ``architecture_name`` / ``generation``
hold the human-readable rollup labels. Browse / Compare / Find render
ONLY a deduped, comma-joined list of ``architecture_code`` values; the
per-SKU detail is preserved in the DB for the Edit screen but no longer
surfaces on the visual tables. The cell's dot color uses the worst
status across the underlying SKU offerings (see ``worst_marker``).

``field_paths`` still enumerates per-SKU bundle paths so Edit and
``find-empty`` keep working unchanged.
"""

from __future__ import annotations

from typing import Any

from .formatting import (
    MARKER_EMPTY,
    display_value,
    marker_for_bundle,
    section_heading,
    worst_marker,
)


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths on the product (excludes catalog leaves —
    those live in ``cpu_catalog`` and are surfaced via ``refresh`` /
    ``manual-edit``)."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("cpu_offerings") or []):
        out.append((f"cpu_offerings.{idx}.model", f"offering {idx} - model"))
    out.append(("cpu_tdp_max", "cpu_tdp_max"))
    return out


def rollup_value(
    product: dict[str, Any],
    cpu_catalog: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the CPU rollup cell.

    Joins ``cpu_offerings`` to ``cpu_catalog`` by model name, extracts
    each row's ``architecture_code`` bundle value, dedupes
    first-occurrence-ordered, comma-joins. The marker is the worst
    status across the *per-SKU offering* bundles (NOT the catalog row's
    bundle status) — what surfaces on the cell is how trustworthy the
    underlying offering data is, not how vouched the curation is.

    When no offerings exist → ``('', MARKER_EMPTY)``.
    When every offering's catalog row is missing / has a NULL
    architecture_code → ``('', <worst-offering-marker>)``. The empty
    string is intentional: render is not gated on catalog population
    (Stage 10b user call). Cells fill in as curation lands.
    """
    offerings = product.get("cpu_offerings") or []
    if not offerings:
        return "", MARKER_EMPTY

    arch_codes: list[str] = []
    offering_markers: list[str] = []
    for offering in offerings:
        model_bundle = offering.get("model")
        offering_markers.append(marker_for_bundle(model_bundle))
        model_value = (
            model_bundle.get("value") if isinstance(model_bundle, dict) else None
        )
        if not model_value:
            continue
        catalog_row = cpu_catalog.get(model_value)
        if catalog_row is None:
            continue
        arch_bundle = catalog_row.get("architecture_code")
        if not isinstance(arch_bundle, dict):
            continue
        arch_value = arch_bundle.get("value")
        if not arch_value:
            continue
        if arch_value not in arch_codes:
            arch_codes.append(arch_value)

    marker = worst_marker(offering_markers)
    return ", ".join(arch_codes), marker


def render(
    product: dict[str, Any],
    cpu_catalog: dict[str, dict[str, Any]],
) -> str:
    """Single-line text render for ``inspect-product`` CLI.

    Stage 10b: just the architecture-code rollup. No per-SKU lines, no
    catalog sub-fields, no ``cpu_tdp_max`` row. Mirrors what the visual
    tables show.
    """
    value, marker = rollup_value(product, cpu_catalog)
    if not value:
        return section_heading("CPU", marker)
    return f"CPU: {value} {marker}"
