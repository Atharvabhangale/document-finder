"""Public API request and response schemas; source paths are intentionally excluded."""

from __future__ import annotations

from pydantic import BaseModel, Field


MAX_SEARCH_LIMIT = 20


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=MAX_SEARCH_LIMIT)


class SearchResult(BaseModel):
    filename: str
    score: float
    section: str
    page: int | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


class HealthResponse(BaseModel):
    status: str
