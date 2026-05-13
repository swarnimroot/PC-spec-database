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
    VENDOR_NO_PUB_TEXT,
    canonicalize_display,
    display_value,
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
