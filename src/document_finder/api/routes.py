"""Retrieval routes backed by the frozen vector-only prototype baseline."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from document_finder.api.schemas import HealthResponse, SearchRequest, SearchResponse, SearchResult
from document_finder.search.lexical import DEFAULT_DATABASE_PATH
from document_finder.search.vector import search_vector


router = APIRouter()
DEFAULT_DOCUMENT_ROOT = Path("data")


def resolve_document_path(filename: str) -> Path | None:
    """Resolve a known indexed filename under the configured document root only."""
    if not filename or Path(filename).name != filename:
        return None
    database_path = DEFAULT_DATABASE_PATH
    if not database_path.is_file():
        return None
    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute(
            "SELECT source_path FROM documents WHERE filename = ? AND status = 'indexed'", (filename,)
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1:
        return None
    root = DEFAULT_DOCUMENT_ROOT.resolve()
    candidate = (root / rows[0][0]).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="query must not be empty")
    try:
        candidates = search_vector(query, limit=request.limit)
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="search index is unavailable") from error
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="search service is unavailable") from error

    # Vector search already aggregates; preserve this API-level boundary if another backend is substituted later.
    best_by_filename: dict[str, dict] = {}
    for candidate in candidates:
        existing = best_by_filename.get(candidate["filename"])
        if existing is None or candidate["score"] > existing["score"]:
            best_by_filename[candidate["filename"]] = candidate
    results = [
        SearchResult(filename=item["filename"], score=item["score"], section=item["section"], page=item["page"])
        for item in sorted(best_by_filename.values(), key=lambda item: (-item["score"], item["filename"]))[:request.limit]
    ]
    return SearchResponse(query=query, results=results)


@router.get("/documents/{filename:path}")
def open_document(filename: str) -> FileResponse:
    path = resolve_document_path(filename)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return FileResponse(path, filename=path.name, content_disposition_type="inline")
