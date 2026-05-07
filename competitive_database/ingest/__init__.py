"""Ingestion runner + catalog resolution.

The runner is the only writer to the database (other than the manual-edit
CLI). Bridge layer hands it a :class:`CandidateProduct`; the runner walks
each cell, decides whether to write, refresh, or queue, and applies the
result inside one SQLite transaction per snapshot.
"""
