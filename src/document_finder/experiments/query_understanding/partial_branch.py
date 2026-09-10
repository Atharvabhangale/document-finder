"""Phase 18 diagnostic: is a "partial-but-meaningful" clarification justified?

Phase 17 requires a facet to partition the *whole* candidate set well enough:
the worst answer must still remove at least `min_option_reduction` of the
candidates. That leaves queries like `work request` and `NPD` on direct search
because one branch dominates, even though the other branches narrow sharply.

The Phase 18 proposal is to expose only the branches that genuinely narrow:

    candidate set
      |-- dominant branch  (rejected today, drags the whole facet down)
      |-- useful branch A
      +-- useful branch B      ->  ask only about A and B

This module exists to test that proposal against the corpus rather than assume
it. It provides two things:

`diagnose()`  every facet, every branch, and the numbers that decide its fate:
              size, reduction, coverage, and a verdict naming *why* a branch is
              or is not a usable option.

`decide()`    the candidate decision under an explicit, named policy, so
              "current decision vs partial-branch decision" is a comparison of
              two computed answers and not of prose.

Nothing here is wired into the product. It is a sibling of the Phase 13
analyzer: it reads the same read-only corpus profile, never calls retrieval,
and `analyzer.py` is not modified by its existence. `evaluation/
query_understanding/phase18_partial_branch.py` is the only caller.

Facet construction deliberately mirrors `analyzer._build_clarification` so the
diagnostic describes the real decision path; the diagnostic needs the raw
branches, including the ones the analyzer discards, which is why it rebuilds
them instead of reusing `_finalize`. A test asserts the mirror still agrees with
the analyzer's own chosen facet and options, so the two cannot drift apart
silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from document_finder.experiments.query_understanding.analyzer import (
    AMBIGUITY_HIGH,
    Candidate,
    CONTENDER_SCORE_RATIO,
    MIN_CANDIDATES_FOR_CLARIFICATION,
    MIN_OPTION_COVERAGE,
    UNINFORMATIVE_TOKENS,
    _candidates,
    _ordered_unique,
    analyze_query,
)
from document_finder.experiments.query_understanding.corpus import CorpusProfile
from document_finder.experiments.query_understanding.taxonomy import (
    DOMAIN_LABELS,
    content_terms,
    tokenize,
)


# The analyzer caps a filename-token facet at five options and leaves semantic
# facets uncapped ("sop" legitimately offers six categories). Reused exactly,
# because capping semantic facets too would change `sop` for a reason that has
# nothing to do with partial branching and would confound the comparison.
MAX_TOKEN_OPTIONS = 5

# A branch is "useful" when it alone removes at least this share of the
# candidates. Reuses the bar the *whole question* has to clear today
# (config.DEFAULT_MIN_CLARIFICATION_REDUCTION), rather than inventing a second
# number: the point of the experiment is to move that bar from the question to
# the branch, not to lower it.
MIN_OPTION_REDUCTION = 0.5

# Retained branches must still reach at least this share of the candidates.
# Reuses the Phase 17 constant that already rejects a facet whose apparent
# narrowing comes from omitting candidates rather than separating them.
MIN_RETAINED_COVERAGE = MIN_OPTION_COVERAGE

# Every branch the corpus offers is a real, named document class, so the
# smallest usable branch is one document: `gate` splits seven candidates into
# MS0..MS6, one document each, and is a required-preserved clarification. A
# larger floor would delete it, so this is fixed by the architecture rather than
# chosen.
MIN_BRANCH_DOCUMENTS = 1


SEARCH_ALL = "search_all"      # selects every candidate: identical to searching everything
EMPTY = "empty"                # selects nothing
DUPLICATE = "duplicate"        # same candidate set as a branch already offered
TOO_SMALL = "too_small"        # below MIN_BRANCH_DOCUMENTS
WEAK = "weak"                  # narrows, but by less than MIN_OPTION_REDUCTION
USEFUL = "useful"              # narrows meaningfully on its own


@dataclass(frozen=True)
class Branch:
    """One facet branch, with the numbers that decide whether it can be an option."""

    label: str
    documents: tuple[str, ...]
    candidates_before: int
    verdict: str

    @property
    def size(self) -> int:
        return len(self.documents)

    @property
    def reduction(self) -> float:
        if self.candidates_before < 1:
            return 0.0
        return round(1 - self.size / self.candidates_before, 4)

    @property
    def narrows(self) -> bool:
        return 0 < self.size < self.candidates_before


@dataclass(frozen=True)
class FacetDiagnostic:
    """One facet's complete branch inventory, before any option filtering."""

    facet: str
    position: int
    candidates_before: int
    branches: tuple[Branch, ...]

    def _reach(self, branches: Iterable[Branch]) -> float:
        documents = {name for branch in branches for name in branch.documents}
        return round(len(documents) / self.candidates_before, 4) if self.candidates_before else 0.0

    @property
    def narrowing(self) -> tuple[Branch, ...]:
        """Branches the analyzer would keep today: strict, non-empty subsets."""
        return tuple(branch for branch in self.branches if branch.verdict in {WEAK, USEFUL})

    @property
    def useful(self) -> tuple[Branch, ...]:
        return tuple(branch for branch in self.branches if branch.verdict == USEFUL)

    @property
    def whole_facet_viable(self) -> bool:
        """Phase 17's test: at least two narrowing branches exist."""
        return len(self.narrowing) >= 2

    @property
    def coverage(self) -> float:
        """Share of candidates reachable through the branches kept today."""
        return self._reach(self.narrowing)

    @property
    def worst_case_reduction(self) -> float:
        """Phase 17's whole-question number: the least helpful answer's reduction."""
        if not self.narrowing:
            return 0.0
        return round(1 - max(branch.size for branch in self.narrowing) / self.candidates_before, 4)

    @property
    def useful_coverage(self) -> float:
        """Share of candidates reachable if only the useful branches were offered."""
        return self._reach(self.useful)

    @property
    def dropped_documents(self) -> tuple[str, ...]:
        """Candidates that partial-branching would hide behind "Search everything"."""
        kept = {name for branch in self.useful for name in branch.documents}
        every = {name for branch in self.branches for name in branch.documents}
        return tuple(sorted(every - kept))


