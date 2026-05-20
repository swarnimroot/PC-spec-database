"""Compose per-category renders into the full inspect-product dump.

Section order is fixed: identity, then the 16 categories. The visible
order (Stage 10b batch 2) groups compute (Processor, Graphics) → screen
(Display) → memory/storage → input (Keyboard, Camera) → audio →
connectivity (Network, I/O) → power (Battery, Adapter) → physical
(Thermals, Dimensions, Weight, Design).
"""

from __future__ import annotations

from typing import Any

from . import (
    adapter,
    audio,
    battery,
    boards,
    camera,
    cpu,
    design,
    dimensions,
    display,
    io,
    keyboard,
    memory,
    network,
    storage,
    thermals,
    weight,
)
from .formatting import format_leaf

_RULE = "=" * 64

_IDENTITY_LEAVES: list[tuple[str, str]] = [
    ("vendor", "vendor_full_name"),
    ("brand", "brand"),
    ("sub-brand", "sub_brand"),
    ("series", "series"),
    ("status", "status"),
    ("segment", "segment"),
]


def _identity_field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    return [(key, key) for _label, key in _IDENTITY_LEAVES]


# (section_name, callable returning [(field_path, display_label), ...])
# Order mirrors ``render_product`` so find-empty groups match inspect-product.
# Stage 10b batch 2: CPU heading renamed to "Processor" and section order
# regrouped (see module docstring).
_SECTION_REGISTRY: list[tuple[str, Any]] = [
    ("Identity", _identity_field_paths),
    ("Processor", cpu.field_paths),
    ("Graphics", boards.field_paths),
    ("Display", display.field_paths),
    ("Memory", memory.field_paths),
    ("Storage", storage.field_paths),
    ("Keyboard", keyboard.field_paths),
    ("Camera", camera.field_paths),
    ("Audio", audio.field_paths),
    ("Network", network.field_paths),
    ("I/O", io.field_paths),
    ("Battery", battery.field_paths),
    ("Adapter", adapter.field_paths),
    ("Thermals", thermals.field_paths),
    ("Dimensions", dimensions.field_paths),
    ("Weight", weight.field_paths),
    ("Design", design.field_paths),
]


# Stage 10b batch 2: sections that surface as a single rollup row (or
# row-set, for I/O) on the visual tables. Keyboard and Thermals are
# intentionally hidden from the rollup but still surface their per-leaf
# bundles on the Edit screen (``_SECTION_REGISTRY`` is unchanged for
# them, so Edit / find-empty keep working).
_VISUAL_SECTIONS: tuple[str, ...] = (
    "Processor",
    "Graphics",
    "Display",
    "Memory",
    "Storage",
    "Camera",
    "Audio",
    "Network",
    "I/O",
    "Battery",
    "Adapter",
    "Dimensions",
    "Weight",
    "Design",
)


def all_field_paths(product: dict[str, Any]) -> list[tuple[str, str, str]]:
    """All fillable cells on a loaded product, in render order.

    Returns ``[(section_name, field_path, display_label), ...]``. Used by
    ``find-empty`` to enumerate empty / vendor-doesn't-publish cells.
    """
    out: list[tuple[str, str, str]] = []
    for section, fn in _SECTION_REGISTRY:
        for path, label in fn(product):
            out.append((section, path, label))
    return out


def render_product(
    product: dict[str, Any],
    cpu_catalog: dict[str, dict[str, Any]],
    gpu_catalog: dict[str, dict[str, Any]],
) -> str:
    parts = [
        _render_identity(product),
        cpu.render(product, cpu_catalog),
        boards.render(product, gpu_catalog),
        display.render(product),
        memory.render(product),
        storage.render(product),
        keyboard.render(product),
        camera.render(product),
        audio.render(product),
        network.render(product),
        io.render(product),
        battery.render(product),
        adapter.render(product),
        thermals.render(product),
        dimensions.render(product),
        weight.render(product),
        design.render(product),
    ]
    return "\n\n".join(parts)


def _render_identity(product: dict[str, Any]) -> str:
    model_code = product.get("model_code", "?")
    year = product.get("year", "?")
    out = [_RULE, f"  {model_code}  ({year})", _RULE]
    for label, key in _IDENTITY_LEAVES:
        out.append(f"  {format_leaf(label, product.get(key))}")
    return "\n".join(out)
