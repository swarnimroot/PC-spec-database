"""CPU section: one or more CPU offerings + product-level TDP cap.

Each offering is a dict containing a ``model`` leaf bundle. The model
name keys into ``cpu_catalog`` for chip-level enrichment (cores, NPU TOPS,
clocks, etc.). Catalog spec columns are plain text, so the chip-level
lines render without per-leaf markers; the row-level ``catalog_status``
is shown alongside the model.
"""

from __future__ import annotations

from typing import Any

from .formatting import (
    MARKER_EMPTY,
    display_value,
    format_leaf,
    marker_for_bundle,
    section_heading,
)


_CATALOG_PLAIN_LEAVES: list[tuple[str, str]] = [
    ("architecture", "architecture"),
    ("cores", "cores"),
    ("NPU TOPS", "npu_tops"),
    ("base clock (GHz)", "base_clock"),
    ("boost clock (GHz)", "boost_clock"),
    ("process node", "process_node"),
    ("nominal TDP (W)", "nominal_tdp"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths on the product (excludes catalog leaves —
    those live in ``cpu_catalog`` and are surfaced via ``refresh``)."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("cpu_offerings") or []):
        out.append((f"cpu_offerings.{idx}.model", f"offering {idx} - model"))
    out.append(("cpu_tdp_max", "cpu_tdp_max"))
    return out


def render(product: dict[str, Any], cpu_catalog: dict[str, dict[str, Any]]) -> str:
    offerings = product.get("cpu_offerings") or []
    tdp_max = product.get("cpu_tdp_max")

    if not offerings and tdp_max is None:
        return section_heading("CPU", MARKER_EMPTY)

    out = [section_heading("CPU")]

    if not offerings:
        out.append(f"  Offerings: {MARKER_EMPTY}")
    else:
        total = len(offerings)
        for idx, offering in enumerate(offerings, 1):
            model_bundle = offering.get("model")
            cpu_name = display_value(model_bundle)
            marker = marker_for_bundle(model_bundle)
            prefix = f"Offering {idx}: " if total > 1 else ""
            if marker == MARKER_EMPTY:
                out.append(f"  {prefix}{MARKER_EMPTY}")
                continue
            out.append(f"  {prefix}{cpu_name} {marker}")

            value = model_bundle.get("value") if model_bundle else None
            catalog_row = cpu_catalog.get(value) if value else None
            if catalog_row is None:
                out.append("    (not in cpu_catalog)")
                continue

            cs = catalog_row.get("catalog_status") or "needs-review"
            out.append(f"    catalog status: {cs}")
            brand_bundle = catalog_row.get("brand")
            if brand_bundle is not None:
                out.append(
                    f"    brand: {display_value(brand_bundle)} "
                    f"{marker_for_bundle(brand_bundle)}"
                )
            for label, key in _CATALOG_PLAIN_LEAVES:
                val = catalog_row.get(key)
                if val is None or val == "":
                    continue
                out.append(f"    {label}: {val}")

    out.append(f"  {format_leaf('TDP max (W)', tdp_max)}")
    return "\n".join(out)
