"""ASUS TUF Intel/AMD merge at ingest (mirrors Lenovo's M4 path).

The bridge (``bridge/asus.py``) stamps every TUF F/A candidate with a
shared ``family_code`` plus a single-element ``source_model_codes`` and
tags each board with an ``arch_marker``. The ingest layer collapses
candidates that share a ``family_code`` into one row with PK
``(family_code, year)``: source codes accumulate, Intel and AMD boards
coexist.

The runner machinery is vendor-agnostic and is covered in detail by
``test_lenovo_merge.py``; tests here exist only to assert the ASUS
bridge participates in that path correctly.
"""

from __future__ import annotations

import json

from competitive_database.bridge.types import CandidateProduct
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import read_offerings
from competitive_database.ingest.runner import ingest_product


_CAPTURED = "2026-05-15T12:00:00+00:00"
_SCRAPER = "asus.fetch_asus_product"
_SRC_INTEL = "https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-f16-2025/"
_SRC_AMD = "https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a16-2025/"

_FAMILY = "asus-tuf-gaming-16-2025"
_INTEL_CODE = "asus-tuf-gaming-f16-2025"
_AMD_CODE = "asus-tuf-gaming-a16-2025"


def _bundle(value, source_url=_SRC_INTEL, status="verified"):
    return {
        "value": value,
        "source_url": source_url,
        "captured_at": _CAPTURED,
        "scraper_id": _SCRAPER,
        "status": status,
    }


def _board(label, gpus, arch_marker, source_url=_SRC_INTEL):
    entry = {
        "label": _bundle(label, source_url=source_url),
        "tpp_max": _bundle(None, source_url=source_url, status="vendor-doesn't-publish"),
        "tgp_max": _bundle(None, source_url=source_url, status="vendor-doesn't-publish"),
        "gpus": [_bundle(g, source_url=source_url) for g in gpus],
    }
    if arch_marker is not None:
        entry["arch_marker"] = arch_marker
    return entry


def _asus_candidate(slug_code, arch_marker, gpu_names, *, source_url):
    """Build an ASUS-shaped candidate post-grouping coercion.

    The refresh CLI coerces ``model_code`` to ``family_code`` before the
    runner sees the candidate (cli/refresh.py); the test mimics that.
    """
    cand = CandidateProduct(model_code=_FAMILY, year=2025)
    cand.family_code = _FAMILY
    cand.source_model_codes = [slug_code]
    cand.vendor_full_name = _bundle(
        f"ASUS TUF Gaming 16 ({slug_code})", source_url=source_url
    )
    cand.boards = [_board("MB1", gpu_names, arch_marker, source_url=source_url)]
    return cand


def _conn(tmp_path):
    c = connect(tmp_path / "asus_merge.db")
    with transaction(c):
        apply_schema(c)
    return c


def _pk():
    return {"product": _FAMILY, "year": 2025}


def test_asus_single_snapshot_writes_family_code_and_source_codes(tmp_path):
    conn = _conn(tmp_path)
    try:
        cand = _asus_candidate(
            _INTEL_CODE, "intel", ["RTX 5070"], source_url=_SRC_INTEL
        )
        ingest_product(conn, [cand])

        row = conn.execute(
            "SELECT model_code, family_code, source_model_codes FROM products "
            "WHERE model_code = ? AND year = ?",
            (_FAMILY, 2025),
        ).fetchone()
        assert row is not None
        assert row["model_code"] == _FAMILY
        assert row["family_code"] == _FAMILY
        assert json.loads(row["source_model_codes"]) == [_INTEL_CODE]

        boards = read_offerings(conn, "products", _pk(), "boards")
        assert boards is not None and len(boards) == 1
        assert boards[0]["arch_marker"] == "intel"
    finally:
        conn.close()


def test_asus_tuf_intel_amd_merge_in_same_batch(tmp_path):
    conn = _conn(tmp_path)
    try:
        intel = _asus_candidate(
            _INTEL_CODE, "intel", ["RTX 5070"], source_url=_SRC_INTEL
        )
        amd = _asus_candidate(
            _AMD_CODE, "amd", ["RTX 5070"], source_url=_SRC_AMD
        )
        report = ingest_product(conn, [intel, amd])

        assert report.conflicts == 0

        boards = read_offerings(conn, "products", _pk(), "boards")
        assert boards is not None and len(boards) == 2
        arches = {b.get("arch_marker") for b in boards}
        assert arches == {"intel", "amd"}

        row = conn.execute(
            "SELECT family_code, source_model_codes FROM products "
            "WHERE model_code = ? AND year = ?",
            (_FAMILY, 2025),
        ).fetchone()
        assert row["family_code"] == _FAMILY
        assert set(json.loads(row["source_model_codes"])) == {
            _INTEL_CODE,
            _AMD_CODE,
        }
    finally:
        conn.close()
