"""Phase 18 experiment: current decision vs partial-branch candidate decision.

Answers one question with corpus evidence rather than argument: should a
clarification expose only the genuinely useful branches of a facet, instead of
requiring the whole facet to partition the candidate set?

    python evaluation/query_understanding/phase18_partial_branch.py            # diagnostic table
    python evaluation/query_understanding/phase18_partial_branch.py --compare  # strategy comparison
    python evaluation/query_understanding/phase18_partial_branch.py --json

The `current` column is the real production decision — `understanding.prepare`,
the same call `POST /query-understanding` makes — so the comparison is between
two computed answers. Production is only read here, never changed: this script
imports the decision layer and the Phase 18 prototype side by side.

The frozen 60-query dataset is reused as the regression surface (its labels are
self-authored; see LABELS.md) and is not modified.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from document_finder import config, understanding
from document_finder.experiments.query_understanding import CorpusProfile
from document_finder.experiments.query_understanding.partial_branch import (
    DUPLICATE,
    EMPTY,
    SEARCH_ALL,
    STRATEGIES,
    USEFUL,
    WEAK,
    decide,
    diagnose,
)


DEFAULT_DATABASE = Path("data/document_finder.sqlite3")
FROZEN_QUERIES = Path(__file__).with_name("queries.json")

# The eight queries the phase brief names, in its order.
PROBES = ("ECR", "work request", "NPD", "BOM", "SOP", "gate", "chatbot", "change management")

# Queries whose current behaviour must survive any change (Phase 16/17 probes).
REGRESSION_PROBES = (
    "gate", "chatbot", "change management", "BOM", "SOP", "user guide", "windchill",
    "work request", "NPD", "ECR", "deployment", "procurement", "part",
    "how do I create an ECR?", "add BOM structure",
    "how do I create a procurement kit?", "engine 37 hp 2900 rpm", "travel expense claim",
)

VERDICT_NOTE = {
    SEARCH_ALL: "same set as Search everything",
    EMPTY: "selects nothing",
    DUPLICATE: "same documents as a branch already listed",
    WEAK: "narrows, but by less than the bar",
    USEFUL: "narrows meaningfully on its own",
}


def current_decision(query: str, database: Path) -> dict[str, Any]:
    """The production decision, read through the real decision layer."""
    prepared = understanding.prepare(query, database)
    return {
        "asks": prepared.needs_clarification,
        "facet": prepared.facet,
        "options": [option.label for option in prepared.options],
        "reduction": prepared.reduction,
        "reason": prepared.reason,
        "candidates": prepared.candidates_before,
    }


def diagnostic_rows(query: str, profile: CorpusProfile) -> list[dict[str, Any]]:
    """One row per facet branch: the table the phase brief asks for."""
    report = diagnose(query, profile)
    rows: list[dict[str, Any]] = []
    for facet in report.facets:
        for branch in facet.branches:
            rows.append({
                "query": report.query,
                "candidates": report.candidates_before,
                "facet": facet.facet,
                "option": branch.label,
                "option_candidates": branch.size,
                "reduction": branch.reduction,
                "verdict": branch.verdict,
                "facet_coverage": facet.coverage,
                "facet_worst_case": facet.worst_case_reduction,
                "useful_only_coverage": facet.useful_coverage,
                "whole_facet_viable": facet.whole_facet_viable,
            })
    return rows


def print_diagnostic(queries: tuple[str, ...], profile: CorpusProfile, database: Path) -> None:
    print("=" * 108)
    print("PHASE 18 DIAGNOSTIC — every semantic facet, every option, measured on the indexed corpus")
    print("=" * 108)
    for query in queries:
        report = diagnose(query, profile)
        current = current_decision(query, database)
        print(f"\nQUERY {query!r}   candidates={report.candidates_before}   "
              f"ambiguity={report.ambiguity}   analyzer considers clarifying="
              f"{report.analyzer_would_consider}")
        print(f"  CURRENT DECISION: {'clarify' if current['asks'] else 'direct'}"
              f"   facet={current['facet'] or '-'}   worst-case reduction={current['reduction']:.2f}"
              f"   reason={current['reason']}")
        if current["options"]:
            print(f"  CURRENT OPTIONS : {current['options']}")
        for name in report.candidates:
            print(f"      - {name}")
        if not report.facets:
            print("  (no candidates: no facet exists)")
            continue
        print(f"  {'facet':<20}{'option':<44}{'n':>4}{'reduction':>11}  verdict")
        for facet in report.facets:
            for branch in facet.branches:
                print(f"  {facet.facet:<20}{branch.label[:43]:<44}{branch.size:>4}"
                      f"{branch.reduction:>10.1%}  {branch.verdict}")
            print(f"  {'':<20}-> narrowing options={len(facet.narrowing)}"
                  f"  coverage={facet.coverage:.0%}"
                  f"  worst-case reduction={facet.worst_case_reduction:.0%}"
                  f"  viable today={facet.whole_facet_viable}")
            if facet.useful:
                print(f"  {'':<20}-> useful-only: {len(facet.useful)} option(s), "
                      f"coverage={facet.useful_coverage:.0%}, "
                      f"hides {len(facet.dropped_documents)} candidate(s)")


def print_comparison(queries: list[str], profile: CorpusProfile, database: Path) -> dict[str, Any]:
    """Current decision vs each partial-branch policy, over every query."""
    summary: dict[str, Any] = {}
    for name, policy in STRATEGIES.items():
        differences = []
        for query in queries:
            current = current_decision(query, database)
            candidate = decide(query, profile, policy)
            same = (candidate.asks == current["asks"]
                    and (not candidate.asks or list(candidate.options) == current["options"]))
            if not same:
                differences.append((query, current, candidate))
        summary[name] = {
            "differs": len(differences),
            "queries": [query for query, _, _ in differences],
            "regression_probes_touched": [
                query for query, _, _ in differences if query in REGRESSION_PROBES
            ],
        }
        print(f"\n{'=' * 108}")
        print(f"STRATEGY {name!r}: {len(differences)} of {len(queries)} decisions differ from production")
        print(f"{'=' * 108}")
        for query, current, candidate in differences:
            print(f"  {query!r} ({current['candidates'] or candidate.coverage and '?' or 0} candidates)")
            print(f"      current : {'clarify' if current['asks'] else 'direct ':<7}"
                  f" facet={current['facet'] or '-':<20} worst={current['reduction']:.2f}"
                  f" {current['options']}")
            if candidate.asks:
                print(f"      {name:<8}: clarify  facet={candidate.facet:<20}"
                      f" worst={candidate.worst_case_reduction:.2f}"
                      f" coverage={candidate.coverage:.2f} {list(candidate.options)}")
                if candidate.dropped_documents:
                    print(f"                hides behind Search everything: "
                          f"{list(candidate.dropped_documents)}")
            else:
                print(f"      {name:<8}: direct   ({candidate.reason})")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 18 partial-branch experiment")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--compare", action="store_true",
                        help="compare every partial-branch strategy against production")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    arguments = parser.parse_args()

    if not arguments.database.is_file():
        print(f"No indexed corpus at {arguments.database}. "
              f"Run: python -m document_finder.corpus <FOLDER>")
        return 1
    # The decision layer must be readable regardless of how the shell is
    # configured: this script reports what production *would* decide.
    os.environ.pop(config.QUERY_UNDERSTANDING_VARIABLE, None)
    understanding.clear_cache()

    profile = CorpusProfile.from_sqlite(arguments.database)
    frozen = [case["query"] for case in json.loads(FROZEN_QUERIES.read_text(encoding="utf-8"))]
    queries = list(PROBES) + [q for q in REGRESSION_PROBES if q not in PROBES]
    queries += [q for q in frozen if q not in queries]

    if arguments.json:
        payload = {
            "database": str(arguments.database),
            "documents": len(profile.documents),
            "min_reduction": config.min_clarification_reduction(),
            "diagnostic": [row for query in PROBES for row in diagnostic_rows(query, profile)],
            "decisions": [
                {
                    "query": query,
                    "current": current_decision(query, arguments.database),
                    "strategies": {
                        name: {
                            "asks": decision.asks, "facet": decision.facet,
                            "options": list(decision.options), "coverage": decision.coverage,
                            "worst_case_reduction": decision.worst_case_reduction,
                            "hidden": list(decision.dropped_documents), "reason": decision.reason,
                        }
                        for name, policy in STRATEGIES.items()
                        for decision in (decide(query, profile, policy),)
                    },
                }
                for query in queries
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Corpus: {arguments.database} ({len(profile.documents)} indexed documents)")
    print(f"Production bar: worst-case reduction >= {config.min_clarification_reduction()}")
    print_diagnostic(PROBES, profile, arguments.database)
    if arguments.compare:
        summary = print_comparison(queries, profile, arguments.database)
        print(f"\n{'=' * 108}")
        print("SUMMARY")
        print(f"{'=' * 108}")
        for name, result in summary.items():
            touched = result["regression_probes_touched"]
            print(f"  {name:<14} differs on {result['differs']:>2} of {len(queries)} queries; "
                  f"{len(touched)} of them are required-preserved probes: {touched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
