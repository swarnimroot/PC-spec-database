"""Lenovo parser: ``ProductSnapshot`` → ``CandidateProduct``.

Lenovo's PSREF site exposes the richest spec sheet of the four vendors.
``scrapers_lib.tier2.lenovo`` flattens the LoadSpecData JSON tree into
a flat ``specs: dict[str, str]`` keyed by a hierarchical 3-level path
(e.g. ``"Performance > Processor > Processor"``). Each key's value is
either a single-line ``DefaultDescription`` (prose) or a multi-row
``Att: AttV; Att: AttV`` payload, with multi-SKU alternatives joined
by ``\\n``.

A few Lenovo-specific quirks the parser absorbs:

* The hierarchical key shape (``"<L1> > <L2> > <FName>"``) is used
  as-is — we look up the keys we care about by their full triple. We
  don't try to canonicalize the path shape.
* PSREF publishes per-model-family — typically one snapshot per
  product line — so cross-tile merge in the runner usually degenerates
  to a single-candidate fast path.
* ``Att: AttV`` rows carry structured per-attribute data inside one
  string. Where Lenovo names CPUs / GPUs explicitly we extract the
  canonical model token; everything else is parsed by ``key in row``.
* USB / Thunderbolt wording on PSREF is unambiguous (``USB 10Gbps``,
  ``USB4`` rather than HP's signaling-rate-only labels). Where Lenovo
  is unambiguous we land verified directly. Anywhere we do have to
  guess (e.g. raw signaling rates with no version label), we attach
  the best-guess value with ``status: 'needs-review'`` via the
  ``(value, status)`` tuple pattern HP introduced.
* Lenovo doesn't publish per-board TPP/TGP (TGP is a per-GPU number on
  PSREF and lives in the GPU row, not the board); board-level TPP/TGP
  stay ``vendor-doesn't-publish``. The static GPU → board map
  (Decision 5) supplies labels.

This module does NOT touch the database.

Status routing (per ARCHITECTURE.md §Provenance shape) matches Dell/HP:

* High confidence → ``status: 'verified'``.
* Regex matched but value smells off → ``status: 'needs-review'`` with
  the value still attached. The runner will queue, not write.
* We looked for the field, Lenovo didn't publish → ``status:
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


SCRAPER_ID = "lenovo.fetch_lenovo_product"


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def parse(snapshot: ProductSnapshot) -> CandidateProduct:
    """Decode a Lenovo snapshot into a :class:`CandidateProduct`.

    The snapshot's ``url``, ``fetched_at``, and ``title`` are used to derive
    identity fields and stamp every emitted bundle.
    """
    specs = dict(snapshot.specs or {})
    captured_at = snapshot.fetched_at.isoformat()
    source_url = snapshot.url

    # --- Identity --------------------------------------------------------
    model_code = _derive_lenovo_model_code(snapshot.title or "", snapshot.url or "")
    year, year_inferred = h.derive_year(
        snapshot.title or "",
        snapshot.url or "",
        snapshot.fetched_at,
    )

    sub_brand = _derive_lenovo_sub_brand(snapshot.title or "", snapshot.url or "")
    series = _derive_lenovo_series(snapshot.title or "", snapshot.url or "")

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
    cand.brand = _scraped_bundle("Lenovo", source_url, captured_at)
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
    cpu_text = specs.get("Performance > Processor > Processor")
    cand.cpu_offerings = _build_cpu_offerings(cpu_text, source_url, captured_at)

    # --- CPU chip specs (catalog seeding) ------------------------------
    # PSREF publishes per-row ``Att: AttV`` attributes (Cores, Base
    # Frequency, Max Frequency, Process Technology) inside each CPU
    # alternative. We map them to the corresponding ``cpu_catalog``
    # columns. ``catalog_resolve`` decides whether to seed or queue.
    cand.cpu_chip_specs = _build_cpu_chip_specs(cpu_text)

    # --- GPU + boards ---------------------------------------------------
    gpu_text = specs.get("Performance > Graphics > Graphics")
    cand.boards = _build_boards(gpu_text, source_url, captured_at)

    # --- Memory ---------------------------------------------------------
    mem_max_text = specs.get("Performance > Memory > Max Memory")
    mem_slots_text = specs.get("Performance > Memory > Memory Slots")
    mem_type_text = specs.get("Performance > Memory > Memory Type")
    _populate_memory(
        cand,
        mem_max_text,
        mem_slots_text,
        mem_type_text,
        source_url,
        captured_at,
    )

    # --- Storage --------------------------------------------------------
    storage_slot_text = specs.get("Performance > Storage > Storage Slot")
    storage_max_text = specs.get("Performance > Storage > Max Storage Support")
    storage_type_text = specs.get("Performance > Storage > Storage Type")
    cand.storage_slots = _build_storage_slots(
        storage_slot_text, storage_type_text, source_url, captured_at
    )
    if storage_max_text is not None or storage_type_text is not None:
        cand.storage_max_gb = _build_storage_max_gb(
            (storage_max_text or "") + "\n" + (storage_type_text or ""),
            source_url,
            captured_at,
        )

    # --- Display --------------------------------------------------------
    display_text = specs.get("Design > Display > Display")
    cand.display_offerings = _build_display_offerings(
        display_text, source_url, captured_at
    )

    # --- Battery --------------------------------------------------------
    battery_text = specs.get("Performance > Battery > Battery")
    cand.battery_offerings = _build_battery_offerings(
        battery_text, source_url, captured_at
    )

    # --- Network --------------------------------------------------------
    wireless_text = specs.get("Connectivity > Network > WLAN + Bluetooth")
    ethernet_text = specs.get("Connectivity > Network > Ethernet")
    ports_text = specs.get("Connectivity > Ports > Standard Ports")
    _populate_network(
        cand,
        wireless_text,
        ethernet_text,
        ports_text,
        source_url,
        captured_at,
    )

    # --- I/O ------------------------------------------------------------
    _populate_io(cand, ports_text, source_url, captured_at)

    # --- Adapter --------------------------------------------------------
    psu_text = specs.get("Performance > Power Adapter > Power Adapter")
    cand.adapter_offerings = _build_adapter_offerings(
        psu_text, source_url, captured_at
    )
    if psu_text:
        connector = _detect_adapter_connector(psu_text)
        cand.adapter_connector = _maybe_bundle(connector, source_url, captured_at)

    # --- Camera ---------------------------------------------------------
    camera_text = specs.get("Performance > Multi-Media > Camera")
    cand.camera_offerings = _build_camera_offerings(
        camera_text, source_url, captured_at
    )

    # --- Audio ----------------------------------------------------------
    speakers_text = specs.get("Performance > Multi-Media > Speakers")
    _populate_audio(cand, speakers_text, source_url, captured_at)

    # --- Keyboard -------------------------------------------------------
    kb_text = specs.get("Design > Input Device > Keyboard")
    kb_backlight_text = specs.get("Design > Input Device > Keyboard Backlight")
    cand.keyboard_offerings = _build_keyboard_offerings(
        kb_text, kb_backlight_text, source_url, captured_at
    )

    # --- Dimensions / Weight -------------------------------------------
    dim_text = specs.get("Design > Mechanical > Dimensions (WxDxH)")
    weight_text = specs.get("Design > Mechanical > Weight")
    _populate_dimensions(cand, dim_text, weight_text, source_url, captured_at)

    # --- Design ---------------------------------------------------------
    case_material_text = specs.get("Design > Mechanical > Case Material")
    lighting_text = specs.get("Design > Mechanical > System Lighting")
    _populate_design(
        cand, case_material_text, lighting_text, source_url, captured_at
    )

    # --- Thermals (Lenovo doesn't publish these on PSREF) --------------
    cand.thermal_design = _vdp_bundle(source_url, captured_at)
    cand.thermal_material = _vdp_bundle(source_url, captured_at)
    cand.tim = _vdp_bundle(source_url, captured_at)
    cand.fan_count = _vdp_bundle(source_url, captured_at)

    return cand


# ---------------------------------------------------------------------------
# Bundle factories (mirror Dell/HP — kept local to keep the bridge import-light
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
# Lenovo identity
# ---------------------------------------------------------------------------


def _derive_lenovo_model_code(title: str, url: str) -> str:
    """Pull the model-code token out of a Lenovo PSREF title or URL.

    PSREF titles read e.g. ``"Legion Pro 7 16AFR10H"`` — the trailing
    alphanumeric token (``"16AFR10H"``) is the machine-type-style
    model code. URL form: ``/Product/Legion/Legion_Pro_7_16AFR10H``;
    the ProductKey segment carries the same token after underscores.

    Falls back to the URL's last path segment when no code matches.
    """
    # Title form: scan whitespace-separated tokens right-to-left for the
    # first one that matches the machine-type pattern (mostly digits +
    # uppercase letters, length >= 5 to avoid catching ``"7"`` or ``"16"``).
    # Right-to-left so a trailing year like ``"(2026)"`` doesn't shadow the
    # real model code.
    if title:
        tokens = title.strip().split()
        for token in reversed(tokens):
            stripped = token.strip(",.()")
            if _LENOVO_MODEL_CODE_RE.fullmatch(stripped):
                return stripped
    if url:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        # Strip query / fragment: ``Legion_Pro_7_16AFR10H?tab=spec``.
        slug = slug.split("?", 1)[0].split("#", 1)[0]
        # PSREF ProductKey segments split on underscores; the model code is
        # the last underscore-separated token.
        last = slug.rsplit("_", 1)[-1]
        if _LENOVO_MODEL_CODE_RE.fullmatch(last):
            return last
        return slug
    return ""


# Lenovo machine-type model codes are 5+ alphanumerics, mixing digits and
# uppercase letters (e.g. ``16AFR10H``, ``15IRX10``, ``16IRX9H``). The
# pattern requires at least one letter and one digit so plain numeric
# strings don't accidentally match.
_LENOVO_MODEL_CODE_RE = re.compile(
    r"(?=.*\d)(?=.*[A-Z])[A-Z0-9]{5,}",
)


# Sub-brand → recognized name patterns. Order matters: more specific first.
# Lenovo's gaming-relevant lines are Legion (mainstream gaming), LOQ
# (entry gaming), ThinkPad / IdeaPad (productivity, included for
# completeness — they aren't gaming targets but the parser must still
# return something stable if pointed at one by accident).
_LENOVO_SUB_BRANDS = (
    ("legion", "Legion"),
    ("loq", "LOQ"),
    ("thinkpad", "ThinkPad"),
    ("ideapad", "IdeaPad"),
    ("yoga", "Yoga"),
)


def _derive_lenovo_sub_brand(title: str, url: str) -> Optional[str]:
    """Return ``"Legion"`` / ``"LOQ"`` / ``"ThinkPad"`` / ``"IdeaPad"`` / ``None``.

    PSREF titles consistently lead with the sub-brand for gaming
    products (``"Legion Pro 7 ..."``, ``"LOQ 15IRX10"``).
    """
    haystack = ((title or "") + " " + (url or "")).lower()
    for needle, label in _LENOVO_SUB_BRANDS:
        if needle in haystack:
            return label
    return None


# Recognized Lenovo Legion series families. We pair the family name with the
# product's screen-size token (14, 15, 16, 18) where one is published in the
# title or URL — e.g. ``"Legion Pro 7"`` already carries no size in the
# family name (size is in the model code suffix), so the series stays
# ``"Legion Pro 7"``. The naming convention stays close to how Lenovo
# markets these lines.
_LENOVO_SERIES_FAMILIES = (
    # Order: most specific first so "Legion Pro 7" wins over "Legion 7".
    "Legion Pro 7i",
    "Legion Pro 7",
    "Legion Pro 5i",
    "Legion Pro 5",
    "Legion Slim 7i",
    "Legion Slim 7",
    "Legion Slim 5i",
    "Legion Slim 5",
    "Legion 9i",
    "Legion 9",
    "Legion 7i",
    "Legion 7",
    "Legion 5i",
    "Legion 5",
)


def _derive_lenovo_series(title: str, url: str) -> Optional[str]:
    """Return e.g. ``"Legion Pro 7"`` / ``"Legion Slim 7i"`` / ``None``.

    The family name comes from the title or URL. PSREF titles read e.g.
    ``"Legion Pro 7 16AFR10H"`` — the family is the run of words up to
    the trailing model-code token. Hyphens / underscores in the URL slug
    carry the same separator force as spaces; we collapse them so
    ``Legion_Pro_7_16AFR10H`` reads as a single phrase.
    """
    haystack_raw = (title or "") + " " + (url or "")
    haystack_norm = re.sub(r"[-_]+", " ", haystack_raw).lower()
    for family in _LENOVO_SERIES_FAMILIES:
        if family.lower() in haystack_norm:
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


# Lenovo-only splitter: split alternatives on newlines (and the literal
# word " or "), but NEVER on ``;`` — Lenovo uses ``;`` to separate
# attributes inside one ``Att: AttV; Att: AttV`` row, not between SKU
# alternatives. ``h.split_options`` splits on ``;`` (Dell/HP do use it
# as an option separator), so we cannot reuse it for the structured
# rows. Empty pieces dropped.
def _split_alternatives(value: str) -> list[str]:
    if not value:
        return []
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    n = len(value)
    while i < n:
        c = value[i]
        if c == "(":
            depth += 1
            buf.append(c)
            i += 1
            continue
        if c == ")":
            depth = max(0, depth - 1)
            buf.append(c)
            i += 1
            continue
        if depth == 0:
            if c == "\n":
                parts.append("".join(buf).strip())
                buf = []
                i += 1
                continue
            if c == " " and value[i : i + 4].lower() == " or ":
                parts.append("".join(buf).strip())
                buf = []
                i += 4
                continue
        buf.append(c)
        i += 1
    parts.append("".join(buf).strip())
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Lenovo row helpers (``Att: AttV; Att: AttV`` rows)
# ---------------------------------------------------------------------------


def _row_attrs(row: str) -> dict[str, str]:
    """Parse one Lenovo PSREF row into a case-insensitive ``Att → AttV`` dict.

    Rows look like ``"Cores: 16; Threads: 32; Cache: 16MB L2 / 64MB L3"``.
    Plain prose (DefaultDescription) returns an empty dict — callers fall
    back to whole-string regexes in that case.
    """
    out: dict[str, str] = {}
    if not row:
        return out
    for part in row.split(";"):
        if ":" not in part:
            continue
        key, _, val = part.partition(":")
        key_norm = key.strip().lower()
        val_norm = val.strip()
        if key_norm and val_norm and key_norm not in out:
            out[key_norm] = val_norm
    return out


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------


# Recognized CPU name forms, after stripping trademark symbols. Mirrors
# Dell's regex so catalog keys agree.
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
        return [{"model": _vdp_bundle(source_url, captured_at)}]

    seen: set[str] = set()
    offerings: OfferingsList = []
    for piece in _split_alternatives(_strip_tm(text)):
        # Lenovo row: ``Processor Name: AMD Ryzen 9 9955HX; Cores: 16; ...``
        # Pull "Processor Name" out first so we get the canonical model
        # without sweeping in the trailing structured attributes.
        attrs = _row_attrs(piece)
        name_field = attrs.get("processor name")
        haystack = name_field if name_field else piece

        m = _CPU_NAME_RE.search(haystack)
        if m is not None:
            model = _normalize_cpu_model(m.group(0))
            status = "verified"
        else:
            model = _normalize_ws(haystack.split(";", 1)[0])
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

    Mirrors Dell/HP's ``_normalize_cpu_model``. Kept local rather than
    shared so the per-vendor parser stays self-contained.
    """
    s = _normalize_ws(raw)
    s = re.sub(r"^Intel\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^AMD\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+processor\s+", " ", s, flags=re.IGNORECASE)
    return s.strip()


