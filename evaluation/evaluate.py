"""Measure the current lexical baseline against manually labelled SOP queries."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from document_finder.search.lexical import DEFAULT_DATABASE_PATH, search_lexical


Case = dict[str, Any]
SearchFunction = Callable[[str, int, Path | str | None], list[dict[str, Any]]]


def load_cases(path: Path) -> list[Case]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("Evaluation dataset must be a JSON array.")
    for index, case in enumerate(cases):
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError(f"Case {index} has no query.")
        if not isinstance(case.get("expected_documents"), list) or not case["expected_documents"]:
            raise ValueError(f"Case {index} has no expected_documents.")
    return cases


def _first_relevant_rank(results: Sequence[dict[str, Any]], expected_documents: set[str]) -> int | None:
    for rank, result in enumerate(results, start=1):
        if result["filename"] in expected_documents:
            return rank
    return None


def evaluate_cases(
    cases: Sequence[Case], database_path: Path | str | None = None, search: SearchFunction = search_lexical
) -> dict[str, Any]:
    """Calculate document-level Recall@K and MRR, accepting any labelled document."""
    successes = {1: 0, 3: 0, 5: 0}
    reciprocal_rank_sum = 0.0
    failures: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    for case in cases:
        expected_documents = set(case["expected_documents"])
        results = search(case["query"], 5, database_path)
        rank = _first_relevant_rank(results, expected_documents)
        for cutoff in successes:
            if rank is not None and rank <= cutoff:
                successes[cutoff] += 1
        if rank is not None:
            reciprocal_rank_sum += 1 / rank
        result_record = {
            "query": case["query"],
            "expected_documents": case["expected_documents"],
            "expected_sections": case.get("expected_sections"),
            "first_relevant_rank": rank,
            "returned_ranking": results,
        }
        case_results.append(result_record)
        if rank is None:
            failures.append(result_record)

    total = len(cases)
    return {
        "total_queries": total,
        "successful_recall_at_1": successes[1],
        "successful_recall_at_3": successes[3],
        "successful_recall_at_5": successes[5],
        "recall_at_1": successes[1] / total if total else 0.0,
        "recall_at_3": successes[3] / total if total else 0.0,
        "recall_at_5": successes[5] / total if total else 0.0,
        "mrr": reciprocal_rank_sum / total if total else 0.0,
        "failed_queries": failures,
        "case_results": case_results,
    }


def print_report(report: dict[str, Any]) -> None:
    print(f"Total queries: {report['total_queries']}")
    print(f"Successful Recall@1: {report['successful_recall_at_1']}")
    print(f"Successful Recall@3: {report['successful_recall_at_3']}")
    print(f"Successful Recall@5: {report['successful_recall_at_5']}")
    print(f"Recall@1: {report['recall_at_1']:.3f}")
    print(f"Recall@3: {report['recall_at_3']:.3f}")
    print(f"Recall@5: {report['recall_at_5']:.3f}")
    print(f"MRR: {report['mrr']:.3f}")
    print(f"Failed queries (no expected document in top 5): {len(report['failed_queries'])}")
    for failure in report["failed_queries"]:
        print(f"\nFAILED: {failure['query']}")
        print(f"  Expected: {', '.join(failure['expected_documents'])}")
        if not failure["returned_ranking"]:
            print("  Returned: no results")
        else:
            for rank, result in enumerate(failure["returned_ranking"], start=1):
                print(f"  {rank}. {result['filename']} — {result['section']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the lexical document-finder baseline.")
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--mode", choices=("lexical", "vector", "hybrid", "ocr-vector"), default="lexical")
    parser.add_argument("--json", action="store_true", help="Print the complete machine-readable report.")
    args = parser.parse_args()
    queries_path = args.queries or Path(__file__).with_name("ocr_queries.json" if args.mode == "ocr-vector" else "queries.json")
    if args.mode in {"vector", "ocr-vector"}:
        from document_finder.search.vector import search_vector
        search = search_vector
    elif args.mode == "hybrid":
        from document_finder.search.hybrid import search_hybrid
        search = search_hybrid
    else:
        search = search_lexical
    report = evaluate_cases(load_cases(queries_path), args.database, search)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
