from __future__ import annotations

from evaluation.evaluate import evaluate_cases
from evaluation.evaluate import load_cases
from pathlib import Path


def test_evaluation_accepts_any_labelled_document_and_reports_failure_ranking() -> None:
    cases = [
        {"query": "ambiguous", "expected_documents": ["A.docx", "B.docx"]},
        {"query": "missing", "expected_documents": ["C.docx"]},
    ]

    def fake_search(query: str, limit: int, database_path: object) -> list[dict[str, object]]:
        if query == "ambiguous":
            return [{"filename": "B.docx"}]
        return [{"filename": "A.docx"}]

    report = evaluate_cases(cases, search=fake_search)
    assert report["successful_recall_at_1"] == 1
    assert report["successful_recall_at_3"] == 1
    assert report["successful_recall_at_5"] == 1
    assert report["mrr"] == 0.5
    assert report["failed_queries"][0]["query"] == "missing"
    assert report["failed_queries"][0]["returned_ranking"] == [{"filename": "A.docx"}]


def test_ocr_query_set_has_grounded_document_labels() -> None:
    cases = load_cases(Path("evaluation/ocr_queries.json"))
    assert 15 <= len(cases) <= 20
    assert all(case["expected_documents"] == ["PR-ECR-ECN-ACN Process.docx"] for case in cases)
    assert all(case["expected_sections"] == [] for case in cases)
