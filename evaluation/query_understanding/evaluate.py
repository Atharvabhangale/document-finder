"""Evaluate the Phase 13 query-understanding experiment.

Metrics are computed ONLY for fields that carry labels in
`evaluation/query_understanding/queries.json`. `topic` and `confidence` are
deliberately unlabelled (see LABELS.md), so no accuracy is reported for them;
confidence is summarised descriptively instead.

Read `LABELS.md` before quoting any number here: the labels are self-authored,
so these figures are a consistency check, not independent validation.

    python evaluation/query_understanding/evaluate.py
    python evaluation/query_understanding/evaluate.py --json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from document_finder.experiments.query_understanding import CorpusProfile, analyze_query
from document_finder.experiments.query_understanding.analyzer import ESCAPE_OPTION


DEFAULT_QUERIES = Path(__file__).with_name("queries.json")
DEFAULT_DATABASE = Path("data/document_finder.sqlite3")

LABELLED_FIELDS = {
    "domain": "expected_domain",
    "intent": "expected_intent",
    "ambiguity": "expected_ambiguity",
    "needs_clarification": "expected_needs_clarification",
}


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Query-understanding dataset must be a non-empty JSON array.")
    for index, case in enumerate(cases):
        if "query" not in case:
            raise ValueError(f"Case {index} has no query field.")
    return cases


def _category_scores(predicted: list[str], expected: list[str]) -> dict[str, Any]:
    """Multi-label category comparison, reported three ways rather than one flattering way."""
    predicted_set, expected_set = set(predicted), set(expected)
    if not expected_set and not predicted_set:
        return {"exact": True, "primary_correct": True, "jaccard": 1.0}
    intersection = predicted_set & expected_set
    union = predicted_set | expected_set
    return {
        "exact": predicted_set == expected_set,
        # Did the top-ranked predicted category land inside the labelled set?
        "primary_correct": bool(predicted) and predicted[0] in expected_set,
        "jaccard": round(len(intersection) / len(union), 4) if union else 1.0,
    }


def evaluate(cases: list[dict[str, Any]], profile: CorpusProfile) -> dict[str, Any]:
    correct = Counter()
    total = Counter()
    confusion: dict[str, Counter] = defaultdict(Counter)
    per_case: list[dict[str, Any]] = []
    category_exact = category_primary = 0
    jaccard_sum = 0.0
    category_total = 0

    for case in cases:
        result = analyze_query(case["query"], profile)
        payload = result.to_dict()
        record: dict[str, Any] = {
            "query": case["query"],
            "case_type": case.get("case_type"),
            "predicted": payload,
            "mismatches": [],
        }

        for field, label_key in LABELLED_FIELDS.items():
            if label_key not in case:
                continue
            expected, predicted = case[label_key], payload[field]
            total[field] += 1
            if expected == predicted:
                correct[field] += 1
            else:
                record["mismatches"].append(
                    {"field": field, "expected": expected, "predicted": predicted}
                )
            confusion[field][f"{expected} -> {predicted}"] += 1

        if "expected_categories" in case:
            scores = _category_scores(payload["candidate_categories"], case["expected_categories"])
            category_total += 1
            category_exact += int(scores["exact"])
            category_primary += int(scores["primary_correct"])
            jaccard_sum += scores["jaccard"]
            record["category_scores"] = scores
            if not scores["exact"]:
                record["mismatches"].append({
                    "field": "candidate_categories",
                    "expected": case["expected_categories"],
                    "predicted": payload["candidate_categories"],
                })

        record["correct"] = not record["mismatches"]
        per_case.append(record)

    clarified = [record for record in per_case if record["predicted"]["needs_clarification"]]
    reducing = [
        record for record in clarified
        if record["predicted"].get("clarification_reduces_search_space")
    ]
    confidences = [record["predicted"]["confidence"] for record in per_case]
    clarified_confidence = [record["predicted"]["confidence"] for record in clarified]
    direct_confidence = [
        record["predicted"]["confidence"] for record in per_case
        if not record["predicted"]["needs_clarification"]
    ]

    return {
        "total_queries": len(cases),
        "accuracy": {
            field: {
                "correct": correct[field],
                "total": total[field],
                "accuracy": round(correct[field] / total[field], 4) if total[field] else None,
            }
            for field in LABELLED_FIELDS
        },
        "category_metrics": {
            "total": category_total,
            "exact_set_match": category_exact,
            "exact_set_accuracy": round(category_exact / category_total, 4) if category_total else None,
            "primary_category_correct": category_primary,
            "primary_category_accuracy": round(category_primary / category_total, 4) if category_total else None,
            "mean_jaccard": round(jaccard_sum / category_total, 4) if category_total else None,
        },
        "fully_correct_cases": sum(1 for record in per_case if record["correct"]),
        "confusion": {field: dict(counter) for field, counter in sorted(confusion.items())},
        "clarification": {
            "queries_triggering_clarification": len(clarified),
            "clarifications_that_reduce_search_space": len(reducing),
            "facets_used": dict(Counter(record["predicted"].get("clarification_facet") for record in clarified)),
        },
        "confidence_distribution": {
            "min": min(confidences) if confidences else None,
            "max": max(confidences) if confidences else None,
            "mean": round(sum(confidences) / len(confidences), 4) if confidences else None,
            "mean_when_clarifying": round(sum(clarified_confidence) / len(clarified_confidence), 4) if clarified_confidence else None,
            "mean_when_searching_directly": round(sum(direct_confidence) / len(direct_confidence), 4) if direct_confidence else None,
            "note": "Confidence is unlabelled; this is descriptive only, not an accuracy measure.",
        },
        "case_results": per_case,
    }


def print_report(report: dict[str, Any]) -> None:
    print("=" * 78)
    print("PHASE 13 QUERY-UNDERSTANDING EXPERIMENT — EVALUATION")
    print("Labels are self-authored (see LABELS.md): consistency check, not validation.")
    print("=" * 78)
    print(f"\nTotal queries: {report['total_queries']}")
    print(f"Fully correct on every labelled field: {report['fully_correct_cases']}/{report['total_queries']}")

    print("\n-- Labelled-field accuracy --")
    for field, metrics in report["accuracy"].items():
        if metrics["accuracy"] is None:
            print(f"  {field:22} no labels present")
        else:
            print(f"  {field:22} {metrics['correct']:>3}/{metrics['total']:<3} = {metrics['accuracy']:.3f}")

    categories = report["category_metrics"]
    print("\n-- Category prediction (multi-label) --")
    print(f"  exact set match        {categories['exact_set_match']:>3}/{categories['total']:<3} = {categories['exact_set_accuracy']:.3f}")
    print(f"  primary category in set{categories['primary_category_correct']:>3}/{categories['total']:<3} = {categories['primary_category_accuracy']:.3f}")
    print(f"  mean Jaccard overlap   {categories['mean_jaccard']:.3f}")

    clarification = report["clarification"]
    print("\n-- Clarification --")
    print(f"  queries triggering clarification: {clarification['queries_triggering_clarification']}")
    print(f"  of those, provably reduce the candidate set: {clarification['clarifications_that_reduce_search_space']}")
    print(f"  facets used: {clarification['facets_used']}")

    confidence = report["confidence_distribution"]
    print("\n-- Confidence (unlabelled, descriptive) --")
    print(f"  range {confidence['min']}–{confidence['max']}, mean {confidence['mean']}")
    print(f"  mean when asking for clarification: {confidence['mean_when_clarifying']}")
    print(f"  mean when searching directly:       {confidence['mean_when_searching_directly']}")

    print("\n-- Confusion (expected -> predicted), non-diagonal only --")
    for field, counter in report["confusion"].items():
        wrong = {key: count for key, count in counter.items() if key.split(" -> ")[0] != key.split(" -> ")[1]}
        if wrong:
            print(f"  {field}: {wrong}")

    failures = [record for record in report["case_results"] if not record["correct"]]
    print(f"\n-- Mismatched cases ({len(failures)}) --")
    for record in failures:
        print(f"\n  QUERY: {record['query']!r}  [{record['case_type']}]")
        for mismatch in record["mismatches"]:
            print(f"    {mismatch['field']}: expected {mismatch['expected']!r}, got {mismatch['predicted']!r}")

    print("\n-- Clarification questions generated --")
    for record in report["case_results"]:
        predicted = record["predicted"]
        if not predicted["needs_clarification"]:
            continue
        counts = predicted.get("clarification_option_counts", {})
        print(f"\n  QUERY: {record['query']!r} ({len(predicted['candidate_documents'])} candidates, facet={predicted['clarification_facet']})")
        print(f"    Q: {predicted['clarification_question']}")
        for option in predicted["clarification_options"]:
            suffix = "" if option == ESCAPE_OPTION else ""
            print(f"       - {option}{suffix}")
        print(f"    reduces search space: {predicted['clarification_reduces_search_space']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the Phase 13 query-understanding experiment.")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    args = parser.parse_args()

    profile = CorpusProfile.from_sqlite(args.database)
    report = evaluate(load_cases(args.queries), profile)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
