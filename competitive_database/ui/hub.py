"""Editorial Hub landing screen (Stage 10 Phase B)."""

from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timezone

import streamlit as st

from competitive_database.ui import find, spec_roster, theme
from competitive_database.views.orchestrator import _SECTION_REGISTRY


# Home CTA / inline-section definitions: (title, description, section key).
# Clicking a CTA opens that section inline on the hub (``hub.section``).
_CTA_CARDS: tuple[tuple[str, str, str], ...] = (
    ("Spec Roster", "View one laptop or compare several, side by side.", "spec_roster"),
    ("Find", "Filter by the spec that matters to you.", "find"),
)

# The inline sections reachable from the hub, in pill order.
_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Spec Roster", "spec_roster"),
    ("Find", "find"),
)


# Welcome modal — one row per function in the "Who it's for" section.
_WELCOME_WHO_ROWS: tuple[tuple[str, str], ...] = (
    ("Product", "Benchmark roadmaps against competitor shipping specs."),
    ("Marketing", "Pull comparison data for decks and battlecards."),
    ("Competitive intel", "Track what every OEM ships, when, at what tier."),
)


_ACCENT: str = str(theme.PALETTE["accent"])

# Inline SVG glyphs rendered in the welcome modal. The Problem→What-it-does
# pair is a small visual story: scattered rectangles snap into a tidy
# grid. No external assets — just the editorial accent color.
_ICON_SCATTERED: str = (
    f'<svg width="32" height="32" viewBox="0 0 32 32" fill="none" '
    f'stroke="{_ACCENT}" stroke-width="1.5">'
    f'<rect x="3" y="5" width="9" height="6" rx="1.5" transform="rotate(-10 7.5 8)"/>'
    f'<rect x="14" y="3" width="9" height="6" rx="1.5" transform="rotate(8 18.5 6)"/>'
    f'<rect x="6" y="17" width="9" height="6" rx="1.5" transform="rotate(-5 10.5 20)"/>'
    f'<rect x="18" y="20" width="9" height="6" rx="1.5" transform="rotate(12 22.5 23)"/>'
    f'</svg>'
)
_ICON_GRID: str = (
    f'<svg width="32" height="32" viewBox="0 0 32 32" fill="none" '
    f'stroke="{_ACCENT}" stroke-width="1.5">'
    f'<rect x="4" y="4" width="10" height="10" rx="1.5"/>'
    f'<rect x="18" y="4" width="10" height="10" rx="1.5"/>'
    f'<rect x="4" y="18" width="10" height="10" rx="1.5"/>'
    f'<rect x="18" y="18" width="10" height="10" rx="1.5"/>'
    f'</svg>'
)
_ICON_NODES: str = (
    f'<svg width="32" height="32" viewBox="0 0 32 32" fill="none" '
    f'stroke="{_ACCENT}" stroke-width="1.5">'
    f'<circle cx="7" cy="9" r="3.5"/>'
    f'<circle cx="25" cy="9" r="3.5"/>'
    f'<circle cx="16" cy="23" r="3.5"/>'
    f'<line x1="10.5" y1="9" x2="21.5" y2="9"/>'
    f'<line x1="8.5" y1="12" x2="14" y2="20.5"/>'
    f'<line x1="23.5" y1="12" x2="18" y2="20.5"/>'
    f'</svg>'
)

def _counts(conn: sqlite3.Connection) -> tuple[int, int]:
    """Return (product_count, distinct_brand_count) from the live DB."""
    products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    brand_rows = conn.execute(
        "SELECT brand FROM products WHERE brand IS NOT NULL"
    ).fetchall()
    brands: set[str] = set()
    for row in brand_rows:
        bundle = json.loads(row[0])
        if isinstance(bundle, dict) and bundle.get("value") is not None:
            brands.add(bundle["value"])
    return products, len(brands)


