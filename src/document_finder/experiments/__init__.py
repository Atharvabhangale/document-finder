"""Isolated experiments.

Nothing in this package is imported by the ingestion pipeline, the retrieval
modules, or the FastAPI application. Experiments read persisted corpus metadata
only; they never alter indexing, ranking, or API behaviour.
"""
