"""SQLite connection + transaction helpers."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Union

from .stage11_audit_data import (
    AUDIT_BY_BRAND,
    DELL_NEW_PRODUCTS,
    EXPECTED_FINAL_ROW_COUNT,
    Stage11Product,
    all_products,
)


_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open (or create) a SQLite DB at ``db_path``.

    Enables foreign-key enforcement and uses ``sqlite3.Row`` as the row
    factory so columns can be accessed by name.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Context manager that commits on success, rolls back on exception."""
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def apply_schema(conn: sqlite3.Connection) -> None:
    """Apply the bundled ``schema.sql`` and any in-place migrations.

    The base ``CREATE TABLE IF NOT EXISTS`` statements are idempotent for fresh
    DBs but do NOT add new columns to a table that already exists. For each
    post-Stage-1 column addition we issue an ``ALTER TABLE ... ADD COLUMN``
    guarded by a ``PRAGMA table_info`` check so the migration is idempotent.
    """
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    _migrate_products_add_lenovo_merge_columns(conn)
    _migrate_cpu_catalog_architecture_split(conn)
    _migrate_gpu_catalog_add_series_board(conn)
    _migrate_products_stage11_pk(conn)


def _migrate_products_add_lenovo_merge_columns(conn: sqlite3.Connection) -> None:
    """Stage 7 T7.0a M1: add ``family_code`` and ``source_model_codes`` to
    ``products`` if missing. Both columns are NULL on existing rows.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
    if "family_code" not in existing:
        conn.execute("ALTER TABLE products ADD COLUMN family_code TEXT")
    if "source_model_codes" not in existing:
        conn.execute("ALTER TABLE products ADD COLUMN source_model_codes TEXT")


def _migrate_cpu_catalog_architecture_split(conn: sqlite3.Connection) -> None:
    """Stage 10b: rename ``cpu_catalog.architecture`` to ``architecture_code``
    and add ``architecture_name`` + ``generation``. All three are JSON
    bundles (curated; populated via manual-edit).
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(cpu_catalog)")}
    if "architecture" in existing and "architecture_code" not in existing:
        conn.execute(
            "ALTER TABLE cpu_catalog RENAME COLUMN architecture TO architecture_code"
        )
        existing.add("architecture_code")
        existing.discard("architecture")
    if "architecture_name" not in existing:
        conn.execute("ALTER TABLE cpu_catalog ADD COLUMN architecture_name TEXT")
    if "generation" not in existing:
        conn.execute("ALTER TABLE cpu_catalog ADD COLUMN generation TEXT")


def _migrate_gpu_catalog_add_series_board(conn: sqlite3.Connection) -> None:
    """Stage 10b: add ``series``, ``board``, and ``gpu_class`` to
    ``gpu_catalog``. Existing ``architecture`` column kept as-is (will
    hold Blackwell / RDNA 4 / etc.). All four are JSON bundles;
    ``gpu_class`` values are ``"discrete"`` / ``"integrated"`` and gate
    whether the GPU contributes to the Graphics rollup.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(gpu_catalog)")}
    if "series" not in existing:
        conn.execute("ALTER TABLE gpu_catalog ADD COLUMN series TEXT")
    if "board" not in existing:
        conn.execute("ALTER TABLE gpu_catalog ADD COLUMN board TEXT")
    if "gpu_class" not in existing:
        conn.execute("ALTER TABLE gpu_catalog ADD COLUMN gpu_class TEXT")


# ---------------------------------------------------------------------------
# Stage 11 — identity hierarchy migration (Session 48)


_STAGE11_AUDIT_NOTE = "Stage 11 identity-hierarchy reclassification (Session 48)"
_STAGE11_ENTERED_BY = "stage11-migration"


def _stage11_manual_bundle(value, *, source_url=None) -> dict:
    """Build a manual provenance bundle for a Stage 11 audit override.

    Matches the ``make_manual_bundle`` shape in ``db/helpers.py`` so the
    rest of the codebase reads these uniformly.
    """
    bundle = {
        "value": value,
        "source_note": _STAGE11_AUDIT_NOTE,
        "entered_by": _STAGE11_ENTERED_BY,
        "entered_at": datetime.now(timezone.utc).isoformat(),
        "status": "vouched",
    }
    if source_url is not None:
        bundle["source_url"] = source_url
    return bundle


def _migrate_products_stage11_pk(conn: sqlite3.Connection) -> None:
    """Stage 11: add ``product`` column, reclassify ``sub_brand``/``series``
    per the locked audit, apply 19 year corrections, apply 20 cross-row
    merges (incl. the orphan ``16AFR10H``), insert net-new ``da15260``, and
    rebuild ``products`` with PK ``(product, year)`` replacing
    ``(model_code, year)``.

    Idempotent — runs only on legacy DBs where ``product`` column is missing
    AND there is at least one pre-Stage-11 row to migrate. Fresh DBs created
    via the post-Stage-11 ``schema.sql`` already have the new shape and skip
    this migration entirely. Legacy DBs with zero rows also skip (no data to
    migrate; PK swap is harmless either way).

    Source of truth for the audit: ``db/stage11_audit_data.py`` (which
    mirrors ``docs/STAGE11_AUDIT.md``).
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
    if "product" in cols:
        return  # already migrated, or fresh DB with post-Stage-11 schema
    row_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    conn.execute("ALTER TABLE products ADD COLUMN product TEXT")
    if row_count > 0:
        _stage11_insert_dell_new_products(conn)
        _stage11_apply_audit(conn)
        _stage11_assert_row_count(conn)
    _stage11_swap_primary_key(conn)


