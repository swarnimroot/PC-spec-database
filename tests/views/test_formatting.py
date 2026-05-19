"""T9.2 — unit tests for the per-field display canonicalizer.

Covers ``display_value`` (back-compat — no ``field_path`` means raw
stored value) and ``canonicalize_display`` (the public hook used by
``ui/find.py`` for plain-string leaves and by ``_cell_matches`` to keep
dropdown picks symmetric with stored values).

The single canonical rule today is ``display_offerings.*.panel_type``
"IPS-level" → "IPS"; tests also exercise the no-rule passthrough,
concrete-path → template collapse, and the value types that should
NEVER pass through canonicalization (None, bool, vendor-doesn't-publish).
"""

from __future__ import annotations

from competitive_database.views.formatting import (
    MARKER_MANUAL,
    MARKER_NEEDS_REVIEW,
    MARKER_VERIFIED,
    VENDOR_NO_PUB_TEXT,
    canonicalize_display,
    display_value,
    marker_for_bundle,
)


def _bundle(value, status="verified"):
    """Minimal bundle for display tests; provenance bookkeeping omitted."""
    return {"value": value, "status": status}


# ---- canonicalize_display direct -----------------------------------------


def test_canonicalize_display_applies_rule_on_template_path():
    assert (
        canonicalize_display("display_offerings.*.panel_type", "IPS-level")
        == "IPS"
    )


def test_canonicalize_display_applies_rule_on_concrete_path():
    # 3-part path with numeric offering index collapses to template form
    # for lookup, so the rule fires regardless of which slot the cell sat in.
    assert (
        canonicalize_display("display_offerings.0.panel_type", "IPS-level")
        == "IPS"
    )
    assert (
        canonicalize_display("display_offerings.7.panel_type", "IPS-level")
        == "IPS"
    )


def test_canonicalize_display_passthrough_when_no_rule_for_field():
    # Field has no entry in _CANONICAL_BY_FIELD → input returns unchanged.
    assert (
        canonicalize_display("display_offerings.*.refresh_rate_hz", "240")
        == "240"
    )


def test_canonicalize_display_passthrough_when_value_not_in_rule():
    # Field is canonicalized but this particular value has no mapping.
    assert (
        canonicalize_display("display_offerings.*.panel_type", "TN")
        == "TN"
    )


# ---- display_value back-compat -------------------------------------------


def test_display_value_no_field_path_returns_raw_string():
    # Pre-T9.2 callers (section views, _markers.render_cell) pass nothing
    # and must still see the raw stored value.
    assert display_value(_bundle("IPS-level")) == "IPS-level"


def test_display_value_with_field_path_applies_canonical_rule():
    assert (
        display_value(_bundle("IPS-level"), field_path="display_offerings.*.panel_type")
        == "IPS"
    )


def test_display_value_with_field_path_already_canonical_unchanged():
    assert (
        display_value(_bundle("IPS"), field_path="display_offerings.*.panel_type")
        == "IPS"
    )


def test_display_value_field_path_does_not_break_non_rule_fields():
    assert (
        display_value(_bundle(240), field_path="display_offerings.*.refresh_rate_hz")
        == "240"
    )


# ---- non-canonicalizable shapes pass through untouched -------------------


def test_display_value_field_path_ignored_for_none_bundle():
    assert display_value(None, field_path="display_offerings.*.panel_type") == ""


def test_display_value_field_path_ignored_for_vendor_no_pub():
    bundle = {"status": "vendor-doesn't-publish"}
    assert (
        display_value(bundle, field_path="display_offerings.*.panel_type")
        == VENDOR_NO_PUB_TEXT
    )


def test_display_value_field_path_ignored_for_missing_value():
    assert (
        display_value(_bundle(None), field_path="display_offerings.*.panel_type")
        == ""
    )


def test_display_value_field_path_ignored_for_bool():
    # Booleans render as yes/no — never a candidate for a string canonical
    # mapping. The canonicalizer should not run on the yes/no string.
    assert (
        display_value(_bundle(True), field_path="display_offerings.*.panel_type")
        == "yes"
    )
    assert (
        display_value(_bundle(False), field_path="display_offerings.*.panel_type")
        == "no"
    )


# ---- marker_for_bundle status mapping -----------------------------------


def test_formatting_status_manual_resolves_to_manual_marker():
    """Stage 10a — a bundle with status='manual' renders the manual marker."""
    bundle = {
        "value": "yes",
        "status": "manual",
        "entered_by": "tester",
        "entered_at": "2026-05-19T00:00:00+00:00",
    }
    assert marker_for_bundle(bundle) == MARKER_MANUAL


def test_formatting_status_manual_marker_without_entered_by():
    """A bundle whose status is 'manual' resolves to MARKER_MANUAL even without entered_by."""
    bundle = {"value": "yes", "status": "manual"}
    assert marker_for_bundle(bundle) == MARKER_MANUAL


def test_formatting_status_vouched_with_entered_by_still_manual_marker():
    """Existing manual bundles (status='vouched' + entered_by) keep the manual marker."""
    bundle = {
        "value": "yes",
        "status": "vouched",
        "entered_by": "tester",
        "entered_at": "2026-05-19T00:00:00+00:00",
    }
    assert marker_for_bundle(bundle) == MARKER_MANUAL


def test_formatting_status_verified_resolves_to_verified_marker():
    bundle = {"value": "yes", "status": "verified"}
    assert marker_for_bundle(bundle) == MARKER_VERIFIED


def test_formatting_status_needs_review_resolves_to_needs_review_marker():
    bundle = {"value": "yes", "status": "needs-review"}
    assert marker_for_bundle(bundle) == MARKER_NEEDS_REVIEW
