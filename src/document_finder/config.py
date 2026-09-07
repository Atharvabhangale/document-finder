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

DEFAULT_DATA_ROOT = Path("data")
DATABASE_FILENAME = "document_finder.sqlite3"
VECTOR_INDEX_RELATIVE = Path("vector") / "qwen3_embedding_0_6b.faiss"


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
