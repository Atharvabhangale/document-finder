"""Public API request and response schemas.

Absolute filesystem paths are intentionally never exposed. A result carries an
opaque `document_id` for opening the exact document, plus the corpus-relative
`folder` so a user can tell apart two documents that share a filename.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


MAX_SEARCH_LIMIT = 20


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=MAX_SEARCH_LIMIT)


class SearchResult(BaseModel):
    document_id: str
    filename: str
    folder: str = ""
    score: float
    section: str
    page: int | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


class HealthResponse(BaseModel):
    status: str
    corpus: str = "ok"
    documents: int = 0
