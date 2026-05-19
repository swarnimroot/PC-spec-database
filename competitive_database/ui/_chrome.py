"""Shared top-bar + footer chrome rendered above each route."""

from __future__ import annotations

import streamlit as st

from competitive_database.ui import theme


# Nav items rendered as hero links in the top bar. Order is locked by
# the Stage 10 chrome mockup; Edit / Refresh / Triage live under the
# ``···`` overflow.
_NAV: tuple[tuple[str, str], ...] = (
    ("Browse", "browse"),
    ("Compare", "compare"),
    ("Find", "find"),
)

_OVERFLOW: tuple[tuple[str, str], ...] = (
    ("Edit", "edit"),
    ("Refresh", "refresh"),
    ("Triage", "queue"),
)


def _go(route: str) -> None:
    st.session_state["view"] = route
    st.rerun()


def render_header(active: str | None = None) -> None:
    """Top bar: logo + Browse/Compare/Find + ``···`` overflow."""
    theme.inject_global_css()
    cols = st.columns([3, 1, 1, 1, 1], gap="small")
    with cols[0]:
        if st.button(
            "◆  Spec Compass",
            key="cd_brand",
            help="Back to hub",
            use_container_width=False,
        ):
            _go("hub")
    for (label, route), col in zip(_NAV, cols[1:4]):
        marker = " —" if active == route else ""
        with col:
            if st.button(
                f"{label}{marker}",
                key=f"cd_nav_{route}",
                use_container_width=True,
            ):
                _go(route)
    with cols[4]:
        with st.popover(
            "···",
            use_container_width=True,
        ):
            for label, route in _OVERFLOW:
                if st.button(
                    label,
                    key=f"cd_overflow_{route}",
                    use_container_width=True,
                ):
                    _go(route)
    st.markdown(
        '<div style="border-bottom:1px solid var(--cd-border);'
        'margin:0 0 var(--cd-space-lg) 0;"></div>',
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    """Thin divider at the page bottom; no footer text."""
    theme.inject_global_css()
    st.markdown(
        '<div style="margin-top:var(--cd-space-xxxl);'
        'border-top:1px solid var(--cd-border);"></div>',
        unsafe_allow_html=True,
    )
