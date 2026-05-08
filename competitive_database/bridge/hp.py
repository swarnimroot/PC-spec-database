"""HP parser: ``ProductSnapshot`` → ``CandidateProduct``.

HP exposes a flat ``specs: dict[str, str]`` flattened from the PDP's
config-picker plus the async tech-specs hydration endpoint. Multi-line
spec values follow HP's "line 0 = configured default, rest = upgrade
options" convention — we map line 0 → ``tier: 'base'`` and every
subsequent line → ``tier: 'optional'`` via :func:`helpers.tier_for_index`.

A few HP-specific quirks the parser absorbs:

* The "Processor, graphics & memory" key bundles CPU + GPU + RAM in a
  single ``+``-separated string per upgrade option. We split per option,
  then per-component within an option.
* The "External I/O Ports" key uses leading-count lines
  (``"2 USB Type-A ..."``) — same shape Dell uses, just under a
  different key.
* HP rarely publishes board-level TPP/TGP — those stay
  ``vendor-doesn't-publish`` like Dell, with the same static GPU →
  board map (Decision 5) supplying labels.

This module does NOT touch the database.

Status routing (per ARCHITECTURE.md §Provenance shape) matches Dell:

* High confidence → ``status: 'verified'``.
* Regex matched but value smells off → ``status: 'needs-review'`` with
  the value still attached. The runner will queue, not write.
* We looked for the field, HP didn't publish → ``status:
  'vendor-doesn't-publish'`` with ``value: null``.
* Fields we don't even attempt → omitted from the candidate entirely.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from scrapers_lib import ProductSnapshot

from . import helpers as h
from .types import Bundle, CandidateProduct, OfferingsList


logger = logging.getLogger(__name__)


SCRAPER_ID = "hp.fetch_hp_product"


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def parse(snapshot: ProductSnapshot) -> CandidateProduct:
    """Decode an HP snapshot into a :class:`CandidateProduct`.

    The snapshot's ``url``, ``fetched_at``, and ``title`` are used to derive
    identity fields and stamp every emitted bundle.
    """
    specs = dict(snapshot.specs or {})
    captured_at = snapshot.fetched_at.isoformat()
    source_url = snapshot.url

    # --- Identity --------------------------------------------------------
    model_code = _derive_hp_model_code(snapshot.title or "", snapshot.url or "")
    year, year_inferred = h.derive_year(
        snapshot.title or "",
        snapshot.url or "",
        snapshot.fetched_at,
    )

    sub_brand = _derive_hp_sub_brand(snapshot.title or "", snapshot.url or "")
    series = _derive_hp_series(snapshot.title or "", snapshot.url or "")

    cand = CandidateProduct(model_code=model_code, year=year)
    cand.year_was_inferred = year_inferred

    # vendor_full_name carries the meaningful identity provenance. If the
    # year was inferred from fetched_at (not the title/URL), flag the
    # bundle for review — wrong year = bad PK = poisons the catalog.
    # The runner sees ``year_was_inferred=True`` and routes the review row
    # to the dedicated ``year_inferred`` queue type (Decision 1).
    cand.vendor_full_name = _scraped_bundle(
        snapshot.title,
        source_url,
        captured_at,
        status="needs-review" if year_inferred else "verified",
    )
    cand.brand = _scraped_bundle("HP", source_url, captured_at)
    if sub_brand:
        cand.sub_brand = _scraped_bundle(sub_brand, source_url, captured_at)
    if series:
        cand.series = _scraped_bundle(series, source_url, captured_at)

    if year_inferred:
        cand.notes.append(
            f"year={year} inferred from fetched_at; vendor_full_name "
            f"flagged needs-review"
        )

    # --- CPU + GPU + Memory (HP's combined "Processor, graphics & memory")
    pgm_text = specs.get("Processor, graphics & memory")
    pgm_options = _split_pgm_options(pgm_text)

    cand.cpu_offerings = _build_cpu_offerings_from_pgm(
        pgm_options, source_url, captured_at
    )
    cand.boards = _build_boards_from_pgm(pgm_options, source_url, captured_at)

    # --- Memory ---------------------------------------------------------
    # HP publishes the per-option RAM size in the combined PG&M line; we
    # take the maximum advertised RAM across options as the platform
    # ceiling. Memory type / speed / slots / overclocking are not
    # consistently published → vendor-doesn't-publish.
    _populate_memory(cand, pgm_options, source_url, captured_at)

    # --- Storage --------------------------------------------------------
    storage_text = specs.get("Storage")
    cand.storage_slots = _build_storage_slots(storage_text, source_url, captured_at)
    if storage_text is not None:
        cand.storage_max_gb = _build_storage_max_gb(
            storage_text, source_url, captured_at
        )

    # --- Display --------------------------------------------------------
    display_text = specs.get("Display")
    cand.display_offerings = _build_display_offerings(
        display_text, source_url, captured_at
    )

    # --- Battery --------------------------------------------------------
    battery_text = specs.get("Primary battery") or specs.get("Battery")
    cand.battery_offerings = _build_battery_offerings(
        battery_text, source_url, captured_at
    )

    # --- Network --------------------------------------------------------
    wireless_text = specs.get("Wireless technology") or specs.get("Wireless")
    ports_text = specs.get("External I/O Ports") or specs.get("Ports")
    _populate_network(cand, wireless_text, ports_text, source_url, captured_at)

    # --- I/O ------------------------------------------------------------
    _populate_io(cand, ports_text, source_url, captured_at)

    # --- Adapter --------------------------------------------------------
    psu_text = specs.get("Power supply") or specs.get("Power Supply")
    cand.adapter_offerings = _build_adapter_offerings(
        psu_text, source_url, captured_at
    )
    if psu_text:
        # HP's Power supply string sometimes carries the connector type
        # (USB Type-C / barrel). Pull it out when present.
        connector = _detect_adapter_connector(psu_text)
        cand.adapter_connector = _maybe_bundle(connector, source_url, captured_at)

    # --- Camera ---------------------------------------------------------
    webcam_text = specs.get("Webcam") or specs.get("Camera")
    cand.camera_offerings = _build_camera_offerings(
        webcam_text, source_url, captured_at
    )

    # --- Audio ----------------------------------------------------------
    audio_text = specs.get("Audio Features") or specs.get("Audio")
    _populate_audio(cand, audio_text, source_url, captured_at)

    # --- Keyboard -------------------------------------------------------
    kb_text = specs.get("Keyboard")
    cand.keyboard_offerings = _build_keyboard_offerings(
        kb_text, source_url, captured_at
    )

    # --- Dimensions / Weight -------------------------------------------
    dim_text = specs.get("Dimensions (W X D X H)") or specs.get("Dimensions")
    weight_text = specs.get("Weight")
    _populate_dimensions(cand, dim_text, weight_text, source_url, captured_at)

    # --- Design ---------------------------------------------------------
    # HP doesn't publish A/C/D cover materials in a structured way on the
    # PDP — record we checked.
    cand.a_cover_material = _vdp_bundle(source_url, captured_at)
    cand.c_cover_material = _vdp_bundle(source_url, captured_at)
    cand.d_cover_material = _vdp_bundle(source_url, captured_at)
    cand.thermal_shelf = _vdp_bundle(source_url, captured_at)
    cand.lighting = _vdp_bundle(source_url, captured_at)

    # --- Thermals (HP rarely publishes these on the PDP) --------------
    cand.thermal_design = _vdp_bundle(source_url, captured_at)
    cand.thermal_material = _vdp_bundle(source_url, captured_at)
    cand.tim = _vdp_bundle(source_url, captured_at)
    cand.fan_count = _vdp_bundle(source_url, captured_at)

    return cand


# ---------------------------------------------------------------------------
# Bundle factories (mirror Dell — kept local to keep the bridge import-light
# and bundle-shape consistent with the docs).
# ---------------------------------------------------------------------------


def _scraped_bundle(
    value: Any,
    source_url: str,
    captured_at: str,
    *,
    status: str = "verified",
) -> Bundle:
    return {
        "value": value,
        "source_url": source_url,
        "captured_at": captured_at,
        "scraper_id": SCRAPER_ID,
        "status": status,
    }


def _vdp_bundle(source_url: str, captured_at: str) -> Bundle:
    return _scraped_bundle(
        None, source_url, captured_at, status="vendor-doesn't-publish"
    )


def _maybe_bundle(
    value: Any,
    source_url: str,
    captured_at: str,
    *,
    status: str = "verified",
) -> Bundle:
    """``value=None`` → vendor-doesn't-publish bundle; else scraped bundle."""
    if value is None:
        return _vdp_bundle(source_url, captured_at)
    return _scraped_bundle(value, source_url, captured_at, status=status)


