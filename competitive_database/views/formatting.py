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
    if "entered_by" in bundle:
        return MARKER_MANUAL
    status = bundle.get("status")
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
