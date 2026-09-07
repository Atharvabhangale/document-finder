"""Deterministic query-understanding analyzer (Phase 13 experiment).

No generative model and no embedding model is used. Intent comes from surface
markers; topic, domain, categories, and ambiguity come from matching the query
against a read-only profile of the indexed corpus.

The central design choice is that **ambiguity is a property of the corpus, not of
query length**. A four-character query that matches exactly one document is not
ambiguous; a two-word query that matches nine documents across two domains is.
That is what lets the layer decide whether a clarification question would
actually narrow the corpus.

This module is not wired into retrieval. It never calls lexical, vector, or
hybrid search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from document_finder.experiments.query_understanding.corpus import (
    CategorizedDocument,
    CorpusProfile,
    FILENAME_WEIGHT,
    HEADING_WEIGHT,
)
from document_finder.experiments.query_understanding.taxonomy import (
    AMBIGUITY_HIGH,
    AMBIGUITY_LOW,
    AMBIGUITY_MEDIUM,
    CATEGORY_BY_NAME,
    CROSS_DOMAIN,
    DOMAIN_LABELS,
    INTENT_UNKNOWN,
    NO_DOMAIN,
    content_terms,
    detect_intent,
    tokenize,
)


# A document is a candidate when it covers at least half the query's content
# terms, matches at least one term in its filename or a section heading, and
# scores within this fraction of the best-scoring document.
#
# The filename/heading requirement is what keeps out-of-corpus queries honest: a
# query like "travel expense claim" can otherwise collect a false candidate off
# an incidental body-text word in a long document. Body text alone is too weak
# to establish that a query is *about* a document.
COVERAGE_THRESHOLD = 0.5
CANDIDATE_SCORE_FLOOR = 0.35
MIN_BEST_TERM_WEIGHT = HEADING_WEIGHT

# Candidates within this fraction of the top score genuinely compete for the
# top rank; ambiguity is judged on these.
STRONG_SCORE_RATIO = 0.75

# Clarification has to pay for itself. Asking the user a question to choose
# between two documents costs a round trip that simply listing both would not,
# so a question is only offered once the candidate set is larger than this.
# This is a policy knob, not a property of the corpus: it should be re-tuned
# against a real result-set size once a large repository is available.
MIN_CANDIDATES_FOR_CLARIFICATION = 3

# Categories and domain are read off candidates scoring within this fraction of
# the best match. Using every weak candidate made long natural-language queries
# report almost the whole taxonomy, because common words like "create" match
# body text everywhere.
CONTENDER_SCORE_RATIO = 0.5

# When a query contains at least one real topic term, terms naming the host
# system or a document kind are down-weighted: "Windchill" in
# "how to create a new part in Windchill" should not outrank "part".
NON_TOPIC_WEIGHT_FACTOR = 0.4

# Terms that name a document kind or the host system rather than a topic. A
# query built only from these carries no topic and is underspecified by nature.
NON_TOPIC_TERMS: frozenset[str] = frozenset({
    "battlecard", "doc", "document", "documents", "guide", "instruction",
    "instructions", "manual", "plm", "procedure", "process", "report", "sop",
    "user", "windchill",
})

# Filename tokens that never distinguish one document from another here.
UNINFORMATIVE_TOKENS: frozenset[str] = frozenset({
    "bel", "docx", "pdf", "v0", "v1", "v2", "v3", "process", "document",
    "sop", "the", "and", "for", "of", "to", "in", "a",
})

ESCAPE_OPTION = "Search everything"


@dataclass(frozen=True)
class Candidate:
    filename: str
    score: float
    coverage: float
    categories: tuple[str, ...]
    domains: tuple[str, ...]
    types: tuple[str, ...]
    document_id: str = ""


@dataclass(frozen=True)
class Clarification:
    question: str
    options: tuple[str, ...]
    facet: str
    option_candidate_counts: dict[str, int] = field(default_factory=dict)
    candidates_before: int = 0
    # Document identities each option selects, so a caller can act on the
    # user's choice without re-deriving the facet. Reporting only; no decision
    # in this module reads it.
    option_documents: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def reduces_search_space(self) -> bool:
        """True when every offered option selects a strict, non-empty subset."""
        real_options = {
            option: count for option, count in self.option_candidate_counts.items()
            if option != ESCAPE_OPTION
        }
        if len(real_options) < 2 or self.candidates_before < 2:
            return False
        return all(0 < count < self.candidates_before for count in real_options.values())

    @property
    def largest_option_candidates(self) -> int:
        real = [count for option, count in self.option_candidate_counts.items() if option != ESCAPE_OPTION]
        return max(real) if real else self.candidates_before


@dataclass(frozen=True)
class QueryUnderstanding:
    original_query: str
    topic: str
    intent: str
    domain: str
    candidate_categories: tuple[str, ...]
    confidence: float
    ambiguity: str
    needs_clarification: bool
    candidate_documents: tuple[str, ...] = ()
    clarification: Clarification | None = None

    def to_dict(self) -> dict[str, Any]:
        """The experiment's structured output. Clarification keys appear only when needed."""
        payload: dict[str, Any] = {
            "original_query": self.original_query,
            "topic": self.topic,
            "intent": self.intent,
            "domain": self.domain,
            "candidate_categories": list(self.candidate_categories),
            "confidence": self.confidence,
            "ambiguity": self.ambiguity,
            "needs_clarification": self.needs_clarification,
            "candidate_documents": list(self.candidate_documents),
        }
        if self.clarification is not None:
            payload["clarification_question"] = self.clarification.question
            payload["clarification_options"] = list(self.clarification.options)
            payload["clarification_facet"] = self.clarification.facet
            payload["clarification_reduces_search_space"] = self.clarification.reduces_search_space
        return payload


