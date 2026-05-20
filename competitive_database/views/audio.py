"""Audio section: speakers, tuning, subwoofer.

Stage 10b rollup: visual tables collapse to ``<n>-speaker
<tuning_brand>``. Either side is optional. ``has_subwoofer`` is dropped
from the rollup (still on the Edit screen).
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
    ("speaker count", "speaker_count"),
    ("tuning brand", "tuning_brand"),
    ("subwoofer", "has_subwoofer"),
]

# Scalars feeding the rollup; has_subwoofer drops.
_ROLLUP_FIELDS: tuple[str, ...] = ("speaker_count", "tuning_brand")


def field_paths(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Fillable bundle paths in this section, in render order."""
    return [(key, key) for _label, key in _FIELDS]


def _bundle_value(bundle: Any) -> Any:
    return bundle.get("value") if isinstance(bundle, dict) else None


def rollup_value(product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(display_string, marker_token)`` for the Audio rollup cell.

    ``<n>-speaker <tuning_brand>``. Either side may be NULL — the
    sentence composes from whatever is present. All-NULL → empty.
    """
    bundles = {key: product.get(key) for key in _ROLLUP_FIELDS}
    if all(b is None for b in bundles.values()):
        return "", MARKER_EMPTY

    marker = worst_marker(marker_for_bundle(b) for b in bundles.values())

    count = _bundle_value(bundles["speaker_count"])
    brand = _bundle_value(bundles["tuning_brand"])
    tokens: list[str] = []
    if count is not None:
        tokens.append(f"{count}-speaker")
    if brand:
        tokens.append(str(brand))
    return " ".join(tokens), marker


def render(product: dict[str, Any]) -> str:
    return render_scalar_section("Audio", product, _FIELDS)
