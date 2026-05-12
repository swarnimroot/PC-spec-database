"""Shared marker + path-resolve helpers for the UI layer.

Three UI screens (``browse``, ``compare``, ``find`` as of T8.4) need the
same six-marker color palette and the same dotted-path → cell resolver.
Extracted out of ``ui/browse.py`` + ``ui/compare.py`` at the rule-of-three
threshold per ARCHITECTURE §UI layer.

Public surface:

- ``MARKER_COLORS`` — color hex per ``views.formatting`` marker constant.
- ``colorize_marker(marker)`` — wrap a single marker token in a colored span.
- ``colorize_text(escaped)`` — substitute every marker token in pre-escaped
  text with colored spans (used by ``browse.py`` for the whole orchestrator
  dump).
- ``resolve_path(product, path)`` — dotted-path → ``(bundle, plain)`` lookup
  matching the union of leaf shapes emitted by
  ``views.orchestrator.all_field_paths``.
- ``render_cell(bundle, plain)`` — render one cell as ``value [marker]`` HTML
  with the marker colored.
"""

from __future__ import annotations

import html
import re
from typing import Any, Optional

from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_MANUAL,
    MARKER_NEEDS_REVIEW,
    MARKER_PARTIAL,
    MARKER_VENDOR_NO_PUB,
    MARKER_VERIFIED,
    display_value,
    marker_for_bundle,
)

MARKER_COLORS: dict[str, str] = {
    MARKER_VERIFIED: "#3fb950",       # green
    MARKER_NEEDS_REVIEW: "#d29922",   # amber
    MARKER_VENDOR_NO_PUB: "#8b949e",  # gray
    MARKER_MANUAL: "#58a6ff",         # blue
    MARKER_EMPTY: "#6e7681",          # dim
    MARKER_PARTIAL: "#d29922",        # amber
}

_MARKER_RE = re.compile("(" + "|".join(re.escape(m) for m in MARKER_COLORS) + ")")


def colorize_marker(marker: str) -> str:
    """Wrap a single marker token in a colored span."""
    color = MARKER_COLORS[marker]
    return f'<span style="color:{color}">{html.escape(marker)}</span>'


def colorize_text(escaped: str) -> str:
    """Substitute every marker token in pre-escaped text with colored spans.

    Caller is responsible for HTML-escaping the input first.
    """
    return _MARKER_RE.sub(lambda m: colorize_marker(m.group(1)), escaped)


def resolve_path(
    product: dict[str, Any],
    path: str,
) -> tuple[Optional[dict], Optional[str]]:
    """Return ``(bundle, plain)`` for one path on a loaded product.

    Exactly one of the two is non-None when the cell is present, else
    ``(None, None)``. Plain-string leaves (e.g. ``boards.N.arch_marker``)
    take the second slot; everything else is bundle-shaped.
    """
    parts = path.split(".")
    if len(parts) == 1:
        val = product.get(parts[0])
        if isinstance(val, dict):
            return val, None
        return None, None
    if len(parts) == 3:
        col, idx_s, leaf = parts
        offerings = product.get(col)
        if not isinstance(offerings, list):
            return None, None
        try:
            idx = int(idx_s)
        except ValueError:
            return None, None
        if idx >= len(offerings):
            return None, None
        leaf_val = offerings[idx].get(leaf)
        if isinstance(leaf_val, dict):
            return leaf_val, None
        if isinstance(leaf_val, str) and leaf_val:
            return None, leaf_val
        return None, None
    return None, None


def render_cell(bundle: Optional[dict], plain: Optional[str]) -> str:
    """Render one cell as ``value [marker]`` HTML; marker is colored.

    Plain-string leaves render as the escaped string with no marker
    (they carry no provenance bundle by design).
    """
    if plain is not None:
        return html.escape(plain)
    marker = marker_for_bundle(bundle)
    marker_html = colorize_marker(marker)
    value = display_value(bundle)
    if not value:
        return marker_html
    return f"{html.escape(value)} {marker_html}"
