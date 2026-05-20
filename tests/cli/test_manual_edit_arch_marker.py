"""Stage 7 T7.0a M7 — manual-edit shape fix for plain-shape board leaves.

The bridge (``bridge/lenovo.py``) and the backfill CLI stamp
``arch_marker`` on each board as a plain string. ``_merge_boards``,
``_gpu_id`` and ``views/boards.py::render`` all read it as a plain
string. Before M7, ``manual-edit`` wrapped every write in a manual
bundle — so a hand-edit on ``boards.N.arch_marker`` landed a dict
that the rest of the codebase didn't recognize: the bundle would
split merge groups silently, and the render would skip the line.

These tests pin the post-fix behaviour: manual-edit routes
``boards.N.arch_marker`` writes through the plain-leaf path so the
stored shape matches what the bridge writes.
"""

from __future__ import annotations

import argparse

from competitive_database.bridge.types import CandidateProduct
from competitive_database.cli import manual_edit
from competitive_database.db.connection import apply_schema, connect, transaction
from competitive_database.db.helpers import (
    make_scraped_bundle,
    read_offerings,
    write_offerings,
    write_scalar,
)
from competitive_database.ingest.runner import _merge_boards
from competitive_database.views.boards import render
from competitive_database.views.load import load_product


_PK = {"model_code": "legion-pro-5-16-gen-10", "year": 2025}
_DB_NAME = "me_arch.db"
_SOURCE_URL = "https://psref.lenovo.com/example"
_CAPTURED_AT = "2026-05-08T00:00:00+00:00"


def _fresh_db(tmp_path):
    conn = connect(tmp_path / _DB_NAME)
    with transaction(conn):
        apply_schema(conn)
    return conn


def _scraped(value, status="verified"):
    return make_scraped_bundle(
        value=value,
        source_url=_SOURCE_URL,
        captured_at=_CAPTURED_AT,
        scraper_id="test",
        status=status,
    )


def _seed_product(tmp_path, *, arch_marker="intel-rtx"):
    """Write one Lenovo-shaped row with one board carrying arch_marker."""
    conn = _fresh_db(tmp_path)
    try:
        # arch_marker is stamped as a plain string on the board entry
        # (mirrors bridge/lenovo.py:148-150).
        board = {
            "label": _scraped("MB1"),
            "tgp_max": _scraped(140),
            "tpp_max": _scraped(None, status="vendor-doesn't-publish"),
            "gpus": [_scraped("RTX 5070")],
            "arch_marker": arch_marker,
        }
        with transaction(conn):
            write_scalar(
                conn, "products", _PK, "brand", _scraped("Lenovo")
            )
            write_offerings(conn, "products", _PK, "boards", [board])
    finally:
        conn.close()


def _manual_edit_args(tmp_path, *, field, value, value_json=None):
    return argparse.Namespace(
        product=_PK["model_code"],
        year=_PK["year"],
        field=field,
        value=value,
        value_json=value_json,
        note=None,
        status="vouched",
        entered_by="tester",
        source_url=None,
        db=str(tmp_path / _DB_NAME),
    )


# ---------------------------------------------------------------------------
# 1. Hand-edit round-trip via manual-edit's actual write path
# ---------------------------------------------------------------------------


def test_manual_edit_arch_marker_writes_plain_string(tmp_path, capsys):
    """``boards.0.arch_marker`` writes a plain string (not a manual bundle).

    Stored shape must match the bridge's shape so ``_merge_boards``,
    ``_gpu_id`` and ``views/boards.py::render`` all keep working.
    """
    _seed_product(tmp_path, arch_marker="intel-rtx")

    args = _manual_edit_args(
        tmp_path, field="boards.0.arch_marker", value="amd-radeon"
    )
    manual_edit.main(args)

    conn = connect(tmp_path / _DB_NAME)
    try:
        boards = read_offerings(conn, "products", _PK, "boards")
    finally:
        conn.close()

    assert boards is not None and len(boards) == 1
    # Plain string, not a bundle dict.
    assert boards[0]["arch_marker"] == "amd-radeon"
    assert not isinstance(boards[0]["arch_marker"], dict)

    out = capsys.readouterr().out
    assert "manual-edit OK" in out
    # Confirmation line uses the plain-shape format.
    assert "before: value='intel-rtx' (plain)" in out
    assert "after:  value='amd-radeon' (plain)" in out


# ---------------------------------------------------------------------------
# 2. _merge_boards keys correctly after a hand-edit
# ---------------------------------------------------------------------------


