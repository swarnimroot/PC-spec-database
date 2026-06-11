"""Stage 7 T7.0a M4 — Lenovo Intel/AMD merge at ingest.

The bridge layer (M2+M3) stamps every Lenovo candidate with a shared
``family_code`` plus a single-element ``source_model_codes`` and tags
each board with an ``arch_marker``. M4 makes the ingest layer collapse
candidates that share a ``family_code`` into one row with PK
``(family_code, year)``: the original machine codes accumulate in
``source_model_codes``, boards from both arches coexist, and a
later-week refresh that surfaces just one arch unions into the
existing row instead of duplicating.

Tests here cover only behaviour that's specific to the M4 path; the
generic ingest/diff semantics are exercised in ``test_runner.py``.
"""

from __future__ import annotations

import json

from competitive_database.bridge.types import CandidateProduct
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import read_offerings, read_scalar
from competitive_database.ingest.runner import ingest_product


_CAPTURED = "2026-05-08T12:00:00+00:00"
_SCRAPER = "lenovo.fetch_lenovo_product"
_SRC_INTEL = "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16IRX10"
_SRC_AMD = "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_5_16ADR10"

_FAMILY = "legion-pro-5-16-gen-10"
_INTEL_CODE = "16IRX10"
_AMD_CODE = "16ADR10"


