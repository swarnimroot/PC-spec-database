"""Shared top-bar + footer chrome rendered above each route."""

from __future__ import annotations

import streamlit as st

from competitive_database.ui import theme


# Top-bar nav. Spec Roster + Find live on the hub (as CTAs / inline-section
# pills), so the banner carries only Edit / Refresh / Triage; the logo
# returns to the hub.
_NAV: tuple[tuple[str, str], ...] = (
    ("Edit", "edit"),
    ("Refresh", "refresh"),
    ("Triage", "queue"),
)


def _go(route: str) -> None:
    st.session_state["view"] = route
    st.rerun()


def render_header(active: str | None = None) -> None:
    """Top bar: logo (home) + Edit / Refresh / Triage."""
    theme.inject_global_css()
    cols = st.columns([3] + [1] * len(_NAV), gap="small")
    with cols[0]:
        if st.button(
            "◆  Spec Compass",
            key="cd_brand",
            help="Home",
            use_container_width=False,
        ):
            # Clear any open inline section so the logo lands on the full home.
            st.session_state.pop("hub.section", None)
            _go("hub")
    for (label, route), col in zip(_NAV, cols[1:]):
        marker = " —" if active == route else ""
        with col:
            if st.button(
                f"{label}{marker}",
                key=f"cd_nav_{route}",
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
