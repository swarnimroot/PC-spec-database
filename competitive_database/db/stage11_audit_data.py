"""Structured per-row audit data for the Stage 11 identity-hierarchy migration.

Mirrors ``docs/STAGE11_AUDIT.md`` (the human-reviewed source of truth). 76 source
rows in the catalog + 1 net-new product (Dell ``da15260``) → 56 final product
rows. Read by ``_migrate_products_stage11_pk`` in ``connection.py``.
"""

from __future__ import annotations

from typing import TypedDict


class Stage11Product(TypedDict):
    """One target row in the post-migration ``products`` table.

    ``source_model_codes`` lists the current-row ``model_code`` keys that merge
    into this product. For a non-merged row, the list has one entry. The
    survivor of each merge group is the first entry; all other entries are
    deleted from ``products`` after the migration unions their data into the
    survivor (today: survivor data is kept; non-survivor data is dropped — a
    future refresh pass can scrape all source URLs into one row).
    """

    product: str
    year: int
    sub_brand: str | None
    series: str | None
    source_model_codes: list[str]


# ---------------------------------------------------------------------------
# ASUS — 28 source rows → 22 product rows (5 merges, 0 year corrections)

ASUS: list[Stage11Product] = [
    {"product": "V16",          "year": 2026, "sub_brand": None,  "series": "V",        "source_model_codes": ["asus-v16-v3607"]},
    {"product": "Flow Z13",     "year": 2025, "sub_brand": "ROG", "series": "Flow",     "source_model_codes": ["rog-flow-z13-2025"]},
    {"product": "Strix G16",    "year": 2025, "sub_brand": "ROG", "series": "Strix",    "source_model_codes": ["rog-strix-g16-2025", "rog-strix-g16-2025-g614"]},
    {"product": "Strix G16",    "year": 2026, "sub_brand": "ROG", "series": "Strix",    "source_model_codes": ["rog-strix-g16-2026"]},
    {"product": "Strix G18",    "year": 2025, "sub_brand": "ROG", "series": "Strix",    "source_model_codes": ["rog-strix-g18-2025-g814"]},
    {"product": "Strix G18",    "year": 2026, "sub_brand": "ROG", "series": "Strix",    "source_model_codes": ["rog-strix-g18-2026"]},
    {"product": "Strix Scar 16","year": 2025, "sub_brand": "ROG", "series": "Strix",    "source_model_codes": ["rog-strix-scar-16-2025"]},
    {"product": "Strix Scar 18","year": 2025, "sub_brand": "ROG", "series": "Strix",    "source_model_codes": ["rog-strix-scar-18-2025"]},
    {"product": "Strix Scar 18","year": 2026, "sub_brand": "ROG", "series": "Strix",    "source_model_codes": ["rog-strix-scar-18-2026"]},
    {"product": "Zephyrus Duo", "year": 2026, "sub_brand": "ROG", "series": "Zephyrus", "source_model_codes": ["rog-zephyrus-duo-2026"]},
    {"product": "Zephyrus G14", "year": 2025, "sub_brand": "ROG", "series": "Zephyrus", "source_model_codes": ["rog-zephyrus-g14-2025"]},
    {"product": "Zephyrus G14", "year": 2026, "sub_brand": "ROG", "series": "Zephyrus", "source_model_codes": ["rog-zephyrus-g14-2026-gu405"]},
    {"product": "Zephyrus G16", "year": 2025, "sub_brand": "ROG", "series": "Zephyrus", "source_model_codes": ["rog-zephyrus-g16-2025-gu605"]},
    {"product": "Zephyrus G16", "year": 2026, "sub_brand": "ROG", "series": "Zephyrus", "source_model_codes": ["rog-zephyrus-g16-2026"]},
    {"product": "TUF 14",       "year": 2025, "sub_brand": None,  "series": "TUF",      "source_model_codes": ["asus-tuf-gaming-a14-2025"]},
    {"product": "TUF 14",       "year": 2026, "sub_brand": None,  "series": "TUF",      "source_model_codes": ["asus-tuf-gaming-a14-2026-fa401ea"]},
    {"product": "TUF 15",       "year": 2023, "sub_brand": None,  "series": "TUF",      "source_model_codes": ["asus-tuf-gaming-f15-2023", "asus-tuf-gaming-a15-2023"]},
    {"product": "TUF 16",       "year": 2024, "sub_brand": None,  "series": "TUF",      "source_model_codes": ["asus-tuf-gaming-f16-2024", "asus-tuf-gaming-a16-2024", "asus-tuf-gaming-a16-2024-fa608"]},
    {"product": "TUF 16",       "year": 2025, "sub_brand": None,  "series": "TUF",      "source_model_codes": ["asus-tuf-gaming-f16-2025", "asus-tuf-gaming-a16-2025"]},
    {"product": "TUF 16",       "year": 2026, "sub_brand": None,  "series": "TUF",      "source_model_codes": ["asus-tuf-gaming-f16-2026"]},
    {"product": "TUF 17",       "year": 2023, "sub_brand": None,  "series": "TUF",      "source_model_codes": ["asus-tuf-gaming-f17-2023", "asus-tuf-gaming-a17-2023"]},
    {"product": "TUF 18",       "year": 2025, "sub_brand": None,  "series": "TUF",      "source_model_codes": ["asus-tuf-gaming-a18-2025"]},
]


