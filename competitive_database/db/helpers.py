"""Single write gateway for the database.

All writes to ``cpu_catalog``, ``gpu_catalog``, ``products`` (excluding the
plain PK columns) and the various offering arrays go through these helpers.
The helpers do NOT manage transactions — the caller is expected to wrap
calls in a ``transaction(conn)`` block from ``connection.py``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


# --- Status enums --------------------------------------------------------

_SCRAPED_STATUSES = {"verified", "needs-review", "vendor-doesn't-publish"}
# Stage 10a: ``manual`` joins ``vouched`` / ``needs-review`` as a real third
# status value so the Edit UI's "manual" pill no longer aliases to vouched.
_MANUAL_STATUSES = {"vouched", "needs-review", "manual"}


# --- Bundle factories ----------------------------------------------------


def make_scraped_bundle(
    value: Any,
    source_url: str,
    captured_at: str,
    scraper_id: str,
    status: str = "verified",
) -> dict:
    """Build a scraped-cell provenance bundle (dict; does not write)."""
    if status not in _SCRAPED_STATUSES:
        raise ValueError(
            f"invalid scraped status {status!r}; expected one of {sorted(_SCRAPED_STATUSES)}"
        )
    return {
        "value": value,
        "source_url": source_url,
        "captured_at": captured_at,
        "scraper_id": scraper_id,
        "status": status,
    }


def make_manual_bundle(
    value: Any,
    entered_by: str,
    source_note: Optional[str] = None,
    status: str = "vouched",
    entered_at: Optional[str] = None,
    source_url: Optional[str] = None,
) -> dict:
    """Build a manual-cell provenance bundle (dict; does not write).

    ``entered_at`` defaults to the current UTC time as ISO-8601.
    ``source_url`` is optional and only persisted when non-None.
    """
    if status not in _MANUAL_STATUSES:
        raise ValueError(
            f"invalid manual status {status!r}; expected one of {sorted(_MANUAL_STATUSES)}"
        )
    if entered_at is None:
        entered_at = datetime.now(timezone.utc).isoformat()
    bundle: dict = {
        "value": value,
        "source_note": source_note,
        "entered_by": entered_by,
        "entered_at": entered_at,
        "status": status,
    }
    if source_url is not None:
        bundle["source_url"] = source_url
    return bundle


def make_vendor_doesnt_publish_bundle(
    source_url: str,
    captured_at: str,
    scraper_id: str,
) -> dict:
    """Convenience wrapper for ``status='vendor-doesn't-publish'`` bundles."""
    return make_scraped_bundle(
        value=None,
        source_url=source_url,
        captured_at=captured_at,
        scraper_id=scraper_id,
        status="vendor-doesn't-publish",
    )


# --- Internal helpers ----------------------------------------------------


def _format_pk_clause(pk: dict) -> tuple[str, str, str, list]:
    """Build the SQL fragments for a PK dict.

    Returns ``(pk_cols, pk_placeholders, pk_conflict_cols, pk_values)`` where:
      - ``pk_cols`` is e.g. ``"product, year"`` (post-Stage-11 canonical PK).
      - ``pk_placeholders`` is e.g. ``"?, ?"``
      - ``pk_conflict_cols`` is the same as pk_cols (used in ``ON CONFLICT(...)``)
      - ``pk_values`` is the list of bound values in the matching order
    """
    if not pk:
        raise ValueError("pk must be a non-empty dict")
    cols = list(pk.keys())
    pk_cols = ", ".join(cols)
    pk_placeholders = ", ".join(["?"] * len(cols))
    pk_values = [pk[c] for c in cols]
    return pk_cols, pk_placeholders, pk_cols, pk_values


# --- Products PK resolution (Stage 11) ------------------------------------


def resolve_products_pk(
    conn: sqlite3.Connection, model_code: str, year: int
) -> dict:
    """Resolve a vendor ``(model_code, year)`` identity to the canonical
    ``{"product": ..., "year": ...}`` pk dict (post-Stage-11 PK).

    Callers that key on the vendor slug (CLI ``--model`` flags, ingest
    candidates, ``review_queue`` rows) resolve once at pk-construction time;
    every ``db.helpers`` read/write then takes the strict pk shape.

    Resolution rules:
      - If a row exists with that model_code + year, use its ``product`` value
        (so refreshes target a user-renamed product, not the slug).
      - Otherwise fall back to ``product = model_code`` (placeholder for
        brand-new rows; matches what ``ingest`` writes on first insert).
    """
    row = conn.execute(
        "SELECT product FROM products WHERE model_code = ? AND year = ?",
        (model_code, year),
    ).fetchone()
    product = row[0] if row and row[0] is not None else model_code
    return {"product": product, "year": year}