def _stage11_insert_dell_new_products(conn: sqlite3.Connection) -> None:
    """Insert net-new product rows that the audit will then reclassify.

    Today only ``da15260`` (Alienware 15, 2026). Minimal field set:
    ``brand``/``vendor_full_name`` as manual bundles; spec backfill deferred
    to future curation. Idempotent — skips rows that already exist.
    """
    for entry in DELL_NEW_PRODUCTS:
        mc = entry["model_code"]
        year = entry["year"]
        existing = conn.execute(
            "SELECT 1 FROM products WHERE model_code = ? AND year = ?",
            (mc, year),
        ).fetchone()
        if existing:
            continue
        brand_bundle = json.dumps(_stage11_manual_bundle("Dell"))
        vendor_full_name_bundle = json.dumps(
            _stage11_manual_bundle(
                entry["vendor_full_name_value"],
                source_url=entry["source_url"],
            )
        )
        conn.execute(
            "INSERT INTO products (model_code, year, brand, vendor_full_name) "
            "VALUES (?, ?, ?, ?)",
            (mc, year, brand_bundle, vendor_full_name_bundle),
        )


def _stage11_apply_audit(conn: sqlite3.Connection) -> None:
    """Apply per-brand reclassification + year corrections + merges.

    Iteration is by ``(brand, audit_row)`` from the structured audit. For
    each target product row:
      1. Look up the survivor by ``source_model_codes[0]``. (Pre-Stage-11
         ``model_code`` is unique across the table, so a model_code-only
         lookup suffices.)
      2. Apply year correction on the survivor if needed.
      3. Stamp ``product`` plain scalar + ``sub_brand``/``series`` manual
         bundles on the survivor.
      4. For each non-survivor source code: capture its source codes (or
         ``[model_code]`` if NULL), rewire any ``review_queue`` entries to
         the survivor, and delete the non-survivor row.
      5. Write the unioned + deduped ``source_model_codes`` list on the
         survivor.
    """
    for _brand, audit_row in all_products():
        _stage11_apply_one_audit_row(conn, audit_row)