# ---------------------------------------------------------------------------
# Dell — 5 source rows → 5 product rows (incl. 1 net-new `da15260`)

DELL: list[Stage11Product] = [
    {"product": "Alienware 15", "year": 2026, "sub_brand": "Alienware", "series": None,      "source_model_codes": ["da15260"]},
    {"product": "Area-51 16",   "year": 2026, "sub_brand": "Alienware", "series": "Area-51", "source_model_codes": ["aa16250"]},
    {"product": "Area-51 18",   "year": 2026, "sub_brand": "Alienware", "series": "Area-51", "source_model_codes": ["aa18250"]},
    {"product": "Aurora 16",    "year": 2026, "sub_brand": "Alienware", "series": "Aurora",  "source_model_codes": ["ac16250"]},
    {"product": "Aurora 16X",   "year": 2026, "sub_brand": "Alienware", "series": "Aurora",  "source_model_codes": ["ac16251"]},
]

# `da15260` is net-new — does not exist in the current DB. The migration
# inserts a minimal product row before applying the audit (so the survivor
# row exists for the audit to point at). Future curation backfills specs.
DELL_NEW_PRODUCTS: list[dict] = [
    {
        "model_code": "da15260",
        "year": 2026,
        "vendor_full_name_value": "Alienware 15 Gaming Laptop",
        "source_url": "https://www.dell.com/en-us/shop/dell-laptops/alienware-15/spd/alienware-15-da15260",
    },
]


# ---------------------------------------------------------------------------
# HP — 23 source rows → 9 product rows (14 merges, 18 year corrections)

HP: list[Stage11Product] = [
    # Legacy OMEN (Sub-brand=OMEN, Series=NULL — all corrected to year=2025 from 2026)
    {"product": "OMEN 16",          "year": 2025, "sub_brand": "OMEN", "series": None, "source_model_codes": ["16-ap0047nr", "16-ap0097nr", "16t-am000", "16z-ap000"]},
    {"product": "OMEN 17",          "year": 2025, "sub_brand": "OMEN", "series": None, "source_model_codes": ["17-db1097nr"]},
    {"product": "OMEN Max 16",      "year": 2025, "sub_brand": "OMEN", "series": None, "source_model_codes": ["16-ah0057nr", "16-ah0097nr", "16-ak0047nr", "16-ak0098nr", "16t-ah000", "16z-ak000"]},
    {"product": "OMEN Slim 16",     "year": 2025, "sub_brand": "OMEN", "series": None, "source_model_codes": ["16t-an000"]},
    {"product": "OMEN Transcend 14","year": 2025, "sub_brand": "OMEN", "series": None, "source_model_codes": ["14-fb1047nr", "14t-fb100"]},
    # HyperX OMEN (Sub-brand=HyperX, Series=OMEN — CES 2026 launches stay at 2026)
    {"product": "OMEN 15",          "year": 2026, "sub_brand": "HyperX", "series": "OMEN", "source_model_codes": ["15-gb0261nr", "15t-ga000", "hyperx-omen-15-inch-gaming-laptop-pc-gb0xxx-c51tpav-1", "hyperx-omen-gaming-laptop-15-gb0xxx-15-cj9d8av-1"]},
    {"product": "OMEN Max 16",      "year": 2026, "sub_brand": "HyperX", "series": "OMEN", "source_model_codes": ["16t-ah100"]},
    # Victus (Sub-brand=NULL, Series=Victus)
    {"product": "Victus 15", "year": 2024, "sub_brand": None, "series": "Victus", "source_model_codes": ["15-fa2047nr", "15-fb3025nr"]},
    {"product": "Victus 15", "year": 2025, "sub_brand": None, "series": "Victus", "source_model_codes": ["15t-fa200", "15z-fb300"]},
]


# ---------------------------------------------------------------------------
# Lenovo — 21 source rows → 20 product rows (1 merge, 1 year correction)

