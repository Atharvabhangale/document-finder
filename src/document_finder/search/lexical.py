"""Document-level lexical baseline backed by the Phase 1 SQLite FTS5 index."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DATABASE_PATH = Path("data/document_finder.sqlite3")
_TERM_PATTERN = re.compile(r"[\w]+", re.UNICODE)


def _terms(query: str) -> list[str]:
    """Return FTS-safe lexical terms; no query syntax is accepted from callers."""
    return [term.casefold() for term in _TERM_PATTERN.findall(query)]


def _fts_query(terms: list[str]) -> str:
    # AND makes multi-term searches precise for this baseline and avoids FTS syntax injection.
    return " AND ".join(f'"{term}"' for term in terms)


def _filename_title_boost(filename: str, title: str | None, terms: list[str]) -> float:
    """A small deterministic boost for explicit document-name/title matches."""
    searchable = f"{filename} {title or ''}".casefold()
    matches = sum(term in searchable for term in terms)
    return 0.25 * matches / len(terms) if terms else 0.0


def _row_to_result(row: sqlite3.Row, terms: list[str], raw_rank: float) -> dict[str, Any]:
    # FTS5 bm25 is a negative value where values nearer negative infinity are better.
    score = max(0.0, -raw_rank) + _filename_title_boost(row["filename"], row["title"], terms)
    section_path = json.loads(row["section_path_json"])
    return {
        "document_id": row["document_id"],
        "filename": row["filename"],
        "score": score,
        "section": section_path[-1] if section_path else row["heading"],
        "page": row["page"],
        "chunk_id": str(row["chunk_id"]),
    }


def search_lexical(
    query: str, limit: int = 10, database_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """Search FTS5 chunks and return at most one best-evidence result per filename.

    `database_path` is optional to keep the normal command simple while allowing
    isolated test/prototype indexes. Search never uses source filesystem paths.
    """
    if limit < 1:
        return []
    terms = _terms(query)
    if not terms:
        return []
    db_path = Path(database_path) if database_path is not None else DEFAULT_DATABASE_PATH
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLite search index does not exist: {db_path}")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        candidates = connection.execute(
            """SELECT
                   c.chunk_id, c.document_id, c.page, s.heading, s.section_path_json,
                   d.filename, d.title, bm25(chunks_fts, 1.0, 3.0) AS lexical_rank
               FROM chunks_fts
               JOIN chunks c ON c.chunk_id = chunks_fts.rowid
               JOIN sections s ON s.section_id = c.section_id
               JOIN documents d ON d.document_id = c.document_id
               WHERE chunks_fts MATCH ?
               ORDER BY lexical_rank ASC
               LIMIT ?""",
            (_fts_query(terms), limit * 20),
        ).fetchall()
        # Titles and filenames are intentionally not source paths. They provide a
        # low-weight fallback when the user knows the document's visible name but
        # its words do not occur in a chunk.
        title_filename_conditions = " AND ".join(
            "LOWER(d.filename || ' ' || COALESCE(d.title, '')) LIKE ?" for _ in terms
        )
        named_candidates = connection.execute(
            f"""SELECT
                    c.chunk_id, c.document_id, c.page, s.heading, s.section_path_json,
                    d.filename, d.title
                FROM documents d
                JOIN chunks c ON c.document_id = d.document_id
                JOIN sections s ON s.section_id = c.section_id
                WHERE {title_filename_conditions}
                GROUP BY d.document_id
                ORDER BY c.chunk_id ASC""",
            tuple(f"%{term}%" for term in terms),
        ).fetchall()
    finally:
        connection.close()

    # One document result per filename is deliberate: filenames are the user-facing identity.
    best_by_filename: dict[str, dict[str, Any]] = {}
    for row in candidates:
        result = _row_to_result(row, terms, float(row["lexical_rank"]))
        prior = best_by_filename.get(result["filename"])
        if prior is None or result["score"] > prior["score"]:
            best_by_filename[result["filename"]] = result
    for row in named_candidates:
        result = _row_to_result(row, terms, 0.0)
        prior = best_by_filename.get(result["filename"])
        if prior is None or result["score"] > prior["score"]:
            best_by_filename[result["filename"]] = result
    return sorted(best_by_filename.values(), key=lambda result: (-result["score"], result["filename"]))[:limit]
