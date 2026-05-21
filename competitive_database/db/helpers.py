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


def _normalize_products_pk(
    conn: sqlite3.Connection, pk: dict
) -> tuple[dict, str | None]:
    """Translate a legacy ``{"model_code": ..., "year": ...}`` pk dict into the
    post-Stage-11 ``{"product": ..., "year": ...}`` shape.

    Returns ``(new_pk, model_code_to_persist)`` where ``model_code_to_persist``
    is the model_code value the caller wanted to write — non-None whenever the
    caller passed a legacy pk dict, so the helper can persist it into the
    (non-PK) ``model_code`` column on first INSERT.

    Resolution rules when only ``model_code`` is provided:
      - If a row exists with that model_code + year, use its ``product`` value.
      - Otherwise fall back to ``product = model_code`` (placeholder; works for
        tests that construct fresh rows without a "real" product name).
    """
    if "product" in pk:
        return dict(pk), pk.get("model_code")
    if "model_code" not in pk or "year" not in pk:
        return dict(pk), None
    mc = pk["model_code"]
    year = pk["year"]
    row = conn.execute(
        "SELECT product FROM products WHERE model_code = ? AND year = ?",
        (mc, year),
    ).fetchone()
    product = row[0] if row and row[0] is not None else mc
    new_pk = {"product": product, "year": year}
    return new_pk, mc


def _upsert_one_field(
    conn: sqlite3.Connection,
    table: str,
    pk: dict,
    field: str,
    encoded_value: str,
) -> None:
    """INSERT-or-UPDATE one column on a row identified by ``pk``."""
    model_code_to_persist: str | None = None
    if table == "products":
        pk, model_code_to_persist = _normalize_products_pk(conn, pk)
    pk_cols, pk_placeholders, conflict_cols, pk_values = _format_pk_clause(pk)
    sql = (
        f"INSERT INTO {table} ({pk_cols}, {field}) "
        f"VALUES ({pk_placeholders}, ?) "
        f"ON CONFLICT({conflict_cols}) DO UPDATE SET {field} = excluded.{field}"
    )
    conn.execute(sql, [*pk_values, encoded_value])
    if (
        table == "products"
        and model_code_to_persist is not None
        and field != "model_code"
    ):
        # Caller passed a legacy pk that included model_code as part of row
        # identity. Persist it to the (non-PK) model_code column so reads via
        # ``WHERE model_code = ?`` still find the row.
        conn.execute(
            "UPDATE products SET model_code = ? "
            "WHERE product = ? AND year = ? AND (model_code IS NULL OR model_code = ?)",
            (
                model_code_to_persist,
                pk["product"],
                pk["year"],
                model_code_to_persist,
            ),
        )


def _read_one_field(
    conn: sqlite3.Connection,
    table: str,
    pk: dict,
    field: str,
) -> Optional[str]:
    """Read the raw text stored in ``field``. Returns None if row missing or NULL.

    Accepts both post-Stage-11 ``{"product": ..., "year": ...}`` and the
    legacy ``{"model_code": ..., "year": ...}`` pk shapes — the latter falls
    through as a WHERE-by-column lookup since ``model_code`` is still a row
    column post-Stage-11 (it's just no longer part of the PK).
    """
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
