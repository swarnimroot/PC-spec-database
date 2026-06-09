"""Streamlit-free curation queries powering the Curation Cockpit API.

This package holds the pure (no-Streamlit, no-HTTP) query layer that backs
the unified Curation Cockpit screen:

  - :mod:`.queue` — the scrape-conflict queue listing (extracted from
    ``ui/triage.py``'s ``_list_unresolved``, which was Streamlit-coupled at
    the module level) plus the field-state scan (needs-review / missing /
    hand-entered cells, derived by walking ``all_field_paths`` exactly the
    way ``cli/find_empty.py`` does).

These live outside ``ui/`` so both the FastAPI surface and any future CLI
can call them without importing Streamlit.
"""
