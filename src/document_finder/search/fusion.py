"""Generic rank fusion helpers for independent retrieval signals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[dict[str, Any]]], weights: Mapping[str, float], rank_constant: int = 60
) -> dict[str, float]:
    """Fuse ranked document results by document ID without comparing raw score scales."""
    scores: dict[str, float] = {}
    for name, results in rankings.items():
        weight = weights.get(name, 1.0)
        for rank, result in enumerate(results, start=1):
            document_id = result["document_id"]
            scores[document_id] = scores.get(document_id, 0.0) + weight / (rank_constant + rank)
    return scores
