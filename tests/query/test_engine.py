"""Unit coverage for the pure spec-query engine (``competitive_database.query``).

These tests use small in-memory product dicts shaped like the output of
``views.load.load_product`` (identity scalars are bundle dicts; offering
leaves are bundle dicts under ``<col>.<i>.<leaf>``). They assert the
operator matching semantics, template union/expansion, distinct-value
collection, and the narrow-by filter — all without touching Streamlit or
a database.
"""

from __future__ import annotations

from competitive_database.query import (
    OPS_ALL,
    OPS_NEED_VALUE,
    Op,
    apply_narrow_by,
    cell_matches,
    coerce_number,
    company_of,
    distinct_values_for_template,
    expand_template,
    find_matches,
    resolve_path,
    series_of,
    status_of,
    template_of,
    union_templates,
    year_of,
)


def _b(value, status="verified"):
    """A minimal scraped-bundle-shaped dict."""
    return {"value": value, "status": status}


def _no_pub():
    return {"value": None, "status": "vendor-doesn't-publish"}


def _empty_bundle():
    return {"value": None, "status": "needs-review"}


def _product(model_code="x", year=2026, **fields):
    return {"model_code": model_code, "year": year, **fields}


# ---------------------------------------------------------------------------
# Operator constants
# ---------------------------------------------------------------------------


def test_ops_all_and_need_value_membership():
    assert set(OPS_ALL) == {
        Op.EQ, Op.GTE, Op.LTE, Op.CONTAINS,
        Op.IS_SET, Op.IS_EMPTY, Op.VENDOR_UNAVAILABLE,
    }
    assert OPS_NEED_VALUE == frozenset({Op.EQ, Op.GTE, Op.LTE, Op.CONTAINS})
    # Value-free operators are excluded from OPS_NEED_VALUE.
    for op in (Op.IS_SET, Op.IS_EMPTY, Op.VENDOR_UNAVAILABLE):
        assert op not in OPS_NEED_VALUE


# ---------------------------------------------------------------------------
# cell_matches — the seven operators
# ---------------------------------------------------------------------------


def test_eq_string_case_insensitive():
    assert cell_matches(_b("IPS"), None, Op.EQ, "ips", "p")
    assert not cell_matches(_b("IPS"), None, Op.EQ, "OLED", "p")


def test_eq_numeric_coercion():
    # Stored "120" equals queried "120.0" via float coercion.
    assert cell_matches(_b(120), None, Op.EQ, "120.0", "x.0.refresh_rate_hz")


def test_contains_substring_case_insensitive():
    assert cell_matches(_b("Dell Inc."), None, Op.CONTAINS, "dell", "p")
    assert not cell_matches(_b("Dell Inc."), None, Op.CONTAINS, "HP", "p")


def test_gte_lte_numeric_coercion():
    path = "display_offerings.0.refresh_rate_hz"
    assert cell_matches(_b(240), None, Op.GTE, "120", path)
    assert not cell_matches(_b(60), None, Op.GTE, "120", path)
    assert cell_matches(_b(60), None, Op.LTE, "120", path)
    assert not cell_matches(_b(240), None, Op.LTE, "120", path)


def test_gte_lte_non_numeric_never_matches():
    # Non-coercible rendered value can't satisfy a numeric comparison.
    assert not cell_matches(_b("IPS"), None, Op.GTE, "120", "p")
    assert not cell_matches(_b("IPS"), None, Op.LTE, "120", "p")


def test_is_set_excludes_vendor_no_publish_and_empty():
    assert cell_matches(_b("IPS"), None, Op.IS_SET, "", "p")
    assert cell_matches(None, "plain", Op.IS_SET, "", "p")  # plain leaf
    assert not cell_matches(None, None, Op.IS_SET, "", "p")
    assert not cell_matches(_no_pub(), None, Op.IS_SET, "", "p")
    assert not cell_matches(_empty_bundle(), None, Op.IS_SET, "", "p")


