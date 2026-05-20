"""Shared markers and leaf-rendering helpers for the view layer.

Every cell in the products / catalog tables either has no value (the
column is NULL) or carries a provenance bundle. The view layer maps each
bundle (or absence) to one of six visible markers so the user can tell
at a glance how trustworthy each line is.

Markers
-------
    [verified]   scraped, vendor page, status='verified'
    [?]          scraped, status='needs-review'
    [—]          scraped, status="vendor-doesn't-publish" (vendor was
                 checked but doesn't publish this field)
    [m]          manual entry (status vouched OR needs-review)
    [empty]      cell never written
    [partial]    aggregate marker for a category whose leaves carry a
                 mix of the above
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

MARKER_VERIFIED = "[verified]"
MARKER_NEEDS_REVIEW = "[?]"
MARKER_VENDOR_NO_PUB = "[—]"
MARKER_MANUAL = "[m]"
MARKER_EMPTY = "[empty]"
MARKER_PARTIAL = "[partial]"

VENDOR_NO_PUB_TEXT = "vendor doesn't publish"

# T9.2 — per-field display canonicalization. Keys are template-form paths
# (offering index collapsed to ``*``); values map raw stored strings to
# their canonical display form. Applied only when a caller passes
# ``field_path`` to ``display_value`` / ``canonicalize_display``; section
# views and inline renders pass nothing and see the raw stored value.
_CANONICAL_BY_FIELD: dict[str, dict[str, str]] = {
    "display_offerings.*.panel_type": {"IPS-level": "IPS"},
}


def _to_template(field_path: str) -> str:
    """Collapse the offering index in a 3-part path to ``*``.

    Mirrors ``ui.find._template_of`` so the canonical lookup table can be
    keyed once per (section, leaf) regardless of which offering slot the
    cell sits in.
    """
    parts = field_path.split(".")
    if len(parts) == 3 and parts[1].isdigit():
        return f"{parts[0]}.*.{parts[2]}"
    return field_path


def canonicalize_display(field_path: str, rendered: str) -> str:
    """Map a rendered display string through per-field canonical rules.

    Returns ``rendered`` unchanged when no rule applies. Used by
    ``ui/find.py`` on both the dropdown side (`_distinct_values_for_template`)
    and the cell-match side (`_cell_matches`) so canonical collapse stays
    symmetric — both sides project to the same string before comparison.
    """
    rules = _CANONICAL_BY_FIELD.get(_to_template(field_path))
    if rules is None:
        return rendered
    return rules.get(rendered, rendered)


def marker_for_bundle(bundle: dict | None) -> str:
    """Map one provenance bundle (or absence) to its visible marker."""
    if bundle is None:
        return MARKER_EMPTY
    status = bundle.get("status")
    if status == "manual":
        return MARKER_MANUAL
    if "entered_by" in bundle:
        return MARKER_MANUAL
    if status == "verified":
        return MARKER_VERIFIED
    if status == "vendor-doesn't-publish":
        return MARKER_VENDOR_NO_PUB
    if status == "needs-review":
        return MARKER_NEEDS_REVIEW
    return MARKER_NEEDS_REVIEW


def aggregate_markers(markers: Iterable[str]) -> str:
    """Collapse per-leaf markers into a single category-level marker.

    All-same → that marker. Mixed → ``[partial]``. Empty input → ``[empty]``.
    """
    distinct = set(markers)
    if not distinct:
        return MARKER_EMPTY
    if len(distinct) == 1:
        return next(iter(distinct))
    return MARKER_PARTIAL


# Worst-status precedence for rollup cells (Stage 10b CPU / Graphics).
# Order: lowest-confidence first. ``MARKER_EMPTY`` ranks above
# needs-review so a partially-populated rollup still surfaces the worst
# real status on the offerings that exist.
_WORST_MARKER_ORDER: tuple[str, ...] = (
    MARKER_NEEDS_REVIEW,
    MARKER_VENDOR_NO_PUB,
    MARKER_MANUAL,
    MARKER_VERIFIED,
)


def worst_marker(markers: Iterable[str]) -> str:
    """Return the worst (lowest-confidence) marker among ``markers``.

    Used by rollup cells (CPU architecture codes, Graphics boards) so a
    single dot color reflects the riskiest underlying SKU offering.
    Unknown markers are treated as needs-review. Empty input → ``[empty]``.
    """
    materialized = list(markers)
    if not materialized:
        return MARKER_EMPTY
    for token in _WORST_MARKER_ORDER:
        if token in materialized:
            return token
    return MARKER_NEEDS_REVIEW


def display_value(bundle: dict | None, *, field_path: str | None = None) -> str:
    """Stringify a bundle's value for display.

    None / missing → ''. ``vendor-doesn't-publish`` → the placeholder text.
    Booleans → 'yes' / 'no'. Otherwise ``str(value)``.

    When ``field_path`` is set (T9.2), the rendered string is passed
    through ``canonicalize_display`` so per-field rules (e.g. panel_type
    "IPS-level" → "IPS") collapse duplicate-meaning variants. Callers
    that want the raw stored string (section views, inline renders) omit
    ``field_path``.
    """
    if bundle is None:
        return ""
    if bundle.get("status") == "vendor-doesn't-publish":
        return VENDOR_NO_PUB_TEXT
    value = bundle.get("value")
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    rendered = str(value)
    if field_path is not None:
        return canonicalize_display(field_path, rendered)
    return rendered


FieldType = Literal["str", "int", "float", "bool"]


# Path-leaf → expected Python type, used by the Edit UI to coerce text
# input back to the right shape before writing. Anything not listed here
# defaults to ``"str"``; numeric suffix rules (see ``field_type``) catch
# the common quantitative leaves so the override map stays small.
_FIELD_TYPE_OVERRIDES: dict[str, FieldType] = {
    "memory_slots": "int",
    "fan_count": "int",
    "speaker_count": "int",
    "cell_count": "int",
    "cpu_tdp_max": "int",
    "tgp_max": "int",
    "tpp_max": "int",
    "wattage_w": "int",
    "wattage_wh": "float",
    "size_inches": "float",
    "base_clock": "float",
    "boost_clock": "float",
    "weight_kg_min": "float",
    "weight_kg_max": "float",
    "width_mm": "float",
    "depth_mm": "float",
    "height_mm_min": "float",
    "height_mm_max": "float",
    "memory_overclocking": "bool",
    "anti_glare": "bool",
    "vrr": "bool",
    "has_subwoofer": "bool",
    "has_numpad": "bool",
    "ir_supported": "bool",
    "privacy_shutter": "bool",
}

# Numeric-suffix rules: a leaf ending in one of these suffixes is the
# named numeric type. Checked after the explicit override map; suffix
# ordering doesn't matter because ``endswith`` is exclusive.
_INT_SUFFIXES: tuple[str, ...] = (
    "_mhz", "_hz", "_w", "_gen", "_count", "_pct",
    "_cores", "_gb", "_mb", "_mts",
)
_FLOAT_SUFFIXES: tuple[str, ...] = (
    "_wh", "_mm", "_kg", "_ms",
)


def field_type(path: str) -> FieldType:
    """Infer the expected Python type for a dotted field path's leaf."""
    leaf = path.split(".")[-1]
    if leaf in _FIELD_TYPE_OVERRIDES:
        return _FIELD_TYPE_OVERRIDES[leaf]
    for suffix in _FLOAT_SUFFIXES:
        if leaf.endswith(suffix):
            return "float"
    for suffix in _INT_SUFFIXES:
        if leaf.endswith(suffix):
            return "int"
    return "str"


