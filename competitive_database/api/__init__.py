"""Local FastAPI backend for the React Spec Finder screen.

Read-only HTTP surface over the importable data/query layer. No Streamlit
dependency — wraps ``db.helpers``, ``views.load`` / ``views.orchestrator``,
and the ``query`` engine only.
"""
