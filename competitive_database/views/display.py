"""Display section: zero or more display offerings, 13 leaves each.

Each offering is rendered as a numbered sub-block; every leaf shows its
own marker independently per the per-leaf provenance rule.

Stage 10b rollup: visual tables collapse the per-offering bundle to one
line of ``<size>" <res_label> <hz>Hz <panel>``. When sizes match across
all offerings the size is hoisted to the front; otherwise each
``(res, hz, panel)`` triple carries its own size. Nits / HDR / color
gamuts / response / VRR / anti-glare / tier are dropped from the rollup
but remain in the DB and on the Edit screen.
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

# Leaves whose values + markers feed the Stage 10b rollup. Only these
# four bundles count toward the rollup cell's worst-marker; the other
# nine still surface on the Edit screen unchanged.
_ROLLUP_LEAVES: tuple[str, ...] = (
    "size_inches",
    "resolution_label",
    "refresh_rate_hz",
    "panel_type",
)


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    out: list[tuple[str, str]] = []
    for idx, _ in enumerate(product.get("display_offerings") or []):
        for _label, key in _DISPLAY_LEAVES:
            out.append((f"display_offerings.{idx}.{key}", f"offering {idx} - {key}"))
    return out


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def _fmt_size(size_val: Any) -> str | None:
    if size_val is None:
        return None
    try:
        f = float(size_val)
    except (TypeError, ValueError):
        return str(size_val)
    # Trim trailing .0 so 16.0 → "16" but 16.1 stays "16.1".
    if f == int(f):
        return f'{int(f)}"'
    return f'{f}"'


def _fmt_hz(hz_val: Any) -> str | None:
    if hz_val is None:
        return None
    try:
        return f"{int(hz_val)}Hz"
    except (TypeError, ValueError):
        return f"{hz_val}Hz"


def rollup_value(product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Display rollup cell.

    Single offering → ``16" 2.5K 240Hz IPS``. Multi-offering: when every
    offering shares the same size, hoist the size out front and join the
    remaining ``(res, hz, panel)`` triples with ``" · "``. When
    sizes diverge across offerings, the size stays attached to each
    triple. Triples are deduped first-occurrence-ordered.

    Marker is the worst across every offering's four rollup-source
    bundle markers (size, resolution_label, refresh_rate_hz, panel_type).
    """
    offerings = product.get("display_offerings") or []
    if not offerings:
        return "", MARKER_EMPTY

    sizes: list[str | None] = []
    triples: list[tuple[str | None, str | None, str | None, str | None]] = []
    markers: list[str] = []
    for offering in offerings:
        size_b = offering.get("size_inches")
        res_b = offering.get("resolution_label")
        hz_b = offering.get("refresh_rate_hz")
        panel_b = offering.get("panel_type")
        markers.extend(
            marker_for_bundle(b) for b in (size_b, res_b, hz_b, panel_b)
        )
        size_str = _fmt_size(_bundle_value(size_b))
        res_str = _bundle_value(res_b)
        hz_str = _fmt_hz(_bundle_value(hz_b))
        panel_str = _bundle_value(panel_b)
        sizes.append(size_str)
        triples.append((size_str, res_str, hz_str, panel_str))

    marker = worst_marker(markers)

    # Build the per-offering display string. Decide once whether sizes
    # can be hoisted (only when every offering has the same non-None size).
    distinct_sizes = {s for s in sizes if s is not None}
    hoist_size = (
        len(distinct_sizes) == 1
        and all(s is not None for s in sizes)
    )
    common_size = next(iter(distinct_sizes)) if hoist_size else None

    parts: list[str] = []
    for size_str, res_str, hz_str, panel_str in triples:
        tokens: list[str] = []
        if not hoist_size and size_str:
            tokens.append(size_str)
        if res_str:
            tokens.append(str(res_str))
        if hz_str:
            tokens.append(hz_str)
        if panel_str:
            tokens.append(str(panel_str))
        if tokens:
            part = " ".join(tokens)
            if part not in parts:
                parts.append(part)

    if not parts:
        return "", marker

    if hoist_size and common_size:
        return f"{common_size} " + " · ".join(parts), marker
    return " · ".join(parts), marker


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
