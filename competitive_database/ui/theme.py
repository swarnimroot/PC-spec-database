"""Editorial-style design tokens + one-shot global CSS injector."""

from __future__ import annotations

import streamlit as st


# Color tokens. The accent is a calm slate-blue chosen to sit alongside
# the marker palette without competing for attention; markers stay
# restrained (one step below Tailwind defaults).
PALETTE: dict[str, object] = {
    "bg_page": "#fafaf7",
    "bg_card": "#ffffff",
    "bg_subtle": "#f3f3ef",
    "border": "#e5e5e2",
    "border_strong": "#d1d5db",
    "text": "#1c1e22",
    "text_muted": "#4b5563",
    "text_faint": "#6b7280",
    "accent": "#3a5a7c",
    "bg_accent_soft": "#eef2f7",
    "bg_accent_soft_hover": "#dde6ef",
    "markers": {
        "verified": "#16a34a",
        "needs_review": "#d97706",
        "manual": "#3b82f6",
        "vendor_no_publish": "#6b7280",
        "empty": "#94a3b8",
        "low_confidence": "#ea580c",
    },
}

SPACE: dict[str, int] = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
    "xxxl": 48,
}

RADIUS: dict[str, int] = {
    "sm": 4,
    "md": 8,
    "lg": 12,
    "pill": 999,
}

TYPE: dict[str, object] = {
    "family": (
        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, '
        '"Helvetica Neue", Arial, sans-serif'
    ),
    "size_xs": 12,
    "size_sm": 14,
    "size_base": 16,
    "size_lg": 18,
    "size_xl": 24,
    "size_hero": 32,
    "weight_normal": 400,
    "weight_medium": 500,
    "weight_semibold": 600,
}


def inject_global_css() -> None:
    """Emit the editorial-style CSS once per page render."""
    if st.session_state.get("__cd_css_injected__"):
        return
    st.session_state["__cd_css_injected__"] = True
    p = PALETTE
    markers = p["markers"]  # type: ignore[index]
    css = f"""
<style>
:root {{
    --cd-bg-page: {p["bg_page"]};
    --cd-bg-card: {p["bg_card"]};
    --cd-bg-subtle: {p["bg_subtle"]};
    --cd-border: {p["border"]};
    --cd-border-strong: {p["border_strong"]};
    --cd-text: {p["text"]};
    --cd-text-muted: {p["text_muted"]};
    --cd-text-faint: {p["text_faint"]};
    --cd-accent: {p["accent"]};
    --cd-bg-accent-soft: {p["bg_accent_soft"]};
    --cd-bg-accent-soft-hover: {p["bg_accent_soft_hover"]};
    --cd-marker-verified: {markers["verified"]};
    --cd-marker-needs-review: {markers["needs_review"]};
    --cd-marker-manual: {markers["manual"]};
    --cd-marker-vendor-no-publish: {markers["vendor_no_publish"]};
    --cd-marker-empty: {markers["empty"]};
    --cd-marker-low-confidence: {markers["low_confidence"]};
    --cd-space-xs: {SPACE["xs"]}px;
    --cd-space-sm: {SPACE["sm"]}px;
    --cd-space-md: {SPACE["md"]}px;
    --cd-space-lg: {SPACE["lg"]}px;
    --cd-space-xl: {SPACE["xl"]}px;
    --cd-space-xxl: {SPACE["xxl"]}px;
    --cd-space-xxxl: {SPACE["xxxl"]}px;
    --cd-radius-sm: {RADIUS["sm"]}px;
    --cd-radius-md: {RADIUS["md"]}px;
    --cd-radius-lg: {RADIUS["lg"]}px;
    --cd-radius-pill: {RADIUS["pill"]}px;
    --cd-font-family: {TYPE["family"]};
    --cd-size-xs: {TYPE["size_xs"]}px;
    --cd-size-sm: {TYPE["size_sm"]}px;
    --cd-size-base: {TYPE["size_base"]}px;
    --cd-size-lg: {TYPE["size_lg"]}px;
    --cd-size-xl: {TYPE["size_xl"]}px;
    --cd-size-hero: {TYPE["size_hero"]}px;
}}

html, body, [class*="stApp"] {{
    background-color: var(--cd-bg-page);
    color: var(--cd-text);
    font-family: var(--cd-font-family);
}}

a, a:visited {{
    color: var(--cd-accent);
    text-decoration: none;
}}
a:hover {{
    text-decoration: underline;
}}

::-webkit-scrollbar {{
    width: 10px;
    height: 10px;
}}
::-webkit-scrollbar-track {{
    background: transparent;
}}
::-webkit-scrollbar-thumb {{
    background: var(--cd-border);
    border-radius: var(--cd-radius-pill);
}}
::-webkit-scrollbar-thumb:hover {{
    background: var(--cd-border-strong);
}}

.cd-header {{
    display: flex;
    align-items: center;
    gap: var(--cd-space-lg);
    padding: var(--cd-space-md) 0 var(--cd-space-sm) 0;
    border-bottom: 1px solid var(--cd-border);
    margin-bottom: var(--cd-space-lg);
}}
.cd-header__brand {{
    display: flex;
    align-items: center;
    gap: var(--cd-space-sm);
    font-size: var(--cd-size-lg);
    font-weight: {TYPE["weight_semibold"]};
    color: var(--cd-text);
}}
.cd-header__brand-mark {{
    color: var(--cd-accent);
    font-size: var(--cd-size-xl);
    line-height: 1;
}}
.cd-header__nav-item {{
    color: var(--cd-text-muted);
    font-size: var(--cd-size-sm);
    font-weight: {TYPE["weight_medium"]};
}}
.cd-header__nav-item--active {{
    color: var(--cd-text);
    border-bottom: 2px solid var(--cd-accent);
    padding-bottom: 2px;
}}

.cd-dot {{
    display: inline-block;
    margin-right: 4px;
    line-height: 1;
}}

[data-testid="baseButton-primary"],
.stButton button[kind="primary"] {{
    background-color: var(--cd-bg-accent-soft);
    color: var(--cd-text);
    border: 1px solid var(--cd-border-strong);
}}
[data-testid="baseButton-primary"]:hover,
.stButton button[kind="primary"]:hover {{
    background-color: var(--cd-bg-accent-soft-hover);
    color: var(--cd-text);
    border-color: var(--cd-border-strong);
}}
[data-testid="baseButton-primary"]:focus,
[data-testid="baseButton-primary"]:focus-visible,
.stButton button[kind="primary"]:focus,
.stButton button[kind="primary"]:focus-visible {{
    outline: 2px solid var(--cd-accent);
    outline-offset: 1px;
    box-shadow: none;
}}
</style>
"""
    st.markdown(css, unsafe_allow_html=True)