def write_model_code(
    conn: sqlite3.Connection, pk: dict, model_code: str
) -> None:
    """Persist the vendor slug into the (non-PK) ``model_code`` column.

    Guarded: a row whose model_code is already set to a *different* slug is
    left alone (e.g. a Lenovo row renamed to its family_code). Keeps reads
    via ``WHERE model_code = ?`` working for rows created through the strict
    ``(product, year)`` pk.
    """
    conn.execute(
        "UPDATE products SET model_code = ? "
        "WHERE product = ? AND year = ? AND (model_code IS NULL OR model_code = ?)",
        (model_code, pk["product"], pk["year"], model_code),
    )


def _upsert_one_field(
    conn: sqlite3.Connection,
    table: str,
    pk: dict,
    field: str,
    encoded_value: str,
) -> None:
    """INSERT-or-UPDATE one column on a row identified by ``pk``."""
    pk_cols, pk_placeholders, conflict_cols, pk_values = _format_pk_clause(pk)
    sql = (
        f"INSERT INTO {table} ({pk_cols}, {field}) "
        f"VALUES ({pk_placeholders}, ?) "
        f"ON CONFLICT({conflict_cols}) DO UPDATE SET {field} = excluded.{field}"
    )
    conn.execute(sql, [*pk_values, encoded_value])


def _read_one_field(
    conn: sqlite3.Connection,
    table: str,
    pk: dict,
    field: str,
) -> Optional[str]:
    """Read the raw text stored in ``field``. Returns None if row missing or NULL."""
    cols = list(pk.keys())
    where = " AND ".join(f"{c} = ?" for c in cols)
    values = [pk[c] for c in cols]
    sql = f"SELECT {field} FROM {table} WHERE {where}"
    row = conn.execute(sql, values).fetchone()
    if row is None:
        return None
    raw = row[0]
    if raw is None:
        return None
    return raw


# --- Scalar bundle I/O ---------------------------------------------------


def write_scalar(
    conn: sqlite3.Connection,
    table: str,
    pk: dict,
    field: str,
    bundle: dict,
) -> None:
    """Write one provenance bundle into a scalar bundle column."""
    encoded = json.dumps(bundle)
    _upsert_one_field(conn, table, pk, field, encoded)


def read_scalar(
    conn: sqlite3.Connection,
    table: str,
    pk: dict,
    field: str,
) -> Optional[dict]:
    """Read a scalar bundle column and decode it to a dict.

    Returns None if the row is missing or the column is NULL.
    """
    raw = _read_one_field(conn, table, pk, field)
    if raw is None:
        return None
    return json.loads(raw)


# --- Offerings I/O -------------------------------------------------------


def write_offerings(
    conn: sqlite3.Connection,
    table: str,
    pk: dict,
    field: str,
    offerings: list[dict[str, dict]],
) -> None:
    """Write an offerings list (list of dicts of leaf bundles) to one column."""
    encoded = json.dumps(offerings)
    _upsert_one_field(conn, table, pk, field, encoded)


def read_offerings(
    conn: sqlite3.Connection,
    table: str,
    pk: dict,
    field: str,
) -> Optional[list[dict[str, dict]]]:
    """Read and decode an offerings list. Returns None if missing/NULL."""
    raw = _read_one_field(conn, table, pk, field)
    if raw is None:
        return None
    return json.loads(raw)


# --- Stage 11 Phase 3 read-side query helpers ----------------------------
#
# These power the picker UI: brand -> series -> product -> year/status. They
# all read from ``products`` and unwrap the ``$.value`` path of bundle
# columns. ``series`` NULL surfaces as the literal sentinel ``"—"`` (em dash)
# so callers can render it as a real option instead of dropping the row.

_SERIES_NULL_SENTINEL = "—"  # em dash


def list_brand_options(conn: sqlite3.Connection) -> list[str]:
    """DISTINCT brand values across all products, alphabetical ascending."""
    rows = conn.execute(
        "SELECT DISTINCT json_extract(brand, '$.value') AS v "
        "FROM products "
        "WHERE json_extract(brand, '$.value') IS NOT NULL "
        "ORDER BY v ASC"
    ).fetchall()
    return [r[0] for r in rows]


def list_series_options(conn: sqlite3.Connection, brand: str) -> list[str]:
    """DISTINCT series values for ``brand``; NULL surfaces as ``"—"``.

    Result is alphabetical ascending, with the NULL sentinel sorted in by
    its codepoint (em dash sorts after ASCII letters).
    """
    rows = conn.execute(
        "SELECT DISTINCT json_extract(series, '$.value') AS v "
        "FROM products "
        "WHERE json_extract(brand, '$.value') = ? "
        "ORDER BY v ASC",
        (brand,),
    ).fetchall()
    return [r[0] if r[0] is not None else _SERIES_NULL_SENTINEL for r in rows]