# ---------------------------------------------------------------------------
# HP identity
# ---------------------------------------------------------------------------


# HP model codes show up as "14t-fb100" (CTO codes), "14-fb0097nr"
# (specific SKUs), or as standalone tokens like "fb0097nr". The regex is
# permissive: pull a "<digits><optional letter>-<letters><digits>..." or
# a bare "<letters><digits><letters>" model token from the title or URL.
_HP_MODEL_CODE_RE = re.compile(
    r"\b(\d{2,3}[a-z]?[- ]?[a-z]{2}\d{3,4}\w*)\b",
    re.IGNORECASE,
)


def _derive_hp_model_code(title: str, url: str) -> str:
    """Pull the model-code token out of an HP title or URL.

    Examples:
        ``"OMEN Transcend Gaming Laptop 14t-fb100, 14\""`` → ``"14t-fb100"``
        ``"OMEN Transcend Laptop 14-fb0097nr"`` → ``"14-fb0097nr"``

    Falls back to the URL's last path segment when no code matches in the
    title or URL slug — the slug always exists and gives the runner a
    stable PK to work with.
    """
    haystack = (title or "") + " " + (url or "")
    m = _HP_MODEL_CODE_RE.search(haystack)
    if m is not None:
        return m.group(1).lower()
    if url:
        return url.rstrip("/").rsplit("/", 1)[-1].lower()
    return ""


# Sub-brand → recognized name patterns. Order matters: more specific first.
_HP_SUB_BRANDS = (
    ("omen", "OMEN"),
    ("victus", "Victus"),
)


def _derive_hp_sub_brand(title: str, url: str) -> Optional[str]:
    """Return ``"OMEN"`` / ``"Victus"`` / ``None``.

    HP's PDP titles consistently lead with the sub-brand for gaming
    products (``"OMEN Transcend ..."``, ``"Victus 16 ..."``). Non-gaming
    consumer PDPs (Pavilion, Envy, OmniBook) return ``None`` — gaming
    laptops are this DB's only scope.
    """
    haystack = ((title or "") + " " + (url or "")).lower()
    for needle, label in _HP_SUB_BRANDS:
        if needle in haystack:
            return label
    return None


# Recognized HP gaming series families. We pair the family name with the
# product's screen-size token (14, 16, 18) when one is published in the
# title or URL — e.g., ``"Transcend 14"`` / ``"Max 16"``. Falls back to
# the family name alone when no size token is present.
_HP_SERIES_FAMILIES = ("Transcend", "Max")
_HP_SERIES_SIZE_RE = re.compile(r"\b(14|16|18)\b")


def _derive_hp_series(title: str, url: str) -> Optional[str]:
    """Return e.g. ``"Transcend 14"`` / ``"Max 16"`` / ``"Transcend"`` / ``None``.

    The family name comes from the title or URL; the size token is the
    first ``14`` / ``16`` / ``18`` we find in the same haystack — that's
    how HP names its gaming lines (Transcend 14 vs Transcend 16, Max 16
    vs Max 18). When no size token is present we fall back to just the
    family name so callers always get a stable string.
    """
    # Hyphens in the URL slug carry the same separator force as spaces;
    # collapse them so ``omen-transcend-14-inch`` reads as a single phrase.
    haystack_raw = (title or "") + " " + (url or "")
    haystack_norm = re.sub(r"[-_]+", " ", haystack_raw)
    haystack = haystack_norm.lower()
    for family in _HP_SERIES_FAMILIES:
        if family.lower() in haystack:
            # Prefer a size token that immediately follows the family name.
            after = haystack.split(family.lower(), 1)[1]
            m = _HP_SERIES_SIZE_RE.search(after)
            if m is not None:
                return f"{family} {m.group(1)}"
            return family
    return None


