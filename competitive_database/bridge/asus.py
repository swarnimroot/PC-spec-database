"""ASUS parser: ``ProductSnapshot`` → ``CandidateProduct``.

ASUS publishes its ROG marketing spec page as a flat ``specs: dict[str,
str]`` keyed by the page's ``<h2>`` section titles (single-level keys —
no hierarchical paths like Lenovo, no combined CPU+GPU+RAM line like
HP). Per-SKU variant rows under one h2 are newline-joined inside the
spec value, deduplicated in first-occurrence order — so a key like
``Graphics`` may carry one line ("RTX 5070 Ti …") or multiple lines
when ASUS ships several GPU SKUs.

A few ASUS-specific quirks the parser absorbs:

* The ``I/O Ports`` value lists every port on **one** line, separated
  by spaces (``"1x 3.5mm Combo Audio Jack 1x HDMI 2.1 FRL 2x USB 3.2
  Gen 2 Type-A …"``). Neither HP's per-line nor Lenovo's ``\n``-joined
  shape applies — we tokenize by leading-count anchors (``\bN[xX]\b``)
  and walk the resulting segments.
* The ``Memory`` value's first line is sometimes prose-only
  (``"Support dual channel memory"``) before the actual capacity line.
  We scan every line for a GB token and pick the maximum.
* ASUS publishes per-GPU TGP inside the Graphics row as marketing
  prose: ``"… Manual mode: 1497MHz at 140W* …"``. Manual mode is the
  unlocked ceiling, so we read the manual-mode wattage as the per-GPU
  TGP and collapse to ``tgp_max`` per board (max across the board's
  GPUs), mirroring the Lenovo Session 7 decision. Falls back to the
  Turbo-mode wattage if Manual mode isn't published.
* Dimensions are published in **cm** with H as a tilde range
  (``"35.4 x 24.6 x 1.49 ~ 1.79 cm"``); we convert to mm. Weight is a
  single value (``"1.95 Kg (4.30 lbs)"``) → ``weight_kg_min`` only,
  ``weight_kg_max`` stays ``vendor-doesn't-publish`` (mirrors HP).
* USB-C signaling rate translation follows the HP / Lenovo
  ``(value, status)`` tuple pattern — unambiguous rates land
  ``verified``; ``20Gbps`` / ``80Gbps`` attach a best-guess version
  with ``status: 'needs-review'``.

This module does NOT touch the database.

Status routing (per ARCHITECTURE.md §Provenance shape) matches the
other vendors:

* High confidence → ``status: 'verified'``.
* Regex matched but value smells off → ``status: 'needs-review'`` with
  the value still attached. The runner will queue, not write.
* We looked for the field, ASUS didn't publish → ``status:
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


SCRAPER_ID = "asus.fetch_asus_product"


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def parse(snapshot: ProductSnapshot) -> CandidateProduct:
    """Decode an ASUS snapshot into a :class:`CandidateProduct`.

    The snapshot's ``url``, ``fetched_at``, and ``title`` are used to derive
    identity fields and stamp every emitted bundle.
    """
    specs = dict(snapshot.specs or {})
    captured_at = snapshot.fetched_at.isoformat()
    source_url = snapshot.url

    # --- Identity --------------------------------------------------------
    model_code = _derive_asus_model_code(snapshot.title or "", snapshot.url or "")
    year, year_inferred = h.derive_year(
        snapshot.title or "",
        snapshot.url or "",
        snapshot.fetched_at,
    )

    sub_brand = _derive_asus_sub_brand(snapshot.title or "", snapshot.url or "")
    series = _derive_asus_series(snapshot.title or "", snapshot.url or "")

    # ASUS TUF Intel/AMD merge: family_code groups F/A variants of the
    # same laptop; arch_marker attributes each board to its CPU vendor.
    # Unparseable slugs (e.g., ROG) leave both ``None`` and the runner
    # skips the merge dispatch for this product.
    family_code, arch_marker = _derive_asus_family_and_arch(model_code)

    cand = CandidateProduct(model_code=model_code, year=year)
    cand.year_was_inferred = year_inferred
    cand.family_code = family_code
    if family_code is not None:
        # Single-element list — merge ingest (M4) extends it across
        # snapshots that share the same family_code.
        cand.source_model_codes = [model_code]

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
    cand.brand = _scraped_bundle("ASUS", source_url, captured_at)
    if sub_brand:
        cand.sub_brand = _scraped_bundle(sub_brand, source_url, captured_at)
    if series:
        cand.series = _scraped_bundle(series, source_url, captured_at)

    if year_inferred:
        cand.notes.append(
            f"year={year} inferred from fetched_at; vendor_full_name "
            f"flagged needs-review"
        )

    # --- CPU ------------------------------------------------------------
    cpu_text = specs.get("Processor")
    cand.cpu_offerings = _build_cpu_offerings(cpu_text, source_url, captured_at)

    # --- CPU chip specs (catalog seeding) ------------------------------
    # ASUS publishes NPU TOPS in a dedicated ``Neural Processor`` h2 and
    # core count inside the Processor prose. Both are per-laptop but
    # apply to whichever CPU SKUs the laptop ships with — we attach to
    # every CPU model name in ``cpu_offerings``. ``catalog_resolve``
    # decides whether to seed the catalog cells or queue a conflict.
    npu_text = specs.get("Neural Processor")
    cand.cpu_chip_specs = _build_cpu_chip_specs(
        cand.cpu_offerings, cpu_text, npu_text
    )

    # --- GPU + boards ---------------------------------------------------
    gpu_text = specs.get("Graphics")
    cand.boards = _build_boards(gpu_text, source_url, captured_at)

    # Stamp arch_marker on every board in this snapshot — all boards in
    # one ASUS TUF snapshot share one arch (CPU vendor is a property of
    # the slug, not per-board). Absent when arch_marker is None.
    if arch_marker is not None and cand.boards:
        for board in cand.boards:
            board["arch_marker"] = arch_marker

    # --- Memory ---------------------------------------------------------
    mem_text = specs.get("Memory")
    _populate_memory(cand, mem_text, source_url, captured_at)

    # --- Storage --------------------------------------------------------
    storage_text = specs.get("Storage")
    slots_text = specs.get("Expansion Slots (includes used)") or specs.get(
        "Expansion Slots"
    )
    cand.storage_slots = _build_storage_slots(
        storage_text, slots_text, source_url, captured_at
    )
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
    battery_text = specs.get("Battery")
    cand.battery_offerings = _build_battery_offerings(
        battery_text, source_url, captured_at
    )

    # --- Network --------------------------------------------------------
    wireless_text = specs.get("Network and Communication") or specs.get("Wireless")
    ports_text = specs.get("I/O Ports") or specs.get("Ports")
    _populate_network(cand, wireless_text, ports_text, source_url, captured_at)

    # --- I/O ------------------------------------------------------------
    _populate_io(cand, ports_text, source_url, captured_at)

    # --- Adapter --------------------------------------------------------
    psu_text = specs.get("Power Supply") or specs.get("Power Adapter")
    cand.adapter_offerings = _build_adapter_offerings(
        psu_text, source_url, captured_at
    )
    if psu_text:
        connector = _detect_adapter_connector(psu_text)
        cand.adapter_connector = _maybe_bundle(connector, source_url, captured_at)

    # --- Camera ---------------------------------------------------------
    camera_text = specs.get("Camera")
    cand.camera_offerings = _build_camera_offerings(
        camera_text, source_url, captured_at
    )

    # --- Audio ----------------------------------------------------------
    audio_text = specs.get("Audio")
    _populate_audio(cand, audio_text, source_url, captured_at)

    # --- Keyboard -------------------------------------------------------
    kb_text = specs.get("Keyboard and Touchpad") or specs.get("Keyboard")
    cand.keyboard_offerings = _build_keyboard_offerings(
        kb_text, source_url, captured_at
    )

    # --- Dimensions / Weight -------------------------------------------
    dim_text = specs.get("Dimensions (W x D x H)") or specs.get("Dimensions")
    weight_text = specs.get("Weight")
    _populate_dimensions(cand, dim_text, weight_text, source_url, captured_at)

    # --- Design ---------------------------------------------------------
    # ROG spec pages don't structurally publish A / C / D cover materials —
    # ASUS marketing prose mentions chassis materials in the highlights
    # section, but the h2-anchored spec sheet doesn't carry a dedicated
    # cover-material key. Record we checked.
    cand.a_cover_material = _vdp_bundle(source_url, captured_at)
    cand.c_cover_material = _vdp_bundle(source_url, captured_at)
    cand.d_cover_material = _vdp_bundle(source_url, captured_at)
    cand.thermal_shelf = _vdp_bundle(source_url, captured_at)

    lighting_text = specs.get("Device Lighting")
    cand.lighting = _maybe_bundle(
        lighting_text.strip() if lighting_text else None,
        source_url,
        captured_at,
    )

    # --- Thermals (ASUS doesn't publish these structurally on the spec page)
    cand.thermal_design = _vdp_bundle(source_url, captured_at)
    cand.thermal_material = _vdp_bundle(source_url, captured_at)
    cand.tim = _vdp_bundle(source_url, captured_at)
    cand.fan_count = _vdp_bundle(source_url, captured_at)

    return cand


# ---------------------------------------------------------------------------
# Bundle factories (mirror Dell/HP/Lenovo — kept local to keep the bridge
# import-light and bundle-shape consistent with the docs).
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
# ASUS identity
# ---------------------------------------------------------------------------


# ASUS ROG slugs look like ``rog-zephyrus-g16-2026`` /
# ``rog-strix-scar-18-2025`` / ``rog-flow-z13-2025``. The slug is itself
# the most stable PK token ASUS publishes — there's no Dell-style
# alphanumeric model code on the marketing spec page. We use the URL
# slug as the model_code, which keeps it unique within the (model_code,
# year) PK and matches what the scraper's ``source_id`` already carries.
def _derive_asus_model_code(title: str, url: str) -> str:
    """Pull the model-code token out of an ASUS title or URL.

    The slug from the URL's last path segment (or second-to-last when
    the trailing segment is ``spec`` for ROG or ``techspec`` for
    ``www.asus.com``) is the canonical identity. Falls back to a
    slug-form of the title when no URL is given.
    """
    if url:
        slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
        # Drop the trailing ``/spec`` (ROG) or ``/techspec/`` (www.asus.com TUF/V)
        # marker so the real model slug is preserved.
        if slug in {"spec", "techspec"}:
            slug = url.rstrip("/").rsplit("/", 2)[-2].lower()
        # Strip query / fragment.
        slug = slug.split("?", 1)[0].split("#", 1)[0]
        if slug:
            return slug
    if title:
        return re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-")
    return ""


# ASUS multi-SKU Intel/AMD merge: TUF Gaming publishes Intel and AMD
# variants at distinct URLs (``asus-tuf-gaming-f16-2025`` /
# ``asus-tuf-gaming-a16-2025``); the letter immediately before the size
# digits is the CPU-vendor signal. Stripping it collapses both onto one
# family_code. ROG slugs (``rog-zephyrus-g16-2026``) reuse ``g`` / ``m``
# as series letters (NOT variant markers), so the merge is anchored on
# the family-line prefix — only slugs whose prefix is in
# ``_ASUS_FAMILY_LINE_PREFIXES`` are considered. Adding a new family
# line that uses the F/A convention is a single allowlist append; no
# per-product entries ever needed.
_ASUS_FAMILY_LINE_PREFIXES = (
    "asus-tuf-gaming",
)
_ASUS_VARIANT_SLUG_RE = re.compile(
    r"^(?P<line>"
    + "|".join(re.escape(p) for p in _ASUS_FAMILY_LINE_PREFIXES)
    + r")-(?P<variant>[fa])(?P<size>\d{2})-(?P<year>\d{4})$"
)
_ASUS_VARIANT_TO_ARCH = {"f": "intel", "a": "amd"}


def _derive_asus_family_and_arch(
    model_code: str,
) -> tuple[Optional[str], Optional[str]]:
    """Derive ``(family_code, arch_marker)`` from an ASUS slug-form model_code.

    Matches TUF Gaming F/A pairs (``asus-tuf-gaming-f16-2025`` /
    ``-a16-2025``) and returns the arch-agnostic family_code plus
    ``intel``/``amd`` marker. Returns ``(None, None)`` for slugs that
    don't match a known family-line variant pattern (e.g., ROG slugs,
    where the URL doesn't encode a CPU-vendor signal). Caller leaves
    both fields ``None`` on the candidate; ingest runner skips merge.
    """
    if not model_code:
        return None, None
    m = _ASUS_VARIANT_SLUG_RE.match(model_code)
    if m is None:
        return None, None
    family = f"{m.group('line')}-{m.group('size')}-{m.group('year')}"
    arch_marker = _ASUS_VARIANT_TO_ARCH[m.group("variant")]
    return family, arch_marker


# Sub-brand → recognized name patterns. Order matters: more specific first.
# ROG (Republic of Gamers) is ASUS's gaming flagship; TUF Gaming is the
# entry tier; ProArt and ZenBook are creator / productivity (not gaming
# targets, but the parser must still return something stable if pointed
# at one by accident).
_ASUS_SUB_BRANDS = (
    ("rog", "ROG"),
    ("tuf", "TUF Gaming"),
    ("proart", "ProArt"),
    ("zenbook", "Zenbook"),
    ("vivobook", "Vivobook"),
)


def _derive_asus_sub_brand(title: str, url: str) -> Optional[str]:
    """Return ``"ROG"`` / ``"TUF Gaming"`` / etc. / ``None``.

    ASUS marketing titles consistently lead with the sub-brand for ROG /
    TUF gaming products (``"ROG Zephyrus G16 (2026)"``). Slug form
    carries the same prefix (``rog-zephyrus-…``).
    """
    haystack = ((title or "") + " " + (url or "")).lower()
    for needle, label in _ASUS_SUB_BRANDS:
        if needle in haystack:
            return label
    return None


# Recognized ROG series families. We pair the family name with the
# product's screen-size token (13, 14, 16, 18) where one is published
# in the title or URL — e.g. ``"Zephyrus G16"`` / ``"Strix G18"``.
# Falls back to the family name alone when no size token is present.
# Order: most specific first so ``Zephyrus Duo`` wins over ``Zephyrus``.
_ASUS_SERIES_FAMILIES = (
    "Zephyrus Duo",
    "Zephyrus",
    "Strix Scar",
    "Strix",
    "Flow",
    "TUF",
)
_ASUS_SERIES_SIZE_RE = re.compile(
    r"\b[GA]?(13|14|15|16|17|18)\b",
    re.IGNORECASE,
)


def _derive_asus_series(title: str, url: str) -> Optional[str]:
    """Return e.g. ``"Zephyrus G16"`` / ``"Strix G18"`` / ``"Zephyrus"`` / ``None``.

    The family name comes from the title or URL; the size token is the
    first ``13`` / ``14`` / ``16`` / ``18`` we find following the family.
    Hyphens / underscores in the URL slug carry the same separator force
    as spaces; we collapse them so ``rog-zephyrus-g16-2026`` reads as a
    single phrase.
    """
    haystack_raw = (title or "") + " " + (url or "")
    haystack_norm = re.sub(r"[-_]+", " ", haystack_raw)
    haystack = haystack_norm.lower()
    for family in _ASUS_SERIES_FAMILIES:
        if family.lower() in haystack:
            after = haystack.split(family.lower(), 1)[1]
            m = _ASUS_SERIES_SIZE_RE.search(after)
            if m is not None:
                # Reconstruct the prefix letter (G14/G16/G18) when present;
                # it's the ROG sub-line letter and is part of the canonical
                # series name (``Zephyrus G16`` not ``Zephyrus 16``).
                size_match = re.search(
                    r"\b([gax])(\d{2})\b", after, re.IGNORECASE
                )
                if size_match is not None:
                    return f"{family} {size_match.group(1).upper()}{size_match.group(2)}"
                return f"{family} {m.group(1)}"
            return family
    return None


# ---------------------------------------------------------------------------
# Trademark / whitespace helpers
# ---------------------------------------------------------------------------


_TM_RE = re.compile(r"[®™©]")


def _strip_tm(text: str) -> str:
    return _TM_RE.sub("", text or "")


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------


# Recognized CPU name forms, after stripping trademark symbols. Mirrors
# Dell/HP/Lenovo so catalog keys agree.
_CPU_NAME_RE = re.compile(
    r"(?:Intel\s+)?"
    r"(?:Core\s+(?:Ultra\s+)?(?:[i]?\d{1,2})(?:\s+processor)?\s+\S+(?:\s+Plus)?"
    r"|Core\s+[i]\d-\d{4,5}\w*"
    r"|AMD\s+Ryzen\s+(?:AI\s+)?\d+\s+\S+(?:\s+\d+)?"
    r"|Ryzen\s+(?:AI\s+)?\d+\s+\S+(?:\s+\d+)?)",
    re.IGNORECASE,
)


def _build_cpu_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    """Pull each line's CPU model out of ASUS's Processor value.

    Multiple lines may name the same CPU; we dedupe on the canonical
    CPU name, keeping the first-seen bundle (which carries provenance).

    ASUS sometimes appends NPU-only prose to the CPU line, separated
    by ``;`` (e.g. ``"Intel Core Ultra 9 386H 2.1 GHz; Intel NPU up
    to 50TOPS"``). The NPU clause is not a CPU offering; we drop any
    piece whose only token is an Intel NPU description.
    """
    if text is None:
        return None
    if not text.strip():
        return [{"model": _vdp_bundle(source_url, captured_at)}]
    seen: set[str] = set()
    offerings: OfferingsList = []
    for piece in h.split_options(_strip_tm(text)):
        # Drop NPU-only pieces — ASUS publishes the NPU line separately
        # under the ``Neural Processor`` h2; when it leaks into the
        # Processor key it's marketing prose, not a CPU SKU.
        if _is_npu_only(piece):
            continue
        m = _CPU_NAME_RE.search(piece)
        if m is not None:
            model = _normalize_cpu_model(m.group(0))
            status = "verified"
        else:
            # Couldn't lock down a canonical model — keep the leading
            # token but flag it for review.
            model = _normalize_ws(piece.split(";", 1)[0])
            status = "needs-review"
        if model in seen:
            continue
        seen.add(model)
        offerings.append(
            {"model": _scraped_bundle(model, source_url, captured_at, status=status)}
        )
    return offerings or None


def _is_npu_only(piece: str) -> bool:
    """True when ``piece`` is just an NPU description (``"Intel NPU up to 50TOPS"``).

    Filters NPU prose that ASUS sometimes joins onto the CPU line via
    ``;`` separators. A piece counts as NPU-only when ``NPU`` /
    ``TOPS`` appear and no canonical CPU model regex matches.
    """
    low = piece.lower()
    if "npu" not in low and "tops" not in low:
        return False
    return _CPU_NAME_RE.search(piece) is None


def _normalize_cpu_model(raw: str) -> str:
    """Drop the noise-word "processor" and Intel/AMD prefix so catalog keys agree.

    Mirrors Dell/HP/Lenovo's ``_normalize_cpu_model``. Kept local rather
    than shared so the per-vendor parser stays self-contained.
    """
    s = _normalize_ws(raw)
    s = re.sub(r"^Intel\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^AMD\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+processor\s+", " ", s, flags=re.IGNORECASE)
    return s.strip()


# ASUS publishes NPU TOPS as ``"50TOPS"`` / ``"50 TOPS"`` / ``"up to
# 50TOPS"``. Skip clocks for now — ASUS publishes "up to X GHz" which
# is boost only and ambiguous between base/boost.
_NPU_TOPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*TOPS\b", re.IGNORECASE)
# Cores token inside the Processor prose: ``"... 16 cores, 16 Threads"``
# / ``"24 cores"``. We anchor on the literal word ``cores`` to avoid
# picking up the chip's model number (e.g. ``"285HX"``).
_CORES_RE = re.compile(r"(\d+)\s*cores?\b", re.IGNORECASE)


def _build_cpu_chip_specs(
    cpu_offerings: Optional[OfferingsList],
    cpu_text: Optional[str],
    npu_text: Optional[str],
) -> dict[str, dict[str, Optional[str]]]:
    """Extract chip-level specs from the laptop spec page for catalog seeding.

    ASUS publishes NPU TOPS in the dedicated ``Neural Processor`` h2 and
    core count in the Processor prose. Both apply to the laptop SKU as
    a whole; we attach the same values to every CPU model name listed
    on the page (the runner's catalog resolver per-cell rules handle
    cross-vendor conflicts).

    Returns ``{}`` when no specs were extracted.
    """
    if not cpu_offerings:
        return {}
    npu_val = _extract_asus_npu_tops(npu_text or cpu_text or "")
    cores_val = _extract_asus_cores(cpu_text or "")
    if npu_val is None and cores_val is None:
        return {}
    out: dict[str, dict[str, Optional[str]]] = {}
    for offering in cpu_offerings:
        model_bundle = offering.get("model")
        if not isinstance(model_bundle, dict):
            continue
        model = model_bundle.get("value")
        if not model:
            continue
        specs: dict[str, Optional[str]] = {}
        if npu_val is not None:
            specs["npu_tops"] = npu_val
        if cores_val is not None:
            specs["cores"] = cores_val
        if specs:
            out[str(model)] = specs
    return out


def _extract_asus_npu_tops(text: str) -> Optional[str]:
    """Pull the NPU TOPS number out of an ASUS spec value as a string."""
    if not text:
        return None
    m = _NPU_TOPS_RE.search(text)
    if m is None:
        return None
    raw = m.group(1)
    # Drop trailing ``.0`` so ``50.0`` → ``"50"`` while preserving
    # genuine fractional values.
    try:
        f = float(raw)
        if f == int(f):
            return str(int(f))
        return raw
    except ValueError:
        return raw


def _extract_asus_cores(text: str) -> Optional[str]:
    """Pull the ``N cores`` count out of ASUS's Processor prose."""
    if not text:
        return None
    m = _CORES_RE.search(text)
    if m is None:
        return None
    return m.group(1)


# ---------------------------------------------------------------------------
# GPU / boards
# ---------------------------------------------------------------------------


_GPU_NAME_RE = re.compile(
    r"(NVIDIA\s+GeForce\s+RTX\s*\d+(?:\s*Ti)?(?:\s*SUPER)?"
    r"|RTX\s*\d+(?:\s*Ti)?(?:\s*SUPER)?"
    r"|AMD\s+Radeon\s+RX\s*\d+\w*"
    r"|Intel\s+Arc\s+\w+)",
    re.IGNORECASE,
)


# ASUS publishes per-GPU TGP as marketing prose:
#   "Manual mode: 1497MHz at 140W* (1447MHz Boost Clock+50MHz OC, 115W+25W…)"
#   "Turbo mode: 1497MHz at 125W* …"
# Manual mode is the unlocked ceiling, so we prefer that wattage. The
# regex captures the wattage immediately after ``at`` so we don't pick
# up the parenthetical "115W+25W" Dynamic Boost split.
_TGP_MANUAL_RE = re.compile(
    r"manual\s+mode\s*:\s*[^()]*?at\s+(\d+)\s*W",
    re.IGNORECASE,
)
_TGP_TURBO_RE = re.compile(
    r"turbo\s+mode\s*:\s*[^()]*?at\s+(\d+)\s*W",
    re.IGNORECASE,
)


def _build_boards(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    """Group GPUs in the Graphics value by their static board label.

    Per Decision 5: board labels come from the static ``GPU_TO_BOARD`` map.
    Unmapped GPUs emit a board with ``label: null`` and the GPU bundle
    marked ``needs-review``. ASUS publishes per-GPU TGP inside the row
    as ``Manual mode: … at NW`` (and ``Turbo mode: … at NW``); we read
    Manual mode (the unlocked ceiling) and collapse to ``tgp_max`` per
    board by taking the max — same convention as Lenovo. Status stays
    ``verified`` (the wattage is right there in the published row).
    """
    if text is None:
        return None
    pieces = h.split_options(_strip_tm(text))
    by_label: dict[Optional[str], list[Bundle]] = {}
    label_order: list[Optional[str]] = []
    seen_gpu_names: dict[Optional[str], set[str]] = {}
    tgp_max_by_label: dict[Optional[str], Optional[int]] = {}
    for piece in pieces:
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
            name = _normalize_ws(piece.split(";", 1)[0])
            gpu_bundle = _scraped_bundle(
                name, source_url, captured_at, status="needs-review"
            )

        # Per-GPU TGP: prefer Manual mode (unlocked ceiling). Fall back
        # to Turbo mode wattage if Manual isn't published. ASUS always
        # publishes at least one of the two for ROG laptops.
        tgp_val = _extract_asus_tgp(piece)

        if label not in by_label:
            by_label[label] = []
            label_order.append(label)
            seen_gpu_names[label] = set()
            tgp_max_by_label[label] = None
        if tgp_val is not None:
            cur = tgp_max_by_label[label]
            if cur is None or tgp_val > cur:
                tgp_max_by_label[label] = tgp_val
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
        tgp_max_value = tgp_max_by_label[label]
        if tgp_max_value is None:
            tgp_bundle = _vdp_bundle(source_url, captured_at)
        else:
            tgp_bundle = _scraped_bundle(tgp_max_value, source_url, captured_at)
        boards.append(
            {
                "label": label_bundle,
                "tpp_max": _vdp_bundle(source_url, captured_at),
                "tgp_max": tgp_bundle,
                "gpus": by_label[label],
            }
        )
    return boards or None


def _extract_asus_tgp(piece: str) -> Optional[int]:
    """Extract per-GPU TGP wattage from one Graphics row.

    Prefers ``Manual mode: … at NW`` (unlocked ceiling); falls back to
    ``Turbo mode: … at NW``. Returns ``None`` when neither is present.
    """
    m = _TGP_MANUAL_RE.search(piece)
    if m is None:
        m = _TGP_TURBO_RE.search(piece)
    if m is None:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _canonicalize_gpu(raw: str) -> str:
    """Strip "NVIDIA GeForce" / "AMD Radeon" prefix; keep "RTX 5090"."""
    cleaned = _normalize_ws(raw)
    cleaned = re.sub(r"^(NVIDIA\s+GeForce\s+)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(AMD\s+)", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


_MEM_TYPE_RE = re.compile(r"\b(DDR5|DDR4|LPDDR5X|LPDDR5|LPDDR4X)\b", re.IGNORECASE)
_MEM_GB_RE = re.compile(r"(\d{1,3})\s*GB\b", re.IGNORECASE)
# ASUS publishes memory speed as a bare 4-digit number after the type
# token, with no MT/s unit (``"LPDDR5X 8533"``). The shared
# ``parse_mts`` helper requires the explicit unit, so we have a
# dedicated regex that anchors on the type token.
_MEM_SPEED_AFTER_TYPE_RE = re.compile(
    r"(?:DDR5|DDR4|LPDDR5X|LPDDR5|LPDDR4X)[^\n]*?(\d{4,5})\b",
    re.IGNORECASE,
)


def _populate_memory(
    cand: CandidateProduct,
    text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    """Populate the five memory bundles from ASUS's Memory value.

    ASUS's Memory value sometimes leads with a prose-only line
    (``"Support dual channel memory"``) before the actual capacity
    line; we scan every line for a GB token and pick the maximum.
    Onboard / soldered language → 0 slots.
    """
    if not text:
        cand.memory_max_gb = _vdp_bundle(source_url, captured_at)
        cand.memory_speed_mts = _vdp_bundle(source_url, captured_at)
        cand.memory_slots = _vdp_bundle(source_url, captured_at)
        cand.memory_type = _vdp_bundle(source_url, captured_at)
        cand.memory_overclocking = _vdp_bundle(source_url, captured_at)
        return

    cleaned = _strip_tm(text)
    capacities: list[int] = []
    for m in _MEM_GB_RE.finditer(cleaned):
        try:
            capacities.append(int(m.group(1)))
        except ValueError:
            pass
    max_gb = max(capacities) if capacities else None
    cand.memory_max_gb = _maybe_bundle(max_gb, source_url, captured_at)

    # Try the explicit MT/s / MHz form first, then fall back to ASUS's
    # ``"<TYPE> <speed>"`` shape (``"LPDDR5X 8533"``).
    speed_val = h.parse_mts(cleaned)
    if speed_val is None:
        m_speed = _MEM_SPEED_AFTER_TYPE_RE.search(cleaned)
        if m_speed is not None:
            try:
                speed_val = int(m_speed.group(1))
            except ValueError:
                speed_val = None
    cand.memory_speed_mts = _maybe_bundle(speed_val, source_url, captured_at)

    m = _MEM_TYPE_RE.search(cleaned)
    type_val = m.group(1).upper() if m else None
    cand.memory_type = _maybe_bundle(type_val, source_url, captured_at)

    low = cleaned.lower()
    if "on board" in low or "onboard" in low or "soldered" in low:
        cand.memory_slots = _scraped_bundle(0, source_url, captured_at)
    else:
        # ASUS doesn't publish a slot count on socketed configs in the
        # spec sheet either — record we checked.
        cand.memory_slots = _vdp_bundle(source_url, captured_at)

    # ASUS spec pages don't structurally publish memory overclocking.
    cand.memory_overclocking = _vdp_bundle(source_url, captured_at)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


# ASUS publishes storage gen as ``"PCIe® 4.0 NVMe™"`` / ``"PCIe® 5.0"``.
_STORAGE_GEN_ASUS_RE = re.compile(
    r"PCIe[^,\n]*?(\d)\.0",
    re.IGNORECASE,
)
# Slot-count form: ``"2x M.2 PCIe"`` (in the Expansion Slots key).
_SLOT_COUNT_RE = re.compile(r"(\d+)\s*[xX×]\s*M\.2", re.IGNORECASE)


def _build_storage_slots(
    storage_text: Optional[str],
    slots_text: Optional[str],
    source_url: str,
    captured_at: str,
) -> Optional[OfferingsList]:
    """Build storage_slots offerings from ASUS's two Storage-related keys.

    The ``Storage`` key carries one drive offering per line
    (``"1TB PCIe® 4.0 NVMe™ M.2 Performance SSD"``); each line carries
    its PCIe gen. The ``Expansion Slots (includes used)`` key carries
    the slot count summary (``"2x M.2 PCIe"``). When the slot count
    exceeds the offering count we pad with the lowest-gen offering's
    gen (matches ASUS's "all slots same gen" common case).
    """
    if storage_text is None and slots_text is None:
        return None

    offering_gens: list[Optional[int]] = []
    if storage_text:
        for piece in h.split_options(_strip_tm(storage_text)):
            m = _STORAGE_GEN_ASUS_RE.search(piece)
            gen: Optional[int] = None
            if m is not None:
                try:
                    gen = int(m.group(1))
                except ValueError:
                    gen = None
            offering_gens.append(gen)

    slot_count: Optional[int] = None
    if slots_text:
        m = _SLOT_COUNT_RE.search(slots_text)
        if m is not None:
            try:
                slot_count = int(m.group(1))
            except ValueError:
                slot_count = None

    # Use the slot count when published, otherwise emit one entry per
    # storage offering line.
    if slot_count is not None:
        slots: OfferingsList = []
        # Pad with the first published gen (ASUS pages typically list one
        # gen across all slots) when slot count exceeds offering count.
        fill_gen = offering_gens[0] if offering_gens else None
        for i in range(slot_count):
            gen = offering_gens[i] if i < len(offering_gens) else fill_gen
            slots.append({"gen": _maybe_bundle(gen, source_url, captured_at)})
        return slots or None

    if offering_gens:
        return [
            {"gen": _maybe_bundle(g, source_url, captured_at)} for g in offering_gens
        ] or None

    return None


_STORAGE_TB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*TB\b", re.IGNORECASE)
_STORAGE_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*GB\b", re.IGNORECASE)


def _build_storage_max_gb(
    text: str, source_url: str, captured_at: str
) -> Bundle:
    """Extract the maximum published storage capacity, in GB.

    Same logic as Dell/HP/Lenovo: collect every TB / GB token; 1 TB →
    1000 GB; the largest wins. ``vendor-doesn't-publish`` when the
    Storage key existed but no capacity number could be parsed.
    """
    capacities_gb: list[float] = []
    cleaned = _strip_tm(text)
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


def _build_display_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = h.split_options(_strip_tm(text))
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

    out["refresh_rate_hz"] = _maybe_bundle(
        h.parse_hz(piece), source_url, captured_at
    )
    out["nits_peak"] = _maybe_bundle(h.parse_nits(piece), source_url, captured_at)
    out["response_time_ms"] = _maybe_bundle(
        h.parse_ms(piece), source_url, captured_at
    )

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
    # ASUS often uses "Anti-reflection" wording instead of "anti-glare".
    if (
        "anti-glare" in low
        or "anti glare" in low
        or "matte" in low
        or "anti-reflection" in low
        or "anti reflection" in low
    ):
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


# ASUS publishes battery wattage as ``"90WHrs"`` (no separator, plural
# 'Hrs'). The shared ``parse_wh`` helper expects ``Wh`` / ``Whr`` only;
# we normalize ``WHrs`` → ``Wh`` before parsing so the same regex hits.
_ASUS_WHRS_RE = re.compile(r"WHrs?\b", re.IGNORECASE)


def _build_battery_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    cleaned = _ASUS_WHRS_RE.sub("Wh", _strip_tm(text))
    pieces = h.split_options(cleaned)
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
        cleaned = _strip_tm(wireless_text)
        m = _WIFI_RE.search(cleaned)
        if m is not None:
            wifi_val = _canonical_wifi(m.group(1))
        m = _BT_RE.search(cleaned)
        if m is not None:
            bt_val = m.group(1)
    cand.wifi_standard = _maybe_bundle(wifi_val, source_url, captured_at)
    cand.bluetooth_version = _maybe_bundle(bt_val, source_url, captured_at)

    eth_val: Optional[str] = None
    if ports_text:
        cleaned_ports = _strip_tm(ports_text)
        low_all = cleaned_ports.lower()
        if "rj45" in low_all or "rj-45" in low_all or "ethernet" in low_all:
            m = _ETHERNET_RE.search(cleaned_ports)
            if m is not None:
                eth_val = _canonical_ethernet(m.group(1))
            else:
                eth_val = "1GbE"
        else:
            eth_val = "none"
    cand.ethernet = _maybe_bundle(eth_val, source_url, captured_at)


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


# ASUS's I/O Ports value lists every port on **one** line, separated
# by spaces, each port carrying a leading-count anchor (``1x``, ``2x``).
# We tokenize on those anchors rather than splitting on newlines.
#
# Example: ``"1x 3.5mm Combo Audio Jack 1x HDMI 2.1 FRL 2x USB 3.2 Gen 2
# Type-A 1x USB 3.2 Gen 2 Type-C support DisplayPort™ / power delivery /
# G-SYNC 1x Thunderbolt™ 4 support DisplayPort™ / power delivery 1x card
# reader (SD) (UHS-II, 312MB/s)"``
_ASUS_PORT_TOKEN_RE = re.compile(r"\b(\d+)\s*[xX×]\s+", re.IGNORECASE)


def _split_asus_ports(text: str) -> list[tuple[int, str]]:
    """Split ASUS's single-line I/O Ports value into ``(count, body)`` tuples.

    Each tuple is one port description. The body is everything between
    one count anchor and the next.
    """
    if not text:
        return []
    out: list[tuple[int, str]] = []
    matches = list(_ASUS_PORT_TOKEN_RE.finditer(text))
    for i, m in enumerate(matches):
        try:
            count = int(m.group(1))
        except ValueError:
            count = 1
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            out.append((count, body))
    return out


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
    # USB-C version: explicit USB-IF version wording lands ``verified``;
    # speed-only labels map to the unambiguous USB-IF version (also
    # ``verified``); ``20Gbps`` / ``80Gbps`` attach a best-guess version
    # with ``status: 'needs-review'`` per the (value, status) tuple
    # pattern HP introduced.
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
    """Walk ASUS's ``I/O Ports`` value and bucket each ``Nx`` segment."""
    text = _strip_tm(text)
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
    for count, body in _split_asus_ports(text):
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

        if (
            "card reader" in low
            or ("sd" in low and ("card" in low or "slot" in low or "reader" in low))
        ):
            if "microsd" in low or "micro sd" in low or "micro-sd" in low:
                out["sd_card"] = "microSD"
            else:
                out["sd_card"] = "SD"
            speed_m = re.search(r"\b(UHS-?II?I?)\b", body, re.IGNORECASE)
            if speed_m is not None:
                out["sd_card_speed"] = speed_m.group(1).upper()
            continue

        if (
            "combo audio" in low
            or "headset" in low
            or "headphone" in low
            or "microphone" in low
            or "audio jack" in low
            or "combo" in low
        ):
            if "combo" in low:
                out["audio_jack"] = "combo"
            elif "separate" in low:
                out["audio_jack"] = "separate"
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


# ASUS publishes USB-C wording explicitly (``USB 3.2 Gen 2 Type-C``,
# ``USB4``). Mirrors HP/Lenovo's tuple-returning helper so ambiguous
# rates can be flagged.
def _extract_usbc_version(low: str) -> Optional[tuple[str, str]]:
    if "usb4" in low or "usb 4" in low:
        return "USB4", "verified"
    if "40gbps" in low:
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
        return "USB 3.2 Gen 2x2", "needs-review"
    if "80gbps" in low:
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
    pieces = h.split_options(_strip_tm(text))
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
    # ASUS publishes either "Rectangle Conn" (the flat rectangular plug
    # used on ROG flagships) or "USB Type-C" (USB-C PD). The rectangle
    # connector is distinct from Dell's round-pin barrel and Lenovo's
    # slim-tip; per Session 7 user decision we surface it as its own
    # ``rectangle`` enum value.
    if "usb type-c" in low or "usb-c" in low or "type c" in low or "type-c" in low:
        return "USB-C PD"
    if "rectangle" in low:
        return "rectangle"
    if "barrel" in low:
        return "barrel"
    return None


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------


_CAM_RES_RE = re.compile(
    r"\b(720p|1080p|1440p|4K|FHD|HD|UHD|\d+(?:\.\d+)?\s*MP)\b",
    re.IGNORECASE,
)


def _build_camera_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = h.split_options(_strip_tm(text))
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces):
        low = piece.lower()
        m = _CAM_RES_RE.search(piece)
        res_val: Optional[str] = None
        res_status = "verified"
        if m is not None:
            res_val, res_status = h.normalize_camera_resolution(m.group(1))
        ir_val = bool(
            "ir camera" in low or "windows hello" in low or " ir " in low
        )
        shutter_val = bool("shutter" in low or "e-shutter" in low)
        offerings.append(
            {
                "resolution": _maybe_bundle(
                    res_val, source_url, captured_at, status=res_status
                ),
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
    r"(\d+)[- ]?speaker"
    r"|(\d+)\s+speakers?"
    r"|(\d+)\s*(?:[xX×])\s*\d+\s*W"
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
    ("Nahimic", "Nahimic"),
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
        cleaned = _strip_tm(text)
        m = _SPEAKER_COUNT_RE.search(cleaned)
        if m is not None:
            num_g = m.group(1) or m.group(2) or m.group(3)
            if num_g is not None:
                try:
                    speakers = int(num_g)
                except (TypeError, ValueError):
                    speakers = None
            elif m.group(4):  # "dual speakers"
                speakers = 2
            elif m.group(5):  # "quad speakers"
                speakers = 4
        for needle, label in _TUNING_BRANDS:
            if needle.lower() in cleaned.lower():
                tuning = label
                break
        # ASUS labels the low-frequency drivers as ``"force woofer"`` /
        # ``"dual-force woofer"`` — both treat as subwoofer for our
        # boolean signal.
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
    pieces = h.split_options(_strip_tm(text))
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


# ASUS publishes dimensions in cm with H as a tilde range:
#   ``"35.4 x 24.6 x 1.49 ~ 1.79 cm (13.94" x 9.69" x 0.59" ~ 0.70")"``
# W and D are single numbers; H is either a single number or a
# ``min ~ max`` range.
_DIM_CM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*"
    r"(\d+(?:\.\d+)?)(?:\s*~\s*(\d+(?:\.\d+)?))?\s*cm",
    re.IGNORECASE,
)
# Same shape but in mm (defensive — ASUS may switch units on some
# product lines):
_DIM_MM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*"
    r"(\d+(?:\.\d+)?)(?:\s*~\s*(\d+(?:\.\d+)?))?\s*mm",
    re.IGNORECASE,
)
_WEIGHT_KG_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kg", re.IGNORECASE)


def _populate_dimensions(
    cand: CandidateProduct,
    dim_text: Optional[str],
    weight_text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    if dim_text is not None:
        cleaned = _strip_tm(dim_text)
        # Prefer mm if both happen to be present; default ASUS shape is cm.
        m = _DIM_MM_RE.search(cleaned)
        scale = 1.0
        if m is None:
            m = _DIM_CM_RE.search(cleaned)
            scale = 10.0  # cm → mm
        if m is not None:
            try:
                width = round(float(m.group(1)) * scale, 2)
                depth = round(float(m.group(2)) * scale, 2)
                h_lo = round(float(m.group(3)) * scale, 2)
                h_hi = (
                    round(float(m.group(4)) * scale, 2) if m.group(4) else None
                )
            except ValueError:
                width = depth = h_lo = None
                h_hi = None
            if width is not None:
                cand.width_mm = _maybe_bundle(width, source_url, captured_at)
            if depth is not None:
                cand.depth_mm = _maybe_bundle(depth, source_url, captured_at)
            if h_hi is not None:
                cand.height_mm_min = _maybe_bundle(h_lo, source_url, captured_at)
                cand.height_mm_max = _maybe_bundle(h_hi, source_url, captured_at)
            elif h_lo is not None:
                cand.height_mm_min = _maybe_bundle(None, source_url, captured_at)
                cand.height_mm_max = _maybe_bundle(h_lo, source_url, captured_at)

    if weight_text is not None:
        cleaned = _strip_tm(weight_text)
        m = _WEIGHT_KG_RE.search(cleaned)
        kg: Optional[float] = None
        if m is not None:
            try:
                kg = float(m.group(1))
            except ValueError:
                kg = None
        # ASUS publishes a single weight figure → treat as min weight
        # (mirrors HP/Lenovo's single-value rule).
        if kg is not None:
            cand.weight_kg_min = _maybe_bundle(kg, source_url, captured_at)
            cand.weight_kg_max = _maybe_bundle(None, source_url, captured_at)
        else:
            cand.weight_kg_min = _vdp_bundle(source_url, captured_at)
            cand.weight_kg_max = _vdp_bundle(source_url, captured_at)
