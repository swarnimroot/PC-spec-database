"""Shared dotted-path helpers for ``manual-edit`` and ``resolve``.

A ``field_path`` references one fillable cell in the DB. Stage 5 supports
three forms:

  - Products scalar bundle:    ``vendor_full_name``, ``audio_jack``, ...
  - Products offering leaf:    ``display_offerings.0.nits_peak``
  - Catalog scalar (text):     ``cpu_catalog.<model>.architecture``
                               ``gpu_catalog.<model>.architecture``

PK columns (``model_code``, ``year`` on products; ``model`` on catalogs)
cannot be edited via this path syntax.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional

from ..db.helpers import (
    read_offerings,
    read_scalar,
    write_offerings,
    write_scalar,
)


_YEAR_SUFFIX_RE = re.compile(r"^(.+)-(\d{4})$")


_OFFERINGS_COLUMNS = frozenset(
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

_PRODUCT_PK_COLUMNS = frozenset({"model_code", "year"})

_CATALOG_TABLES = ("cpu_catalog", "gpu_catalog")


@dataclass(frozen=True)
class ParsedPath:
    kind: str  # "products_scalar" | "products_offering_leaf" | "catalog_text"
    table: str
    column: str
    offering_idx: Optional[int] = None
    leaf_key: Optional[str] = None
    catalog_model: Optional[str] = None


def parse_path(field_path: str) -> ParsedPath:
    """Parse a dotted ``field_path`` into a structured form."""
    if not field_path:
        raise ValueError("field_path must be non-empty")
    parts = field_path.split(".")
    head = parts[0]
    if head in _CATALOG_TABLES:
        if len(parts) != 3:
            raise ValueError(
                f"catalog path must be '<table>.<model>.<column>', got {field_path!r}"
            )
        return ParsedPath(
            kind="catalog_text",
            table=head,
            column=parts[2],
            catalog_model=parts[1],
        )
    if head in _PRODUCT_PK_COLUMNS:
        raise ValueError(f"cannot edit PK column {head!r} via field_path")
    if head in _OFFERINGS_COLUMNS:
        if len(parts) != 3:
            raise ValueError(
                f"offering path must be '<column>.<idx>.<leaf>', got {field_path!r}"
            )
        try:
            idx = int(parts[1])
        except ValueError as exc:
            raise ValueError(
                f"offering index must be an integer, got {parts[1]!r}"
            ) from exc
        return ParsedPath(
            kind="products_offering_leaf",
            table="products",
            column=head,
            offering_idx=idx,
            leaf_key=parts[2],
        )
    if len(parts) != 1:
        raise ValueError(
            f"unknown column {head!r} or malformed path {field_path!r}"
        )
    return ParsedPath(kind="products_scalar", table="products", column=head)


def read_at_path(
    conn: sqlite3.Connection,
    pk: dict,
    parsed: ParsedPath,
) -> Any:
    """Read the current value at the parsed path.

    Returns:
      - bundle dict (or None) for products_scalar / products_offering_leaf
      - plain string (or None) for catalog_text
    """
    if parsed.kind == "products_scalar":
        return read_scalar(conn, "products", pk, parsed.column)
    if parsed.kind == "products_offering_leaf":
        offerings = read_offerings(conn, "products", pk, parsed.column) or []
        assert parsed.offering_idx is not None
        if parsed.offering_idx >= len(offerings):
            return None
        return offerings[parsed.offering_idx].get(parsed.leaf_key)
    if parsed.kind == "catalog_text":
        row = conn.execute(
            f"SELECT {parsed.column} FROM {parsed.table} WHERE model = ?",
            (parsed.catalog_model,),
        ).fetchone()
        if row is None:
            return None
        return row[0]
    raise ValueError(f"unknown parsed kind {parsed.kind!r}")


def write_bundle_at_path(
    conn: sqlite3.Connection,
    pk: dict,
    parsed: ParsedPath,
    bundle: dict,
) -> None:
    """Write a provenance bundle at a products-table path."""
    if parsed.kind == "products_scalar":
        write_scalar(conn, "products", pk, parsed.column, bundle)
        return
    if parsed.kind == "products_offering_leaf":
        offerings = read_offerings(conn, "products", pk, parsed.column) or []
        assert parsed.offering_idx is not None
        if parsed.offering_idx >= len(offerings):
            raise IndexError(
                f"offering index {parsed.offering_idx} out of range "
                f"(have {len(offerings)} offerings on {parsed.column})"
            )
        offerings[parsed.offering_idx][parsed.leaf_key] = bundle
        write_offerings(conn, "products", pk, parsed.column, offerings)
        return
    raise ValueError(
        "cannot write bundle at catalog path; use write_catalog_text_at_path"
    )


def write_catalog_text_at_path(
    conn: sqlite3.Connection,
    parsed: ParsedPath,
    raw_value: Optional[str],
) -> None:
    """Write a plain-text value (or NULL) into a catalog scalar column."""
    if parsed.kind != "catalog_text":
        raise ValueError(
            f"write_catalog_text_at_path called with non-catalog path {parsed.kind!r}"
        )
    conn.execute(
        f"INSERT INTO {parsed.table} (model, {parsed.column}) "
        f"VALUES (?, ?) "
        f"ON CONFLICT(model) DO UPDATE SET {parsed.column} = excluded.{parsed.column}",
        (parsed.catalog_model, raw_value),
    )


def format_product_pk(model_code: str, year: int) -> str:
    """Format a product PK for display, collapsing a redundant year suffix.

    Most vendor slugs do not embed the model year, so the canonical
    display form is ``{model_code}-{year}``. ASUS ROG slugs *do* embed
    the year (``rog-strix-g16-2026``), which would otherwise render as
    ``rog-strix-g16-2026-2026``. When ``model_code`` already ends with
    ``-{year}``, return it unchanged.
    """
    suffix = f"-{year}"
    if model_code.endswith(suffix):
        return model_code
    return f"{model_code}{suffix}"


def parse_product_arg(
    conn: sqlite3.Connection,
    arg: str,
    *,
    year_arg: Optional[int] = None,
) -> tuple[str, Optional[int]]:
    """Resolve a user-supplied product argument to ``(model_code, year)``.

    Accepts both bare slug (``ac16251``) and the display form
    (``ac16251-2026``) printed by ``refresh`` and other CLIs.

    When the input ends with ``-YYYY``, prefer the split form
    (``model_code=ac16251``, ``year=2026``) iff a matching row exists.
    Otherwise fall back to treating the whole string as a model_code —
    that covers ASUS ROG slugs that bake the year into the URL token
    (``rog-strix-g16-2026``).

    An explicit ``year_arg`` always wins over a year inferred from the
    suffix.
    """
    suffix_match = _YEAR_SUFFIX_RE.match(arg)
    if suffix_match is not None:
        candidate_slug = suffix_match.group(1)
        candidate_year = int(suffix_match.group(2))
        row = conn.execute(
            "SELECT 1 FROM products WHERE model_code = ? AND year = ?",
            (candidate_slug, candidate_year),
        ).fetchone()
        if row is not None:
            return candidate_slug, year_arg if year_arg is not None else candidate_year
    return arg, year_arg
