"""In-memory candidate-product shape emitted by each vendor parser.

A :class:`CandidateProduct` is a plain dataclass that mirrors the
``products`` row in :mod:`competitive_database.db.schema` plus the
two-column primary key ``(product, year)`` (Stage 11). ``model_code``
remains a non-PK identity column carrying the vendor-slug for the
survivor row of each (Product, Year) merge group.

Every populated cell carries a provenance bundle (or, for list-of-offerings
columns, a list of dicts whose leaves carry their own bundles). Cells the
parser did not attempt are absent from the dataclass — they remain ``None``.

The runner is the only consumer; nothing in this module touches SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# A scalar provenance bundle (see ``db/helpers.py`` for the canonical shape).
Bundle = dict[str, Any]

# A list-of-offerings column. Each offering is a dict whose leaf values are
# themselves Bundles (or, occasionally, plain Python primitives — but the
# parser is expected to wrap every leaf the schema cares about in a Bundle).
OfferingsList = list[dict[str, Bundle]]


@dataclass
class CandidateProduct:
    """All fields the bridge layer can populate for one product.

    The PK fields (``product`` and ``year``, Stage 11) and the row-identity
    column ``model_code`` are plain scalars: the schema stores them as plain
    SQL columns. The provenance for the derivation lives on
    ``vendor_full_name``.

    Every other attribute is optional. ``None`` means "the parser did not
    attempt this field"; the runner will simply not write that cell.
    """

    # --- Identity (PK columns are plain values, Stage 11) ---------------
    # ``model_code`` stays as a non-PK identity column carrying the vendor-
    # slug identifier of the survivor row of each (Product, Year) merge
    # group. ``year`` is the product GENERATION year. ``product`` is the
    # canonical readable product name (e.g. "Strix G16", "Legion Pro 7 16")
    # and is part of the post-Stage-11 PK; today bridges leave it as
    # ``None`` and the runner falls back to ``model_code`` as a placeholder
    # until per-bridge name derivation lands in a follow-up.
    model_code: str
    year: int
    product: Optional[str] = None

    # --- Identity flags (NOT written to the DB) ------------------------
    # ``year_was_inferred`` is True when the parser had to fall back to
    # ``snapshot.fetched_at.year`` because the title/URL did not carry a
    # year. The runner uses this to route ``vendor_full_name`` review
    # entries to the dedicated ``year_inferred`` queue type instead of the
    # generic ``low_confidence_extraction`` bucket.
    year_was_inferred: bool = False

    # --- Vendor multi-SKU merge (plain scalars, NOT bundles) ---------
    # ``family_code`` groups variants that share a physical platform.
    # Lenovo: ``legion-pro-5-16-gen-10`` covers Intel ``16IRX10`` + AMD
    # ``16ADR10``. ASUS TUF: ``asus-tuf-gaming-16-2025`` covers the F16
    # (Intel) and A16 (AMD) slugs. ``source_model_codes`` is the list of
    # vendor SKU codes that merged into this product (each parser emits
    # a single-element list; M4 merge ingest extends it). Both stay
    # ``None`` for bridges or slugs the parser couldn't recognize as
    # part of a merge pair — the runner skips merge dispatch then.
    family_code: Optional[str] = None
    source_model_codes: Optional[list[str]] = None

    # --- Identity (bundles) --------------------------------------------
    vendor_full_name: Optional[Bundle] = None
    brand: Optional[Bundle] = None
    sub_brand: Optional[Bundle] = None
    series: Optional[Bundle] = None
    status: Optional[Bundle] = None
    segment: Optional[Bundle] = None

    # --- CPU -----------------------------------------------------------
    cpu_offerings: Optional[OfferingsList] = None
    cpu_tdp_max: Optional[Bundle] = None

    # --- CPU chip specs (vendor-published, seeds cpu_catalog) ---------
    # Map of CPU model name → {column_name: value}. Column names match
    # bridge-seedable ``cpu_catalog`` columns (``cores``, ``npu_tops``,
    # ``base_clock``, ``boost_clock``, ``process_node``, ``nominal_tdp``).
    # The Stage 10b curated columns (``architecture_code`` /
    # ``architecture_name`` / ``generation``) are user-curated and NOT
    # seedable from scrapers. Values are stored as strings (matching the
    # column type), or ``None`` to indicate "vendor doesn't publish this
    # for this chip". Parsers only populate fields the vendor actually
    # publishes — catalog seed rules live in ``ingest/catalog_resolve.py``.
    cpu_chip_specs: dict[str, dict[str, Optional[str]]] = field(
        default_factory=dict
    )

    # --- GPU / power ---------------------------------------------------
    boards: Optional[OfferingsList] = None

    # --- Display -------------------------------------------------------
    display_offerings: Optional[OfferingsList] = None

    # --- Battery -------------------------------------------------------
    battery_offerings: Optional[OfferingsList] = None

    # --- Memory --------------------------------------------------------
    memory_max_gb: Optional[Bundle] = None
    memory_speed_mts: Optional[Bundle] = None
    memory_slots: Optional[Bundle] = None
    memory_type: Optional[Bundle] = None
    memory_overclocking: Optional[Bundle] = None

    # --- Storage -------------------------------------------------------
    storage_slots: Optional[OfferingsList] = None
    storage_max_gb: Optional[Bundle] = None

    # --- Network -------------------------------------------------------
    wifi_standard: Optional[Bundle] = None
    ethernet: Optional[Bundle] = None
    bluetooth_version: Optional[Bundle] = None

    # --- I/O (split scalar columns) ------------------------------------
    usbc_thunderbolt_count: Optional[Bundle] = None
    usbc_thunderbolt_version: Optional[Bundle] = None
    usbc_non_thunderbolt_count: Optional[Bundle] = None
    usbc_non_thunderbolt_version: Optional[Bundle] = None
    usba_count: Optional[Bundle] = None
    usba_version: Optional[Bundle] = None
    hdmi_count: Optional[Bundle] = None
    hdmi_version: Optional[Bundle] = None
    sd_card: Optional[Bundle] = None
    sd_card_speed: Optional[Bundle] = None
    audio_jack: Optional[Bundle] = None

    # --- Adapter -------------------------------------------------------
    adapter_offerings: Optional[OfferingsList] = None
    adapter_connector: Optional[Bundle] = None

    # --- Camera --------------------------------------------------------
    camera_offerings: Optional[OfferingsList] = None

    # --- Audio ---------------------------------------------------------
    speaker_count: Optional[Bundle] = None
    tuning_brand: Optional[Bundle] = None
    has_subwoofer: Optional[Bundle] = None

    # --- Keyboard ------------------------------------------------------
    keyboard_offerings: Optional[OfferingsList] = None

    # --- Thermals ------------------------------------------------------
    thermal_design: Optional[Bundle] = None
    thermal_material: Optional[Bundle] = None
    tim: Optional[Bundle] = None
    fan_count: Optional[Bundle] = None

    # --- Dimensions ----------------------------------------------------
    width_mm: Optional[Bundle] = None
    depth_mm: Optional[Bundle] = None
    height_mm_min: Optional[Bundle] = None
    height_mm_max: Optional[Bundle] = None

    # --- Weight --------------------------------------------------------
    weight_kg_min: Optional[Bundle] = None
    weight_kg_max: Optional[Bundle] = None

    # --- Design --------------------------------------------------------
    a_cover_material: Optional[Bundle] = None
    c_cover_material: Optional[Bundle] = None
    d_cover_material: Optional[Bundle] = None
    thermal_shelf: Optional[Bundle] = None
    lighting: Optional[Bundle] = None

    # --- Notes / debug -------------------------------------------------
    # Free-form bag of warnings or extraction notes; not written to the DB.
    notes: list[str] = field(default_factory=list)


# Ordered list of every column the runner is responsible for writing.
# (PK columns + ``notes`` deliberately excluded.) The runner uses this to
# walk the candidate fields uniformly.
SCALAR_FIELDS: tuple[str, ...] = (
    "vendor_full_name",
    "brand",
    "sub_brand",
    "series",
    "status",
    "segment",
    "cpu_tdp_max",
    "memory_max_gb",
    "memory_speed_mts",
    "memory_slots",
    "memory_type",
    "memory_overclocking",
    "storage_max_gb",
    "wifi_standard",
    "ethernet",
    "bluetooth_version",
    "usbc_thunderbolt_count",
    "usbc_thunderbolt_version",
    "usbc_non_thunderbolt_count",
    "usbc_non_thunderbolt_version",
    "usba_count",
    "usba_version",
    "hdmi_count",
    "hdmi_version",
    "sd_card",
    "sd_card_speed",
    "audio_jack",
    "adapter_connector",
    "speaker_count",
    "tuning_brand",
    "has_subwoofer",
    "thermal_design",
    "thermal_material",
    "tim",
    "fan_count",
    "width_mm",
    "depth_mm",
    "height_mm_min",
    "height_mm_max",
    "weight_kg_min",
    "weight_kg_max",
    "a_cover_material",
    "c_cover_material",
    "d_cover_material",
    "thermal_shelf",
    "lighting",
)

OFFERINGS_FIELDS: tuple[str, ...] = (
    "cpu_offerings",
    "boards",
    "display_offerings",
    "battery_offerings",
    "storage_slots",
    "adapter_offerings",
    "camera_offerings",
    "keyboard_offerings",
)