def _bundle(value, source_url=_SRC_INTEL, captured_at=_CAPTURED, status="verified"):
    return {
        "value": value,
        "source_url": source_url,
        "captured_at": captured_at,
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


def _lenovo_candidate(
    machine_code, arch_marker, gpu_names, *, source_url, family_code=_FAMILY
):
    """Build a Lenovo-shaped candidate (model_code already coerced to family).

    The grouping layer in ``cli/refresh.py`` coerces ``model_code`` to
    ``family_code`` before the runner sees the candidate, so the tests
    mimic that here. The candidate carries the original machine code
    in ``source_model_codes``.
    """
    cand = CandidateProduct(model_code=family_code, year=2025)
    cand.family_code = family_code
    cand.source_model_codes = [machine_code]
    cand.vendor_full_name = _bundle(
        f"Lenovo Legion Pro 5 Gen 10 ({machine_code})", source_url=source_url
    )
    cand.boards = [_board("MB1", gpu_names, arch_marker, source_url=source_url)]
    return cand


def _conn(tmp_path):
    c = connect(tmp_path / "lenovo_merge.db")
    with transaction(c):
        apply_schema(c)
    return c


def _pk():
    return {"product": _FAMILY, "year": 2025}


# ---------------------------------------------------------------------------
# 1. Single-snapshot Lenovo ingest stamps family_code and source_model_codes
# ---------------------------------------------------------------------------


def test_lenovo_single_snapshot_writes_family_code_and_source_codes(tmp_path):
    """One Intel-only snapshot: one row, model_code=family_code,
    source_model_codes=[16IRX10], boards carry arch_marker."""
    conn = _conn(tmp_path)
    try:
        cand = _lenovo_candidate(
            _INTEL_CODE, "intel-nvidia", ["RTX 5070"], source_url=_SRC_INTEL
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
        assert boards[0]["arch_marker"] == "intel-nvidia"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Two-arch merge in same batch
# ---------------------------------------------------------------------------


def test_lenovo_two_arch_merge_in_same_batch(tmp_path):
    """Intel + AMD candidates in one refresh produce one row, 2 boards,
    and source_model_codes carries both machine codes (order-independent)."""
    conn = _conn(tmp_path)
    try:
        intel = _lenovo_candidate(
            _INTEL_CODE, "intel-nvidia", ["RTX 5070"], source_url=_SRC_INTEL
        )
        amd = _lenovo_candidate(
            _AMD_CODE, "amd-nvidia", ["RTX 5070"], source_url=_SRC_AMD
        )
        report = ingest_product(conn, [intel, amd])

        # No conflicts: boards keyed by (label, arch) so the two MB1
        # entries stay distinct.
        assert report.conflicts == 0

        boards = read_offerings(conn, "products", _pk(), "boards")
        assert boards is not None and len(boards) == 2
        arches = {b.get("arch_marker") for b in boards}
        assert arches == {"intel-nvidia", "amd-nvidia"}

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


# ---------------------------------------------------------------------------
# 3. Same family, different year — stays as two separate rows
# ---------------------------------------------------------------------------


def test_lenovo_same_family_different_year_stays_split(tmp_path):
    """Year is part of the PK — same family_code with different years
    produces two distinct rows."""
    conn = _conn(tmp_path)
    try:
        c2024 = _lenovo_candidate(
            "16IRX9", "intel-nvidia", ["RTX 4070"], source_url=_SRC_INTEL
        )
        c2024.year = 2024
        c2025 = _lenovo_candidate(
            _INTEL_CODE, "intel-nvidia", ["RTX 5070"], source_url=_SRC_INTEL
        )

        ingest_product(conn, [c2024])
        ingest_product(conn, [c2025])

        rows = conn.execute(
            "SELECT model_code, year FROM products WHERE family_code = ? "
            "ORDER BY year",
            (_FAMILY,),
        ).fetchall()
        assert [(r["model_code"], r["year"]) for r in rows] == [
            (_FAMILY, 2024),
            (_FAMILY, 2025),
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. AMD ingest after Intel row already exists — boards + source codes union
# ---------------------------------------------------------------------------


def test_lenovo_amd_ingest_merges_into_existing_intel_row(tmp_path):
    """Intel ingested first (one boards entry, one source code). AMD
    arrives in a later refresh — boards grows to two, source_model_codes
    grows to two. No value_disagreement on either column."""
    conn = _conn(tmp_path)
    try:
        intel = _lenovo_candidate(
            _INTEL_CODE, "intel-nvidia", ["RTX 5070"], source_url=_SRC_INTEL
        )
        ingest_product(conn, [intel])

        amd = _lenovo_candidate(
            _AMD_CODE, "amd-nvidia", ["RTX 5070"], source_url=_SRC_AMD
        )
        report = ingest_product(conn, [amd])

        # No conflict on boards — the pre-merge unioned Intel's existing
        # row with the AMD candidate before the diff ran.
        boards_conflicts = conn.execute(
            "SELECT COUNT(*) FROM review_queue WHERE field_path = 'boards'"
        ).fetchone()[0]
        assert boards_conflicts == 0

        boards = read_offerings(conn, "products", _pk(), "boards")
        assert boards is not None and len(boards) == 2
        arches = {b.get("arch_marker") for b in boards}
        assert arches == {"intel-nvidia", "amd-nvidia"}

        row = conn.execute(
            "SELECT source_model_codes FROM products "
            "WHERE model_code = ? AND year = ?",
            (_FAMILY, 2025),
        ).fetchone()
        assert set(json.loads(row["source_model_codes"])) == {
            _INTEL_CODE,
            _AMD_CODE,
        }

        # vendor_full_name legitimately differs ("…(16IRX10)" vs
        # "…(16ADR10)") — that's an expected value_disagreement that
        # the user will resolve manually. Just confirm the report
        # doesn't blow up.
        assert report is not None

        # Re-ingesting the Intel snapshot a third time is idempotent
        # on the columns the M4 path manages: boards count and
        # source_model_codes don't grow.
        ingest_product(conn, [intel])
        boards2 = read_offerings(conn, "products", _pk(), "boards")
        assert len(boards2) == 2
        row2 = conn.execute(
            "SELECT source_model_codes FROM products "
            "WHERE model_code = ? AND year = ?",
            (_FAMILY, 2025),
        ).fetchone()
        assert set(json.loads(row2["source_model_codes"])) == {
            _INTEL_CODE,
            _AMD_CODE,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. Non-Lenovo passthrough — family_code=None takes legacy path unchanged
# ---------------------------------------------------------------------------


def test_non_lenovo_candidate_takes_legacy_path(tmp_path):
    """An ASUS-shaped candidate (family_code=None, source_model_codes=None)
    writes a normal row keyed by its raw model_code — no Lenovo merge
    columns populated."""
    conn = _conn(tmp_path)
    try:
        cand = CandidateProduct(model_code="rog-zephyrus-g16-2026", year=2026)
        cand.vendor_full_name = _bundle(
            "ASUS ROG Zephyrus G16 (2026)",
            source_url="https://rog.asus.com/.../spec/",
        )
        ingest_product(conn, [cand])

        row = conn.execute(
            "SELECT model_code, family_code, source_model_codes FROM products "
            "WHERE model_code = ? AND year = ?",
            ("rog-zephyrus-g16-2026", 2026),
        ).fetchone()
        assert row is not None
        assert row["model_code"] == "rog-zephyrus-g16-2026"
        assert row["family_code"] is None
        assert row["source_model_codes"] is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. Lenovo with family_code=None (unparseable slug) — legacy path
# ---------------------------------------------------------------------------


def test_lenovo_unparseable_slug_falls_back_to_legacy(tmp_path):
    """When the bridge couldn't derive a family (family_code is None),
    the runner stamps no merge columns and the model_code stays as the
    raw machine code. Two such rows with different machine codes do
    NOT merge."""
    conn = _conn(tmp_path)
    try:
        cand_a = CandidateProduct(model_code="16IRX10", year=2025)
        cand_a.vendor_full_name = _bundle(
            "Lenovo Legion Pro 5 16IRX10", source_url=_SRC_INTEL
        )
        cand_b = CandidateProduct(model_code="16ADR10", year=2025)
        cand_b.vendor_full_name = _bundle(
            "Lenovo Legion Pro 5 16ADR10", source_url=_SRC_AMD
        )

        ingest_product(conn, [cand_a])
        ingest_product(conn, [cand_b])

        rows = conn.execute(
            "SELECT model_code, family_code, source_model_codes FROM products "
            "ORDER BY model_code"
        ).fetchall()
        assert [r["model_code"] for r in rows] == ["16ADR10", "16IRX10"]
        for r in rows:
            assert r["family_code"] is None
            assert r["source_model_codes"] is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. Scalar conflict between arches still routes to the conflict queue
# ---------------------------------------------------------------------------


def test_lenovo_scalar_conflict_between_arches_still_queues(tmp_path):
    """If Intel publishes weight_kg_max=2.5 and AMD publishes 2.6, the
    M4 merge does NOT collapse the conflict — scalars stay first-write-
    wins and the second value enqueues a value_disagreement. (Same
    behaviour as the existing cross-tile scalar-diff path.)"""
    conn = _conn(tmp_path)
    try:
        intel = _lenovo_candidate(
            _INTEL_CODE, "intel-nvidia", ["RTX 5070"], source_url=_SRC_INTEL
        )
        intel.weight_kg_max = _bundle(2.5, source_url=_SRC_INTEL)
        ingest_product(conn, [intel])

        amd = _lenovo_candidate(
            _AMD_CODE, "amd-nvidia", ["RTX 5070"], source_url=_SRC_AMD
        )
        amd.weight_kg_max = _bundle(2.6, source_url=_SRC_AMD)
        report = ingest_product(conn, [amd])

        assert report.conflicts >= 1
        rows = conn.execute(
            "SELECT conflict_type, field_path, candidate_value "
            "FROM review_queue WHERE field_path = 'weight_kg_max'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["conflict_type"] == "value_disagreement"
        assert json.loads(rows[0]["candidate_value"])["value"] == 2.6

        # Existing value untouched.
        got = read_scalar(conn, "products", _pk(), "weight_kg_max")
        assert got is not None
        assert got["value"] == 2.5
    finally:
        conn.close()
