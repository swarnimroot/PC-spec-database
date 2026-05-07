"""One-shot helper: fetch a Dell URL and dump snapshots to JSON fixtures.

Usage::

    python scripts/capture_dell.py <url> <slug>

Writes ``tests/fixtures/dell/snapshot_<oc>.json`` for each tile produced by
``fetch_dell_product``. If the live fetch fails (Akamai block, Playwright
issue, etc.), prints the exception and exits non-zero so the caller knows
to fall back to synthetic fixtures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scrapers_lib import Anchor, AttributionRegex
from scrapers_lib.tier2.dell import fetch_dell_product


def main(url: str, slug: str) -> int:
    out_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "dell"
    out_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir = Path(__file__).resolve().parent.parent / ".profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    anchor = Anchor(
        anchor_id=slug,
        anchor_type="product",
        name=slug,
        attribution_regex=AttributionRegex(primary=[slug]),
        source_urls={"dell": url},
    )

    try:
        snapshots = fetch_dell_product(
            url,
            anchors=[anchor],
            profiles_dir=str(profiles_dir),
            warm=True,
        )
    except Exception as e:  # pragma: no cover - live fetch
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    print(f"Got {len(snapshots)} snapshot(s).")
    for snap in snapshots:
        oc = snap.source_id
        path = out_dir / f"snapshot_{oc}.json"
        path.write_text(snap.model_dump_json(indent=2), encoding="utf-8")
        print(f"  -> {path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))