LENOVO: list[Stage11Product] = [
    # LOQ — sub_brand reclassifies LOQ → NULL; series := LOQ
    {"product": "LOQ 15",           "year": 2024, "sub_brand": None, "series": "LOQ", "source_model_codes": ["loq-15-gen-9"]},
    {"product": "LOQ 15",           "year": 2025, "sub_brand": None, "series": "LOQ", "source_model_codes": ["loq-15-gen-10"]},
    {"product": "LOQ 15",           "year": 2026, "sub_brand": None, "series": "LOQ", "source_model_codes": ["loq-15-gen-11"]},
    {"product": "LOQ 17",           "year": 2025, "sub_brand": None, "series": "LOQ", "source_model_codes": ["loq-17-gen-10"]},
    {"product": "LOQ Essential 15", "year": 2026, "sub_brand": None, "series": "LOQ", "source_model_codes": ["loq-essential-15-gen-11"]},
    # Legion 5 / 7 / 9 — series stays at family root; Pro modifier rides on Product
    {"product": "Legion 5 15",      "year": 2024, "sub_brand": "Legion", "series": "Legion 5", "source_model_codes": ["legion-5-15-gen-9"]},
    {"product": "Legion 5 15",      "year": 2025, "sub_brand": "Legion", "series": "Legion 5", "source_model_codes": ["legion-5-15-gen-10"]},
    {"product": "Legion 5 15",      "year": 2026, "sub_brand": "Legion", "series": "Legion 5", "source_model_codes": ["legion-5-15-gen-11"]},
    {"product": "Legion 5 16",      "year": 2024, "sub_brand": "Legion", "series": "Legion 5", "source_model_codes": ["legion-5-16-gen-9"]},
    {"product": "Legion 5 16",      "year": 2025, "sub_brand": "Legion", "series": "Legion 5", "source_model_codes": ["legion-5-16-gen-10"]},
    {"product": "Legion Pro 5 16",  "year": 2023, "sub_brand": "Legion", "series": "Legion 5", "source_model_codes": ["legion-pro-5-16-gen-8"]},
    {"product": "Legion Pro 5 16",  "year": 2024, "sub_brand": "Legion", "series": "Legion 5", "source_model_codes": ["legion-pro-5-16-gen-9"]},
    {"product": "Legion Pro 5 16",  "year": 2025, "sub_brand": "Legion", "series": "Legion 5", "source_model_codes": ["legion-pro-5-16-gen-10"]},
    {"product": "Legion 7 16",      "year": 2024, "sub_brand": "Legion", "series": "Legion 7", "source_model_codes": ["legion-7-16-gen-9"]},
    {"product": "Legion 7 16",      "year": 2025, "sub_brand": "Legion", "series": "Legion 7", "source_model_codes": ["legion-7-16-gen-10"]},
    {"product": "Legion 7 16",      "year": 2026, "sub_brand": "Legion", "series": "Legion 7", "source_model_codes": ["legion-7-16-gen-11"]},
    {"product": "Legion Pro 7 16",  "year": 2024, "sub_brand": "Legion", "series": "Legion 7", "source_model_codes": ["legion-pro-7-16-gen-9"]},
    # Orphan `16AFR10H` (brand=NULL row) merges into legion-pro-7-16-gen-10 here.
    # legion-pro-7-16-gen-10 is the survivor (it already has populated specs); the
    # orphan is deleted. The survivor's source_model_codes column (Stage-7 inner
    # codes) is appended with "16AFR10H" by the migration.
    {"product": "Legion Pro 7 16",  "year": 2025, "sub_brand": "Legion", "series": "Legion 7", "source_model_codes": ["legion-pro-7-16-gen-10", "16AFR10H"]},
    {"product": "Legion 9 16",      "year": 2024, "sub_brand": "Legion", "series": "Legion 9", "source_model_codes": ["legion-9-16-gen-9"]},
    {"product": "Legion 9 18",      "year": 2025, "sub_brand": "Legion", "series": "Legion 9", "source_model_codes": ["legion-9-18-gen-10"]},
]


# ---------------------------------------------------------------------------
# Brand → audit slice mapping (driven by the row's existing ``brand`` value)

AUDIT_BY_BRAND: dict[str, list[Stage11Product]] = {
    "ASUS":   ASUS,
    "Dell":   DELL,
    "HP":     HP,
    "Lenovo": LENOVO,
}


def all_products() -> list[tuple[str, Stage11Product]]:
    """Yield ``(brand, product_row)`` pairs for every post-migration product row."""
    out: list[tuple[str, Stage11Product]] = []
    for brand, rows in AUDIT_BY_BRAND.items():
        for row in rows:
            out.append((brand, row))
    return out


# Summary numbers (for the migration's assertion check):
EXPECTED_FINAL_ROW_COUNT = 56  # 22 ASUS + 5 Dell + 9 HP + 20 Lenovo
EXPECTED_SOURCE_ROW_COUNT = 77  # 28 + 5 + 23 + 21 (5 Dell includes 1 net-new)