def list_product_options(
    conn: sqlite3.Connection, brand: str, series: Optional[str]
) -> list[str]:
    """DISTINCT product names for ``(brand, series)``, alphabetical.

    ``series=None`` matches rows where ``series IS NULL``; otherwise the
    ``$.value`` path is compared to ``series``.
    """
    if series is None:
        sql = (
            "SELECT DISTINCT product FROM products "
            "WHERE json_extract(brand, '$.value') = ? "
            "AND series IS NULL "
            "ORDER BY product ASC"
        )
        params: tuple = (brand,)
    else:
        sql = (
            "SELECT DISTINCT product FROM products "
            "WHERE json_extract(brand, '$.value') = ? "
            "AND json_extract(series, '$.value') = ? "
            "ORDER BY product ASC"
        )
        params = (brand, series)
    rows = conn.execute(sql, params).fetchall()
    return [r[0] for r in rows]


def list_all_product_identities(conn: sqlite3.Connection) -> list[dict]:
    """DISTINCT ``(brand, series, product)`` identities across all products.

    Ordered by brand, then series, then product. NULL series is kept as
    ``None``. Each dict matches the picker's return shape
    ``{"brand": str, "series": str | None, "product": str}``. Powers the
    single-search product combobox (one type-to-filter list instead of the
    3-rung cascade). Reads the stored series value directly, so products
    with a non-null series surface with their real series here.
    """
    rows = conn.execute(
        "SELECT DISTINCT json_extract(brand, '$.value') AS b, "
        "json_extract(series, '$.value') AS s, product AS p "
        "FROM products "
        "WHERE json_extract(brand, '$.value') IS NOT NULL "
        "ORDER BY b ASC, s ASC, p ASC"
    ).fetchall()
    return [{"brand": r[0], "series": r[1], "product": r[2]} for r in rows]


def list_years_for_product(
    conn: sqlite3.Connection,
    brand: str,
    series: Optional[str],
    product: str,
) -> list[int]:
    """DESC year list for the exact ``(brand, series, product)`` identity."""
    if series is None:
        sql = (
            "SELECT year FROM products "
            "WHERE json_extract(brand, '$.value') = ? "
            "AND series IS NULL "
            "AND product = ? "
            "ORDER BY year DESC"
        )
        params: tuple = (brand, product)
    else:
        sql = (
            "SELECT year FROM products "
            "WHERE json_extract(brand, '$.value') = ? "
            "AND json_extract(series, '$.value') = ? "
            "AND product = ? "
            "ORDER BY year DESC"
        )
        params = (brand, series, product)
    rows = conn.execute(sql, params).fetchall()
    return [r[0] for r in rows]


def load_product_rows(
    conn: sqlite3.Connection,
    brand: str,
    series: Optional[str],
    product: str,
    years: list[int],
    statuses: list[str],
) -> list[dict]:
    """Fully load every ``(product, year)`` row matching the picker filters.

    Filtering rules:
      - empty ``years`` -> include all years for that product identity
      - empty ``statuses`` -> include all rows regardless of status
      - otherwise: include row if ``status.value IN statuses`` OR
        ``status IS NULL`` (NULL is treated as Active; 0/76 rows have
        status set today).

    Each returned dict is the same shape that ``views.load.load_product``
    produces (every bundle column decoded). The loader keys on
    ``model_code`` so we resolve that per row before delegating.
    """
    # Local import keeps ``db.helpers`` free of a module-level dependency on
    # the ``views`` package (which itself depends on ``db``).
    from ..views.load import load_product

    if series is None:
        base_sql = (
            "SELECT model_code, year, json_extract(status, '$.value') AS status_v "
            "FROM products "
            "WHERE json_extract(brand, '$.value') = ? "
            "AND series IS NULL "
            "AND product = ?"
        )
        base_params: list = [brand, product]
    else:
        base_sql = (
            "SELECT model_code, year, json_extract(status, '$.value') AS status_v "
            "FROM products "
            "WHERE json_extract(brand, '$.value') = ? "
            "AND json_extract(series, '$.value') = ? "
            "AND product = ?"
        )
        base_params = [brand, series, product]

    clauses: list[str] = []
    params: list = list(base_params)
    if years:
        clauses.append("year IN (" + ", ".join(["?"] * len(years)) + ")")
        params.extend(years)
    if statuses:
        placeholders = ", ".join(["?"] * len(statuses))
        clauses.append(
            f"(status_v IN ({placeholders}) OR status_v IS NULL)"
        )
        params.extend(statuses)
    sql = base_sql
    if clauses:
        sql += " AND " + " AND ".join(clauses)
    sql += " ORDER BY year DESC"

    rows = conn.execute(sql, params).fetchall()
    out: list[dict] = []
    for row in rows:
        out.append(load_product(conn, row["model_code"], row["year"]))
    return out