def _multipliers(terms: list[str]) -> dict[str, float]:
    """Down-weight system/document-type words, but only if a topic term is present."""
    has_topic_term = any(term not in NON_TOPIC_TERMS for term in terms)
    return {
        term: NON_TOPIC_WEIGHT_FACTOR if has_topic_term and term in NON_TOPIC_TERMS else 1.0
        for term in terms
    }


def _score_document(
    document: CategorizedDocument, terms: list[str], multipliers: dict[str, float]
) -> tuple[float, float, float]:
    """Return (mean weighted score per query term, fraction of terms present, best raw weight).

    The best *raw* weight drives the filename/heading gate, so down-weighting a
    system word never changes whether a document qualifies as a candidate at all.
    """
    raw = [document.profile.term_weight(term) for term in terms]
    weighted = [weight * multipliers.get(term, 1.0) for term, weight in zip(terms, raw)]
    matched = [weight for weight in raw if weight > 0]
    if not matched:
        return 0.0, 0.0, 0.0
    return round(sum(weighted) / len(terms), 4), round(len(matched) / len(terms), 4), max(matched)


def _candidates(profile: CorpusProfile, terms: list[str]) -> list[Candidate]:
    multipliers = _multipliers(terms)
    scored: list[tuple[CategorizedDocument, float, float]] = []
    for document in profile.documents:
        score, coverage, best_term = _score_document(document, terms, multipliers)
        if score > 0 and coverage >= COVERAGE_THRESHOLD and best_term >= MIN_BEST_TERM_WEIGHT:
            scored.append((document, score, coverage))
    if not scored:
        return []
    top = max(score for _, score, _ in scored)
    kept = [
        Candidate(document.filename, score, coverage, document.categories, document.domains,
                  document.types, document.document_id)
        for document, score, coverage in scored
        if score >= CANDIDATE_SCORE_FLOOR * top
    ]
    return sorted(kept, key=lambda candidate: (-candidate.score, candidate.filename))


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return tuple(seen)


def _finalize(
    question: str, facet: str, members: dict[str, list[Candidate]], before: int
) -> Clarification | None:
    """Keep only options that genuinely narrow the candidate set.

    An option selecting every candidate (or none) teaches the user nothing, so it
    is dropped rather than allowed to invalidate an otherwise useful question. At
    least two narrowing options must survive.
    """
    narrowing = {
        option: selected for option, selected in members.items() if 0 < len(selected) < before
    }
    if len(narrowing) < 2:
        return None
    options = (*sorted(narrowing), ESCAPE_OPTION)
    counts = {option: len(selected) for option, selected in narrowing.items()}
    documents = {
        option: tuple(candidate.document_id for candidate in selected if candidate.document_id)
        for option, selected in narrowing.items()
    }
    return Clarification(
        question, options, facet, {**counts, ESCAPE_OPTION: before}, before, documents
    )


def _build_clarification(
    candidates: list[Candidate], strong: list[Candidate], categories: tuple[str, ...],
    domains: tuple[str, ...], terms: list[str],
) -> Clarification | None:
    """Pick the facet that best partitions the candidates, most discriminating first."""
    before = len(candidates)
    if before < MIN_CANDIDATES_FOR_CLARIFICATION:
        return None

    if len(domains) > 1:
        by_domain = {
            DOMAIN_LABELS[domain]: [c for c in candidates if domain in c.domains]
            for domain in domains if domain in DOMAIN_LABELS
        }
        clarification = _finalize("Which area are you looking in?", "domain", by_domain, before)
        if clarification is not None:
            return clarification

    if len(categories) > 1:
        by_category = {
            category: [c for c in candidates if category in c.categories]
            for category in categories
        }
        clarification = _finalize("What are you looking for?", "category", by_category, before)
        if clarification is not None:
            return clarification

    by_type: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        for document_type in candidate.types:
            by_type.setdefault(document_type, []).append(candidate)
    clarification = _finalize("What kind of document do you need?", "document_type", by_type, before)
    if clarification is not None:
        return clarification

    query_terms = set(terms)
    by_token: dict[str, list[Candidate]] = {}
    preceding: dict[str, str] = {}
    for candidate in candidates:
        tokens = tokenize(candidate.filename)
        for position, token in enumerate(tokens):
            # A token the user already typed cannot separate the candidates.
            if token in UNINFORMATIVE_TOKENS or token in query_terms or len(token) < 2:
                continue
            if position > 0:
                preceding.setdefault(token, tokens[position - 1])
            by_token.setdefault(token, []).append(candidate)
    discriminating = sorted(
        ((token, selected) for token, selected in by_token.items() if 0 < len(selected) < before),
        key=lambda item: (-len(item[1]), item[0]),
    )[:5]
    labelled: dict[str, list[Candidate]] = {}
    for token, selected in discriminating:
        # A bare number ("01") is meaningless as an option label; qualify it with
        # the word in front of it in the filename ("Version 01").
        if token.isdigit() and preceding.get(token):
            label = f"{preceding[token].title()} {token}"
        else:
            label = token.upper() if len(token) <= 3 else token.title()
        labelled[label] = selected
    return _finalize("Which one do you need?", "distinguishing_term", labelled, before)