# ---------------------------------------------------------------------------
# Trademark stripping (shared with Dell)
# ---------------------------------------------------------------------------


_TM_RE = re.compile(r"[®™©]")


def _strip_tm(text: str) -> str:
    return _TM_RE.sub("", text or "")


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


# Strip HP's trailing footnote anchors (e.g. ``<a ...>[19,42]</a>``) before
# regexing. The async hydration HTML carries them inline.
_FOOTNOTE_ANCHOR_RE = re.compile(
    r"<a\s+[^>]*class=['\"]footerLink['\"][^>]*>.*?</a>",
    re.IGNORECASE | re.DOTALL,
)


def _strip_footnotes(text: str) -> str:
    return _FOOTNOTE_ANCHOR_RE.sub("", text or "")


# ---------------------------------------------------------------------------
# CPU / GPU / Memory (HP's combined "Processor, graphics & memory")
# ---------------------------------------------------------------------------


# HP's combined string is ``CPU + GPU + RAM`` per option, joined by ``+``.
# Each option lives on its own newline-separated line. We split per line,
# then per ``+`` to recover the three components.
_CPU_NAME_RE = re.compile(
    r"(?:Intel\s+)?"
    r"(?:Core\s+(?:Ultra\s+)?(?:[i]?\d{1,2})(?:\s+processor)?\s+\S+(?:\s+Plus)?"
    r"|Core\s+[i]\d-\d{4,5}\w*"
    r"|AMD\s+Ryzen\s+(?:AI\s+)?\d+\s+\S+(?:\s+\d+)?"
    r"|Ryzen\s+(?:AI\s+)?\d+\s+\S+(?:\s+\d+)?)",
    re.IGNORECASE,
)

_GPU_NAME_RE = re.compile(
    r"(NVIDIA\s+GeForce\s+RTX\s*\d+(?:\s*Ti)?(?:\s*SUPER)?"
    r"|RTX\s*\d+(?:\s*Ti)?(?:\s*SUPER)?"
    r"|AMD\s+Radeon\s+RX\s*\d+\w*"
    r"|Intel\s+Arc\s+\w+)",
    re.IGNORECASE,
)


def _split_pgm_options(text: Optional[str]) -> list[str]:
    """Split the "Processor, graphics & memory" key into one line per option.

    Returns an empty list when ``text`` is None or whitespace-only. The
    list preserves HP's line ordering — caller relies on line 0 being the
    base configuration (per HP's convention) and any later lines being
    upgrade options.
    """
    if not text:
        return []
    return h.split_options(_strip_tm(_strip_footnotes(text)))


