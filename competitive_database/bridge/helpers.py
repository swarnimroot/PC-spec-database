"""Shared bridge-layer utilities.

Pure functions only — every helper takes text/strings/dicts in and returns
parsed values. Vendor-specific quirks live in the per-vendor modules; this
file is intentionally generic.

Three concern areas:

* **Unit parsing.** Pull a number out of a "value + unit" string (``"32 GB"``
  → ``32``).
* **Name decomposition.** Take a vendor full name + URL and derive
  ``brand`` / ``sub_brand`` / ``series`` / ``model_code`` / ``year``.
* **Tier derivation.** Tier flag mechanics shared across vendors.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Unit / number parsing
# ---------------------------------------------------------------------------


_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:GB|GiB)\b", re.IGNORECASE)
_MTS_RE = re.compile(r"(\d{3,5})\s*(?:MT/s|MHz)\b", re.IGNORECASE)
_HZ_RE = re.compile(r"(\d{2,4})\s*Hz\b", re.IGNORECASE)
_MS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ms\b", re.IGNORECASE)
_INCH_RE = re.compile(
    r"(\d{1,2}(?:\.\d+)?)[\s\-]*(?:\"|inch(?:es)?|in\.|in\b)",
    re.IGNORECASE,
)
_NITS_RE = re.compile(r"(\d{2,4})\s*(?:nit|nits|cd/m²|cd/m2)\b", re.IGNORECASE)
_W_RE = re.compile(r"(\d+(?:\.\d+)?)\s*W\b")
_WH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*W(?:h|hr)\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_MM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm\b", re.IGNORECASE)
_KG_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kg\b", re.IGNORECASE)
_LB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*lb\b", re.IGNORECASE)
_CELLS_RE = re.compile(r"(\d+)\s*[- ]?cell", re.IGNORECASE)


def parse_int(text: str, pattern: re.Pattern[str]) -> Optional[int]:
    """Run ``pattern`` against ``text``, return ``int(group 1)`` or ``None``."""
    if not text:
        return None
    m = pattern.search(text)
    if m is None:
        return None
    try:
        return int(float(m.group(1)))
    except (TypeError, ValueError):
        return None


def parse_float(text: str, pattern: re.Pattern[str]) -> Optional[float]:
    """Run ``pattern`` against ``text``, return ``float(group 1)`` or ``None``."""
    if not text:
        return None
    m = pattern.search(text)
    if m is None:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def parse_gb(text: str) -> Optional[int]:
    """``"32 GB"`` / ``"32GB"`` / ``"32GB DDR5 5600 MT/s"`` → ``32``."""
    return parse_int(text, _GB_RE)


def parse_mts(text: str) -> Optional[int]:
    """``"5600 MT/s"`` / ``"DDR5 5600MHz"`` → ``5600``."""
    return parse_int(text, _MTS_RE)


def parse_hz(text: str) -> Optional[int]:
    """``"240Hz"`` / ``"240 Hz"`` → ``240``."""
    return parse_int(text, _HZ_RE)


def parse_ms(text: str) -> Optional[float]:
    """``"3 ms"`` / ``"1ms"`` → ``3.0`` / ``1.0``."""
    return parse_float(text, _MS_RE)


def parse_inches(text: str) -> Optional[float]:
    """``'18\"'`` / ``"18-inch"`` / ``"18 inches"`` → ``18.0``."""
    return parse_float(text, _INCH_RE)


def parse_nits(text: str) -> Optional[int]:
    """``"600 nits"`` → ``600``."""
    return parse_int(text, _NITS_RE)


def parse_watts(text: str) -> Optional[int]:
    """``"330W"`` → ``330``."""
    return parse_int(text, _W_RE)


def parse_wh(text: str) -> Optional[int]:
    """``"99Wh"`` → ``99``."""
    return parse_int(text, _WH_RE)


def parse_percent(text: str) -> Optional[float]:
    """``"100%"`` / ``"99.5%"`` → ``100.0`` / ``99.5``."""
    return parse_float(text, _PERCENT_RE)


def parse_mm(text: str) -> Optional[float]:
    """``"410.50 mm"`` / ``"35mm"`` → ``410.5`` / ``35.0``."""
    return parse_float(text, _MM_RE)


def parse_kg(text: str) -> Optional[float]:
    """``"3.86 kg"`` → ``3.86``."""
    return parse_float(text, _KG_RE)


def parse_lb(text: str) -> Optional[float]:
    """``"8.5 lb"`` → ``8.5``."""
    return parse_float(text, _LB_RE)


def parse_cell_count(text: str) -> Optional[int]:
    """``"6-cell"`` / ``"6 cell"`` → ``6``."""
    return parse_int(text, _CELLS_RE)


# ---------------------------------------------------------------------------
# Resolution / pixel helpers
# ---------------------------------------------------------------------------


_RES_PIXELS_RE = re.compile(r"(\d{3,4})\s*[x×X]\s*(\d{3,4})")


def parse_resolution_pixels(text: str) -> Optional[str]:
    """``"2560 x 1600"`` / ``"2560×1600"`` → ``"2560×1600"`` (canonical form)."""
    if not text:
        return None
    m = _RES_PIXELS_RE.search(text)
    if m is None:
        return None
    return f"{m.group(1)}×{m.group(2)}"


# ---------------------------------------------------------------------------
# Name decomposition
# ---------------------------------------------------------------------------


# Heuristic year regexes — must be 4 digits in the 20xx range to avoid
# matching model codes like ``aa18250`` (which contain "1825" but no year).
_YEAR_PARENS_RE = re.compile(r"\((20\d{2})\)")
_YEAR_BARE_RE = re.compile(r"\b(20\d{2})\b")

# Dell/Alienware URL slug → model code. Slugs look like
# ``alienware-area-51-aa18250-gaming-laptop``. The model-code segment is the
# alphanumeric token that mixes letters and digits (e.g. ``aa18250``,
# ``m18r2``). Falls back to the whole slug stripped of generic suffixes.
_DELL_MODEL_CODE_RE = re.compile(r"(?<![\w])([a-z]{1,3}\d{2,5}[a-z\d]*)(?![\w])")


# Generic marketing suffixes to strip from a DERIVED friendly product name.
# Ordered LONGEST-first so multi-word phrases match before their single-word
# tails (otherwise "Gaming Laptop" would only lose "Laptop" then stop). The
# cleaner iterates, so "… Gaming Laptop" fully strips across passes too.
_MARKETING_SUFFIXES = (
    "Gaming Laptop",
    "Gaming Notebook",
    "Laptop",
    "Notebook",
    "Gaming",
)


def clean_product_name(name: str) -> str:
    """Strip trailing generic marketing suffixes from a derived product name.

    Removes case-insensitive TRAILING marketing tokens/phrases — "Gaming
    Laptop", "Gaming Notebook", "Laptop", "Notebook", "Gaming" — longest match
    first, iterating so a tail like "… Gaming Laptop" strips fully. Only
    TRAILING tokens are removed: an internal "Gaming"/"Laptop" is preserved,
    as is the original casing of whatever remains. Trailing whitespace, commas,
    and hyphens left behind are trimmed.

    Idempotent: ``clean_product_name(clean_product_name(x)) == x``. GUARD: if
    cleaning would yield an empty string, the original ``name`` is returned
    unchanged (so a bare "Gaming Laptop" stays as-is rather than vanishing).
    """
    if not name:
        return name
    result = name
    changed = True
    while changed:
        changed = False
        stripped = result.rstrip().rstrip(",-").rstrip()
        for suffix in _MARKETING_SUFFIXES:
            # Case-insensitive match on the trailing suffix as a whole word:
            # the char before the suffix (if any) must be whitespace.
            if len(stripped) < len(suffix):
                continue
            tail = stripped[-len(suffix):]
            if tail.lower() != suffix.lower():
                continue
            before = stripped[: -len(suffix)]
            if before and not before[-1].isspace():
                continue
            candidate = before.rstrip().rstrip(",-").rstrip()
            if not candidate:
                # Stripping this suffix empties the name — bail out and keep
                # what we had (empty-result guard).
                return result.strip() or name
            result = candidate
            changed = True
            break
    cleaned = result.strip()
    return cleaned or name


def derive_year(title: str, url: str, fallback: datetime) -> tuple[int, bool]:
    """Best-effort year extraction.

    Order of attempts:

    1. Year in parentheses in the title (e.g. "ROG Strix G16 (2025)").
    2. Bare 4-digit 20xx year anywhere in title or URL.
    3. ``fallback.year``.

    Returns ``(year, was_inferred)``. ``was_inferred`` is ``True`` only when
    we fell through to the fallback timestamp — the runner uses that flag to
    decide between ``status: 'verified'`` and ``status: 'needs-review'`` on
    the ``vendor_full_name`` bundle.
    """
    for source in (title or "", url or ""):
        m = _YEAR_PARENS_RE.search(source)
        if m is not None:
            return int(m.group(1)), False
    for source in (title or "", url or ""):
        m = _YEAR_BARE_RE.search(source)
        if m is not None:
            return int(m.group(1)), False
    return int(fallback.year), True


def derive_dell_model_code(url: str, slug_fallback: Optional[str] = None) -> str:
    """Pull the model-code token out of a Dell ``/spd/<slug>`` URL.

    Dell slugs look like ``alienware-area-51-aa18250-gaming-laptop``. We
    extract the first ``[letters][digits...]`` token (here ``aa18250``).
    Falls back to ``slug_fallback`` (then to the whole slug) if the regex
    misses.
    """
    if not url:
        return slug_fallback or ""
    # Pull the path's last ``/spd/<slug>`` segment.
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    m = _DELL_MODEL_CODE_RE.search(slug)
    if m is not None:
        return m.group(1)
    return slug_fallback or slug


# Sub-brand → recognized name patterns. Order matters: more specific first.
_DELL_SUB_BRANDS = (
    ("alienware", "Alienware"),
    ("xps", "XPS"),
    ("inspiron", "Inspiron"),
    ("g series", "G Series"),
    ("dell g", "G Series"),
)


def derive_sub_brand(title: str, url: str) -> Optional[str]:
    """Return ``"Alienware"`` / ``"XPS"`` / ``"Inspiron"`` / ``"G Series"`` / ``None``."""
    haystack = ((title or "") + " " + (url or "")).lower()
    for needle, label in _DELL_SUB_BRANDS:
        if needle in haystack:
            return label
    return None


# Known Alienware series tokens. Ordered most-specific first to avoid
# matching a substring of a longer name.
_ALIENWARE_SERIES = (
    "Area-51",
    "Aurora",
    "m16",
    "m17",
    "m18",
    "x14",
    "x15",
    "x16",
    "x17",
    "Tactx",
)


def derive_alienware_series(title: str, url: str) -> Optional[str]:
    """Return e.g. ``"Area-51"`` / ``"Aurora"`` / ``"m18"`` / ``None``."""
    haystack = ((title or "") + " " + (url or "")).lower()
    for token in _ALIENWARE_SERIES:
        if token.lower() in haystack:
            return token
    return None


# ---------------------------------------------------------------------------
# Tier derivation
# ---------------------------------------------------------------------------


def tier_for_index(idx: int) -> str:
    """First entry → ``"base"``, every later entry → ``"optional"``.

    HP relies on this exact convention; Dell and others reuse it for
    multi-option fields when the vendor doesn't tag them otherwise.
    """
    return "base" if idx == 0 else "optional"


# ---------------------------------------------------------------------------
# Splitting helpers
# ---------------------------------------------------------------------------


def split_options(value: str) -> list[str]:
    """Split a multi-option spec value into trimmed pieces.

    Splits on newline, semicolon, or the literal word "or". Commas are NOT
    split on by default because real vendor strings often carry meaningful
    commas inside a single option (e.g. ``"32GB, 2x16GB, DDR5, 6400MT/s"``
    or ``"Intel Core Ultra 9 285HX (24-Core, 36MB Cache)"``). Use
    :func:`split_options_aggressive` if you do want comma splits.

    Parentheses are NOT split into. Empty pieces are dropped.
    """
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
            if c == "\n" or c == ";":
                parts.append("".join(buf).strip())
                buf = []
                i += 1
                continue
            # Match the literal word "or" surrounded by spaces.
            if (
                c == " "
                and value[i : i + 4].lower() == " or "
            ):
                parts.append("".join(buf).strip())
                buf = []
                i += 4
                continue
        buf.append(c)
        i += 1
    parts.append("".join(buf).strip())
    return [p for p in parts if p]


_AGGRESSIVE_SPLIT_RE = re.compile(r"\s*(?:\n|;|\bor\b|,)\s*", re.IGNORECASE)


def split_options_aggressive(value: str) -> list[str]:
    """Like :func:`split_options` but also splits on top-level commas.

    Useful for ports lists and other places where every comma is genuinely
    a separator.
    """
    if not value:
        return []
    parts = _AGGRESSIVE_SPLIT_RE.split(value)
    return [p.strip() for p in parts if p and p.strip()]


# ---------------------------------------------------------------------------
# Static GPU → board (motherboard tier) map
# ---------------------------------------------------------------------------
#
# Hard-coded mapping for current laptop GPU power tiers. Vendors don't
# publish per-product board labels; we group GPUs by power class. Keys are
# normalized canonical model strings (no "GeForce" / "NVIDIA" prefix).
#
# When a vendor parser sees multiple GPUs across all tiles for a single
# product, it groups by ``lookup_board(gpu)`` and emits one boards entry
# per group. Unknown GPUs return ``None`` — the parser surfaces those as
# a board with ``label: null`` and the boards entry's leaves marked
# ``needs-review`` (no new queue type per Decision 5).

GPU_TO_BOARD: dict[str, str] = {
    "RTX 5070 Ti": "MB1",
    "RTX 5080":    "MB1",
    "RTX 5090":    "MB1",
    "RTX 5050":    "MB2",
    "RTX 5060":    "MB2",
    "RTX 5070":    "MB2",
    "RTX 3050":    "MB3",
    "RTX 4050":    "MB3",
}


_GPU_PREFIX_RE = re.compile(
    r"^(?:NVIDIA\s+)?(?:GeForce\s+)?(?:AMD\s+)?(?:Radeon\s+)?",
    re.IGNORECASE,
)


def _normalize_gpu_name(model: str) -> str:
    """Drop "NVIDIA"/"GeForce"/"AMD"/"Radeon" prefixes and collapse whitespace.

    Used to align catalog model strings with the keys in :data:`GPU_TO_BOARD`.
    Match is case-sensitive on the canonical token after this normalization.
    """
    if not model:
        return ""
    s = re.sub(r"\s+", " ", model.strip())
    s = _GPU_PREFIX_RE.sub("", s, count=1).strip()
    return s


def lookup_board(gpu_model: str) -> Optional[str]:
    """Return ``"MB1"`` / ``"MB2"`` / ``"MB3"`` / ``None`` for ``gpu_model``.

    Input may carry vendor prefixes (e.g. ``"NVIDIA GeForce RTX 5090"``) —
    we normalize before lookup. Returns ``None`` for any GPU not present
    in :data:`GPU_TO_BOARD` (caller flags as ``needs-review``).
    """
    if not gpu_model:
        return None
    canon = _normalize_gpu_name(gpu_model)
    if not canon:
        return None
    # Build a case-insensitive view of the table on first call; the table
    # is small enough that doing it inline is fine.
    for key, label in GPU_TO_BOARD.items():
        if canon.lower() == key.lower():
            return label
    return None


# ---------------------------------------------------------------------------
# Chip brand inference (used by ingest/catalog_resolve.py)
# ---------------------------------------------------------------------------


def infer_cpu_brand(model: str) -> Optional[str]:
    """Best-effort CPU brand from a model string."""
    if not model:
        return None
    low = model.lower()
    if "intel" in low or "core" in low or "xeon" in low or "pentium" in low:
        return "Intel"
    if "amd" in low or "ryzen" in low or "epyc" in low or "athlon" in low:
        return "AMD"
    if "snapdragon" in low or "qualcomm" in low:
        return "Qualcomm"
    if "apple" in low and ("m1" in low or "m2" in low or "m3" in low or "m4" in low):
        return "Apple"
    return None


def infer_gpu_brand(model: str) -> Optional[str]:
    """Best-effort GPU brand from a model string."""
    if not model:
        return None
    low = model.lower()
    if "nvidia" in low or "geforce" in low or "rtx" in low or "gtx" in low:
        return "NVIDIA"
    if "amd" in low or "radeon" in low or "rdna" in low:
        return "AMD"
    if "intel" in low or "arc" in low or "iris" in low:
        return "Intel"
    return None


# ---------------------------------------------------------------------------
# Camera resolution normalization (shared by Lenovo + ASUS bridges)
# ---------------------------------------------------------------------------


# Megapixel → vertical-pixel form for typical laptop webcam sensors.
# Lenovo PSREF advertises camera resolution in MP (``"5.0MP"``); some
# ASUS pages do the same. Dell / HP publish vertical-pixel form
# (``"720p"`` / ``"1080p"`` / ``"4K"``). Normalize MP into the same
# enum so the catalog is comparable across vendors. Values not in this
# table are kept as the raw ``NMP`` form with ``status="needs-review"``
# so manual review can normalize anything unusual.
CAMERA_MP_TO_P_FORM = {
    "0.9": "720p",
    "1.0": "720p",
    "2.0": "1080p",
    "5.0": "1440p",
    "8.0": "4K",
}


def normalize_camera_resolution(label: str) -> tuple[str, str]:
    """Map a regex-matched camera-resolution label to canonical p-form.

    Accepts the labels matched by the shared camera-resolution regex —
    ``720p / 1080p / 1440p / 4K / FHD / HD / UHD / NMP`` (case-
    insensitive). Returns ``(value, status)``:

    * Known forms (p-form, FHD/HD/UHD/4K, MP in
      ``CAMERA_MP_TO_P_FORM``) → canonical p-form value with
      ``status="verified"``.
    * MP values not in the table → raw ``NMP`` form with
      ``status="needs-review"`` so manual review can normalize them.
    """
    low = label.strip().lower()
    if low == "fhd":
        return "1080p", "verified"
    if low == "hd":
        return "720p", "verified"
    if low in ("uhd", "4k"):
        return "4K", "verified"
    if "mp" in low:
        mp_str = re.sub(r"\s*mp\s*$", "", low, flags=re.IGNORECASE).strip()
        normalized = CAMERA_MP_TO_P_FORM.get(mp_str)
        if normalized is not None:
            return normalized, "verified"
        return mp_str.upper().replace(" ", "") + "MP", "needs-review"
    # Already in p-form (720p / 1080p / 1440p).
    return low, "verified"