def _build_cpu_chip_specs(
    cpu_text: Optional[str],
) -> dict[str, dict[str, Optional[str]]]:
    """Extract chip-level specs from PSREF's structured Processor rows.

    Each PSREF alternative is a ``Att: AttV; Att: AttV`` row carrying
    Processor Name, Cores, Threads, Base Frequency, Max Frequency,
    Process Technology, Cache, Processor Graphics. We map a subset to
    the corresponding ``cpu_catalog`` columns:

    * ``Cores`` → ``cores``
    * ``Base Frequency`` → ``base_clock``
    * ``Max Frequency`` → ``boost_clock``
    * ``Process Technology`` → ``process_node``
    * ``Processor Family`` (when present in row) → ``architecture``

    Returns ``{}`` when no chip specs were extracted.
    """
    if not cpu_text:
        return {}
    out: dict[str, dict[str, Optional[str]]] = {}
    for piece in _split_alternatives(_strip_tm(cpu_text)):
        attrs = _row_attrs(piece)
        name_field = attrs.get("processor name")
        haystack = name_field if name_field else piece
        m = _CPU_NAME_RE.search(haystack)
        if m is None:
            continue
        model = _normalize_cpu_model(m.group(0))
        specs: dict[str, Optional[str]] = {}
        if "cores" in attrs:
            specs["cores"] = attrs["cores"]
        if "base frequency" in attrs:
            specs["base_clock"] = attrs["base frequency"]
        if "max frequency" in attrs:
            specs["boost_clock"] = attrs["max frequency"]
        if "process technology" in attrs:
            specs["process_node"] = attrs["process technology"]
        if "processor family" in attrs:
            specs["architecture"] = attrs["processor family"]
        if specs and model not in out:
            out[model] = specs
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


