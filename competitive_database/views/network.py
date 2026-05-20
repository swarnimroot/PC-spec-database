"""Network section: Wi-Fi, Ethernet, Bluetooth scalars.

Stage 10b rollup: visual tables surface only the ``wifi_standard``
value. Ethernet + Bluetooth drop from the rollup (still on Edit).
"""

from __future__ import annotations

from typing import Any

from .formatting import (
    MARKER_EMPTY,
    marker_for_bundle,
    render_scalar_section,
)


_FIELDS: list[tuple[str, str]] = [
    ("Wi-Fi standard", "wifi_standard"),
    ("Ethernet", "ethernet"),
    ("Bluetooth version", "bluetooth_version"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def rollup_value(product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Network rollup cell.

    Just the ``wifi_standard`` value. Marker reflects only that bundle —
    ethernet + bluetooth_version are out of scope for the rollup, so
    their status doesn't drag the marker.
    """
    bundle = product.get("wifi_standard")
    if bundle is None:
        return "", MARKER_EMPTY
    marker = marker_for_bundle(bundle)
    value = _bundle_value(bundle)
    if value is None:
        return "", marker
    return str(value), marker


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("Network", product, _FIELDS)
