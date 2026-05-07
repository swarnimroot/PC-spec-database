"""Debug helper: parse one fixture snapshot and print the resulting candidate."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from scrapers_lib import ProductSnapshot

from competitive_database.bridge import dell as dell_bridge


def main(path: str) -> int:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    # Strip synthetic-only keys before validating.
    for k in list(raw.keys()):
        if k.startswith("_"):
            raw.pop(k)
    snap = ProductSnapshot.model_validate(raw)
    cand = dell_bridge.parse(snap)
    print(json.dumps(asdict(cand), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
