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
    # Optional answer to a clarification question. Absent for a normal search,
    # which behaves exactly as it did before the clarification layer existed.
    clarification: str | None = None


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


class QueryUnderstandingRequest(BaseModel):
    query: str


class ClarificationOptionResponse(BaseModel):
    label: str
    value: str


class QueryUnderstandingResponse(BaseModel):
    """Search assistance only.

    Deliberately carries no intent, confidence, ambiguity or candidate counts:
    those are internal concepts and are not shown to users.
    """

    query: str
    needs_clarification: bool
    question: str | None = None
    options: list[ClarificationOptionResponse] = Field(default_factory=list)
