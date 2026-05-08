"""Unit tests for ``refresh`` URL coercion + slug resolution."""

from competitive_database.cli.refresh import _coerce_vendor_url, _resolve_url


def test_coerce_asus_url_without_spec_appends_subpath():
    coerced = _coerce_vendor_url(
        "asus",
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/",
    )
    assert coerced == (
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec/"
    )


def test_coerce_asus_url_with_spec_keeps_form():
    coerced = _coerce_vendor_url(
        "asus",
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec/",
    )
    assert coerced == (
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec/"
    )


def test_coerce_asus_url_spec_without_trailing_slash_gets_one():
    coerced = _coerce_vendor_url(
        "asus",
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec",
    )
    assert coerced == (
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/spec/"
    )


def test_coerce_non_asus_url_unchanged():
    url = "https://www.dell.com/en-us/shop/dell-laptops/foo/spd/ac16251"
    assert _coerce_vendor_url("dell", url) == url


def test_resolve_asus_url_without_spec_gets_coerced():
    url, _slug = _resolve_url(
        "asus",
        "https://rog.asus.com/us/laptops/rog-strix/rog-strix-g16-2026/",
        None,
    )
    assert url.endswith("/spec/")


def test_resolve_dell_template_used_when_only_slug_given():
    url, slug = _resolve_url("dell", None, "ac16251")
    assert "ac16251" in url
    assert slug == "ac16251"