def _confidence(
    candidates: list[Candidate], strong: list[Candidate], intent: str, ambiguity: str, non_topic_only: bool
) -> float:
    """Deterministic confidence in a *single* interpretation of the query.

    Capped when the query is highly ambiguous or carries no topic term: a
    confident-looking score on a query the layer wants to clarify would be
    self-contradictory.
    """
    if not candidates:
        return 0.1
    score_component = min(candidates[0].score / FILENAME_WEIGHT, 1.0) * 0.5
    intent_component = 0.25 if intent != INTENT_UNKNOWN else 0.05
    if len(strong) == 1:
        concentration = 0.25
    elif len(strong) <= 3:
        concentration = 0.12
    else:
        concentration = 0.03
    confidence = score_component + intent_component + concentration
    if ambiguity == AMBIGUITY_HIGH:
        confidence = min(confidence, 0.5)
    if non_topic_only:
        confidence = min(confidence, 0.4)
    return round(min(max(confidence, 0.0), 1.0), 2)


def analyze_query(query: str, profile: CorpusProfile) -> QueryUnderstanding:
    """Interpret one query against the corpus profile. Deterministic and side-effect free."""
    original = query if isinstance(query, str) else ""
    terms = content_terms(original)
    intent = detect_intent(original)

    if not terms:
        return QueryUnderstanding(
            original_query=original, topic="", intent=INTENT_UNKNOWN, domain=NO_DOMAIN,
            candidate_categories=(), confidence=0.1, ambiguity=AMBIGUITY_HIGH,
            needs_clarification=False,
        )

    candidates = _candidates(profile, terms)
    if not candidates:
        # No corpus match. Clarification cannot rescue this; an honest no-match is correct.
        return QueryUnderstanding(
            original_query=original, topic=" ".join(terms), intent=intent, domain=NO_DOMAIN,
            candidate_categories=(), confidence=0.1, ambiguity=AMBIGUITY_HIGH,
            needs_clarification=False,
        )

    top = candidates[0].score
    strong = [candidate for candidate in candidates if candidate.score >= STRONG_SCORE_RATIO * top]
    contenders = [candidate for candidate in candidates if candidate.score >= CONTENDER_SCORE_RATIO * top]
    categories = _ordered_unique([name for candidate in contenders for name in candidate.categories])
    domains = _ordered_unique([domain for candidate in contenders for domain in candidate.domains])
    non_topic_only = all(term in NON_TOPIC_TERMS for term in terms)

    # Topic: the query's corpus-anchored terms, preferring those that matched a
    # filename. Not evaluated against labels (see LABELS.md).
    anchored = [
        term for term in terms
        if any(candidate_profile.profile.term_weight(term) >= FILENAME_WEIGHT for candidate_profile in profile.documents)
    ]
    topic = " ".join(anchored or terms)

    domain = CROSS_DOMAIN if len(domains) > 1 else (domains[0] if domains else NO_DOMAIN)

    # A query carrying no topic term ("SOP", "user guide") is underspecified, but
    # only *problematically* so when it actually admits many candidates: exactly
    # one battlecard exists, so "battlecard" needs no clarification.
    if non_topic_only and len(candidates) >= MIN_CANDIDATES_FOR_CLARIFICATION:
        ambiguity = AMBIGUITY_HIGH
    elif len(strong) == 1:
        ambiguity = AMBIGUITY_LOW
    elif intent == INTENT_UNKNOWN:
        ambiguity = AMBIGUITY_HIGH
    else:
        ambiguity = AMBIGUITY_MEDIUM

    clarification = None
    if ambiguity == AMBIGUITY_HIGH:
        clarification = _build_clarification(candidates, strong, categories, domains, terms)
        if clarification is not None and not clarification.reduces_search_space:
            clarification = None

    return QueryUnderstanding(
        original_query=original,
        topic=topic,
        intent=intent,
        domain=domain,
        candidate_categories=categories,
        confidence=_confidence(candidates, strong, intent, ambiguity, non_topic_only),
        ambiguity=ambiguity,
        needs_clarification=clarification is not None,
        candidate_documents=tuple(candidate.filename for candidate in candidates),
        clarification=clarification,
    )