_TGP_RE = re.compile(r"(\d+)\s*W\b", re.IGNORECASE)


def _build_boards(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    """Group GPUs in the Graphics row by their static board label.

    Per Decision 5: board labels come from the static ``GPU_TO_BOARD`` map.
    Unmapped GPUs emit a board with ``label: null`` and the GPU bundle
    marked ``needs-review``. Lenovo publishes per-GPU TGP inside the row
    (``"TGP: 140W"``); per a Session 7 user decision we collapse those to
    one number per board by taking the max — the data model has one
    ``tgp_max`` per board so the highest-TGP GPU on the board sets the
    ceiling. Status stays ``verified`` (we read the number directly).
    """
    if text is None:
        return None
    pieces = _split_alternatives(_strip_tm(text))
    by_label: dict[Optional[str], list[Bundle]] = {}
    label_order: list[Optional[str]] = []
    seen_gpu_names: dict[Optional[str], set[str]] = {}
    tgp_max_by_label: dict[Optional[str], Optional[int]] = {}
    for piece in pieces:
        # Lenovo row: ``Graphics: NVIDIA GeForce RTX 5070 Ti Laptop GPU; ...``.
        # Look up "Graphics" first so trailing attributes (Memory: 12GB,
        # TGP: 140W) don't leak into the model token.
        attrs = _row_attrs(piece)
        gname_field = attrs.get("graphics")
        haystack = gname_field if gname_field else piece

        m = _GPU_NAME_RE.search(haystack)
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
            name = _normalize_ws(haystack)
            gpu_bundle = _scraped_bundle(
                name, source_url, captured_at, status="needs-review"
            )

        # Per-GPU TGP: parse from the row's ``TGP`` attribute and track
        # the max per board. Falls back silently if PSREF didn't list it.
        tgp_val: Optional[int] = None
        tgp_field = attrs.get("tgp")
        if tgp_field:
            tgp_match = _TGP_RE.search(tgp_field)
            if tgp_match:
                try:
                    tgp_val = int(tgp_match.group(1))
                except ValueError:
                    tgp_val = None

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
            tgp_bundle = _scraped_bundle(
                tgp_max_value, source_url, captured_at
            )
        boards.append(
            {
                "label": label_bundle,
                "tpp_max": _vdp_bundle(source_url, captured_at),
                "tgp_max": tgp_bundle,
                "gpus": by_label[label],
            }
        )
    return boards or None


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
_MEM_SLOTS_COUNT_RE = re.compile(r"\b(?:Two|Three|Four|One|\d+)\b", re.IGNORECASE)
_MEM_SLOT_NUM_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
}


