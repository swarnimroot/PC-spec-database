"""Bridge layer — vendor-specific parsers + shared helpers.

Each vendor module takes a :class:`scrapers_lib.ProductSnapshot` and emits a
:class:`competitive_database.bridge.types.CandidateProduct`. Bridge code does
NOT touch the database — that is the runner's job.
"""
