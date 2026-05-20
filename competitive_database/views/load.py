"""Single-product DB read path used by the view layer.

The cell-bundle helpers in ``db/helpers.py`` work column-by-column. The
view layer needs every column at once for one product, so this module
adds a per-product loader and bulk catalog loaders.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

# Columns in ``products`` whose value is a list of offerings (each item
# is a dict-of-bundles), not a single scalar bundle.
_OFFERINGS_FIELDS = frozenset(
    {
        "cpu_offerings",
        "boards",
        "display_offerings",
        "battery_offerings",
        "keyboard_offerings",
        "storage_slots",
        "adapter_offerings",
        "camera_offerings",
    }
)

# Plain (non-bundle) products columns. ``family_code`` is plain TEXT.
# ``source_model_codes`` is stored as a JSON array of strings (see
# ``db/schema.sql``); it's decoded into a Python list below in a small
# special-case arm rather than left as raw JSON, so callers don't have
# to ``json.loads`` it themselves.
_PLAIN_PRODUCT_FIELDS = frozenset(
    {"model_code", "year", "family_code", "source_model_codes"}
)
_JSON_LIST_PRODUCT_FIELDS = frozenset({"source_model_codes"})

# In ``cpu_catalog`` / ``gpu_catalog`` JSON-bundled columns. The other
# spec columns (cores, clocks, etc.) are plain text seeded by the
# bridge layer; the columns below are curated and carry full provenance
# bundles (status + source_url + entered_by, etc.).
_CATALOG_BUNDLED_COLUMNS = frozenset(
    {
        "brand",
        # Stage 10b CPU catalog rollup fields (curated).
        "architecture_code",
        "architecture_name",
        "generation",
        # Stage 10b GPU catalog rollup fields (curated). ``architecture``
        # stays bundled for symmetry with the CPU side; ``brand`` was
        # already in the set.
        "architecture",
        "series",
        "board",
        "gpu_class",
    }
)


def resolve_year(conn: sqlite3.Connection, model_code: str) -> int:
    """Look up the row's year for one model_code. Errors if 0 or >1 match."""
    rows = conn.execute(
        "SELECT year FROM products WHERE model_code = ? ORDER BY year",
        (model_code,),
    ).fetchall()
    if not rows:
        raise LookupError(f"no product with model_code={model_code!r}")
    if len(rows) > 1:
        years = [r[0] for r in rows]
        raise LookupError(
            f"model_code={model_code!r} has {len(years)} variants "
            f"(years: {years}); pass --year to disambiguate"
        )
    return rows[0][0]


def load_product(
    conn: sqlite3.Connection,
    model_code: str,
    year: int | None = None,
) -> dict[str, Any]:
    """Read one full product row, decoding every bundled column.

    Returns a dict mapping each column to its decoded form:
      - PK columns (``model_code``, ``year``): plain Python value
      - offerings columns: ``list[dict[str, dict]]`` or None if NULL
      - all other columns: bundle dict or None if NULL
    """
    if year is None:
        year = resolve_year(conn, model_code)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(products)")]
    select = ", ".join(cols)
    row = conn.execute(
        f"SELECT {select} FROM products WHERE model_code = ? AND year = ?",
        (model_code, year),
    ).fetchone()
    if row is None:
        raise LookupError(
            f"no product with model_code={model_code!r} year={year}"
        )
    out: dict[str, Any] = {}
    for col, raw in zip(cols, row):
        if col in _PLAIN_PRODUCT_FIELDS:
            if col in _JSON_LIST_PRODUCT_FIELDS and raw is not None:
                out[col] = json.loads(raw)
            else:
                out[col] = raw
        elif raw is None:
            out[col] = None
        else:
            out[col] = json.loads(raw)
    return out


def _load_catalog(conn: sqlite3.Connection, table: str) -> dict[str, dict[str, Any]]:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        rec: dict[str, Any] = {}
        for col, raw in zip(cols, row):
            if col in _CATALOG_BUNDLED_COLUMNS and raw is not None:
                rec[col] = json.loads(raw)
            else:
                rec[col] = raw
        out[rec["model"]] = rec
    return out


def load_cpu_catalog(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """All cpu_catalog rows keyed by ``model``."""
    return _load_catalog(conn, "cpu_catalog")


def load_gpu_catalog(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """All gpu_catalog rows keyed by ``model``."""
    return _load_catalog(conn, "gpu_catalog")