@dataclass(frozen=True)
class QueryDiagnostic:
    query: str
    terms: tuple[str, ...]
    candidates: tuple[str, ...]
    ambiguity: str
    facets: tuple[FacetDiagnostic, ...]

    @property
    def candidates_before(self) -> int:
        return len(self.candidates)

    @property
    def analyzer_would_consider(self) -> bool:
        """Whether the query even reaches facet selection in the analyzer."""
        return (
            self.ambiguity == AMBIGUITY_HIGH
            and self.candidates_before >= MIN_CANDIDATES_FOR_CLARIFICATION
        )


@dataclass(frozen=True)
class PartialBranchPolicy:
    """Explicit, named criteria. Every default is inherited, not invented.

    `drop_dominant_branches` is the Phase 18 proposal itself: with it off, the
    policy keeps every narrowing branch and only relaxes *which* whole-question
    rule decides, which is the honest alternative reading of the same idea.

    The useful/weak bar (`MIN_OPTION_REDUCTION`) is deliberately *not* a knob
    here. It is computed once per query in `diagnose()`, so every policy is
    compared against the same branch verdicts and the comparison isolates one
    variable: what the policy does with them.
    """

    name: str
    min_branch_documents: int = MIN_BRANCH_DOCUMENTS
    # Applies to the filename-token facet only, as in the analyzer.
    max_token_options: int = MAX_TOKEN_OPTIONS
    min_retained_coverage: float = MIN_RETAINED_COVERAGE
    # Phase 17 treats coverage as a rank *bucket*, not a floor: a facet reaching
    # too little of the candidate set is ranked behind better-covering ones but
    # can still win if nothing else is viable. With this on, the policy ports
    # that behaviour exactly instead of rejecting such a facet outright.
    coverage_as_rank: bool = False
    # Drop branches that narrow too little to be useful (the proposal), instead
    # of letting them sink the whole facet.
    drop_dominant_branches: bool = True
    # Branches selecting an identical candidate set are always collapsed — the
    # same choice under two names is not two choices. This asks the stronger
    # question: should finding one reject the facet outright? A duplicate means
    # the facet does not really separate those documents.
    reject_on_duplicates: bool = False
    # The filename-token facet stays last resort, as in Phase 17: its branches
    # are filename fragments, not choices.
    allow_filename_tokens: bool = True
    # Require at least this many useful branches for the question to be asked.
    min_useful_options: int = 2


@dataclass(frozen=True)
class PartialBranchDecision:
    query: str
    asks: bool
    facet: str = ""
    options: tuple[str, ...] = ()
    documents: tuple[tuple[str, ...], ...] = ()
    coverage: float = 0.0
    worst_case_reduction: float = 0.0
    dropped_documents: tuple[str, ...] = ()
    reason: str = ""