def test_is_empty_excludes_vendor_no_publish():
    # Missing cell and value-None bundle count as empty...
    assert cell_matches(None, None, Op.IS_EMPTY, "", "p")
    assert cell_matches(_empty_bundle(), None, Op.IS_EMPTY, "", "p")
    # ...but a vendor-doesn't-publish cell is NOT "empty".
    assert not cell_matches(_no_pub(), None, Op.IS_EMPTY, "", "p")
    # A set value is not empty; a plain leaf is never empty.
    assert not cell_matches(_b("IPS"), None, Op.IS_EMPTY, "", "p")
    assert not cell_matches(None, "plain", Op.IS_EMPTY, "", "p")


def test_vendor_unavailable_matches_only_no_publish_status():
    assert cell_matches(_no_pub(), None, Op.VENDOR_UNAVAILABLE, "", "p")
    assert not cell_matches(_b("IPS"), None, Op.VENDOR_UNAVAILABLE, "", "p")
    assert not cell_matches(None, None, Op.VENDOR_UNAVAILABLE, "", "p")
    assert not cell_matches(None, "plain", Op.VENDOR_UNAVAILABLE, "", "p")


def test_coerce_number():
    assert coerce_number("120") == 120.0
    assert coerce_number(" 60 ") == 60.0
    assert coerce_number("IPS") is None
    assert coerce_number(None) is None


# ---------------------------------------------------------------------------
# Path resolution + template helpers
# ---------------------------------------------------------------------------


def test_resolve_path_scalar_and_offering():
    prod = _product(
        brand=_b("Dell"),
        display_offerings=[{"panel_type": _b("IPS")}],
    )
    assert resolve_path(prod, "brand") == (_b("Dell"), None)
    bundle, plain = resolve_path(prod, "display_offerings.0.panel_type")
    assert bundle == _b("IPS") and plain is None
    # Out-of-range / missing → (None, None).
    assert resolve_path(prod, "display_offerings.9.panel_type") == (None, None)
    assert resolve_path(prod, "missing") == (None, None)


def test_template_of_and_expand_template():
    assert template_of("display_offerings.0.panel_type") == (
        "display_offerings.*.panel_type"
    )
    assert template_of("brand") == "brand"
    prod = _product(
        display_offerings=[{"panel_type": _b("IPS")}, {"panel_type": _b("OLED")}]
    )
    assert expand_template(prod, "display_offerings.*.panel_type") == [
        "display_offerings.0.panel_type",
        "display_offerings.1.panel_type",
    ]
    # Non-templated path returns itself.
    assert expand_template(prod, "brand") == ["brand"]


def test_union_templates_collapses_offering_index_and_keeps_order():
    p1 = _product(
        brand=_b("Dell"),
        display_offerings=[{"panel_type": _b("IPS")}],
    )
    p2 = _product(
        model_code="y",
        brand=_b("HP"),
        display_offerings=[{"panel_type": _b("OLED")}],
    )
    templates = union_templates([p1, p2])
    # Brand (Identity section) comes before Display offering leaves.
    assert ("Identity", "brand") in templates
    assert ("Display", "display_offerings.*.panel_type") in templates
    # Offering index collapsed to '*' and deduped across products.
    panel = [t for t in templates if t[1].endswith("panel_type")]
    assert panel == [("Display", "display_offerings.*.panel_type")]
    # Identity ordering precedes Display.
    assert templates.index(("Identity", "brand")) < templates.index(
        ("Display", "display_offerings.*.panel_type")
    )


# ---------------------------------------------------------------------------
# distinct_values_for_template
# ---------------------------------------------------------------------------


def test_distinct_values_numeric_sorted_and_dedup():
    prods = [
        _product(display_offerings=[{"refresh_rate_hz": _b(240)}]),
        _product(model_code="b", display_offerings=[{"refresh_rate_hz": _b(60)}]),
        _product(model_code="c", display_offerings=[{"refresh_rate_hz": _b(120)}]),
        _product(model_code="d", display_offerings=[{"refresh_rate_hz": _b(120)}]),
    ]
    vals = distinct_values_for_template(
        prods, "display_offerings.*.refresh_rate_hz"
    )
    assert vals == ["60", "120", "240"]