def _populate_memory(
    cand: CandidateProduct,
    max_text: Optional[str],
    slots_text: Optional[str],
    type_text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    """Populate the five memory bundles from PSREF's three Memory keys."""
    cand.memory_max_gb = _maybe_bundle(
        h.parse_gb(max_text or ""), source_url, captured_at
    )
    cand.memory_speed_mts = _maybe_bundle(
        h.parse_mts(_combined_mem_text(max_text, type_text)),
        source_url,
        captured_at,
    )

    slots_val = _parse_memory_slots(slots_text)
    cand.memory_slots = _maybe_bundle(slots_val, source_url, captured_at)

    # Memory Type key is sometimes a bare ``DDR5-5600`` token; pull the
    # type half and ignore the speed half (already captured above).
    type_haystack = (type_text or "") + " " + (max_text or "")
    m = _MEM_TYPE_RE.search(type_haystack)
    type_val = m.group(1).upper() if m else None
    cand.memory_type = _maybe_bundle(type_val, source_url, captured_at)

    # PSREF doesn't structurally publish memory overclocking on the spec
    # page; record we checked.
    cand.memory_overclocking = _vdp_bundle(source_url, captured_at)


def _combined_mem_text(*parts: Optional[str]) -> str:
    return " ".join(p for p in parts if p)


def _parse_memory_slots(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    low = text.lower()
    if "soldered" in low or "onboard" in low or "non-upgradeable" in low:
        # Lenovo rarely publishes soldered RAM with a slot count; treat as 0.
        return 0
    # Word-form first: ``"Two DDR5 SODIMM slots, dual-channel capable"``.
    for word, n in _MEM_SLOT_NUM_WORDS.items():
        if re.search(rf"\b{word}\b", low):
            return n
    m = re.search(r"(\d+)\s+(?:DDR\d|SODIMM|slot)", text, re.IGNORECASE)
    if m is not None:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


_STORAGE_GEN_RE = re.compile(
    r"PCIe[^,\n]*?(\d)\.0",
    re.IGNORECASE,
)


def _build_storage_slots(
    slot_text: Optional[str],
    type_text: Optional[str],
    source_url: str,
    captured_at: str,
) -> Optional[OfferingsList]:
    """Build storage_slots offerings from Lenovo's two Storage keys.

    The "Storage Slot" key reads e.g.
        ``"Two M.2 slots • One M.2 2280 PCIe 5.0 x4 slot • One M.2 2280 PCIe 4.0 x4 slot"``
    enumerating physical slots and their PCIe gens. The "Storage Type"
    key reads
        ``"Disk Type: M.2 2242 SSD; Interface: PCIe NVMe, PCIe 4.0 x4; Offering: 1TB"``
    per drive offering, joined by newlines.

    We prefer the Slot key for gen extraction (one slot entry per
    bullet-separated physical slot) and fall back to per-offering rows
    from the Type key when the Slot key is absent.
    """
    if slot_text is None and type_text is None:
        return None

    if slot_text:
        # Bullet-separated slots; the leading "Two M.2 slots" summary is
        # usually followed by per-slot gen lines. We split on bullets and
        # keep entries that look like a slot description (mention "slot"
        # or "M.2").
        pieces = [
            p.strip()
            for p in re.split(r"[•\n]+", slot_text)
            if p.strip()
        ]
        # Drop the leading summary entry (``"Two M.2 slots"``) — it
        # double-counts otherwise.
        slot_pieces: list[str] = []
        for p in pieces:
            if re.match(r"^(?:One|Two|Three|Four|\d+)\s+M\.2\s+slots?$", p, re.IGNORECASE):
                continue
            if "slot" in p.lower() or "m.2" in p.lower() or "pcie" in p.lower():
                slot_pieces.append(p)
        if slot_pieces:
            slots: OfferingsList = []
            for piece in slot_pieces:
                gen = _extract_pcie_gen(piece)
                slots.append({"gen": _maybe_bundle(gen, source_url, captured_at)})
            return slots

    # Fall back: one slot per "Storage Type" offering line.
    if type_text:
        pieces = _split_alternatives(type_text)
        slots = []
        for piece in pieces:
            gen = _extract_pcie_gen(piece)
            slots.append({"gen": _maybe_bundle(gen, source_url, captured_at)})
        return slots or None

    return None


def _extract_pcie_gen(text: str) -> Optional[int]:
    m = _STORAGE_GEN_RE.search(text)
    if m is not None:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


_STORAGE_TB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*TB\b", re.IGNORECASE)
_STORAGE_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*GB\b", re.IGNORECASE)


def _build_storage_max_gb(
    text: str, source_url: str, captured_at: str
) -> Bundle:
    """Extract the maximum published storage capacity, in GB.

    Same logic as Dell/HP: collect every TB / GB token; 1 TB → 1000 GB; the
    largest wins. ``vendor-doesn't-publish`` when the Storage keys existed
    but no capacity number could be parsed.
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
# PSREF publishes nits as ``"1100nits (HDR peak) / 500nits (SDR typical)"``.
# Prefer the HDR-tagged figure if both are listed.
_HDR_NITS_PSREF_RE = re.compile(
    r"(\d{2,4})\s*nits?\s*\(HDR[^)]*\)",
    re.IGNORECASE,
)


def _build_display_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = _split_alternatives(_strip_tm(text))
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces):
        offerings.append(_parse_one_display(piece, idx, source_url, captured_at))
    return offerings or None


def _parse_one_display(
    piece: str, idx: int, source_url: str, captured_at: str
) -> dict[str, Bundle]:
    out: dict[str, Bundle] = {}
    attrs = _row_attrs(piece)

    # Size: prefer ``Size: 16"`` field, fall back to whole-row regex.
    size_val = h.parse_inches(attrs.get("size") or piece)
    out["size_inches"] = _maybe_bundle(size_val, source_url, captured_at)

    # Resolution: ``Resolution: WQXGA (2560x1600)``.
    res_haystack = attrs.get("resolution") or piece
    label_m = _RES_LABEL_RE.search(res_haystack)
    out["resolution_label"] = _maybe_bundle(
        label_m.group(1).upper() if label_m else None, source_url, captured_at
    )
    out["resolution_pixels"] = _maybe_bundle(
        h.parse_resolution_pixels(res_haystack), source_url, captured_at
    )

    out["refresh_rate_hz"] = _maybe_bundle(
        h.parse_hz(attrs.get("refresh rate") or piece), source_url, captured_at
    )

    # Nits: prefer ``Brightness: 1100nits (HDR peak) / 500nits (SDR typical)``.
    bright_haystack = attrs.get("brightness") or piece
    hdr_m = _HDR_NITS_PSREF_RE.search(bright_haystack)
    if hdr_m is not None:
        try:
            nits_val: Optional[int] = int(hdr_m.group(1))
        except ValueError:
            nits_val = None
    else:
        nits_val = h.parse_nits(bright_haystack)
    out["nits_peak"] = _maybe_bundle(nits_val, source_url, captured_at)

    out["response_time_ms"] = _maybe_bundle(
        h.parse_ms(piece), source_url, captured_at
    )

    panel_haystack = attrs.get("type") or piece
    panel_m = _PANEL_RE.search(panel_haystack)
    if panel_m is not None:
        canonical = _canonical_panel(panel_m.group(1))
        out["panel_type"] = _scraped_bundle(canonical, source_url, captured_at)
    else:
        out["panel_type"] = _vdp_bundle(source_url, captured_at)

    # HDR / VRR are usually packed into ``Key Features:`` on PSREF.
    feature_haystack = attrs.get("key features") or piece
    hdr_m = _HDR_RE.search(feature_haystack)
    out["hdr_certification"] = _maybe_bundle(
        _normalize_ws(hdr_m.group(1)) if hdr_m else None,
        source_url,
        captured_at,
    )

    color_haystack = attrs.get("color gamut") or piece
    dci_m = _DCI_P3_RE.search(color_haystack)
    out["dci_p3_pct"] = _maybe_bundle(
        float(dci_m.group(1)) if dci_m else None, source_url, captured_at
    )
    srgb_m = _SRGB_RE.search(color_haystack)
    out["srgb_pct"] = _maybe_bundle(
        float(srgb_m.group(1)) if srgb_m else None, source_url, captured_at
    )

    vrr_m = _VRR_RE.search(feature_haystack)
    if vrr_m is not None:
        out["vrr"] = _scraped_bundle(
            _canonical_vrr(vrr_m.group(1)), source_url, captured_at
        )
    else:
        out["vrr"] = _vdp_bundle(source_url, captured_at)

    surface_haystack = (attrs.get("surface") or piece).lower()
    if "anti-glare" in surface_haystack or "anti glare" in surface_haystack or "matte" in surface_haystack:
        anti = "matte"
    elif "glossy" in surface_haystack:
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
    pieces = _split_alternatives(text)
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
    ethernet_text: Optional[str],
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
    # Lenovo publishes Ethernet under its own key (``"2.5GbE, 1x RJ-45"``)
    # AND in the ports list. Prefer the dedicated key.
    if ethernet_text:
        low = ethernet_text.lower()
        if "no support" in low or "none" in low:
            eth_val = "none"
        else:
            m = _ETHERNET_RE.search(ethernet_text)
            if m is not None:
                eth_val = _canonical_ethernet(m.group(1))
            elif "rj-45" in low or "rj45" in low or "ethernet" in low:
                eth_val = "1GbE"
    elif ports_text:
        cleaned_ports = _strip_tm(ports_text)
        eth_line: Optional[str] = None
        for raw_line in re.split(r"[\n;]+", cleaned_ports):
            low = raw_line.lower()
            if "rj-45" in low or "rj45" in low or "ethernet" in low:
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
    # USB-C version: where Lenovo publishes an explicit USB-IF version
    # ("USB4", "USB 3.2 Gen 2") it lands ``verified``. Speed-only labels
    # ("USB 5Gbps", "USB 10Gbps") map to the unambiguous USB-IF version
    # and also land ``verified``. Truly ambiguous wording (20Gbps,
    # 80Gbps) attaches the best-guess version with ``status:
    # 'needs-review'`` per the (value, status) tuple pattern HP
    # introduced.
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


# Lenovo's port lines lead with a count token like ``"2x USB-A"`` or
# ``"1x USB-C"``. The counter regex matches both bare-digit (``"2 USB-A"``,
# Dell/HP shape) and the ``"<n>x"`` shape PSREF uses.
_LENOVO_PORT_COUNT_RE = re.compile(r"^\s*(\d+)\s*[xX×]?\s+(.*)$")


def _io_counts(text: str) -> dict[str, Any]:
    """Walk Lenovo's "Standard Ports" list and bucket each line.

    The list is newline-separated. Each line starts with a count
    (``"2x USB-A"``) and describes one port group.
    """
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
    for raw_line in re.split(r"[\n;]+", text):
        line = raw_line.strip()
        if not line:
            continue
        m = _LENOVO_PORT_COUNT_RE.match(line)
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

        if "usb-c" in low or "usb c" in low or "type-c" in low or "type c" in low:
            out["usbc_count"] += count
            ver_pair = _extract_usbc_version(low)
            if ver_pair is not None:
                out["usbc_version"], out["usbc_version_status"] = ver_pair
            continue

        if "usb-a" in low or "usb a" in low or "type-a" in low or "type a" in low:
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

        if ("sd" in low and ("card" in low or "slot" in low or "reader" in low)) or "sd reader" in low:
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
            elif "headphone" in low and "microphone" in low:
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


# Lenovo's USB-C wording is mostly explicit (``USB 10Gbps``, ``USB4``).
# Mirrors HP's tuple-returning helper so ambiguous rates can be flagged.
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
        # Could be USB 3.2 Gen 2x2 or early USB4 wording. Best-guess +
        # flag for human review (mirrors HP).
        return "USB 3.2 Gen 2x2", "needs-review"
    if "80gbps" in low:
        # USB4 v2 / TB5 share 80Gbps; without explicit wording we can't
        # decide.
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
    pieces = _split_alternatives(_strip_tm(text))
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces):
        # Skip the ``"No power adapter"`` literal — it's a SKU option,
        # not a real adapter.
        if "no power adapter" in piece.lower() or piece.lower().startswith("no "):
            continue
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
    if "slim tip" in low or "slim-tip" in low:
        return "slim-tip"
    if "usb type-c" in low or "usb-c" in low or "type c" in low or "type-c" in low:
        return "USB-C PD"
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

# Megapixel → vertical-pixel form for typical laptop webcam sensors.
# Lenovo PSREF advertises camera resolution in MP (``"5.0MP"``); Dell /
# HP / ASUS publish vertical-pixel form (``"720p"`` / ``"1080p"`` /
# ``"4K"``). Normalize Lenovo values into the same enum so the catalog
# is comparable across vendors. Values not in this table are kept as
# the raw ``NMP`` form with ``status="needs-review"`` so manual review
# can normalize anything unusual.
_MP_TO_P_FORM = {
    "0.9": "720p",
    "1.0": "720p",
    "2.0": "1080p",
    "5.0": "1440p",
    "8.0": "4K",
}


def _build_camera_offerings(
    text: Optional[str], source_url: str, captured_at: str
) -> Optional[OfferingsList]:
    if text is None:
        return None
    pieces = _split_alternatives(_strip_tm(text))
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces):
        low = piece.lower()
        m = _CAM_RES_RE.search(piece)
        res_val: Optional[str] = None
        res_status = "verified"
        if m is not None:
            label = m.group(1).lower()
            if label == "fhd":
                res_val = "1080p"
            elif label == "hd":
                res_val = "720p"
            elif label in ("uhd", "4k"):
                res_val = "4K"
            elif "mp" in label:
                mp_str = re.sub(
                    r"\s*mp\s*$", "", label, flags=re.IGNORECASE
                ).strip()
                normalized = _MP_TO_P_FORM.get(mp_str)
                if normalized is not None:
                    res_val = normalized
                else:
                    # Unknown MP value — keep raw form, flag for review.
                    res_val = mp_str.upper().replace(" ", "") + "MP"
                    res_status = "needs-review"
            else:
                res_val = label
        ir_val = bool(
            "ir camera" in low or "windows hello" in low or " ir " in low
        )
        # PSREF often calls it ``"E-shutter"`` (electronic shutter).
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
    r"(\d+)\s*stereo\s*speakers?"
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
        # Lenovo names "woofers" / "subwoofers" in the speaker breakdown.
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
    kb_text: Optional[str],
    backlight_text: Optional[str],
    source_url: str,
    captured_at: str,
) -> Optional[OfferingsList]:
    """Build keyboard offerings from PSREF's two Keyboard keys.

    PSREF publishes one description per product — the Keyboard key is
    almost always a single string (no upgrade options). We append the
    backlight key into the description so the view layer has the full
    picture in one place.
    """
    if kb_text is None and backlight_text is None:
        return None
    pieces = _split_alternatives(kb_text or "")
    offerings: OfferingsList = []
    for idx, piece in enumerate(pieces or [""]):
        # Extend description with backlight info from the sibling key
        # (only on the first / base offering — backlight is product-level
        # on PSREF).
        description = piece
        if idx == 0 and backlight_text:
            description = f"{piece}; {backlight_text}".strip("; ").strip()
        low = description.lower()
        if "no numpad" in low or "no numeric" in low:
            has_numpad: Optional[bool] = False
        elif "numpad" in low or "numeric keypad" in low or "num pad" in low:
            has_numpad = True
        else:
            has_numpad = None
        offerings.append(
            {
                "description": _scraped_bundle(
                    description, source_url, captured_at
                ),
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


# PSREF dimension shape:
#   ``"Models: All models; Dimensions: 364.38 x 275.94 x 21.9-26.65 mm (14.35 x 10.86 x 0.86-1.05 inches)"``
# We always prefer the mm group. Height may be a single value or a
# ``min-max`` range (front/rear thickness).
_DIM_MM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*"
    r"(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?\s*mm",
    re.IGNORECASE,
)
_WEIGHT_KG_RE = re.compile(
    r"(?:starting\s+at\s+)?(\d+(?:\.\d+)?)\s*kg",
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
        m = _DIM_MM_RE.search(dim_text)
        if m is not None:
            try:
                width = float(m.group(1))
                depth = float(m.group(2))
                h_lo = float(m.group(3))
                h_hi = float(m.group(4)) if m.group(4) else None
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
        cleaned = weight_text
        m = _WEIGHT_KG_RE.search(cleaned)
        kg: Optional[float] = None
        if m is not None:
            try:
                kg = float(m.group(1))
            except ValueError:
                kg = None
        # PSREF publishes ``"Starting at X kg"`` as a single value →
        # treat as min weight (mirrors HP's single-value rule).
        if kg is not None:
            cand.weight_kg_min = _maybe_bundle(kg, source_url, captured_at)
            cand.weight_kg_max = _maybe_bundle(None, source_url, captured_at)
        else:
            cand.weight_kg_min = _vdp_bundle(source_url, captured_at)
            cand.weight_kg_max = _vdp_bundle(source_url, captured_at)


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


def _populate_design(
    cand: CandidateProduct,
    case_material_text: Optional[str],
    lighting_text: Optional[str],
    source_url: str,
    captured_at: str,
) -> None:
    """Populate cover materials + lighting from PSREF's Mechanical keys.

    PSREF publishes ``Case Material`` as a single string referencing the
    top and bottom covers (e.g. ``"Aluminium (top), aluminium (bottom)"``).
    We map ``top`` → A-cover, ``bottom`` → D-cover. Palm rest (C-cover)
    is rarely called out separately; if we don't see it we record
    ``vendor-doesn't-publish``.
    """
    a_val: Optional[str] = None
    c_val: Optional[str] = None
    d_val: Optional[str] = None
    if case_material_text:
        # Walk each comma-separated clause and find the cover anchor +
        # material in that clause.
        for clause in re.split(r",\s*", case_material_text):
            low = clause.lower()
            material = _material_in(low)
            if material is None:
                continue
            if "top" in low or "a-cover" in low or "lid" in low:
                a_val = material
            if "bottom" in low or "d-cover" in low or "base" in low:
                d_val = material
            if "palm" in low or "c-cover" in low or "deck" in low:
                c_val = material
        # If we found at least one material but couldn't anchor it to a
        # specific cover, leave the unmatched covers as
        # vendor-doesn't-publish (we know the material but not where).
    cand.a_cover_material = _maybe_bundle(a_val, source_url, captured_at)
    cand.c_cover_material = _maybe_bundle(c_val, source_url, captured_at)
    cand.d_cover_material = _maybe_bundle(d_val, source_url, captured_at)

    cand.lighting = _maybe_bundle(
        _clean_lighting(lighting_text) if lighting_text else None,
        source_url,
        captured_at,
    )
    # Thermal shelf isn't structurally published on PSREF.
    cand.thermal_shelf = _vdp_bundle(source_url, captured_at)


# PSREF embeds straight + curly quote variants around brand-name tokens
# (``'"Legion" logo with RGB...'``); strip them so the stored value is
# clean prose.
_LIGHTING_QUOTE_RE = re.compile(r'["“”‘’]')


def _clean_lighting(text: str) -> Optional[str]:
    cleaned = _LIGHTING_QUOTE_RE.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _material_in(low: str) -> Optional[str]:
    for needle, label in _MATERIAL_TOKENS:
        if needle in low:
            return label
    return None
