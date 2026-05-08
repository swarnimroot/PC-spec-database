"""Boards section: GPU + power configuration(s).

Each board offering has a label, TGP/TPP caps, and a list of GPU options
(``gpus``). Each GPU model keys into ``gpu_catalog`` for catalog enrichment
mirroring the CPU view: catalog spec columns are plain text, brand is a
bundle, and the row-level ``catalog_status`` is shown alongside.
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


_BOARD_SCALAR_LEAVES: list[tuple[str, str]] = [
    ("label", "label"),
    ("TGP max (W)", "tgp_max"),
    ("TPP max (W)", "tpp_max"),
]

_GPU_CATALOG_PLAIN_LEAVES: list[tuple[str, str]] = [
    ("architecture", "architecture"),
    ("CUDA cores", "cuda_cores"),
    ("VRAM base (GB)", "vram_base"),
    ("base clock (GHz)", "base_clock"),
    ("boost clock (GHz)", "boost_clock"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths on the board (excludes per-GPU bundles in
    ``gpus`` arrays — those use a 4-level path not yet supported by
    ``manual-edit`` and are populated via ``refresh``)."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("boards") or []):
        for _label, key in _BOARD_SCALAR_LEAVES:
            out.append((f"boards.{idx}.{key}", f"board {idx} - {key}"))
    return out


def render(product: dict[str, Any], gpu_catalog: dict[str, dict[str, Any]]) -> str:
    offerings = product.get("boards") or []
    if not offerings:
        return section_heading("Boards", MARKER_EMPTY)

    out = [section_heading("Boards")]
    total = len(offerings)
    for idx, offering in enumerate(offerings, 1):
        if total > 1:
            out.append(f"  Board {idx}")
            indent = "    "
        else:
            indent = "  "

        for label, key in _BOARD_SCALAR_LEAVES:
            out.append(f"{indent}{format_leaf(label, offering.get(key))}")

        gpus = offering.get("gpus") or []
        if not gpus:
            out.append(f"{indent}GPUs: {MARKER_EMPTY}")
            continue
        out.append(f"{indent}GPUs:")
        gpu_indent = indent + "  "
        for gpu_bundle in gpus:
            gpu_name = display_value(gpu_bundle)
            marker = marker_for_bundle(gpu_bundle)
            if marker == MARKER_EMPTY:
                out.append(f"{gpu_indent}{MARKER_EMPTY}")
                continue
            out.append(f"{gpu_indent}{gpu_name} {marker}")

            value = gpu_bundle.get("value") if gpu_bundle else None
            catalog_row = gpu_catalog.get(value) if value else None
            if catalog_row is None:
                out.append(f"{gpu_indent}  (not in gpu_catalog)")
                continue

            cs = catalog_row.get("catalog_status") or "needs-review"
            out.append(f"{gpu_indent}  catalog status: {cs}")
            brand_bundle = catalog_row.get("brand")
            if brand_bundle is not None:
                out.append(
                    f"{gpu_indent}  brand: {display_value(brand_bundle)} "
                    f"{marker_for_bundle(brand_bundle)}"
                )
            for label, key in _GPU_CATALOG_PLAIN_LEAVES:
                val = catalog_row.get(key)
                if val is None or val == "":
                    continue
                out.append(f"{gpu_indent}  {label}: {val}")

    return "\n".join(out)
