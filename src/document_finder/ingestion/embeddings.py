"""Semantic-index boundary; intentionally no model or FAISS work in Phase 1."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    model_name: str

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Return one embedding for each text."""


class OcrProvider(Protocol):
    def extract_text(self, source_path: str) -> str:
        """Return OCR text for a source document in a later phase."""


class EmbeddingsDeferred(RuntimeError):
    """Raised if semantic indexing is requested before its dedicated phase."""