def _facet_branches(candidates: list[Candidate], terms: list[str]) -> list[tuple[str, dict[str, list[Candidate]]]]:
    """Raw branches per facet, in the analyzer's ladder order.

    Mirrors `analyzer._build_clarification`, including which candidates supply
    the category and domain vocabulary, but keeps the branches the analyzer
    discards so the diagnostic can say why they were discarded.
    """
    top = candidates[0].score
    contenders = [c for c in candidates if c.score >= CONTENDER_SCORE_RATIO * top]
    categories = _ordered_unique([name for c in contenders for name in c.categories])
    domains = _ordered_unique([domain for c in contenders for domain in c.domains])

    ladder: list[tuple[str, dict[str, list[Candidate]]]] = []
    if len(domains) > 1:
        ladder.append(("domain", {
            DOMAIN_LABELS[domain]: [c for c in candidates if domain in c.domains]
            for domain in domains if domain in DOMAIN_LABELS
        }))
    if len(categories) > 1:
        ladder.append(("category", {
            category: [c for c in candidates if category in c.categories]
            for category in categories
        }))
    by_type: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        for document_type in candidate.types:
            by_type.setdefault(document_type, []).append(candidate)
    ladder.append(("document_type", by_type))

    query_terms = set(terms)
    by_token: dict[str, list[Candidate]] = {}
    preceding: dict[str, str] = {}
    for candidate in candidates:
        tokens = tokenize(candidate.filename)
        for position, token in enumerate(tokens):
            if token in UNINFORMATIVE_TOKENS or token in query_terms or len(token) < 2:
                continue
            if position > 0:
                preceding.setdefault(token, tokens[position - 1])
            by_token.setdefault(token, []).append(candidate)
    labelled: dict[str, list[Candidate]] = {}
    for token, selected in by_token.items():
        if token.isdigit() and preceding.get(token):
            label = f"{preceding[token].title()} {token}"
        else:
            label = token.upper() if len(token) <= 3 else token.title()
        labelled[label] = selected
    ladder.append(("distinguishing_term", labelled))
    return ladder


def _verdict(size: int, before: int, seen: set[frozenset[str]], documents: frozenset[str]) -> str:
    if size == 0:
        return EMPTY
    if size >= before:
        return SEARCH_ALL
    if documents in seen:
        return DUPLICATE
    if size < MIN_BRANCH_DOCUMENTS:
        return TOO_SMALL
    return USEFUL if 1 - size / before >= MIN_OPTION_REDUCTION else WEAK


def diagnose(query: str, profile: CorpusProfile) -> QueryDiagnostic:
    """Full facet/branch inventory for one query. Deterministic, side-effect free."""
    terms = content_terms(query)
    candidates = _candidates(profile, terms) if terms else []
    understanding = analyze_query(query, profile)
    before = len(candidates)
    if not candidates:
        return QueryDiagnostic(query, tuple(terms), (), understanding.ambiguity, ())

    facets: list[FacetDiagnostic] = []
    for position, (facet, buckets) in enumerate(_facet_branches(candidates, terms)):
        seen: set[frozenset[str]] = set()
        branches: list[Branch] = []
        # Largest first, then alphabetical: the analyzer's own option ordering,
        # so "which branch is the duplicate" is decided the same way it would be.
        for label in sorted(buckets, key=lambda name: (-len(buckets[name]), name)):
            selected = buckets[label]
            names = tuple(sorted(candidate.filename for candidate in selected))
            verdict = _verdict(len(selected), before, seen, frozenset(names))
            if verdict in {WEAK, USEFUL}:
                seen.add(frozenset(names))
            branches.append(Branch(label, names, before, verdict))
        facets.append(FacetDiagnostic(facet, position, before, tuple(branches)))
    return QueryDiagnostic(
        query, tuple(terms), tuple(c.filename for c in candidates),
        understanding.ambiguity, tuple(facets),
    )


