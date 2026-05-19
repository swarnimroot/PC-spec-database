"""Shared marker palette + path-resolve helpers for the UI layer.

Color values live in ``theme.PALETTE['markers']``; ``MARKER_COLORS`` is
a derived re-export keyed by the canonical ``views.formatting`` marker
constants so existing callers keep working unchanged.

Public surface:

- ``MARKER_COLORS`` — color hex per ``views.formatting`` marker constant.
- ``resolve_path(product, path)`` — dotted-path → ``(bundle, plain)`` lookup
  matching the union of leaf shapes emitted by
  ``views.orchestrator.all_field_paths``.
"""

from __future__ import annotations

from typing import Any, Optional

from competitive_database.ui.theme import PALETTE
from competitive_database.views.formatting import (
    MARKER_EMPTY,
    MARKER_MANUAL,
    MARKER_NEEDS_REVIEW,
    MARKER_PARTIAL,
    MARKER_VENDOR_NO_PUB,
    MARKER_VERIFIED,
)

_TOKEN_TO_CONCEPT: dict[str, str] = {
    MARKER_VERIFIED: "verified",
    MARKER_NEEDS_REVIEW: "needs_review",
    MARKER_VENDOR_NO_PUB: "vendor_no_publish",
    MARKER_MANUAL: "manual",
    MARKER_EMPTY: "empty",
    MARKER_PARTIAL: "needs_review",
}

MARKER_COLORS: dict[str, str] = {
    token: PALETTE["markers"][concept]  # type: ignore[index]
    for token, concept in _TOKEN_TO_CONCEPT.items()
}


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
