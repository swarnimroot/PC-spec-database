"""Snapshot → CandidateProduct dispatch by ``snapshot.source``.

Each vendor has one parser module. The dispatcher is the single entry
point the runner calls; new vendors are added by registering them here.
"""

from __future__ import annotations

from scrapers_lib import ProductSnapshot

from . import dell as dell_bridge
from .types import CandidateProduct


_PARSERS = {
    "dell": dell_bridge.parse,
    # Stage 3+ adds: "hp": hp_bridge.parse, "lenovo": ..., "asus": ...
}


def dispatch(snapshot: ProductSnapshot) -> CandidateProduct:
    """Route ``snapshot`` to the correct vendor parser.

    Raises :class:`ValueError` if no parser is registered for the
    snapshot's ``source``.
    """
    parser = _PARSERS.get(snapshot.source)
    if parser is None:
        raise ValueError(
            f"no bridge parser registered for source {snapshot.source!r}; "
            f"known sources: {sorted(_PARSERS)}"
        )
    return parser(snapshot)
