"""Dell parser: ``ProductSnapshot`` → ``CandidateProduct``.

Dell exposes a flat ``specs: dict[str, str]`` (the techspecs payload). We
run a small extractor per DATA_MODEL field over those strings. Multi-
option values within a single key (e.g., ``Display`` with two panel
options separated by ``\\n``) become multiple offerings.

This module does NOT touch the database.

Status routing (per ARCHITECTURE.md §Provenance shape):

* High confidence → ``status: 'verified'``.
* Regex matched but value smells off (out-of-range, ambiguous unit,
  multiple plausible interpretations) → ``status: 'needs-review'`` with
  the value still attached. The runner will queue, not write.
* We looked for the field, Dell didn't publish → ``status:
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


SCRAPER_ID = "dell.fetch_dell_product"


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def parse(snapshot: ProductSnapshot) -> CandidateProduct:
    """Decode a Dell snapshot into a :class:`CandidateProduct`.

    The snapshot's ``url``, ``fetched_at``, and ``title`` are used to derive
    identity fields and stamp every emitted bundle.
    """
    specs = dict(snapshot.specs or {})
    captured_at = snapshot.fetched_at.isoformat()
    source_url = snapshot.url

    # --- Identity --------------------------------------------------------
    model_code = h.derive_dell_model_code(snapshot.url)
    year, year_inferred = h.derive_year(
        snapshot.title or "",
        snapshot.url or "",
        snapshot.fetched_at,
    )

    sub_brand = h.derive_sub_brand(snapshot.title or "", snapshot.url or "")
    series = (
        h.derive_alienware_series(snapshot.title or "", snapshot.url or "")
        if sub_brand == "Alienware"
        else None
    )

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
    cand.brand = _scraped_bundle("Dell", source_url, captured_at)
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
    # Dell publishes core counts inline in the Processor prose
    # (``"... (24-Core, 36MB Cache, ...)"``). Other catalog fields are
    # not consistently published, so we only attempt cores. ``catalog_resolve``
    # decides whether to seed or queue a conflict.
    cand.cpu_chip_specs = _build_cpu_chip_specs(
        cand.cpu_offerings, cpu_text
    )

    # --- GPU + boards ---------------------------------------------------
    gpu_text = specs.get("Graphics Card")
    cand.boards = _build_boards(gpu_text, source_url, captured_at)

    # --- Memory ---------------------------------------------------------
    mem_text = specs.get("Memory")
    _populate_memory(cand, mem_text, source_url, captured_at)

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
    battery_text = specs.get("Battery") or specs.get("Primary Battery")
    cand.battery_offerings = _build_battery_offerings(
        battery_text, source_url, captured_at
    )

    # --- Network --------------------------------------------------------
    wireless_text = specs.get("Wireless")
    _populate_network(cand, wireless_text, specs.get("Ports"), source_url, captured_at)

    # --- I/O ------------------------------------------------------------
    ports_text = specs.get("Ports")
    _populate_io(cand, ports_text, source_url, captured_at)

    # --- Adapter --------------------------------------------------------
    # Dell sometimes ships adapter info as its own key, sometimes only
    # mentions wattage inside "Dimensions & Weight". We accept either.
    psu_text = (
        specs.get("Power Supply")
        or specs.get("Power Adapter")
        or specs.get("Adapter")
    )
    if psu_text is None and (specs.get("Dimensions & Weight") or ""):
        # Pull the wattage line out of dim text if present.
        dim = specs.get("Dimensions & Weight") or ""
        m = re.search(r"(\d+\s*W\s*power adapter)", dim, re.IGNORECASE)
        if m is not None:
            psu_text = m.group(1)
    cand.adapter_offerings = _build_adapter_offerings(
        psu_text, source_url, captured_at
    )
    if psu_text:
        # Dell's psu strings don't reliably indicate the connector type;
        # mark as vendor-doesn't-publish so we record we checked.
        cand.adapter_connector = _vdp_bundle(source_url, captured_at)

    # --- Camera ---------------------------------------------------------
    webcam_text = specs.get("Webcam") or specs.get("Camera")
    cand.camera_offerings = _build_camera_offerings(
        webcam_text, source_url, captured_at
    )

    # --- Audio ----------------------------------------------------------
    audio_text = specs.get("Audio") or specs.get("Audio and Speakers")
    _populate_audio(cand, audio_text, source_url, captured_at)

    # --- Keyboard -------------------------------------------------------
    kb_text = specs.get("Keyboard")
    cand.keyboard_offerings = _build_keyboard_offerings(
        kb_text, source_url, captured_at
    )

    # --- Dimensions / Weight -------------------------------------------
    dim_text = specs.get("Dimensions & Weight") or specs.get("Dimensions")
    _populate_dimensions(cand, dim_text, source_url, captured_at)

    # --- Design ---------------------------------------------------------
    chassis_text = specs.get("Chassis") or specs.get("Materials")
    _populate_design(cand, chassis_text, source_url, captured_at)

    # --- Thermals (Dell rarely publishes these) ------------------------
    cand.thermal_design = _vdp_bundle(source_url, captured_at)
    cand.thermal_material = _vdp_bundle(source_url, captured_at)
    cand.tim = _vdp_bundle(source_url, captured_at)
    cand.fan_count = _vdp_bundle(source_url, captured_at)

    return cand


# ---------------------------------------------------------------------------
# Bundle factories (thin wrappers over db.helpers — kept local to keep the
# bridge import-light and bundle-shape consistent with the docs).
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
# CPU
# ---------------------------------------------------------------------------


# Strip ®, ™, and similar trademark glyphs.
_TM_RE = re.compile(r"[®™©]")


def _strip_tm(text: str) -> str:
    return _TM_RE.sub("", text or "")


# Recognized CPU name forms, after stripping trademark symbols:
#   "Intel Core Ultra 9 285HX"
#   "Intel Core Ultra 9 processor 290HX Plus"
#   "Intel Core i9-14900HX"
#   "AMD Ryzen 9 9955HX3D"
#   "AMD Ryzen AI 9 HX 370"
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
    if text is None:
        return None
    if not text.strip():
        return [
            {"model": _vdp_bundle(source_url, captured_at)},
        ]
    offerings: OfferingsList = []
    for piece in h.split_options(_strip_tm(text)):
        m = _CPU_NAME_RE.search(piece)
        if m is not None:
            model = _normalize_cpu_model(m.group(0))
            status = "verified"
        else:
            # Couldn't lock down a canonical model — keep the raw piece but
            # flag it for review.
            model = _normalize_ws(piece)
            status = "needs-review"
        offerings.append(
            {"model": _scraped_bundle(model, source_url, captured_at, status=status)}
        )
    return offerings or None


def _normalize_cpu_model(raw: str) -> str:
    """Drop the noise-word "processor" and intel prefix so catalog keys agree.

    ``"Intel Core Ultra 9 processor 290HX Plus"`` → ``"Core Ultra 9 290HX Plus"``.
    ``"Intel Core Ultra 9 285HX"`` → ``"Core Ultra 9 285HX"``.
    ``"AMD Ryzen 9 9955HX3D"`` → ``"Ryzen 9 9955HX3D"``.
    """
    s = _normalize_ws(raw)
    s = re.sub(r"^Intel\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^AMD\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+processor\s+", " ", s, flags=re.IGNORECASE)
    return s.strip()


# Dell publishes the core count as ``"24-Core"`` (hyphenated) inside
# the Processor parenthetical, or ``"24 cores"`` in some variants.
# Anchored on the literal word ``core`` to avoid model-number hits.
_DELL_CORES_RE = re.compile(r"(\d+)[- ]?cores?\b", re.IGNORECASE)


def _build_cpu_chip_specs(
    cpu_offerings: Optional[OfferingsList],
    cpu_text: Optional[str],
) -> dict[str, dict[str, Optional[str]]]:
    """Extract chip-level specs from Dell's Processor prose.

    Dell publishes the core count alongside cache + clock range inside
    a parenthetical (``"... (24-Core, 36MB Cache, 2.7GHz to 5.5GHz)"``).
    We attach ``cores`` to whichever CPU the Processor key names. Other
    catalog fields are not consistently published on the techspecs page,
    so we only attempt cores. Returns ``{}`` when nothing was extracted.
    """
    if not cpu_offerings or not cpu_text:
        return {}
    cores_m = _DELL_CORES_RE.search(_strip_tm(cpu_text))
    if cores_m is None:
        return {}
    cores_val = cores_m.group(1)
    out: dict[str, dict[str, Optional[str]]] = {}
    for offering in cpu_offerings:
        model_bundle = offering.get("model")
        if not isinstance(model_bundle, dict):
            continue
        model = model_bundle.get("value")
        if not model:
            continue
        out[str(model)] = {"cores": cores_val}
    return out


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


def _build_boards(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    """Group GPUs in this single tile by their static board label.

    Per Decision 5: board labels come from the static ``GPU_TO_BOARD`` map
    (laptop GPU power tiers), NOT from a per-tile counter. The bridge sees
    one tile at a time; the runner unions boards across tiles by matching
    labels. Unmapped GPUs emit a board with ``label: null`` and the GPU's
    bundle marked ``needs-review`` (no new queue type — the existing
    ``low_confidence_extraction`` path picks it up).
    """
    if text is None:
        return None
    pieces = h.split_options(_strip_tm(text))
    # Group this tile's GPUs by board label so a tile with two power-class
    # GPUs (rare on Dell, common on HP/Lenovo) folds into one entry.
    by_label: dict[Optional[str], list[Bundle]] = {}
    label_order: list[Optional[str]] = []
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
        else:
            # No recognizable model — keep the raw piece as needs-review.
            label = None
            gpu_bundle = _scraped_bundle(
                _normalize_ws(piece),
                source_url,
                captured_at,
                status="needs-review",
            )
        if label not in by_label:
            by_label[label] = []
            label_order.append(label)
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
                # gpus is a list of bundles inside the offering. Storing as
                # a JSON array of bundle dicts keeps the per-leaf provenance
                # structure intact.
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
# Memory
# ---------------------------------------------------------------------------


_MEM_TYPE_RE = re.compile(r"\b(DDR5|DDR4|LPDDR5X|LPDDR5|LPDDR4X)\b", re.IGNORECASE)
_MEM_SLOTS_RE = re.compile(r"(\d+)\s*x\s*\d+\s*GB", re.IGNORECASE)
_MEM_SOLDERED_RE = re.compile(r"\b(soldered|onboard|non-upgradeable)\b", re.IGNORECASE)


def _populate_memory(
    cand: CandidateProduct,
    text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    cand.memory_max_gb = _maybe_bundle(h.parse_gb(text or ""), source_url, captured_at)
    cand.memory_speed_mts = _maybe_bundle(
        h.parse_mts(text or ""), source_url, captured_at
    )

    slots_val: Optional[int] = None
    if text:
        m = _MEM_SLOTS_RE.search(text)
        if m is not None:
            try:
                slots_val = int(m.group(1))
            except ValueError:
                slots_val = None
        if slots_val is None and _MEM_SOLDERED_RE.search(text):
            slots_val = 0
    cand.memory_slots = _maybe_bundle(slots_val, source_url, captured_at)

    type_val: Optional[str] = None
    if text:
        m = _MEM_TYPE_RE.search(text)
        if m is not None:
            type_val = m.group(1).upper()
    cand.memory_type = _maybe_bundle(type_val, source_url, captured_at)

    # Dell virtually never advertises memory overclocking on the techspecs
    # page; record we checked.
    cand.memory_overclocking = _vdp_bundle(source_url, captured_at)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


_STORAGE_GEN_RE = re.compile(
    r"(?:PCIe\s*Gen\s*(\d)|Gen\s*(\d)\s*PCIe|PCIe\s*(\d)|Gen(\d))",
    re.IGNORECASE,
)


def _build_storage_slots(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = h.split_options(text)
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
        slots.append({"gen": _maybe_bundle(gen, source_url, captured_at)})
    return slots or None


# Capacity tokens inside Dell storage strings:
#   "1TB", "2 TB", "4TB SSD", "Up to 4TB", "1024GB", "512 GB"
# 1 TB = 1000 GB by convention; if Dell publishes "1024GB" we keep 1024
# (no silent unit conversion).
_STORAGE_TB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*TB\b", re.IGNORECASE)
_STORAGE_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*GB\b", re.IGNORECASE)


def _build_storage_max_gb(
    text: str, source_url: str, captured_at: str
) -> Bundle:
    """Extract the maximum published storage capacity, in GB.

    Dell strings range from a single capacity token (``"1 TB, M.2, ...``)
    through newline-separated SKU options (``"1TB SSD\\n2TB SSD\\n4TB SSD"``)
    up to "Up to NTB" marketing copy. We collect every capacity token in
    the spec text and return the largest one in GB (1 TB → 1000 GB; GB
    values are taken as-published — see ``1024GB`` note above).

    Status routing:
      * ``verified`` when at least one number was parsed.
      * ``vendor-doesn't-publish`` (``value=None``) when the Storage spec
        existed but no capacity number could be parsed.
    """
    capacities_gb: list[float] = []
    for m in _STORAGE_TB_RE.finditer(text):
        try:
            capacities_gb.append(float(m.group(1)) * 1000)
        except ValueError:
            pass
    for m in _STORAGE_GB_RE.finditer(text):
        try:
            capacities_gb.append(float(m.group(1)))
        except ValueError:
            pass
    if not capacities_gb:
        return _vdp_bundle(source_url, captured_at)
    max_gb = max(capacities_gb)
    # Cast to int when the value is whole (the common case — TB values
    # all round to whole GB; "1024GB" stays an int).
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
    r"\b(QHD\+?|UHD\+?|FHD\+?|WUXGA|WQXGA|WQUXGA|2\.5K|4K|3K)\b",
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
    out["refresh_rate_hz"] = _maybe_bundle(h.parse_hz(piece), source_url, captured_at)
    out["nits_peak"] = _maybe_bundle(h.parse_nits(piece), source_url, captured_at)
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

    if "anti-glare" in piece.lower() or "anti glare" in piece.lower() or "matte" in piece.lower():
        anti = "matte"
    elif "glossy" in piece.lower():
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
    pieces = h.split_options(text)
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
        m = _WIFI_RE.search(wireless_text)
        if m is not None:
            wifi_val = _canonical_wifi(m.group(1))
        m = _BT_RE.search(wireless_text)
        if m is not None:
            bt_val = m.group(1)
    cand.wifi_standard = _maybe_bundle(wifi_val, source_url, captured_at)
    cand.bluetooth_version = _maybe_bundle(bt_val, source_url, captured_at)

    eth_val: Optional[str] = None
    if ports_text:
        # Pick the line that mentions RJ45/Ethernet so we don't grab a
        # speed token from elsewhere in the ports list.
        eth_line: Optional[str] = None
        for raw_line in re.split(r"[\n;]+", ports_text):
            low = raw_line.lower()
            if "rj45" in low or "ethernet" in low:
                eth_line = raw_line
                break
        if eth_line is not None:
            m = _ETHERNET_RE.search(eth_line)
            if m is not None:
                eth_val = _canonical_ethernet(m.group(1))
            else:
                eth_val = "1GbE"  # ethernet present, no speed = assume gigabit
        else:
            # No RJ45 mention at all → genuinely none.
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


def _populate_io(
    cand: CandidateProduct,
    text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    if text is None:
        # We didn't even see a Ports key — nothing to claim.
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
    cand.usbc_non_thunderbolt_version = _maybe_bundle(
        counts["usbc_version"], source_url, captured_at
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
    """Walk the per-line Ports list and bucket each line into a category."""
    text = _strip_tm(text)
    out: dict[str, Any] = {
        "tb_count": 0,
        "tb_version": None,
        "usbc_count": 0,
        "usbc_version": None,
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
            ver = _extract_usbc_version(low)
            if ver:
                out["usbc_version"] = ver
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

        if "headset" in low or "headphone" in low or "audio" in low or "combo" in low:
            if "combo" in low:
                out["audio_jack"] = "combo"
            elif "separate" in low:
                out["audio_jack"] = "separate"
            else:
                out["audio_jack"] = "combo"
            continue

    # If we never saw the relevant category at all, surface as
    # vendor-doesn't-publish for some fields rather than a count of 0.
    if out["tb_version"] is None and out["tb_count"] == 0:
        out["tb_version"] = None
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


def _extract_usbc_version(low: str) -> Optional[str]:
    if "usb4" in low or "usb 4" in low:
        return "USB4"
    if "3.2 gen 2" in low or "gen 2" in low:
        return "USB 3.2 Gen 2"
    if "3.2 gen 1" in low or "gen 1" in low:
        return "USB 3.2 Gen 1"
    return None


def _extract_usba_version(low: str) -> Optional[str]:
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
    pieces = h.split_options(text)
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


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------


_CAM_RES_RE = re.compile(r"\b(720p|1080p|1440p|4K|FHD|HD|UHD)\b", re.IGNORECASE)


def _build_camera_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = h.split_options(text)
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
            elif label == "uhd" or label == "4k":
                res_val = "4K"
            else:
                res_val = label
        ir_val = bool("ir camera" in low or "windows hello" in low or "ir " in low)
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
    r"|(\d+)\s+speakers?",
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
        m = _SPEAKER_COUNT_RE.search(text)
        if m is not None:
            try:
                speakers = int(m.group(1) or m.group(2))
            except (TypeError, ValueError):
                speakers = None
        for needle, label in _TUNING_BRANDS:
            if needle.lower() in text.lower():
                tuning = label
                break
        subwoofer = "subwoofer" in text.lower()
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
    pieces = h.split_options(text)
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces):
        low = piece.lower()
        # Numpad: explicit "numpad" or "numeric keypad"; "no numpad" → False.
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


# Height/Width/Depth: either ``: 24.32 mm`` (Alienware older format) or
# ``: 0.95 in. (24.32 mm)`` (Alienware Area-51 2026 format). We always
# prefer the mm value if both are present; if only inches is given we
# convert and flag for review (Dell virtually always publishes mm).
_DIM_LINE_RE = lambda label: re.compile(
    rf"{label}[^\n:]*[:\-]\s*"
    rf"(?:(?P<inches>\d+(?:\.\d+)?)\s*in(?:\.|ches)?\s*"
    rf"(?:\((?P<mm_paren>\d+(?:\.\d+)?)\s*mm\))?"
    rf"|(?P<mm>\d+(?:\.\d+)?)\s*mm)",
    re.IGNORECASE,
)
_HEIGHT_LINE_RE = _DIM_LINE_RE("Height")
_WIDTH_LINE_RE = _DIM_LINE_RE("Width")
_DEPTH_LINE_RE = _DIM_LINE_RE("Depth")

# Range form: ``Height: 25.70 mm to 30.20 mm``.
_HEIGHT_RANGE_RE = re.compile(
    r"Height[^\n:]*[:\-]\s*(\d+(?:\.\d+)?)\s*mm\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*mm",
    re.IGNORECASE,
)

# Weight: either kg directly, or "9.56 lb (4.34 kg)".
_WEIGHT_KG_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kg", re.IGNORECASE)
_WEIGHT_LB_THEN_KG_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*lb\s*\((\d+(?:\.\d+)?)\s*kg\)", re.IGNORECASE
)
_WEIGHT_START_RE = re.compile(
    r"(?:Starting\s+Weight|Weight\s+\(starting\))\s*[:\-]?\s*"
    r"(?:\d+(?:\.\d+)?\s*lb\s*\()?(\d+(?:\.\d+)?)\s*kg",
    re.IGNORECASE,
)
_WEIGHT_MAX_RE = re.compile(
    r"Weight\s*\(maximum\)[:\s\n]*"
    r"(?:\d+(?:\.\d+)?\s*lb\s*\()?(\d+(?:\.\d+)?)\s*kg",
    re.IGNORECASE,
)
_WEIGHT_RANGE_RE = re.compile(
    r"Weight[^\n:]*[:\-]?\s*(\d+(?:\.\d+)?)\s*kg\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*kg",
    re.IGNORECASE,
)


def _populate_dimensions(
    cand: CandidateProduct,
    text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    if text is None:
        return

    cand.width_mm = _maybe_bundle(
        _dim_mm(_WIDTH_LINE_RE, text), source_url, captured_at
    )
    cand.depth_mm = _maybe_bundle(
        _dim_mm(_DEPTH_LINE_RE, text), source_url, captured_at
    )

    # Height — try range first, fall back to single-line form.
    height_min: Optional[float] = None
    height_max: Optional[float] = None
    m = _HEIGHT_RANGE_RE.search(text)
    if m is not None:
        try:
            height_min = float(m.group(1))
            height_max = float(m.group(2))
        except ValueError:
            height_min = height_max = None
    else:
        height_max = _dim_mm(_HEIGHT_LINE_RE, text)

    cand.height_mm_min = _maybe_bundle(height_min, source_url, captured_at)
    cand.height_mm_max = _maybe_bundle(height_max, source_url, captured_at)

    # Weight — multiple shapes:
    #  1. "Weight (maximum): 9.56 lb (4.34 kg)" → max only.
    #  2. "Starting Weight: 3.86 kg" → min only.
    #  3. "Weight: X kg to Y kg" → both.
    weight_min: Optional[float] = None
    weight_max: Optional[float] = None

    m = _WEIGHT_RANGE_RE.search(text)
    if m is not None:
        try:
            weight_min = float(m.group(1))
            weight_max = float(m.group(2))
        except ValueError:
            pass

    if weight_min is None:
        m = _WEIGHT_START_RE.search(text)
        if m is not None:
            try:
                weight_min = float(m.group(1))
            except ValueError:
                weight_min = None

    if weight_max is None:
        m = _WEIGHT_MAX_RE.search(text)
        if m is not None:
            try:
                weight_max = float(m.group(1))
            except ValueError:
                weight_max = None

    cand.weight_kg_min = _maybe_bundle(weight_min, source_url, captured_at)
    cand.weight_kg_max = _maybe_bundle(weight_max, source_url, captured_at)


def _dim_mm(pattern: re.Pattern[str], text: str) -> Optional[float]:
    """Run a Width/Height/Depth pattern; prefer ``mm`` group, else convert inches."""
    m = pattern.search(text)
    if m is None:
        return None
    g = m.groupdict()
    for key in ("mm_paren", "mm"):
        if g.get(key):
            try:
                return float(g[key])
            except ValueError:
                pass
    if g.get("inches"):
        try:
            return round(float(g["inches"]) * 25.4, 2)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Design
# ---------------------------------------------------------------------------


_MATERIAL_TOKENS = (
    ("aluminum", "aluminum"),
    ("aluminium", "aluminum"),
    ("magnesium", "magnesium"),
    ("carbon fiber", "carbon-fiber"),
    ("carbon-fiber", "carbon-fiber"),
    ("plastic", "plastic"),
)

_LID_PAT = re.compile(r"(?:lid|a[- ]cover|top cover)", re.IGNORECASE)
_PALM_PAT = re.compile(r"(?:palm rest|c[- ]cover|deck)", re.IGNORECASE)
_BOTTOM_PAT = re.compile(r"(?:bottom|d[- ]cover|base)", re.IGNORECASE)


def _populate_design(
    cand: CandidateProduct,
    text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    if text is None:
        return
    a_val = _material_near(text, _LID_PAT)
    c_val = _material_near(text, _PALM_PAT)
    d_val = _material_near(text, _BOTTOM_PAT)
    cand.a_cover_material = _maybe_bundle(a_val, source_url, captured_at)
    cand.c_cover_material = _maybe_bundle(c_val, source_url, captured_at)
    cand.d_cover_material = _maybe_bundle(d_val, source_url, captured_at)
    # Free-form fields Dell doesn't typically publish.
    cand.lighting = _vdp_bundle(source_url, captured_at)
    cand.thermal_shelf = _vdp_bundle(source_url, captured_at)


def _material_near(text: str, anchor: re.Pattern[str]) -> Optional[str]:
    """Find the material token closest to (and within ~40 chars of) the anchor."""
    m = anchor.search(text)
    if m is None:
        return None
    window_start = max(0, m.start() - 40)
    window_end = min(len(text), m.end() + 40)
    window = text[window_start:window_end].lower()
    for needle, label in _MATERIAL_TOKENS:
        if needle in window:
            return label
    return None


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())