def _build_cpu_offerings_from_pgm(
    options: list[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    """Pull each option's CPU model from the combined PG&M string.

    Multiple options may name the same CPU (HP often varies GPU and RAM
    while holding the CPU constant); we dedupe on the canonical CPU
    name, keeping the first-seen bundle (which carries provenance).
    """
    if not options:
        return None
    seen: set[str] = set()
    offerings: OfferingsList = []
    for piece in options:
        m = _CPU_NAME_RE.search(piece)
        if m is not None:
            model = _normalize_cpu_model(m.group(0))
            status = "verified"
        else:
            # Couldn't lock down a canonical model — keep the raw piece's
            # leading token but flag it for review.
            model = _normalize_ws(piece.split("+", 1)[0])
            status = "needs-review"
        if model in seen:
            continue
        seen.add(model)
        offerings.append(
            {"model": _scraped_bundle(model, source_url, captured_at, status=status)}
        )
    return offerings or None


def _normalize_cpu_model(raw: str) -> str:
    """Drop the noise-word "processor" and Intel/AMD prefix so catalog keys agree.

    Mirrors Dell's ``_normalize_cpu_model``. Kept local rather than shared
    so the per-vendor parser stays self-contained.
    """
    s = _normalize_ws(raw)
    s = re.sub(r"^Intel\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^AMD\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+processor\s+", " ", s, flags=re.IGNORECASE)
    return s.strip()


def _build_boards_from_pgm(
    options: list[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    """Group GPUs from the combined PG&M lines by their static board label.

    Per Decision 5, board labels come from the static ``GPU_TO_BOARD`` map.
    Unmapped GPUs emit a board with ``label: null`` and the GPU bundle
    marked ``needs-review``. HP doesn't publish board-level TPP/TGP — both
    stay ``vendor-doesn't-publish``.
    """
    if not options:
        return None
    by_label: dict[Optional[str], list[Bundle]] = {}
    label_order: list[Optional[str]] = []
    seen_gpu_names: dict[Optional[str], set[str]] = {}
    for piece in options:
        m = _GPU_NAME_RE.search(piece)
        if m is not None:
            canonical = _canonicalize_gpu(m.group(1))
            label = h.lookup_board(canonical)
            gpu_bundle = _scraped_bundle(
                canonical,
                source_url,
                captured_at,
                # Unmapped GPU → flag the GPU bundle for review per
                # Decision 5. Catalog auto-add will still fire via the
                # existing ``new_chip_unverified`` queue.
                status="verified" if label is not None else "needs-review",
            )
            name = canonical
        else:
            label = None
            name = _normalize_ws(piece)
            gpu_bundle = _scraped_bundle(
                name, source_url, captured_at, status="needs-review"
            )
        if label not in by_label:
            by_label[label] = []
            label_order.append(label)
            seen_gpu_names[label] = set()
        # Within one tile multiple options often name the same GPU; dedupe.
        if name in seen_gpu_names[label]:
            continue
        seen_gpu_names[label].add(name)
        by_label[label].append(gpu_bundle)

    boards: OfferingsList = []
    for label in label_order:
        if label is None:
            label_bundle: Bundle = _scraped_bundle(
                None, source_url, captured_at, status="needs-review"
            )
        else:
            label_bundle = _scraped_bundle(label, source_url, captured_at)
        boards.append(
            {
                "label": label_bundle,
                "tpp_max": _vdp_bundle(source_url, captured_at),
                "tgp_max": _vdp_bundle(source_url, captured_at),
                "gpus": by_label[label],
            }
        )
    return boards or None


def _canonicalize_gpu(raw: str) -> str:
    """Strip "NVIDIA GeForce" prefix; keep "RTX 5090"."""
    cleaned = _normalize_ws(raw)
    cleaned = re.sub(r"^(NVIDIA\s+GeForce\s+)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(AMD\s+)", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Memory (HP doesn't carry a dedicated Memory key on gaming PDPs;
# RAM size comes from the combined PG&M string)
# ---------------------------------------------------------------------------


# Pull "16 GB(onboard)" / "32 GB" / "64GB" tokens out of the PG&M line.
_PGM_RAM_RE = re.compile(r"(\d{1,3})\s*GB\b", re.IGNORECASE)


def _populate_memory(
    cand: CandidateProduct,
    options: list[str],
    source_url: str,
    captured_at: str,
) -> None:
    if not options:
        # No Memory or PG&M key → record we checked.
        cand.memory_max_gb = _vdp_bundle(source_url, captured_at)
        cand.memory_speed_mts = _vdp_bundle(source_url, captured_at)
        cand.memory_slots = _vdp_bundle(source_url, captured_at)
        cand.memory_type = _vdp_bundle(source_url, captured_at)
        cand.memory_overclocking = _vdp_bundle(source_url, captured_at)
        return

    capacities: list[int] = []
    onboard_seen = False
    for piece in options:
        for m in _PGM_RAM_RE.finditer(piece):
            try:
                capacities.append(int(m.group(1)))
            except ValueError:
                pass
        if "onboard" in piece.lower() or "soldered" in piece.lower():
            onboard_seen = True
    max_gb = max(capacities) if capacities else None
    cand.memory_max_gb = _maybe_bundle(max_gb, source_url, captured_at)

    # HP gaming PDPs almost never publish memory speed / type / OC support
    # in a structured form — record we checked.
    cand.memory_speed_mts = _vdp_bundle(source_url, captured_at)
    cand.memory_type = _vdp_bundle(source_url, captured_at)
    cand.memory_overclocking = _vdp_bundle(source_url, captured_at)

    # Onboard / soldered → 0 slots; otherwise we don't know.
    if onboard_seen:
        cand.memory_slots = _scraped_bundle(0, source_url, captured_at)
    else:
        cand.memory_slots = _vdp_bundle(source_url, captured_at)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


_STORAGE_GEN_RE = re.compile(
    r"(?:PCIe\s*Gen\s*(\d)|Gen\s*(\d)\s*PCIe|PCIe\s*(\d)|Gen(\d))",
    re.IGNORECASE,
)
# HP shorthand "(4x4 SSD)" / "(5x4 SSD)" — first digit = PCIe gen, second
# = lane count. We only need the gen, so capture the leading digit.
_STORAGE_HP_LANES_RE = re.compile(r"\((\d)\s*x\s*\d\s*SSD\)", re.IGNORECASE)


def _build_storage_slots(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = h.split_options(_strip_tm(_strip_footnotes(text)))
    slots: OfferingsList = []
    for piece in pieces:
        m = _STORAGE_GEN_RE.search(piece)
        gen: Optional[int] = None
        if m is not None:
            for g in m.groups():
                if g is not None:
                    try:
                        gen = int(g)
                    except ValueError:
                        gen = None
                    break
        if gen is None:
            m2 = _STORAGE_HP_LANES_RE.search(piece)
            if m2 is not None:
                try:
                    gen = int(m2.group(1))
                except ValueError:
                    gen = None
        slots.append({"gen": _maybe_bundle(gen, source_url, captured_at)})
    return slots or None


_STORAGE_TB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*TB\b", re.IGNORECASE)
_STORAGE_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*GB\b", re.IGNORECASE)


def _build_storage_max_gb(
    text: str, source_url: str, captured_at: str
) -> Bundle:
    """Extract the maximum published storage capacity, in GB.

    Same logic as Dell: collect every TB / GB token; 1 TB → 1000 GB; the
    largest wins. ``vendor-doesn't-publish`` when the Storage key existed
    but no capacity number could be parsed.
    """
    capacities_gb: list[float] = []
    cleaned = _strip_footnotes(text)
    for m in _STORAGE_TB_RE.finditer(cleaned):
        try:
            capacities_gb.append(float(m.group(1)) * 1000)
        except ValueError:
            pass
    for m in _STORAGE_GB_RE.finditer(cleaned):
        try:
            capacities_gb.append(float(m.group(1)))
        except ValueError:
            pass
    if not capacities_gb:
        return _vdp_bundle(source_url, captured_at)
    max_gb = max(capacities_gb)
    value: Any = int(max_gb) if max_gb == int(max_gb) else max_gb
    return _scraped_bundle(value, source_url, captured_at)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


_DCI_P3_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*DCI[- ]?P3", re.IGNORECASE)
_SRGB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*sRGB", re.IGNORECASE)
_HDR_RE = re.compile(
    r"(HDR\s*\d{3,4}|DisplayHDR(?:\s+True\s+Black)?(?:\s+\d{3,4})?|VESA\s+HDR\s*\d+)",
    re.IGNORECASE,
)
_VRR_RE = re.compile(r"(G[- ]?SYNC|FreeSync|Adaptive[- ]?Sync)", re.IGNORECASE)
_PANEL_RE = re.compile(
    r"\b(IPS-level|IPS|OLED|mini[- ]?LED|TN|VA|LCD)\b", re.IGNORECASE
)
_RES_LABEL_RE = re.compile(
    r"\b(QHD\+?|UHD\+?|FHD\+?|WUXGA|WQXGA|WQUXGA|2\.5K|3K|4K)\b",
    re.IGNORECASE,
)
# HP publishes "48-120 Hz" (VRR range) — pick the maximum.
_HZ_RANGE_RE = re.compile(r"(\d{2,4})\s*-\s*(\d{2,4})\s*Hz\b", re.IGNORECASE)
# HP publishes peak nits as "HDR 500 nits" — prefer the HDR figure if both
# SDR and HDR are listed; otherwise fall back to any nits token.
_HDR_NITS_RE = re.compile(r"HDR\s*(\d{2,4})\s*nits?\b", re.IGNORECASE)


def _build_display_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = h.split_options(_strip_tm(_strip_footnotes(text)))
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces):
        offerings.append(_parse_one_display(piece, idx, source_url, captured_at))
    return offerings or None


def _parse_one_display(
    piece: str, idx: int, source_url: str, captured_at: str
) -> dict[str, Bundle]:
    out: dict[str, Bundle] = {}

    out["size_inches"] = _maybe_bundle(h.parse_inches(piece), source_url, captured_at)

    label_m = _RES_LABEL_RE.search(piece)
    out["resolution_label"] = _maybe_bundle(
        label_m.group(1).upper() if label_m else None, source_url, captured_at
    )
    out["resolution_pixels"] = _maybe_bundle(
        h.parse_resolution_pixels(piece), source_url, captured_at
    )

    # HP publishes refresh as "48-120 Hz" (VRR range) — take the high end.
    hz_range_m = _HZ_RANGE_RE.search(piece)
    if hz_range_m is not None:
        try:
            refresh_val: Optional[int] = int(hz_range_m.group(2))
        except ValueError:
            refresh_val = None
    else:
        refresh_val = h.parse_hz(piece)
    out["refresh_rate_hz"] = _maybe_bundle(refresh_val, source_url, captured_at)

    # Prefer HDR nits over SDR nits when both are listed.
    hdr_nits_m = _HDR_NITS_RE.search(piece)
    if hdr_nits_m is not None:
        try:
            nits_val: Optional[int] = int(hdr_nits_m.group(1))
        except ValueError:
            nits_val = None
    else:
        nits_val = h.parse_nits(piece)
    out["nits_peak"] = _maybe_bundle(nits_val, source_url, captured_at)

    out["response_time_ms"] = _maybe_bundle(h.parse_ms(piece), source_url, captured_at)

    panel_m = _PANEL_RE.search(piece)
    if panel_m is not None:
        canonical = _canonical_panel(panel_m.group(1))
        out["panel_type"] = _scraped_bundle(canonical, source_url, captured_at)
    else:
        out["panel_type"] = _vdp_bundle(source_url, captured_at)

    hdr_m = _HDR_RE.search(piece)
    out["hdr_certification"] = _maybe_bundle(
        _normalize_ws(hdr_m.group(1)) if hdr_m else None,
        source_url,
        captured_at,
    )

    dci_m = _DCI_P3_RE.search(piece)
    out["dci_p3_pct"] = _maybe_bundle(
        float(dci_m.group(1)) if dci_m else None, source_url, captured_at
    )
    srgb_m = _SRGB_RE.search(piece)
    out["srgb_pct"] = _maybe_bundle(
        float(srgb_m.group(1)) if srgb_m else None, source_url, captured_at
    )

    vrr_m = _VRR_RE.search(piece)
    if vrr_m is not None:
        out["vrr"] = _scraped_bundle(
            _canonical_vrr(vrr_m.group(1)), source_url, captured_at
        )
    else:
        out["vrr"] = _vdp_bundle(source_url, captured_at)

    low = piece.lower()
    if "anti-glare" in low or "anti glare" in low or "matte" in low:
        anti = "matte"
    elif "glossy" in low:
        anti = "glossy"
    else:
        anti = None
    out["anti_glare"] = _maybe_bundle(anti, source_url, captured_at)

    out["tier"] = _scraped_bundle(h.tier_for_index(idx), source_url, captured_at)
    return out


def _canonical_panel(raw: str) -> str:
    s = raw.strip().lower().replace(" ", "-")
    if s in {"ips", "oled", "tn", "va", "lcd"}:
        return s.upper() if s != "lcd" else "LCD"
    if s in {"mini-led", "miniled"}:
        return "mini-LED"
    if s == "ips-level":
        return "IPS-level"
    return raw.strip()


def _canonical_vrr(raw: str) -> str:
    s = raw.strip().lower().replace(" ", "").replace("-", "")
    if "gsync" in s:
        return "G-Sync"
    if "freesync" in s:
        return "FreeSync"
    if "adaptivesync" in s:
        return "Adaptive Sync"
    return raw.strip()


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------


def _build_battery_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = h.split_options(_strip_footnotes(text))
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces):
        offerings.append(
            {
                "wattage_wh": _maybe_bundle(
                    h.parse_wh(piece), source_url, captured_at
                ),
                "cell_count": _maybe_bundle(
                    h.parse_cell_count(piece), source_url, captured_at
                ),
                "tier": _scraped_bundle(
                    h.tier_for_index(idx), source_url, captured_at
                ),
            }
        )
    return offerings or None


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


_WIFI_RE = re.compile(
    r"(Wi[- ]?Fi\s*\d(?:E)?|Wi[- ]?Fi\s*\d|802\.11(?:ax|be|ac))",
    re.IGNORECASE,
)
_BT_RE = re.compile(r"Bluetooth\s*([\d\.]+)", re.IGNORECASE)
_ETHERNET_RE = re.compile(
    r"(10\s*GbE|5\s*GbE|2\.5\s*GbE|2\.5\s*Gigabit|1\s*GbE|Gigabit\s*Ethernet)",
    re.IGNORECASE,
)


def _populate_network(
    cand: CandidateProduct,
    wireless_text: Optional[str],
    ports_text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    wifi_val: Optional[str] = None
    bt_val: Optional[str] = None
    if wireless_text:
        # HP often lists a base + optional pair (Wi-Fi 6E / Wi-Fi 7).
        # We pick the highest published Wi-Fi standard and Bluetooth
        # version across all listed options as the platform capability.
        cleaned = _strip_tm(_strip_footnotes(wireless_text))
        wifi_candidates: list[str] = []
        bt_candidates: list[str] = []
        for line in re.split(r"[\n;]+", cleaned):
            mw = _WIFI_RE.search(line)
            if mw is not None:
                wifi_candidates.append(_canonical_wifi(mw.group(1)))
            mb = _BT_RE.search(line)
            if mb is not None:
                bt_candidates.append(mb.group(1))
        if wifi_candidates:
            wifi_val = _highest_wifi(wifi_candidates)
        if bt_candidates:
            bt_val = max(bt_candidates, key=_bt_sort_key)
    cand.wifi_standard = _maybe_bundle(wifi_val, source_url, captured_at)
    cand.bluetooth_version = _maybe_bundle(bt_val, source_url, captured_at)

    eth_val: Optional[str] = None
    if ports_text:
        cleaned_ports = _strip_tm(_strip_footnotes(ports_text))
        eth_line: Optional[str] = None
        for raw_line in re.split(r"[\n;]+", cleaned_ports):
            low = raw_line.lower()
            if "rj45" in low or "ethernet" in low:
                eth_line = raw_line
                break
        if eth_line is not None:
            m = _ETHERNET_RE.search(eth_line)
            if m is not None:
                eth_val = _canonical_ethernet(m.group(1))
            else:
                eth_val = "1GbE"
        else:
            eth_val = "none"
    cand.ethernet = _maybe_bundle(eth_val, source_url, captured_at)


_WIFI_RANK = {
    "Wi-Fi 7": 7,
    "Wi-Fi 6E": 6.5,
    "Wi-Fi 6": 6,
    "Wi-Fi 5": 5,
}


def _highest_wifi(values: list[str]) -> str:
    best = values[0]
    best_rank = _WIFI_RANK.get(best, 0)
    for v in values[1:]:
        r = _WIFI_RANK.get(v, 0)
        if r > best_rank:
            best = v
            best_rank = r
    return best


def _bt_sort_key(s: str) -> tuple[int, ...]:
    # "5.4" → (5, 4); "5" → (5,); used to pick the highest Bluetooth ver.
    parts: list[int] = []
    for tok in s.split("."):
        try:
            parts.append(int(tok))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _canonical_wifi(raw: str) -> str:
    s = raw.strip().lower().replace("-", "").replace(" ", "")
    if "wifi7" in s or "802.11be" in s:
        return "Wi-Fi 7"
    if "wifi6e" in s:
        return "Wi-Fi 6E"
    if "wifi6" in s or "802.11ax" in s:
        return "Wi-Fi 6"
    if "wifi5" in s or "802.11ac" in s:
        return "Wi-Fi 5"
    return raw.strip()


def _canonical_ethernet(raw: str) -> str:
    s = raw.lower()
    if "10" in s and "gbe" in s:
        return "10GbE"
    if "5" in s and "gbe" in s and "2.5" not in s:
        return "5GbE"
    if "2.5" in s:
        return "2.5GbE"
    if "gigabit" in s or "1gbe" in s or "rj45" in s:
        return "1GbE"
    return raw.strip()


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _populate_io(
    cand: CandidateProduct,
    text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    if text is None:
        return

    counts = _io_counts(text)
    cand.usbc_thunderbolt_count = _maybe_bundle(
        counts["tb_count"], source_url, captured_at
    )
    cand.usbc_thunderbolt_version = _maybe_bundle(
        counts["tb_version"], source_url, captured_at
    )
    cand.usbc_non_thunderbolt_count = _maybe_bundle(
        counts["usbc_count"], source_url, captured_at
    )
    # USB-C version: when HP labels the port by signaling rate, only the
    # rates with a single unambiguous USB-IF mapping are emitted as
    # ``verified``. 20Gbps / 80Gbps / unrecognized speed wording attach the
    # best-guess version with ``status: 'needs-review'`` so the runner queues
    # it (Decision: "translate, but flag for review when uncertain").
    if counts["usbc_version"] is None:
        cand.usbc_non_thunderbolt_version = _vdp_bundle(source_url, captured_at)
    else:
        cand.usbc_non_thunderbolt_version = _scraped_bundle(
            counts["usbc_version"],
            source_url,
            captured_at,
            status=counts["usbc_version_status"],
        )
    cand.usba_count = _maybe_bundle(counts["usba_count"], source_url, captured_at)
    cand.usba_version = _maybe_bundle(
        counts["usba_version"], source_url, captured_at
    )
    cand.hdmi_count = _maybe_bundle(counts["hdmi_count"], source_url, captured_at)
    cand.hdmi_version = _maybe_bundle(
        counts["hdmi_version"], source_url, captured_at
    )
    cand.sd_card = _maybe_bundle(counts["sd_card"], source_url, captured_at)
    cand.sd_card_speed = _maybe_bundle(
        counts["sd_card_speed"], source_url, captured_at
    )
    cand.audio_jack = _maybe_bundle(counts["audio_jack"], source_url, captured_at)


def _io_counts(text: str) -> dict[str, Any]:
    """Walk the per-line External I/O Ports list and bucket each line."""
    text = _strip_tm(_strip_footnotes(text))
    out: dict[str, Any] = {
        "tb_count": 0,
        "tb_version": None,
        "usbc_count": 0,
        "usbc_version": None,
        "usbc_version_status": "verified",
        "usba_count": 0,
        "usba_version": None,
        "hdmi_count": 0,
        "hdmi_version": None,
        "sd_card": "none",
        "sd_card_speed": None,
        "audio_jack": "none",
    }
    line_count_re = re.compile(r"^\s*(\d+)\s+(.*)$", re.IGNORECASE)
    for raw_line in re.split(r"[\n;]+", text):
        line = raw_line.strip()
        if not line:
            continue
        m = line_count_re.match(line)
        if m is not None:
            try:
                count = int(m.group(1))
            except ValueError:
                count = 1
            body = m.group(2)
        else:
            count = 1
            body = line
        low = body.lower()

        if "thunderbolt" in low:
            out["tb_count"] += count
            tbv = _extract_tb_version(low)
            if tbv:
                out["tb_version"] = tbv
            continue

        if "type-c" in low or "type c" in low or "usb-c" in low or "usb c" in low:
            out["usbc_count"] += count
            ver_pair = _extract_usbc_version(low)
            if ver_pair is not None:
                out["usbc_version"], out["usbc_version_status"] = ver_pair
            continue

        if "type-a" in low or "type a" in low:
            out["usba_count"] += count
            ver = _extract_usba_version(low)
            if ver:
                out["usba_version"] = ver
            continue

        if "hdmi" in low:
            out["hdmi_count"] += count
            hv = _extract_hdmi_version(low)
            if hv:
                out["hdmi_version"] = hv
            continue

        if "sd" in low and ("card" in low or "slot" in low or "reader" in low):
            if "microsd" in low or "micro sd" in low or "micro-sd" in low:
                out["sd_card"] = "microSD"
            else:
                out["sd_card"] = "SD"
            speed_m = re.search(r"\b(UHS-?II?I?)\b", body, re.IGNORECASE)
            if speed_m is not None:
                out["sd_card_speed"] = speed_m.group(1).upper()
            continue

        if (
            "headset" in low
            or "headphone" in low
            or "microphone" in low
            or "audio" in low
            or "combo" in low
        ):
            if "combo" in low:
                out["audio_jack"] = "combo"
            elif "separate" in low:
                out["audio_jack"] = "separate"
            else:
                # HP's "headphone/microphone combo" line lacks the literal
                # word "combo" sometimes; default to combo when both
                # headphone and microphone show up on one line.
                if "headphone" in low and "microphone" in low:
                    out["audio_jack"] = "combo"
                else:
                    out["audio_jack"] = "combo"
            continue

    return out


def _extract_tb_version(low: str) -> Optional[str]:
    for k in ("thunderbolt 5", "thunderbolt5", "tb5"):
        if k in low:
            return "TB5"
    for k in ("thunderbolt 4", "thunderbolt4", "tb4"):
        if k in low:
            return "TB4"
    for k in ("thunderbolt 3", "thunderbolt3", "tb3"):
        if k in low:
            return "TB3"
    return None


# HP labels USB-C ports by signaling rate ("10Gbps", "40Gbps") instead of
# the explicit "USB 3.2 Gen 2" / "USB4" version Dell uses. We map the rate
# to the closest USB-IF version label so catalog comparisons across
# vendors stay aligned.
#
# Returns ``(version, status)``. Status is ``"verified"`` only for
# unambiguous rates / explicit version wording; ambiguous rates (20Gbps,
# 80Gbps) attach a best-guess version with ``"needs-review"`` so the
# runner queues it for manual confirmation.
def _extract_usbc_version(low: str) -> Optional[tuple[str, str]]:
    if "usb4" in low or "usb 4" in low:
        return "USB4", "verified"
    if "40gbps" in low:
        # 40Gbps on USB-C without a Thunderbolt label means USB4 (TB lines
        # are siphoned off earlier in _io_counts).
        return "USB4", "verified"
    if "10gbps" in low:
        return "USB 3.2 Gen 2", "verified"
    if "5gbps" in low:
        return "USB 3.2 Gen 1", "verified"
    if "3.2 gen 2" in low or "gen 2" in low:
        return "USB 3.2 Gen 2", "verified"
    if "3.2 gen 1" in low or "gen 1" in low:
        return "USB 3.2 Gen 1", "verified"
    if "20gbps" in low:
        # USB 3.2 Gen 2x2 is rare on laptops; 20Gbps could also be early
        # USB4 wording on some HP families. Flag for human review.
        return "USB 3.2 Gen 2x2", "needs-review"
    if "80gbps" in low:
        # USB4 v2 / TB5 share 80Gbps; without explicit wording we can't
        # decide. Flag for human review.
        return "USB4", "needs-review"
    return None


def _extract_usba_version(low: str) -> Optional[str]:
    if "10gbps" in low:
        return "USB 3.2 Gen 2"
    if "5gbps" in low:
        return "USB 3.2 Gen 1"
    if "3.2 gen 2" in low or "gen 2" in low:
        return "USB 3.2 Gen 2"
    if "3.2 gen 1" in low or "gen 1" in low:
        return "USB 3.2 Gen 1"
    return None


def _extract_hdmi_version(low: str) -> Optional[str]:
    if "2.1" in low:
        return "2.1"
    if "2.0" in low:
        return "2.0"
    return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def _build_adapter_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = h.split_options(_strip_tm(_strip_footnotes(text)))
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces):
        offerings.append(
            {
                "wattage_w": _maybe_bundle(
                    h.parse_watts(piece), source_url, captured_at
                ),
                "tier": _scraped_bundle(
                    h.tier_for_index(idx), source_url, captured_at
                ),
            }
        )
    return offerings or None


def _detect_adapter_connector(text: str) -> Optional[str]:
    low = (text or "").lower()
    if "usb type-c" in low or "usb-c" in low or "type c" in low or "type-c" in low:
        return "USB-C PD"
    if "barrel" in low:
        return "barrel"
    return None


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------


_CAM_RES_RE = re.compile(r"\b(720p|1080p|1440p|4K|FHD|HD|UHD)\b", re.IGNORECASE)


def _build_camera_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = h.split_options(_strip_tm(_strip_footnotes(text)))
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces):
        low = piece.lower()
        m = _CAM_RES_RE.search(piece)
        res_val: Optional[str] = None
        if m is not None:
            label = m.group(1).lower()
            if label == "fhd":
                res_val = "1080p"
            elif label == "hd":
                res_val = "720p"
            elif label in ("uhd", "4k"):
                res_val = "4K"
            else:
                res_val = label
        ir_val = bool(
            "ir camera" in low or "windows hello" in low or " ir " in low
        )
        shutter_val = bool("shutter" in low)
        offerings.append(
            {
                "resolution": _maybe_bundle(res_val, source_url, captured_at),
                "ir_supported": _scraped_bundle(ir_val, source_url, captured_at),
                "privacy_shutter": _scraped_bundle(
                    shutter_val, source_url, captured_at
                ),
                "tier": _scraped_bundle(
                    h.tier_for_index(idx), source_url, captured_at
                ),
            }
        )
    return offerings or None


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


_SPEAKER_COUNT_RE = re.compile(
    r"(\d+)\s*(?:[xX×])\s*\d+\s*W"
    r"|(\d+)\s+speakers?"
    r"|\b(dual)\s+speakers?\b"
    r"|\b(quad)\s+speakers?\b",
    re.IGNORECASE,
)
_TUNING_BRANDS = (
    ("Dolby Atmos", "Dolby Atmos"),
    ("Dolby", "Dolby Atmos"),
    ("Bang & Olufsen", "B&O"),
    ("B&O", "B&O"),
    ("Harman/Kardon", "Harman"),
    ("Harman", "Harman"),
    ("JBL", "JBL"),
    ("DTS:X", "DTS"),
    ("DTS", "DTS"),
)


def _populate_audio(
    cand: CandidateProduct,
    text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    speakers: Optional[int] = None
    tuning: Optional[str] = None
    subwoofer: Optional[bool] = None
    if text:
        cleaned = _strip_tm(_strip_footnotes(text))
        m = _SPEAKER_COUNT_RE.search(cleaned)
        if m is not None:
            num_g = m.group(1) or m.group(2)
            if num_g is not None:
                try:
                    speakers = int(num_g)
                except (TypeError, ValueError):
                    speakers = None
            elif m.group(3):  # "dual speakers"
                speakers = 2
            elif m.group(4):  # "quad speakers"
                speakers = 4
        for needle, label in _TUNING_BRANDS:
            if needle.lower() in cleaned.lower():
                tuning = label
                break
        subwoofer = "subwoofer" in cleaned.lower() or "woofer" in cleaned.lower()
    cand.speaker_count = _maybe_bundle(speakers, source_url, captured_at)
    cand.tuning_brand = _maybe_bundle(tuning, source_url, captured_at)
    cand.has_subwoofer = (
        _scraped_bundle(subwoofer, source_url, captured_at)
        if subwoofer is not None
        else _vdp_bundle(source_url, captured_at)
    )


# ---------------------------------------------------------------------------
# Keyboard
# ---------------------------------------------------------------------------


def _build_keyboard_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = h.split_options(_strip_footnotes(text))
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces):
        low = piece.lower()
        if "no numpad" in low or "no numeric" in low:
            has_numpad: Optional[bool] = False
        elif "numpad" in low or "numeric keypad" in low or "num pad" in low:
            has_numpad = True
        else:
            has_numpad = None
        offerings.append(
            {
                "description": _scraped_bundle(piece, source_url, captured_at),
                "has_numpad": (
                    _scraped_bundle(has_numpad, source_url, captured_at)
                    if has_numpad is not None
                    else _vdp_bundle(source_url, captured_at)
                ),
                "tier": _scraped_bundle(
                    h.tier_for_index(idx), source_url, captured_at
                ),
            }
        )
    return offerings or None


# ---------------------------------------------------------------------------
# Dimensions / Weight
# ---------------------------------------------------------------------------


# HP publishes dimensions as ``"12.32 x 9.19 x 0.67 in (front)"``. The
# numbers are W x D x H in inches; mm has to be derived. Some product
# lines list a min/max H pair on two lines (front / rear).
_DIM_LINE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*in",
    re.IGNORECASE,
)


def _populate_dimensions(
    cand: CandidateProduct,
    dim_text: Optional[str],
    weight_text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    if dim_text is not None:
        widths_in: list[float] = []
        depths_in: list[float] = []
        heights_in: list[float] = []
        for m in _DIM_LINE_RE.finditer(_strip_footnotes(dim_text)):
            try:
                widths_in.append(float(m.group(1)))
                depths_in.append(float(m.group(2)))
                heights_in.append(float(m.group(3)))
            except ValueError:
                pass
        if widths_in:
            cand.width_mm = _maybe_bundle(
                round(max(widths_in) * 25.4, 2), source_url, captured_at
            )
            cand.depth_mm = _maybe_bundle(
                round(max(depths_in) * 25.4, 2), source_url, captured_at
            )
            if len(heights_in) >= 2:
                cand.height_mm_min = _maybe_bundle(
                    round(min(heights_in) * 25.4, 2), source_url, captured_at
                )
                cand.height_mm_max = _maybe_bundle(
                    round(max(heights_in) * 25.4, 2), source_url, captured_at
                )
            else:
                cand.height_mm_min = _maybe_bundle(
                    None, source_url, captured_at
                )
                cand.height_mm_max = _maybe_bundle(
                    round(heights_in[0] * 25.4, 2), source_url, captured_at
                )

    if weight_text is not None:
        cleaned = _strip_footnotes(weight_text)
        # HP often publishes only one weight ("3.6 lb"); use the
        # single-value rule for weight: that goes into weight_kg_min.
        kg = h.parse_kg(cleaned)
        lb = h.parse_lb(cleaned)
        if kg is not None:
            cand.weight_kg_min = _maybe_bundle(kg, source_url, captured_at)
        elif lb is not None:
            cand.weight_kg_min = _maybe_bundle(
                round(lb * 0.453592, 2), source_url, captured_at
            )
        else:
            cand.weight_kg_min = _vdp_bundle(source_url, captured_at)
        cand.weight_kg_max = _maybe_bundle(None, source_url, captured_at)
