"""Hybrid experiment: RRF over lexical/vector retrieval plus generic heading/title evidence."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from document_finder.search.fusion import reciprocal_rank_fusion
from document_finder.search.lexical import DEFAULT_DATABASE_PATH, search_lexical
from document_finder.search.vector import search_vector


_TOKEN = re.compile(r"[\w]+", re.UNICODE)
_STOPWORDS = {"a", "an", "and", "do", "for", "how", "i", "in", "is", "of", "on", "the", "to"}


@dataclass(frozen=True)
class HybridConfig:
    rrf_rank_constant: int = 60
    vector_weight: float = 1.0
    lexical_weight: float = 1.0
    heading_weight: float = 0.04
    title_weight: float = 0.025
    candidate_multiplier: int = 5


def _terms(query: str) -> list[str]:
    return [term.casefold() for term in _TOKEN.findall(query) if term.casefold() not in _STOPWORDS]


def _match_score(terms: list[str], text: str) -> tuple[float, bool]:
    words = _terms(text)
    if not terms or not words:
        return 0.0, False
    matched = sum(any(word == term or word.startswith(term) for word in words) for term in terms)
    phrase = " ".join(terms) in " ".join(words)
    return matched / len(terms), phrase


def heading_title_evidence(query: str, database_path: Path | str) -> list[dict[str, Any]]:
    """Return generic document evidence from headings, titles, and filenames only."""
    terms = _terms(query)
    if not terms:
        return []
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute("""
            SELECT d.document_id, d.filename, d.title, s.heading, s.section_path_json,
                   c.chunk_id, c.page
            FROM documents d JOIN sections s ON s.document_id=d.document_id
            JOIN chunks c ON c.section_id=s.section_id
            GROUP BY s.section_id
        """).fetchall()
    finally:
        connection.close()
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        heading_score, heading_phrase = _match_score(terms, row["heading"])
        title_score, title_phrase = _match_score(terms, f"{row['title'] or ''} {row['filename']}")
        evidence = max(heading_score + (0.25 if heading_phrase else 0), title_score + (0.15 if title_phrase else 0))
        if evidence <= 0:
            continue
        path = json.loads(row["section_path_json"])
        result = {"document_id": row["document_id"], "filename": row["filename"], "score": evidence,
                  "section": path[-1] if path else row["heading"], "page": row["page"],
                  "chunk_id": str(row["chunk_id"]), "heading_score": heading_score,
                  "title_score": title_score}
        previous = best.get(row["document_id"])
        if previous is None or result["score"] > previous["score"]:
            best[row["document_id"]] = result
    return sorted(best.values(), key=lambda item: (-item["score"], item["filename"]))


def search_hybrid(
    query: str, limit: int = 10, database_path: Path | str | None = None, config: HybridConfig = HybridConfig(),
    lexical_search: Callable[..., list[dict[str, Any]]] = search_lexical,
    vector_search: Callable[..., list[dict[str, Any]]] = search_vector,
) -> list[dict[str, Any]]:
    if not isinstance(query, str) or not query.strip() or limit < 1:
        return []
    database = Path(database_path or DEFAULT_DATABASE_PATH)
    candidate_limit = max(limit * config.candidate_multiplier, limit)
    lexical = lexical_search(query, candidate_limit, database)
    vector = vector_search(query, candidate_limit, database)
    heading = heading_title_evidence(query, database)
    rankings = {"lexical": lexical, "vector": vector}
    fused = reciprocal_rank_fusion(rankings, {"lexical": config.lexical_weight, "vector": config.vector_weight}, config.rrf_rank_constant)
    all_results: dict[str, dict[str, Any]] = {}
    for results in (vector, lexical, heading):
        for result in results:
            document_id = result["document_id"]
            existing = all_results.get(document_id)
            if existing is None or result.get("heading_score", 0) > existing.get("heading_score", 0):
                all_results[document_id] = result
    for result in heading:
        fused[result["document_id"]] = fused.get(result["document_id"], 0.0) + (
            config.heading_weight * result["heading_score"] + config.title_weight * result["title_score"]
        )
    ordered = sorted(all_results.values(), key=lambda result: (-fused.get(result["document_id"], 0.0), result["filename"]))
    return [{key: value for key, value in result.items() if key not in {"heading_score", "title_score"}} |
            {"score": fused.get(result["document_id"], 0.0)} for result in ordered[:limit]]
