"""I/O section: port counts and versions (USB-C TB / non-TB, USB-A,
HDMI, SD card, audio jack)."""

from __future__ import annotations

from typing import Any

from .formatting import render_scalar_section


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


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("I/O", product, _FIELDS)
