"""I/O section: port counts and versions (USB-C TB / non-TB, USB-A,
HDMI, SD card, audio jack).

Stage 10b rollup: visual tables render four sub-rows under one I/O
section header (multi-row shape — unique among the rollup sections):

    USB         : <N× TB · M× USB-C · K× USB-A>
    HDMI        : <count>× <version>
    SD card     : <literal value>
    Audio jack  : <literal value>

Each sub-row's marker is the worst across just that sub-row's source
bundles. Zero-count tokens are dropped from the USB sub-row.
"""

from __future__ import annotations

from typing import Any

from .formatting import (
    MARKER_EMPTY,
    marker_for_bundle,
    render_scalar_section,
    worst_marker,
)


_FIELDS: list[tuple[str, str]] = [
    ("USB-C Thunderbolt count", "usbc_thunderbolt_count"),
    ("USB-C Thunderbolt version", "usbc_thunderbolt_version"),
    ("USB-C non-Thunderbolt count", "usbc_non_thunderbolt_count"),
    ("USB-C non-Thunderbolt version", "usbc_non_thunderbolt_version"),
    ("USB-A count", "usba_count"),
    ("USB-A version", "usba_version"),
    ("HDMI count", "hdmi_count"),
    ("HDMI version", "hdmi_version"),
    ("SD card", "sd_card"),
    ("SD card speed", "sd_card_speed"),
    ("audio jack", "audio_jack"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def _usb_row(product: dict[str, Any]) -> tuple[str, str, str]:
    """Build the USB sub-row from the six TB/non-TB/USB-A bundles."""
    tb_count_b = product.get("usbc_thunderbolt_count")
    tb_ver_b = product.get("usbc_thunderbolt_version")
    nontb_count_b = product.get("usbc_non_thunderbolt_count")
    nontb_ver_b = product.get("usbc_non_thunderbolt_version")
    usba_count_b = product.get("usba_count")
    usba_ver_b = product.get("usba_version")

    source_bundles = [
        tb_count_b,
        tb_ver_b,
        nontb_count_b,
        nontb_ver_b,
        usba_count_b,
        usba_ver_b,
    ]
    if all(b is None for b in source_bundles):
        return "USB", "—", MARKER_EMPTY

    marker = worst_marker(marker_for_bundle(b) for b in source_bundles)

    tokens: list[str] = []

    def _maybe(count_bundle: Any, label: str) -> None:
        count = _bundle_value(count_bundle)
        if count is None:
            return
        try:
            if int(count) == 0:
                return
        except (TypeError, ValueError):
            pass
        tokens.append(f"{count}× {label}")

    _maybe(tb_count_b, "TB")
    _maybe(nontb_count_b, "USB-C")
    _maybe(usba_count_b, "USB-A")

    if not tokens:
        return "USB", "—", marker
    return "USB", " · ".join(tokens), marker


def _hdmi_row(product: dict[str, Any]) -> tuple[str, str, str]:
    count_b = product.get("hdmi_count")
    ver_b = product.get("hdmi_version")
    if count_b is None and ver_b is None:
        return "HDMI", "—", MARKER_EMPTY

    marker = worst_marker(marker_for_bundle(b) for b in (count_b, ver_b))
    count = _bundle_value(count_b)
    version = _bundle_value(ver_b)

    if count is None and version is None:
        return "HDMI", "—", marker
    if count is None:
        return "HDMI", str(version), marker
    if version is None:
        return "HDMI", f"{count}×", marker
    return "HDMI", f"{count}× {version}", marker


def _literal_row(
    product: dict[str, Any], key: str, label: str
) -> tuple[str, str, str]:
    bundle = product.get(key)
    if bundle is None:
        return label, "—", MARKER_EMPTY
    marker = marker_for_bundle(bundle)
    value = _bundle_value(bundle)
    if value is None:
        return label, "—", marker
    return label, str(value), marker


def rollup_rows(
    product: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Return the four I/O sub-rows: ``[(label, value_str, marker), ...]``.

    Order: USB, HDMI, SD card, Audio jack. Each sub-row's marker is
    the worst across only that sub-row's source bundles. Sub-rows with
    no data render ``—`` and ``MARKER_EMPTY``.
    """
    return [
        _usb_row(product),
        _hdmi_row(product),
        _literal_row(product, "sd_card", "SD card"),
        _literal_row(product, "audio_jack", "Audio jack"),
    ]


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("I/O", product, _FIELDS)
