"""Graphics section (Stage 10b rollup).

The product carries one or more motherboard variants in ``boards``, each
holding a ``gpus`` list referencing ``gpu_catalog`` by model name.
Curated ``gpu_catalog`` columns ``series`` and ``board`` hold the
human-readable rollup labels (NVIDIA only — for AMD / Intel discrete
GPUs we surface the brand name instead).

Browse / Compare / Find render ONE deduped, comma-joined string per
product: each GPU contributes either its ``board`` value (when the
catalog ``brand`` is NVIDIA) or its brand name (when AMD or Intel). The
section header is ``Graphics`` (renamed from ``Boards``). TGP / TPP /
per-board detail are hidden for now.

``field_paths`` still enumerates per-board bundle paths (label
excluded — synthesized at render time elsewhere) so Edit and
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


_BOARD_SCALAR_LEAVES: list[tuple[str, str]] = [
    ("label", "label"),
    ("TGP max (W)", "tgp_max"),
    ("TPP max (W)", "tpp_max"),
    # arch_marker is a plain string leaf (e.g. "intel-rtx" / "amd-radeon"),
    # not a provenance bundle. User Decision 2 keeps it hand-editable via
    # manual-edit, so it lives in this list for field_paths().
    ("Architecture marker", "arch_marker"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths on the board (excludes per-GPU bundles in
    ``gpus`` arrays — those use a 4-level path not yet supported by
    ``manual-edit`` and are populated via ``refresh``).

    ``label`` is excluded: the view layer synthesizes per-product
    ordinals (``MB{n}``) at render time, so any manual edit would be
    silently masked. The bridge owns the underlying tier label.
    """
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("boards") or []):
        for _label, key in _BOARD_SCALAR_LEAVES:
            if key == "label":
                continue
            out.append((f"boards.{idx}.{key}", f"board {idx} - {key}"))
    return out


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def rollup_value(
    product: dict[str, Any],
    gpu_catalog: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Graphics rollup cell.

    For every GPU on every board: look up the catalog row, branch on
    ``brand``:

    * Brand ``"NVIDIA"`` → contribute the catalog ``board`` value
      (``MB1`` / ``MB2`` / ``MB3``).
    * Brand ``"AMD"`` or ``"Intel"`` → contribute the brand string.
    * Brand NULL / unknown / catalog row missing → contribute nothing
      (cell renders blank for that GPU; render is not gated on
      curation).

    Dedupe first-occurrence-ordered, comma-join. The marker is the worst
    status across the *per-GPU offering* bundles (NOT the catalog).
    """
    boards = product.get("boards") or []
    if not boards:
        return "", MARKER_EMPTY

    parts: list[str] = []
    gpu_markers: list[str] = []
    for board in boards:
        gpus = board.get("gpus") or []
        for gpu_bundle in gpus:
            gpu_markers.append(marker_for_bundle(gpu_bundle))
            model_value = _bundle_value(gpu_bundle)
            if not model_value:
                continue
            catalog_row = gpu_catalog.get(model_value)
            if catalog_row is None:
                continue
            # Integrated GPUs (curated via gpu_class=integrated) are
            # dropped from the displayed rollup but still contribute to
            # the worst-status marker via the per-GPU offering bundle
            # collected above. NULL gpu_class is treated as discrete so
            # existing uncurated rows keep rendering.
            gpu_class_value = _bundle_value(catalog_row.get("gpu_class"))
            if gpu_class_value == "integrated":
                continue
            brand_bundle = catalog_row.get("brand")
            brand_value = _bundle_value(brand_bundle)
            if brand_value == "NVIDIA":
                board_bundle = catalog_row.get("board")
                board_value = _bundle_value(board_bundle)
                if board_value and board_value not in parts:
                    parts.append(str(board_value))
            elif brand_value in ("AMD", "Intel"):
                if brand_value not in parts:
                    parts.append(str(brand_value))

    if not gpu_markers:
        return "", MARKER_EMPTY
    return ", ".join(parts), worst_marker(gpu_markers)


def render(
    product: dict[str, Any],
    gpu_catalog: dict[str, dict[str, Any]],
) -> str:
    """Single-line text render for ``inspect-product`` CLI.

    Stage 10b: just the Graphics rollup (board values for NVIDIA, brand
    name for AMD / Intel). Section header is ``Graphics`` (renamed from
    ``Boards``).
    """
    value, marker = rollup_value(product, gpu_catalog)
    if not value:
        return section_heading("Graphics", marker)
    return f"Graphics: {value} {marker}"