def coerce_to_field_type(path: str, raw: str) -> object:
    """Coerce a string value to the expected type for ``path``; raises ValueError."""
    expected = field_type(path)
    text = raw.strip()
    if expected == "str":
        return raw
    if expected == "int":
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError(
                f"expected an integer for '{path.split('.')[-1]}'; got {raw!r}"
            ) from exc
    if expected == "float":
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(
                f"expected a number for '{path.split('.')[-1]}'; got {raw!r}"
            ) from exc
    if expected == "bool":
        lowered = text.casefold()
        if lowered in {"true", "yes", "y", "1"}:
            return True
        if lowered in {"false", "no", "n", "0"}:
            return False
        raise ValueError(
            f"expected yes/no for '{path.split('.')[-1]}'; got {raw!r}"
        )
    return raw


def format_leaf(label: str, bundle: dict | None) -> str:
    """One-line ``label: value [marker]`` (or ``label: [empty]``)."""
    marker = marker_for_bundle(bundle)
    if marker == MARKER_EMPTY:
        return f"{label}: {MARKER_EMPTY}"
    return f"{label}: {display_value(bundle)} {marker}"


def section_heading(name: str, marker: str | None = None) -> str:
    """Top-of-section heading. If ``marker`` is given, append it."""
    if marker is None:
        return f"{name}:"
    return f"{name}: {marker}"


def render_scalar_section(
    section_name: str,
    product: dict,
    fields: list[tuple[str, str]],
) -> str:
    """Render a category that's purely scalar bundles (no offerings).

    Used by ``storage``, ``network``, ``io``, ``audio``, ``thermals``,
    ``dimensions``, ``weight``, and ``design`` — every field is one
    bundle on the products row. ``fields`` is a list of
    ``(label, column_name)`` tuples.
    """
    bundles = [product.get(key) for _, key in fields]
    if all(b is None for b in bundles):
        return section_heading(section_name, MARKER_EMPTY)
    out = [section_heading(section_name)]
    for label, key in fields:
        out.append(f"  {format_leaf(label, product.get(key))}")
    return "\n".join(out)
