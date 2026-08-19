from __future__ import annotations

from fastapi.testclient import TestClient
from pathlib import Path

from document_finder.api.app import app
from document_finder.api import routes


client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_valid_query_and_response_schema(monkeypatch) -> None:
    monkeypatch.setattr(routes, "search_vector", lambda query, limit: [
        {"document_id": "d1", "filename": "Part Creation & EBOM Process.docx", "score": 0.91,
         "section": "Procedure for Part Creation", "page": None, "chunk_id": "9"}
    ])
    response = client.post("/search", json={"query": "how do I create a new part?", "limit": 5})
    assert response.status_code == 200
    assert response.json() == {"query": "how do I create a new part?", "results": [{
        "filename": "Part Creation & EBOM Process.docx", "score": 0.91,
        "section": "Procedure for Part Creation", "page": None,
    }]}


def test_empty_query_and_limit_validation() -> None:
    assert client.post("/search", json={"query": "   "}).status_code == 422
    assert client.post("/search", json={"query": "part", "limit": 21}).status_code == 422
    assert client.post("/search", json={"query": "part", "limit": 0}).status_code == 422


def test_duplicate_aggregation_and_limit(monkeypatch) -> None:
    monkeypatch.setattr(routes, "search_vector", lambda query, limit: [
        {"filename": "Same.docx", "score": 0.6, "section": "Older", "page": None},
        {"filename": "Same.docx", "score": 0.9, "section": "Best", "page": 4},
        {"filename": "Other.docx", "score": 0.7, "section": "Other", "page": None},
    ])
    response = client.post("/search", json={"query": "change", "limit": 1})
    assert response.status_code == 200
    assert response.json()["results"] == [{"filename": "Same.docx", "score": 0.9, "section": "Best", "page": 4}]


def test_no_result_behavior(monkeypatch) -> None:
    monkeypatch.setattr(routes, "search_vector", lambda query, limit: [])
    response = client.post("/search", json={"query": "unmatched process"})
    assert response.status_code == 200
    assert response.json() == {"query": "unmatched process", "results": []}


def test_safe_document_opening_and_static_frontend(monkeypatch, tmp_path: Path) -> None:
    document = tmp_path / "Approved SOP.docx"
    document.write_bytes(b"document bytes")
    monkeypatch.setattr(routes, "resolve_document_path", lambda filename: document if filename == document.name else None)
    opened = client.get("/documents/Approved%20SOP.docx")
    assert opened.status_code == 200 and opened.content == b"document bytes"
    assert client.get("/documents/..%2Fsecret.docx").status_code in {404, 422}
    page = client.get("/")
    assert page.status_code == 200 and "Document Finder" in page.text and "Open Document" not in page.text