def _stage11_apply_one_audit_row(
    conn: sqlite3.Connection, audit_row: Stage11Product
) -> None:
    sources = audit_row["source_model_codes"]
    survivor = sources[0]
    target_year = audit_row["year"]

    survivor_row = conn.execute(
        "SELECT model_code, year, source_model_codes "
        "FROM products WHERE model_code = ?",
        (survivor,),
    ).fetchone()
    if survivor_row is None:
        raise RuntimeError(
            f"Stage 11: survivor model_code {survivor!r} not found in products"
        )

    current_year = survivor_row["year"]
    if current_year != target_year:
        collision = conn.execute(
            "SELECT 1 FROM products WHERE model_code = ? AND year = ?",
            (survivor, target_year),
        ).fetchone()
        if collision:
            raise RuntimeError(
                f"Stage 11: year correction for {survivor!r} would collide "
                f"with existing row at year={target_year}"
            )
        conn.execute(
            "UPDATE products SET year = ? WHERE model_code = ? AND year = ?",
            (target_year, survivor, current_year),
        )
        conn.execute(
            "UPDATE review_queue SET product_year = ? "
            "WHERE product_model_code = ? AND product_year = ?",
            (target_year, survivor, current_year),
        )

    sub_brand_bundle = json.dumps(_stage11_manual_bundle(audit_row["sub_brand"]))
    series_bundle = json.dumps(_stage11_manual_bundle(audit_row["series"]))
    conn.execute(
        "UPDATE products SET product = ?, sub_brand = ?, series = ? "
        "WHERE model_code = ? AND year = ?",
        (audit_row["product"], sub_brand_bundle, series_bundle, survivor, target_year),
    )

    if survivor_row["source_model_codes"]:
        new_source_codes = list(json.loads(survivor_row["source_model_codes"]))
    else:
        new_source_codes = [survivor]

    for non_survivor in sources[1:]:
        row = conn.execute(
            "SELECT model_code, year, source_model_codes "
            "FROM products WHERE model_code = ?",
            (non_survivor,),
        ).fetchone()
        if row is not None:
            if row["source_model_codes"]:
                new_source_codes.extend(json.loads(row["source_model_codes"]))
            else:
                new_source_codes.append(non_survivor)
            conn.execute(
                "UPDATE review_queue SET product_model_code = ?, product_year = ? "
                "WHERE product_model_code = ? AND product_year = ?",
                (survivor, target_year, row["model_code"], row["year"]),
            )
            conn.execute(
                "DELETE FROM products WHERE model_code = ? AND year = ?",
                (row["model_code"], row["year"]),
            )
        else:
            new_source_codes.append(non_survivor)

    seen: set[str] = set()
    deduped: list[str] = []
    for code in new_source_codes:
        if code not in seen:
            seen.add(code)
            deduped.append(code)

    conn.execute(
        "UPDATE products SET source_model_codes = ? "
        "WHERE model_code = ? AND year = ?",
        (json.dumps(deduped), survivor, target_year),
    )


def _stage11_assert_row_count(conn: sqlite3.Connection) -> None:
    """Sanity check before the PK swap — exactly 56 rows should survive."""
    n = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if n != EXPECTED_FINAL_ROW_COUNT:
        raise RuntimeError(
            f"Stage 11: post-audit row count is {n}, expected "
            f"{EXPECTED_FINAL_ROW_COUNT}. Migration aborted."
        )
    null_products = conn.execute(
        "SELECT COUNT(*) FROM products WHERE product IS NULL"
    ).fetchone()[0]
    if null_products:
        raise RuntimeError(
            f"Stage 11: {null_products} rows have NULL product after audit. "
            "Migration aborted."
        )


def _stage11_swap_primary_key(conn: sqlite3.Connection) -> None:
    """Rebuild ``products`` with PK ``(product, year)`` replacing
    ``(model_code, year)``.

    SQLite cannot alter a PRIMARY KEY in place. We:
      1. CREATE TABLE products_new with the new PK and otherwise-identical schema.
      2. INSERT INTO products_new SELECT * FROM products.
      3. DROP TABLE products.
      4. ALTER TABLE products_new RENAME TO products.
      5. Recreate the existing indexes.
    """
    cols_info = list(conn.execute("PRAGMA table_info(products)"))
    columns = [row["name"] for row in cols_info]

    for idx in (
        "idx_products_brand",
        "idx_products_year",
        "idx_products_status",
        "idx_products_segment",
    ):
        conn.execute(f"DROP INDEX IF EXISTS {idx}")

    col_decls: list[str] = []
    for row in cols_info:
        name = row["name"]
        # ``year`` is INTEGER; everything else is TEXT (bundles or plain scalars
        # stored as JSON text).
        sql_type = "INTEGER" if name == "year" else "TEXT"
        if name in ("product", "year"):
            col_decls.append(f"    {name} {sql_type} NOT NULL")
        else:
            col_decls.append(f"    {name} {sql_type}")
    col_block = ",\n".join(col_decls)
    create_sql = (
        "CREATE TABLE products_new (\n"
        f"{col_block},\n"
        "    PRIMARY KEY (product, year)\n"
        ")"
    )
    conn.execute(create_sql)

    col_list = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    insert_sql = (
        f"INSERT INTO products_new ({col_list}) VALUES ({placeholders})"
    )
    rows = conn.execute(f"SELECT {col_list} FROM products").fetchall()
    for row in rows:
        conn.execute(insert_sql, [row[c] for c in columns])

    conn.execute("DROP TABLE products")
    conn.execute("ALTER TABLE products_new RENAME TO products")

    conn.execute(
        "CREATE INDEX idx_products_brand "
        "ON products(json_extract(brand, '$.value'))"
    )
    conn.execute("CREATE INDEX idx_products_year ON products(year)")
    conn.execute(
        "CREATE INDEX idx_products_status "
        "ON products(json_extract(status, '$.value'))"
    )
    conn.execute(
        "CREATE INDEX idx_products_segment "
        "ON products(json_extract(segment, '$.value'))"
    )
