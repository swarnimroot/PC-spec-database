"""Session 52 — apply the locked status curation rule to all products.

Rule (user-locked, Session 52):
    year IN (2025, 2026) -> status.value = "Active"
    year IN (2023, 2024) -> status.value = "Discontinued"

Bundle shape: manual provenance bundle produced by
``competitive_database.db.helpers.make_manual_bundle`` (status="vouched"),
which is the canonical scalar-bundle write path used by ``manual-edit``.

Idempotent: skips rows where the existing ``status.value`` already matches
the target. Single transaction; rolls back on any per-row failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/curate_status_session52.py` from the repo root.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from competitive_database.db.connection import connect, transaction
from competitive_database.db.helpers import make_manual_bundle, read_scalar, write_scalar


_DB_PATH = _ROOT / "competitive.db"

_ENTERED_BY = "session52-curation"
_SOURCE_NOTE = (
    "Session 52 status curation rule: "
    "year 2025/2026 -> Active; year 2023/2024 -> Discontinued"
)


def _target_status(year: int) -> str:
    if year in (2025, 2026):
        return "Active"
    if year in (2023, 2024):
        return "Discontinued"
    raise ValueError(f"year {year!r} outside curation rule (expected 2023-2026)")


def main() -> None:
    conn = connect(_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT product, year FROM products ORDER BY year, product"
        ).fetchall()
        updates_by_year: dict[int, int] = {}
        skipped_by_year: dict[int, int] = {}
        with transaction(conn):
            for row in rows:
                product = row["product"]
                year = row["year"]
                target = _target_status(year)
                pk = {"product": product, "year": year}
                current = read_scalar(conn, "products", pk, "status")
                current_value = (
                    current.get("value") if isinstance(current, dict) else None
                )
                if current_value == target:
                    skipped_by_year[year] = skipped_by_year.get(year, 0) + 1
                    continue
                bundle = make_manual_bundle(
                    value=target,
                    entered_by=_ENTERED_BY,
                    source_note=_SOURCE_NOTE,
                    status="vouched",
                )
                write_scalar(conn, "products", pk, "status", bundle)
                updates_by_year[year] = updates_by_year.get(year, 0) + 1
        total_updates = sum(updates_by_year.values())
        total_skipped = sum(skipped_by_year.values())
        print(f"curate-status: updated {total_updates} rows, skipped {total_skipped}")
        for year in sorted(set(updates_by_year) | set(skipped_by_year)):
            u = updates_by_year.get(year, 0)
            s = skipped_by_year.get(year, 0)
            print(f"  year={year}: updated={u}, skipped={s}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