def _options_for(facet: FacetDiagnostic, policy: PartialBranchPolicy) -> tuple[tuple[Branch, ...], str]:
    """Branches this policy would offer for one facet, or a reason it offers none."""
    pool = facet.useful if policy.drop_dominant_branches else facet.narrowing
    if policy.reject_on_duplicates and any(branch.verdict == DUPLICATE for branch in facet.branches):
        return (), "duplicate_branches"
    kept = sorted(
        (branch for branch in pool if branch.size >= policy.min_branch_documents),
        # Largest first, then alphabetical — the analyzer's own cap ordering.
        key=lambda branch: (-branch.size, branch.label),
    )
    if facet.facet == "distinguishing_term":
        kept = kept[:policy.max_token_options]
    if len(kept) < 2:
        return (), "fewer_than_two_options"
    useful = sum(1 for branch in kept if branch.verdict == USEFUL)
    if useful < policy.min_useful_options:
        return (), "too_few_useful_options"
    reachable = {name for branch in kept for name in branch.documents}
    coverage = len(reachable) / facet.candidates_before
    if coverage < policy.min_retained_coverage and not policy.coverage_as_rank:
        return (), "retained_coverage_too_low"
    return tuple(kept), ""


def decide(
    query: str, profile: CorpusProfile, policy: PartialBranchPolicy,
    diagnostic: QueryDiagnostic | None = None,
) -> PartialBranchDecision:
    """The clarification this policy would offer, or why it offers none.

    Ranking keeps Phase 17's order — semantic facets before filename tokens,
    then best worst-case split, then ladder order — so any difference from
    production comes from the branch-selection change under test and not from a
    re-ordered ladder. Coverage is the one place a policy may differ: by default
    it is a hard floor here, and with `coverage_as_rank` it is the rank bucket
    Phase 17 actually uses.
    """
    report = diagnostic if diagnostic is not None else diagnose(query, profile)
    if not report.analyzer_would_consider:
        return PartialBranchDecision(query, False, reason="analyzer_declines")

    viable: list[tuple[int, FacetDiagnostic, tuple[Branch, ...]]] = []
    reasons: list[str] = []
    for facet in report.facets:
        if facet.facet == "distinguishing_term" and not policy.allow_filename_tokens:
            continue
        options, reason = _options_for(facet, policy)
        if options:
            viable.append((facet.position, facet, options))
        else:
            reasons.append(f"{facet.facet}:{reason}")
    if not viable:
        return PartialBranchDecision(query, False, reason="; ".join(reasons) or "no_facet")

    def rank(item: tuple[int, FacetDiagnostic, tuple[Branch, ...]]) -> tuple[int, int, int]:
        position, _, options = item
        reached = {name for branch in options for name in branch.documents}
        coverage = len(reached) / item[1].candidates_before
        representative = (
            0 if not policy.coverage_as_rank or coverage >= policy.min_retained_coverage else 1
        )
        return representative, max(branch.size for branch in options), position

    semantic = [item for item in viable if item[1].facet != "distinguishing_term"]
    position, facet, options = min(semantic or viable, key=rank)
    reachable = {name for branch in options for name in branch.documents}
    every = {name for branch in facet.branches for name in branch.documents}
    before = facet.candidates_before
    return PartialBranchDecision(
        query=query,
        asks=True,
        facet=facet.facet,
        options=tuple(sorted(branch.label for branch in options)),
        documents=tuple(branch.documents for branch in sorted(options, key=lambda b: b.label)),
        coverage=round(len(reachable) / before, 4) if before else 0.0,
        worst_case_reduction=round(1 - max(branch.size for branch in options) / before, 4) if before else 0.0,
        dropped_documents=tuple(sorted(every - reachable)),
        reason="ask",
    )


# The strategies the experiment compares. Each is one reading of "expose only
# the genuinely useful branches"; the differences between them are exactly the
# design questions the phase brief asks about.
STRATEGIES: dict[str, PartialBranchPolicy] = {
    # The proposal at face value: drop branches that do not narrow enough, take
    # whichever facet then splits best. No coverage guard.
    "naive": PartialBranchPolicy(
        "naive", min_retained_coverage=0.0, min_useful_options=2,
    ),
    # The proposal with Phase 17's coverage guard retained.
    "guarded": PartialBranchPolicy("guarded"),
    # The proposal restricted to semantic facets, so it can never answer with
    # filename fragments.
    "semantic_only": PartialBranchPolicy("semantic_only", allow_filename_tokens=False),
    # The proposal with Phase 17's coverage treated the way Phase 17 treats it —
    # a rank bucket, not a floor — so a low-coverage facet loses to a better one
    # rather than being discarded.
    "phase17_ranked": PartialBranchPolicy("phase17_ranked", coverage_as_rank=True),
    # The honest alternative: keep every branch the corpus offers — including the
    # dominant one — and instead ask whenever at least two branches are
    # individually useful, the partition is fair, and no branch is a duplicate.
    "keep_dominant": PartialBranchPolicy(
        "keep_dominant", drop_dominant_branches=False, reject_on_duplicates=True,
    ),
}