def test_merge_boards_after_arch_marker_hand_edit_keys_correctly(tmp_path):
    """After a hand-edit through ``manual-edit``, ``_merge_boards`` still
    keys boards on the plain ``arch_marker`` value. A bridge-derived
    board with ``arch_marker="amd-radeon"`` merges with the edited one
    (same arch), and one with ``arch_marker="intel-rtx"`` stays distinct
    (different arch)."""
    _seed_product(tmp_path, arch_marker="intel-rtx")

    # Hand-edit arch_marker via manual-edit.
    args = _manual_edit_args(
        tmp_path, field="boards.0.arch_marker", value="amd-radeon"
    )
    manual_edit.main(args)

    # Reload the edited boards into a synthetic CandidateProduct (this is
    # how ``_premerge_lenovo_existing_row`` does it).
    conn = connect(tmp_path / _DB_NAME)
    try:
        edited_boards = read_offerings(conn, "products", _PK, "boards")
    finally:
        conn.close()
    edited_holder = CandidateProduct(model_code=_PK["model_code"], year=2025)
    edited_holder.boards = edited_boards

    # Build a fresh bridge-shape candidate with a *different* arch_marker
    # value, same label → should stay distinct after merge.
    intel_holder = CandidateProduct(model_code=_PK["model_code"], year=2025)
    intel_holder.boards = [
        {
            "label": _scraped("MB1"),
            "tgp_max": _scraped(140),
            "tpp_max": _scraped(None, status="vendor-doesn't-publish"),
            "gpus": [_scraped("RTX 5070")],
            "arch_marker": "intel-rtx",
        }
    ]

    merged_distinct = _merge_boards([edited_holder, intel_holder])
    assert merged_distinct is not None
    # Two entries — different arch_markers → different keys.
    assert len(merged_distinct) == 2
    arches = {b.get("arch_marker") for b in merged_distinct}
    assert arches == {"amd-radeon", "intel-rtx"}

    # And a same-arch candidate merges into the edited entry.
    amd_holder = CandidateProduct(model_code=_PK["model_code"], year=2025)
    amd_holder.boards = [
        {
            "label": _scraped("MB1"),
            "tgp_max": _scraped(120),
            "tpp_max": _scraped(None, status="vendor-doesn't-publish"),
            "gpus": [_scraped("RX 9070")],
            "arch_marker": "amd-radeon",
        }
    ]
    merged_same = _merge_boards([edited_holder, amd_holder])
    assert merged_same is not None
    assert len(merged_same) == 1
    assert merged_same[0]["arch_marker"] == "amd-radeon"
    # GPUs unioned across the two same-arch boards.
    gpu_names = {g["value"] for g in merged_same[0]["gpus"]}
    assert gpu_names == {"RTX 5070", "RX 9070"}


# ---------------------------------------------------------------------------
# 3. render still produces clean output after a hand-edit
# ---------------------------------------------------------------------------


def test_render_after_arch_marker_hand_edit_has_no_dict_leak(tmp_path):
    """After a manual-edit on ``boards.0.arch_marker``, the Graphics
    view renders without leaking the underlying dict literal.

    Stage 10b note: ``arch_marker`` itself no longer surfaces in the
    rendered view (the Graphics rollup shows only board labels for
    NVIDIA / brand for AMD/Intel). The hand-edit + load round-trip is
    covered by ``test_load_product_decodes_plain_arch_marker_after_hand_edit``;
    this test only guards against a regression where a stored bundle or
    raw dict leaks into the rendered output.
    """
    _seed_product(tmp_path, arch_marker="intel-rtx")

    args = _manual_edit_args(
        tmp_path, field="boards.0.arch_marker", value="amd-radeon"
    )
    manual_edit.main(args)

    conn = connect(tmp_path / _DB_NAME)
    try:
        product = load_product(conn, _PK["model_code"], _PK["year"])
    finally:
        conn.close()

    out = render(product, {})
    # No raw-dict leak.
    assert "{'value':" not in out
    assert "'arch_marker'" not in out


# ---------------------------------------------------------------------------
# 4. load_product round-trip after the hand-edit
# ---------------------------------------------------------------------------


def test_load_product_decodes_plain_arch_marker_after_hand_edit(tmp_path):
    """``load_product`` returns the edited ``arch_marker`` as a plain
    string inside the boards JSON list (no bundle decode special-case
    needed — it's stored inside the offerings JSON array)."""
    _seed_product(tmp_path, arch_marker="intel-rtx")

    args = _manual_edit_args(
        tmp_path, field="boards.0.arch_marker", value="amd-radeon"
    )
    manual_edit.main(args)

    conn = connect(tmp_path / _DB_NAME)
    try:
        product = load_product(conn, _PK["model_code"], _PK["year"])
    finally:
        conn.close()
    boards = product["boards"]
    assert boards is not None and len(boards) == 1
    assert boards[0]["arch_marker"] == "amd-radeon"
    assert isinstance(boards[0]["arch_marker"], str)


# ---------------------------------------------------------------------------
# 5. Sanity: other (bundle-shaped) board leaves still write as bundles
# ---------------------------------------------------------------------------


def test_manual_edit_tgp_max_still_writes_bundle(tmp_path):
    """Sibling regression test — ``boards.0.tgp_max`` is a regular
    bundle-shape leaf. The plain-leaf branch must not steal writes to
    other board leaves; they keep their manual-bundle scaffolding."""
    _seed_product(tmp_path, arch_marker="intel-rtx")

    args = _manual_edit_args(
        tmp_path, field="boards.0.tgp_max", value="175"
    )
    manual_edit.main(args)

    conn = connect(tmp_path / _DB_NAME)
    try:
        boards = read_offerings(conn, "products", _PK, "boards")
    finally:
        conn.close()
    assert boards is not None
    tgp = boards[0]["tgp_max"]
    # Bundle dict, not a plain int.
    assert isinstance(tgp, dict)
    assert tgp["value"] == 175
    assert tgp["entered_by"] == "tester"
    assert tgp["status"] == "vouched"
    # Sibling arch_marker untouched.
    assert boards[0]["arch_marker"] == "intel-rtx"
