"""T8.8 — unit tests for pure helpers in ``ui/refresh.py``.

The streamlit-rendering surface (``render``, ``_render_one_mode``,
``_render_all_mode``, ``_run_one``, ``_run_all``) is deferred to the
``streamlit.testing.v1.AppTest`` harness (Stage 8 / T8.8 follow-on).
This file covers ``_validate_url_brand`` (the Custom-URL host
pre-flight check added in T8.8) since it's pure logic.
"""

from __future__ import annotations

import pytest

from competitive_database.ui.refresh import _validate_url_brand


@pytest.mark.parametrize(
    "brand, url",
    [
        ("dell", "https://www.dell.com/en-us/shop/dell-laptops/foo/spd/ac16251"),
        ("hp", "https://www.hp.com/us-en/shop/pdp/16t-ah100"),
        ("lenovo", "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec"),
        ("lenovo", "https://www.lenovo.com/us/en/p/laptops/legion/legion-pro/legion-pro-7-16/foo"),
        ("asus", "https://rog.asus.com/us/laptops/rog-zephyrus/rog-zephyrus-g16-2026/spec/"),
        ("asus", "https://www.asus.com/us/laptops/for-gaming/rog-strix/foo/"),
        ("DELL", "https://www.dell.com/en-us/foo"),  # case-insensitive brand
        ("dell", "HTTPS://WWW.DELL.COM/EN-US/foo"),  # case-insensitive host
    ],
)
def test_url_matches_brand_returns_none(brand, url):
    assert _validate_url_brand(brand, url) is None


@pytest.mark.parametrize(
    "brand, url, expect_substr",
    [
        ("hp", "https://www.dell.com/en-us/foo", "doesn't match brand `hp`"),
        ("dell", "https://www.hp.com/us-en/shop/pdp/foo", "doesn't match brand `dell`"),
        ("lenovo", "https://rog.asus.com/us/foo", "doesn't match brand `lenovo`"),
        ("asus", "https://psref.lenovo.com/foo", "doesn't match brand `asus`"),
        # Sneaky lookalikes: the suffix check must require either an
        # exact host match or a `.dell.com`-style boundary, not a bare
        # substring — otherwise dellxxx.com or notdell.com would pass.
        ("dell", "https://www.notdell.com/foo", "doesn't match brand `dell`"),
        ("hp", "https://www.hpfake.com/foo", "doesn't match brand `hp`"),
    ],
)
def test_mismatched_brand_returns_error(brand, url, expect_substr):
    err = _validate_url_brand(brand, url)
    assert err is not None
    assert expect_substr in err


def test_unparseable_url_returns_error():
    err = _validate_url_brand("dell", "not-a-url")
    assert err is not None
    assert "hostname" in err.lower()


def test_unknown_brand_returns_none():
    # Unknown brand falls through to the downstream check (which
    # rejects it with a typed error); this helper is a UX pre-flight,
    # not an authority on supported brands.
    assert _validate_url_brand("acer", "https://www.acer.com/foo") is None
    assert _validate_url_brand("", "https://www.dell.com/foo") is None