def test_distinct_values_skips_no_publish_and_empty():
    prods = [
        _product(display_offerings=[{"panel_type": _b("IPS")}]),
        _product(model_code="b", display_offerings=[{"panel_type": _no_pub()}]),
        _product(model_code="c", display_offerings=[{"panel_type": _empty_bundle()}]),
    ]
    vals = distinct_values_for_template(prods, "display_offerings.*.panel_type")
    assert vals == ["IPS"]


# ---------------------------------------------------------------------------
# find_matches
# ---------------------------------------------------------------------------


def test_find_matches_one_representative_per_product():
    prods = [
        _product(
            model_code="dell",
            display_offerings=[
                {"refresh_rate_hz": _b(60)},
                {"refresh_rate_hz": _b(240)},
            ],
        ),
        _product(
            model_code="hp",
            display_offerings=[{"refresh_rate_hz": _b(60)}],
        ),
    ]
    matches = find_matches(
        prods, "display_offerings.*.refresh_rate_hz", Op.GTE, "120"
    )
    # Only the Dell product has a >=120 offering; one row, not two.
    assert len(matches) == 1
    prod, vstr, marker = matches[0]
    assert prod["model_code"] == "dell"
    assert vstr == "240"


# ---------------------------------------------------------------------------
# Identity accessors + apply_narrow_by
# ---------------------------------------------------------------------------


def test_identity_accessors():
    prod = _product(
        brand=_b("Dell"),
        series=_b("m18"),
        status=_b("Discontinued"),
    )
    assert company_of(prod) == "Dell"
    assert series_of(prod) == "m18"
    assert status_of(prod) == "Discontinued"
    assert year_of(prod) == 2026
    # Absent brand → "Unknown"; absent others → None.
    bare = _product(model_code="z", year=None)
    assert company_of(bare) == "Unknown"
    assert series_of(bare) is None
    assert status_of(bare) is None
    assert year_of(bare) is None


def _identity_set():
    return [
        _product(model_code="dell-25", year=2025, brand=_b("Dell"),
                 series=_b("m18"), product="dell-x", status=_b("Active")),
        _product(model_code="dell-26", year=2026, brand=_b("Dell"),
                 series=_b("m18"), product="dell-x", status=_b("Discontinued")),
        # NULL status → treated as Active.
        _product(model_code="hp-26", year=2026, brand=_b("HP"),
                 series=_b("Transcend"), product="hp-y"),
    ]


def test_narrow_by_brand_series_product():
    prods = _identity_set()
    assert {p["model_code"] for p in apply_narrow_by(prods, brands="Dell")} == {
        "dell-25", "dell-26"
    }
    assert {p["model_code"] for p in apply_narrow_by(prods, series="Transcend")} == {
        "hp-26"
    }
    assert {p["model_code"] for p in apply_narrow_by(prods, products_names="hp-y")} == {
        "hp-26"
    }


def test_narrow_by_years():
    prods = _identity_set()
    assert {p["model_code"] for p in apply_narrow_by(prods, years={2025})} == {
        "dell-25"
    }
    # Empty / None years → no filtering.
    assert len(apply_narrow_by(prods, years=set())) == 3
    assert len(apply_narrow_by(prods, years=None)) == 3


def test_narrow_by_status_null_treated_as_active():
    prods = _identity_set()
    active = apply_narrow_by(prods, statuses={"Active"})
    # dell-25 (explicit Active) AND hp-26 (NULL status → Active).
    assert {p["model_code"] for p in active} == {"dell-25", "hp-26"}
    disc = apply_narrow_by(prods, statuses={"Discontinued"})
    assert {p["model_code"] for p in disc} == {"dell-26"}


def test_narrow_by_axes_are_additive():
    prods = _identity_set()
    out = apply_narrow_by(prods, brands="Dell", years={2026})
    assert {p["model_code"] for p in out} == {"dell-26"}


def test_narrow_by_none_returns_all_unfiltered():
    prods = _identity_set()
    out = apply_narrow_by(prods)
    assert len(out) == 3
    # Returns a new list, not the same object.
    assert out is not prods