def _vendor_names(conn: sqlite3.Connection) -> list[str]:
    """Distinct, sorted brand names from the products table.

    Used by the welcome modal to name vendors live rather than hardcoding
    the list. New vendors flow through automatically when seeded.
    """
    rows = conn.execute(
        "SELECT brand FROM products WHERE brand IS NOT NULL"
    ).fetchall()
    names: set[str] = set()
    for row in rows:
        try:
            bundle = json.loads(row[0])
        except (TypeError, ValueError):
            continue
        if isinstance(bundle, dict) and bundle.get("value") is not None:
            names.add(str(bundle["value"]))
    return sorted(names)


def _walk_captured_at(node: object, out: list[str]) -> None:
    if isinstance(node, dict):
        cap = node.get("captured_at")
        if isinstance(cap, str):
            out.append(cap)
        for v in node.values():
            _walk_captured_at(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_captured_at(item, out)


def _days_since_last_refresh(conn: sqlite3.Connection) -> int | None:
    """Days since the most recent ``captured_at`` across all products."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(products)")]
    bundled = [c for c in cols if c not in {"product", "model_code", "year", "family_code", "source_model_codes"}]
    if not bundled:
        return None
    select = ", ".join(bundled)
    captured: list[str] = []
    for row in conn.execute(f"SELECT {select} FROM products").fetchall():
        for raw in row:
            if raw is None:
                continue
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError):
                continue
            _walk_captured_at(decoded, captured)
    if not captured:
        return None
    latest: datetime | None = None
    for ts in captured:
        try:
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if latest is None or parsed > latest:
            latest = parsed
    if latest is None:
        return None
    delta = datetime.now(timezone.utc) - latest
    return max(delta.days, 0)


def _tile(value: str, label: str) -> str:
    """Render a rounded box with a large value on top and a small label below."""
    p = theme.PALETTE
    return (
        f'<div style="'
        f'background:{p["bg_card"]};'
        f'border:1px solid {p["border"]};'
        f'border-radius:{theme.RADIUS["lg"]}px;'
        f'padding:{theme.SPACE["lg"]}px;'
        f'">'
        f'<div style="'
        f'font-size:{theme.TYPE["size_hero"]}px;'
        f'font-weight:{theme.TYPE["weight_semibold"]};'
        f'color:{p["text"]};'
        f'line-height:1.1;'
        f'">{html.escape(value)}</div>'
        f'<div style="'
        f'margin-top:{theme.SPACE["xs"]}px;'
        f'font-size:{theme.TYPE["size_sm"]}px;'
        f'color:{p["text_muted"]};'
        f'">{html.escape(label)}</div>'
        f'</div>'
    )


def _card_shell(title: str, description: str) -> str:
    """Render the top half of a CTA card (title + sub-copy)."""
    p = theme.PALETTE
    return (
        f'<div style="'
        f'background:{p["bg_card"]};'
        f'border:1px solid {p["border"]};'
        f'border-radius:{theme.RADIUS["lg"]}px;'
        f'padding:{theme.SPACE["lg"]}px;'
        f'">'
        f'<div style="'
        f'font-size:{theme.TYPE["size_lg"]}px;'
        f'font-weight:{theme.TYPE["weight_semibold"]};'
        f'color:{p["text"]};'
        f'">{html.escape(title)}</div>'
        f'<div style="'
        f'margin-top:{theme.SPACE["sm"]}px;'
        f'font-size:{theme.TYPE["size_sm"]}px;'
        f'color:{p["text_muted"]};'
        f'line-height:1.5;'
        f'">{html.escape(description)}</div>'
        f'</div>'
    )


def _categories_count() -> int:
    """Number of top-level spec sections the orchestrator renders."""
    return len(_SECTION_REGISTRY)


def _hero_grid_svg(count: int, cols: int) -> str:
    """Render a grid of squares — one per product — for the modal hero.

    The visual conveys catalog scale at a glance: the eye lands on the
    dense band before reading any text. Layout is left-to-right,
    top-to-bottom; the final row is partially filled when ``count`` is
    not a multiple of ``cols``. With an empty DB the function falls back
    to a muted outline placeholder so the layout doesn't collapse.
    """
    cell = 14
    gap = 4
    cols = max(cols, 1)
    p = theme.PALETTE
    empty = count <= 0
    display_count = cols * 2 if empty else count
    rows = (display_count + cols - 1) // cols
    width = cols * (cell + gap) - gap
    height = rows * (cell + gap) - gap
    fill = "transparent" if empty else _ACCENT
    stroke_attr = (
        f' stroke="{p["border_strong"]}" stroke-width="1"' if empty else ""
    )
    cells = "".join(
        f'<rect x="{(i % cols) * (cell + gap)}" '
        f'y="{(i // cols) * (cell + gap)}" '
        f'width="{cell}" height="{cell}" rx="2.5" '
        f'fill="{fill}"{stroke_attr}/>'
        for i in range(display_count)
    )
    return (
        f'<svg width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'style="display:block;margin:0 auto;">'
        f'{cells}'
        f'</svg>'
    )


def _welcome_hero_html(products: int, categories: int) -> str:
    """Hero block: density grid, math reveal (products × categories =
    total fields), and the kicker tagline. Sits at the top of the
    welcome modal — the eye lands here first.
    """
    p = theme.PALETTE
    grid = _hero_grid_svg(products, cols=max(categories, 1))
    total = products * categories if products > 0 and categories > 0 else 0

    def _fmt(value: int) -> str:
        return f"{value:,}" if value > 0 else "—"

    def _tile(value: str, label: str) -> str:
        return (
            f'<div style="text-align:center;flex:0 0 auto;min-width:90px;">'
            f'<div style="'
            f'font-size:48px;'
            f'font-weight:{theme.TYPE["weight_semibold"]};'
            f'color:{p["text"]};'
            f'line-height:1;'
            f'">{html.escape(value)}</div>'
            f'<div style="'
            f'margin-top:{theme.SPACE["xs"]}px;'
            f'font-size:{theme.TYPE["size_xs"]}px;'
            f'color:{p["text_muted"]};'
            f'text-transform:uppercase;'
            f'letter-spacing:0.5px;'
            f'">{html.escape(label)}</div>'
            f'</div>'
        )

    def _op(symbol: str) -> str:
        return (
            f'<div style="'
            f'flex:0 0 auto;'
            f'font-size:28px;'
            f'color:{p["text_faint"]};'
            f'font-weight:{theme.TYPE["weight_normal"]};'
            f'padding-top:6px;'
            f'">{html.escape(symbol)}</div>'
        )

    return (
        f'<div style="margin-bottom:{theme.SPACE["xxl"]}px;">'
        f'<div style="margin-bottom:{theme.SPACE["xl"]}px;">{grid}</div>'
        f'<div style="'
        f'display:flex;'
        f'gap:{theme.SPACE["xl"]}px;'
        f'align-items:center;'
        f'justify-content:center;'
        f'margin-bottom:{theme.SPACE["md"]}px;'
        f'">'
        f'{_tile(_fmt(products), "products")}'
        f'{_op("×")}'
        f'{_tile(_fmt(categories), "spec categories")}'
        f'{_op("=")}'
        f'{_tile(_fmt(total), "fields")}'
        f'</div>'
        f'<div style="'
        f'text-align:center;'
        f'font-size:{theme.TYPE["size_sm"]}px;'
        f'color:{p["text_muted"]};'
        f'font-style:italic;'
        f'">Hand-normalized across vendor catalogs.</div>'
        f'</div>'
    )


def _welcome_card_html(icon: str, title: str, body: str) -> str:
    """One column of the 3-up explanatory grid: icon-top, title, body.

    Sized via ``flex:1 1 0`` so the parent flex row distributes equal
    width across all cards.
    """
    p = theme.PALETTE
    return (
        f'<div style="'
        f'flex:1 1 0;'
        f'display:flex;'
        f'flex-direction:column;'
        f'gap:{theme.SPACE["sm"]}px;'
        f'">'
        f'<div style="line-height:0;">{icon}</div>'
        f'<div style="'
        f'font-size:{theme.TYPE["size_lg"]}px;'
        f'font-weight:{theme.TYPE["weight_semibold"]};'
        f'color:{p["text"]};'
        f'">{html.escape(title)}</div>'
        f'<div style="'
        f'font-size:{theme.TYPE["size_sm"]}px;'
        f'color:{p["text_muted"]};'
        f'line-height:1.55;'
        f'">{html.escape(body)}</div>'
        f'</div>'
    )


def _welcome_who_card_html(
    icon: str,
    title: str,
    rows: tuple[tuple[str, str], ...],
) -> str:
    """``Who it's for`` card — function label stacked above its use case
    line, repeated per row. Designed for the narrow 3-column layout: the
    label-on-left / description-on-right pattern doesn't fit at column
    widths, so each row collapses vertically.
    """
    p = theme.PALETTE
    row_html = "".join(
        f'<div style="margin-bottom:{theme.SPACE["sm"]}px;">'
        f'<div style="'
        f'font-size:{theme.TYPE["size_sm"]}px;'
        f'font-weight:{theme.TYPE["weight_medium"]};'
        f'color:{p["text"]};'
        f'">{html.escape(label)}</div>'
        f'<div style="'
        f'font-size:{theme.TYPE["size_sm"]}px;'
        f'color:{p["text_muted"]};'
        f'line-height:1.55;'
        f'margin-top:2px;'
        f'">{html.escape(use_case)}</div>'
        f'</div>'
        for label, use_case in rows
    )
    return (
        f'<div style="'
        f'flex:1 1 0;'
        f'display:flex;'
        f'flex-direction:column;'
        f'gap:{theme.SPACE["sm"]}px;'
        f'">'
        f'<div style="line-height:0;">{icon}</div>'
        f'<div style="'
        f'font-size:{theme.TYPE["size_lg"]}px;'
        f'font-weight:{theme.TYPE["weight_semibold"]};'
        f'color:{p["text"]};'
        f'">{html.escape(title)}</div>'
        f'<div>{row_html}</div>'
        f'</div>'
    )


@st.dialog("Welcome to Spec Compass", width="large")
def _welcome_dialog(
    products: int,
    categories: int,
    vendor_list_str: str,
) -> None:
    """One-time welcome modal — shown on the first hub render per session.

    Takes plain values rather than the live ``sqlite3.Connection``:
    Streamlit reruns the dialog body on a worker thread distinct from
    the one that created ``conn``, and SQLite forbids cross-thread
    access. All DB-derived values are therefore computed by ``render``
    (on the main thread) and passed in as primitives that travel safely
    across the boundary.
    """
    # Hero — density grid + math reveal. The eye lands here first.
    st.markdown(
        _welcome_hero_html(products, categories),
        unsafe_allow_html=True,
    )

    # Divider between the hero and the explanatory sections.
    st.markdown(
        f'<div style="'
        f'border-top:1px solid {theme.PALETTE["border"]};'
        f'margin-bottom:{theme.SPACE["xl"]}px;'
        f'"></div>',
        unsafe_allow_html=True,
    )

    # Three-up explanatory grid: Problem | What this does | Who it's for.
    # ``align-items:stretch`` makes the column frames equal-height so the
    # tallest card (Who, with three sub-rows) doesn't leave the others
    # ragged.
    problem_card = _welcome_card_html(
        icon=_ICON_SCATTERED,
        title="The problem",
        body=(
            "Competitor spec data lives on 4+ vendor sites, in 4+ "
            "formats. No one normalizes it."
        ),
    )
    what_card = _welcome_card_html(
        icon=_ICON_GRID,
        title="What this does",
        body=(
            f"One catalog. Every shipping gaming laptop from "
            f"{vendor_list_str} — normalized field-by-field, "
            f"side-by-side comparable."
        ),
    )
    who_card = _welcome_who_card_html(
        icon=_ICON_NODES,
        title="Who it's for",
        rows=_WELCOME_WHO_ROWS,
    )
    st.markdown(
        f'<div style="'
        f'display:flex;'
        f'gap:{theme.SPACE["xxxl"]}px;'
        f'align-items:stretch;'
        f'margin-bottom:{theme.SPACE["xl"]}px;'
        f'">'
        f'{problem_card}{what_card}{who_card}'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div style="height:{theme.SPACE["lg"]}px"></div>',
        unsafe_allow_html=True,
    )

    cols = st.columns([2, 1, 2])
    with cols[1]:
        if st.button(
            "Got it",
            key="welcome_dismiss",
            type="primary",
            use_container_width=True,
        ):
            st.rerun()


def _render_section_pills(active: str) -> None:
    """Render the Spec Roster / Find pill switcher above an inline section.

    The hub's logo (top-left) returns to the full home; these pills swap
    which section is open without leaving the hub.
    """
    cols = st.columns([1, 1, 6])
    for (label, sec), col in zip(_SECTIONS, cols[: len(_SECTIONS)]):
        is_active = sec == active
        with col:
            if st.button(
                f"● {label}" if is_active else f"○ {label}",
                key=f"hub_pill_{sec}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                if not is_active:
                    st.session_state["hub.section"] = sec
                    st.rerun()
    st.markdown(
        f'<div style="border-bottom:1px solid {theme.PALETTE["border"]};'
        f'margin:{theme.SPACE["sm"]}px 0 {theme.SPACE["lg"]}px 0;"></div>',
        unsafe_allow_html=True,
    )


def render(conn: sqlite3.Connection, *, db_path: str) -> None:
    """Render the Hub landing screen."""
    del db_path  # chrome handles attribution; no internal IDs leak here.

    # Welcome modal — shows once per Streamlit session on the first hub
    # render. Setting the flag *before* opening the dialog covers
    # X-dismissal too: whether the user clicks "Got it" or the built-in
    # close button, the dialog won't reappear later in the session.
    # All DB-derived values are computed *here* (main script thread) so
    # the dialog body can rerun on its own worker thread without ever
    # touching ``conn``.
    if not st.session_state.get("welcome_seen"):
        st.session_state["welcome_seen"] = True
        welcome_products, _ = _counts(conn)
        welcome_names = _vendor_names(conn)
        if welcome_names:
            welcome_vendor_list = ", ".join(welcome_names) + ", etc."
        else:
            welcome_vendor_list = "every major OEM"
        _welcome_dialog(
            welcome_products,
            _categories_count(),
            welcome_vendor_list,
        )

    # A section open? Render the pill switcher + that section inline.
    section = st.session_state.get("hub.section")
    if section in dict(_SECTIONS).values():
        _render_section_pills(active=section)
        if section == "spec_roster":
            spec_roster.render(conn, db_path="")
        else:
            find.render(conn, db_path="")
        return

    # ---- Full home: metric tiles + CTA cards (no tagline) ----
    st.markdown(
        f'<div style="height:{theme.SPACE["lg"]}px"></div>',
        unsafe_allow_html=True,
    )
    products, vendors = _counts(conn)
    days = _days_since_last_refresh(conn)
    days_value = "—" if (products == 0 or days is None) else f"{days} days"
    metric_cols = st.columns(3)
    with metric_cols[0]:
        st.markdown(_tile(str(products), "products"), unsafe_allow_html=True)
    with metric_cols[1]:
        st.markdown(_tile(str(vendors), "vendors"), unsafe_allow_html=True)
    with metric_cols[2]:
        st.markdown(_tile(days_value, "since refresh"), unsafe_allow_html=True)

    st.markdown(
        f'<div style="height:{theme.SPACE["xl"]}px"></div>',
        unsafe_allow_html=True,
    )

    card_cols = st.columns(len(_CTA_CARDS))
    for col, (title, description, sec) in zip(card_cols, _CTA_CARDS):
        with col:
            st.markdown(_card_shell(title, description), unsafe_allow_html=True)
            if st.button(
                "Open →",
                key=f"hub_cta_{sec}",
                use_container_width=True,
                type="primary",
            ):
                st.session_state["hub.section"] = sec
                st.rerun()
