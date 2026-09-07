from __future__ import annotations

from fastapi.testclient import TestClient
from pathlib import Path

from document_finder.api.app import app
from document_finder.api import routes


client = TestClient(app)

DOCUMENT_A = "a" * 64
DOCUMENT_B = "b" * 64


def _serving(monkeypatch, documents: int = 3) -> None:
    """Pretend a usable corpus is configured, so response shape is tested in isolation."""
    monkeypatch.setattr(routes, "corpus_state", lambda: ("ok", documents))


def test_health_reports_corpus_state(monkeypatch) -> None:
    _serving(monkeypatch, documents=36)
    payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["corpus"] == "ok"
    assert payload["documents"] == 36
    # The configured filesystem location is never exposed to clients.
    assert not any("/" in str(value) for value in payload.values())


def test_valid_query_and_response_schema(monkeypatch) -> None:
    _serving(monkeypatch)
    monkeypatch.setattr(routes, "search_vector", lambda query, **kwargs: [
        {"document_id": DOCUMENT_A, "filename": "Part Creation & EBOM Process.docx",
         "source_path": "Engineering/Part Creation & EBOM Process.docx", "score": 0.91,
         "section": "Procedure for Part Creation", "page": None, "chunk_id": "9"}
    ])
    response = client.post("/search", json={"query": "how do I create a new part?", "limit": 5})
    assert response.status_code == 200
    assert response.json() == {"query": "how do I create a new part?", "results": [{
        "document_id": DOCUMENT_A,
        "filename": "Part Creation & EBOM Process.docx",
        "folder": "Engineering",
        "score": 0.91,
        "section": "Procedure for Part Creation",
        "page": None,
    }]}


def test_empty_query_and_limit_validation() -> None:
    assert client.post("/search", json={"query": "   "}).status_code == 422
    assert client.post("/search", json={"query": "part", "limit": 21}).status_code == 422
    assert client.post("/search", json={"query": "part", "limit": 0}).status_code == 422


def test_same_document_collapses_but_same_filename_does_not(monkeypatch) -> None:
    """One row per document, not per filename: duplicates must stay distinguishable."""
    _serving(monkeypatch)
    monkeypatch.setattr(routes, "search_vector", lambda query, **kwargs: [
        {"document_id": DOCUMENT_A, "filename": "Same.docx", "source_path": "one/Same.docx",
         "score": 0.6, "section": "Older", "page": None},
        {"document_id": DOCUMENT_A, "filename": "Same.docx", "source_path": "one/Same.docx",
         "score": 0.9, "section": "Best", "page": 4},
        {"document_id": DOCUMENT_B, "filename": "Same.docx", "source_path": "two/Same.docx",
         "score": 0.7, "section": "Other folder", "page": None},
    ])
    results = client.post("/search", json={"query": "change", "limit": 5}).json()["results"]

    # The same document keeps only its best-scoring evidence...
    assert [result["section"] for result in results] == ["Best", "Other folder"]
    # ...but the two distinct documents both survive and can be told apart.
    assert [result["document_id"] for result in results] == [DOCUMENT_A, DOCUMENT_B]
    assert [result["folder"] for result in results] == ["one", "two"]


def test_limit_is_applied_after_aggregation(monkeypatch) -> None:
    _serving(monkeypatch)
    monkeypatch.setattr(routes, "search_vector", lambda query, **kwargs: [
        {"document_id": DOCUMENT_A, "filename": "Same.docx", "source_path": "one/Same.docx",
         "score": 0.9, "section": "Best", "page": 4},
        {"document_id": DOCUMENT_B, "filename": "Other.docx", "source_path": "Other.docx",
         "score": 0.7, "section": "Other", "page": None},
    ])
    results = client.post("/search", json={"query": "change", "limit": 1}).json()["results"]
    assert results == [{
        "document_id": DOCUMENT_A, "filename": "Same.docx", "folder": "one",
        "score": 0.9, "section": "Best", "page": 4,
    }]


def test_no_result_behavior(monkeypatch) -> None:
    _serving(monkeypatch)
    monkeypatch.setattr(routes, "search_vector", lambda query, **kwargs: [])
    response = client.post("/search", json={"query": "unmatched process"})
    assert response.status_code == 200
    assert response.json() == {"query": "unmatched process", "results": []}


def test_search_refuses_when_no_corpus_is_indexed(monkeypatch) -> None:
    monkeypatch.setattr(routes, "corpus_state", lambda: ("unindexed", 0))
    response = client.post("/search", json={"query": "part"})
    assert response.status_code == 503
    assert "python -m document_finder.corpus" in response.json()["detail"]


def test_search_refuses_when_index_belongs_to_another_folder(monkeypatch) -> None:
    """Serving the wrong corpus must fail loudly rather than quietly."""
    monkeypatch.setattr(routes, "corpus_state", lambda: ("mismatch", 12))
    response = client.post("/search", json={"query": "part"})
    assert response.status_code == 503
    assert "different document folder" in response.json()["detail"]


def test_safe_document_opening_and_static_frontend(monkeypatch, tmp_path: Path) -> None:
    _serving(monkeypatch)
    document = tmp_path / "Approved SOP.docx"
    document.write_bytes(b"document bytes")
    monkeypatch.setattr(routes, "resolve_document_path", lambda filename: document if filename == document.name else None)
    monkeypatch.setattr(routes, "resolve_document_id", lambda identifier: document if identifier == DOCUMENT_A else None)

    opened = client.get("/documents/Approved%20SOP.docx")
    assert opened.status_code == 200 and opened.content == b"document bytes"
    by_id = client.get(f"/documents/by-id/{DOCUMENT_A}")
    assert by_id.status_code == 200 and by_id.content == b"document bytes"

    assert client.get("/documents/..%2Fsecret.docx").status_code in {404, 422}
    assert client.get(f"/documents/by-id/{DOCUMENT_B}").status_code == 404
    assert client.get("/documents/by-id/not-a-valid-id").status_code == 404

    page = client.get("/")
    assert page.status_code == 200 and "Document Finder" in page.text and "Open Document" not in page.text
