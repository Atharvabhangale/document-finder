"""Retrieval routes backed by the frozen vector-only prototype baseline.

The corpus served here is whatever `document_finder.config` resolves, so the
application can serve a customer's own folder without code changes. Documents
are opened by opaque document identifier, never by a path supplied by the
browser.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from document_finder import config
from document_finder import understanding
from document_finder.api.schemas import (
    ClarificationOptionResponse,
    HealthResponse,
    QueryUnderstandingRequest,
    QueryUnderstandingResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from document_finder.search.vector import search_vector


router = APIRouter()

DOCUMENT_ROOT_KEY = "document_root"
_DOCUMENT_ID_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")

# When a clarification is applied, retrieve deeper before narrowing so the
# chosen subset is still filled from the same ranking rather than from
# whatever happened to fit in the top few rows.
CLARIFIED_CANDIDATE_MULTIPLIER = 4
MAX_CLARIFIED_CANDIDATES = 40


def _connect(database_path: Path) -> sqlite3.Connection | None:
    if not database_path.is_file():
        return None
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def corpus_state() -> tuple[str, int]:
    """Report whether the configured corpus is usable: (state, document count).

    `mismatch` means the index was built against a different folder than the one
    this process is configured to serve. Serving it would hand users documents
    from the wrong corpus, so it is treated as unavailable rather than guessed at.
    """
    connection = _connect(config.database_path())
    if connection is None:
        return "unindexed", 0
    try:
        documents = connection.execute(
            "SELECT COUNT(*) FROM documents WHERE status = 'indexed'"
        ).fetchone()[0]
        try:
            row = connection.execute(
                "SELECT value FROM index_metadata WHERE key = ?", (DOCUMENT_ROOT_KEY,)
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
    except sqlite3.OperationalError:
        return "unindexed", 0
    finally:
        connection.close()
    # An index written before this metadata existed cannot be checked; it is
    # accepted so existing local workflows keep working.
    if row is not None and Path(row["value"]).resolve() != config.resolved_data_root():
        return "mismatch", documents
    return "ok", documents


def _require_usable_corpus() -> None:
    state, _ = corpus_state()
    if state == "unindexed":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "no indexed corpus was found for the configured document root; "
                "run: python -m document_finder.corpus <FOLDER>"
            ),
        )
    if state == "mismatch":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "the search index was built for a different document folder than this "
                "service is configured to serve; re-index, or correct "
                f"{config.DATA_ROOT_VARIABLE}"
            ),
        )


def _contained(root: Path, source_path: str) -> Path | None:
    """Join a stored relative source path to the corpus root, refusing escapes."""
    candidate = (root / source_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def resolve_document_id(document_id: str) -> Path | None:
    """Resolve an indexed document identifier to a file inside the corpus root.

    The identifier is opaque and comes from the index, so the browser never
    chooses a path. An unknown identifier, a document whose file has since been
    removed, or any path that would escape the corpus root all resolve to None.
    """
    if not document_id or not _DOCUMENT_ID_PATTERN.match(document_id):
        return None
    connection = _connect(config.database_path())
    if connection is None:
        return None
    try:
        row = connection.execute(
            "SELECT source_path FROM documents WHERE document_id = ? AND status = 'indexed'",
            (document_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return _contained(config.resolved_data_root(), row["source_path"])


def resolve_document_path(filename: str) -> Path | None:
    """Resolve an unambiguous indexed filename. Retained for the earlier route.

    Deliberately refuses rather than guessing when a filename matches more than
    one indexed document; the identifier route handles that case exactly.
    """
    if not filename or Path(filename).name != filename:
        return None
    connection = _connect(config.database_path())
    if connection is None:
        return None
    try:
        rows = connection.execute(
            "SELECT source_path FROM documents WHERE filename = ? AND status = 'indexed'", (filename,)
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1:
        return None
    return _contained(config.resolved_data_root(), rows[0]["source_path"])


def _folder(source_path: str | None) -> str:
    """Corpus-relative folder for display. Never an absolute machine path."""
    if not source_path:
        return ""
    parent = PurePosixPath(source_path).parent
    return "" if str(parent) in {".", "/", ""} else str(parent)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    state, documents = corpus_state()
    return HealthResponse(status="ok", corpus=state, documents=documents)


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="query must not be empty")
    _require_usable_corpus()

    # A clarification answer narrows which documents may be shown. Retrieval
    # itself is unchanged: the same query, the same embeddings, the same index
    # and the same ordering — only the presented set is scoped.
    allowed: tuple[str, ...] | None = None
    if request.clarification:
        try:
            allowed = understanding.documents_for_choice(query, request.clarification)
        except Exception:
            allowed = None
    fetch_limit = (
        min(request.limit * CLARIFIED_CANDIDATE_MULTIPLIER, MAX_CLARIFIED_CANDIDATES)
        if allowed else request.limit
    )

    try:
        candidates = search_vector(
            query,
            limit=fetch_limit,
            database_path=config.database_path(),
            index_path=config.index_path(),
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="search index is unavailable") from error
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="search service is unavailable") from error

    # Aggregated per document identity, so two documents sharing a filename stay
    # distinct. Vector search already aggregates; this boundary is preserved in
    # case another backend is substituted later.
    best: dict[str, dict] = {}
    for candidate in candidates:
        key = candidate.get("document_id") or candidate["filename"]
        existing = best.get(key)
        if existing is None or candidate["score"] > existing["score"]:
            best[key] = candidate
    ordered = sorted(best.values(), key=lambda item: (-item["score"], item["filename"], item.get("document_id") or ""))
    if allowed:
        scoped = [item for item in ordered if item.get("document_id") in set(allowed)]
        # Never let a narrowing choice leave the user with nothing to look at.
        ordered = scoped or ordered
    results = [
        SearchResult(
            document_id=item.get("document_id") or "",
            filename=item["filename"],
            folder=_folder(item.get("source_path")),
            score=item["score"],
            section=item["section"],
            page=item["page"],
        )
        for item in ordered[:request.limit]
    ]
    return SearchResponse(query=query, results=results)


@router.post("/query-understanding", response_model=QueryUnderstandingResponse)
def query_understanding(request: QueryUnderstandingRequest) -> QueryUnderstandingResponse:
    """Decide whether one clarification question is worth asking before searching.

    Always answers. If the layer is disabled or fails, the answer is simply
    "no clarification needed", and the client proceeds to search.
    """
    query = request.query.strip()
    if not query:
        return QueryUnderstandingResponse(query=query, needs_clarification=False)
    prepared = understanding.prepare(query)
    if not prepared.needs_clarification:
        return QueryUnderstandingResponse(query=query, needs_clarification=False)
    return QueryUnderstandingResponse(
        query=query,
        needs_clarification=True,
        question=prepared.question,
        options=[
            ClarificationOptionResponse(label=option.label, value=option.value)
            for option in prepared.options
        ],
    )


@router.get("/documents/by-id/{document_id}")
def open_document_by_id(document_id: str) -> FileResponse:
    """Open the exact indexed document named by an opaque identifier."""
    _require_usable_corpus()
    path = resolve_document_id(document_id)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@router.get("/documents/{filename:path}")
def open_document(filename: str) -> FileResponse:
    path = resolve_document_path(filename)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return FileResponse(path, filename=path.name, content_disposition_type="inline")
