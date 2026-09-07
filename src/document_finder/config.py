"""Corpus location configuration.

The corpus root used to be the hardcoded, repository-relative `data/`
directory. It is now read from the environment so a customer's own document
folder can be served without editing code:

    DOCUMENT_FINDER_DATA_ROOT=/path/to/customer/documents

Defaults keep the previous development behaviour exactly: with nothing set the
corpus root is `data/`, the SQLite index is `data/document_finder.sqlite3`, and
the vector index is `data/vector/qwen3_embedding_0_6b.faiss`.

Values are read on each call rather than cached at import, so a process can be
started with different settings without reloading modules.
"""

from __future__ import annotations

import os
from pathlib import Path


DATA_ROOT_VARIABLE = "DOCUMENT_FINDER_DATA_ROOT"
DATABASE_VARIABLE = "DOCUMENT_FINDER_DATABASE"
INDEX_VARIABLE = "DOCUMENT_FINDER_INDEX"
QUERY_UNDERSTANDING_VARIABLE = "QUERY_UNDERSTANDING_ENABLED"
MIN_REDUCTION_VARIABLE = "QUERY_UNDERSTANDING_MIN_REDUCTION"

DEFAULT_DATA_ROOT = Path("data")
DATABASE_FILENAME = "document_finder.sqlite3"
VECTOR_INDEX_RELATIVE = Path("vector") / "qwen3_embedding_0_6b.faiss"

# A clarification question must at least halve the candidate set to be worth
# asking. Chosen as a round, explainable rule rather than fitted to any
# labelled dataset: a question that removes less than half the work costs the
# user a round trip for little gain. Override with
# QUERY_UNDERSTANDING_MIN_REDUCTION (0.0 asks whenever any narrowing exists,
# 1.0 effectively never asks).
DEFAULT_MIN_CLARIFICATION_REDUCTION = 0.5


def data_root() -> Path:
    """The folder holding the customer's documents, and the corpus the API serves."""
    configured = os.environ.get(DATA_ROOT_VARIABLE, "").strip()
    return Path(configured) if configured else DEFAULT_DATA_ROOT


def database_path() -> Path:
    """SQLite index location; defaults to inside the corpus root."""
    configured = os.environ.get(DATABASE_VARIABLE, "").strip()
    return Path(configured) if configured else data_root() / DATABASE_FILENAME


def index_path() -> Path:
    """Persisted FAISS index location; defaults to inside the corpus root."""
    configured = os.environ.get(INDEX_VARIABLE, "").strip()
    return Path(configured) if configured else data_root() / VECTOR_INDEX_RELATIVE


def resolved_data_root() -> Path:
    """Absolute corpus root, used for containment checks and mismatch detection."""
    return data_root().resolve()


def describe() -> dict[str, str]:
    """Human-readable configuration, for CLI output. Not returned by the API."""
    return {
        "data_root": str(resolved_data_root()),
        "database": str(database_path()),
        "index": str(index_path()),
    }


def _flag(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def query_understanding_enabled() -> bool:
    """Whether the clarification layer runs in front of search.

    Defaults to enabled: this is the customer-facing flow Phase 16 introduces,
    the layer only speaks up for ambiguous queries, and it falls back to normal
    search on any failure. Setting QUERY_UNDERSTANDING_ENABLED=false restores
    the exact pre-Phase-16 behaviour.
    """
    configured = os.environ.get(QUERY_UNDERSTANDING_VARIABLE)
    return True if configured is None else _flag(configured)


def min_clarification_reduction() -> float:
    """Smallest worst-case candidate reduction that justifies asking a question."""
    configured = os.environ.get(MIN_REDUCTION_VARIABLE, "").strip()
    if not configured:
        return DEFAULT_MIN_CLARIFICATION_REDUCTION
    try:
        return min(max(float(configured), 0.0), 1.0)
    except ValueError:
        return DEFAULT_MIN_CLARIFICATION_REDUCTION
