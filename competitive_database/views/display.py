"""Display section: zero or more display offerings, 13 leaves each.

Each offering is rendered as a numbered sub-block; every leaf shows its
own marker independently per the per-leaf provenance rule.
"""

from __future__ import annotations

from typing import Any

from .formatting import MARKER_EMPTY, format_leaf, section_heading


_DISPLAY_LEAVES: list[tuple[str, str]] = [
    ("size (in)", "size_inches"),
    ("panel", "panel_type"),
    ("resolution label", "resolution_label"),
    ("resolution px", "resolution_pixels"),
    ("refresh (Hz)", "refresh_rate_hz"),
    ("peak nits", "nits_peak"),
    ("HDR cert", "hdr_certification"),
    ("DCI-P3 (%)", "dci_p3_pct"),
    ("sRGB (%)", "srgb_pct"),
    ("response (ms)", "response_time_ms"),
    ("VRR", "vrr"),
    ("anti-glare", "anti_glare"),
    ("tier", "tier"),
]


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("display_offerings") or []):
        for _label, key in _DISPLAY_LEAVES:
            out.append((f"display_offerings.{idx}.{key}", f"offering {idx} - {key}"))
    return out


def render(product: dict[str, Any]) -> str:
    offerings = product.get("display_offerings") or []
    if not offerings:
        return section_heading("Display", MARKER_EMPTY)

    out = [section_heading("Display")]
    total = len(offerings)
    for idx, offering in enumerate(offerings, 1):
        if total > 1:
            out.append(f"  Offering {idx}")
            leaf_indent = "    "
        else:
            leaf_indent = "  "
        for label, key in _DISPLAY_LEAVES:
            bundle = offering.get(key)
            out.append(f"{leaf_indent}{format_leaf(label, bundle)}")
    return "\n".join(out)
