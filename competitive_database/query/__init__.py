"""Pure, importable spec-query engine.

No Streamlit, no UI imports — safe to call from a FastAPI backend or any
non-UI caller. Operates on loaded product dicts (the shape returned by
``views.load.load_product``).
"""

from __future__ import annotations

from competitive_database.query.engine import (
    OPS_ALL,
    OPS_NEED_VALUE,
    Op,
    apply_narrow_by,
    cell_matches,
    coerce_number,
    company_of,
    distinct_values_for_template,
    expand_template,
    find_matches,
    format_match,
    resolve_path,
    series_of,
    status_of,
    sub_brand_of,
    template_of,
    union_templates,
    year_of,
)

__all__ = [
    "Op",
    "OPS_ALL",
    "OPS_NEED_VALUE",
    "apply_narrow_by",
    "cell_matches",
    "coerce_number",
    "company_of",
    "distinct_values_for_template",
    "expand_template",
    "find_matches",
    "format_match",
    "resolve_path",
    "series_of",
    "status_of",
    "sub_brand_of",
    "template_of",
    "union_templates",
    "year_of",
]
