"""Optional query-understanding layer that sits in front of search.

This is the product-side integration of the Phase 13 experiment. It adds no
retrieval logic of its own: it calls the unmodified Phase 13 analyzer, decides
whether asking the user one question would be worth the round trip, and — if
the user answers — reports which documents that answer selects.

    query -> analyze -> worth asking? -> clarify, else search unchanged

Retrieval is untouched. Embeddings, FAISS, similarity, lexical and hybrid
search, ingestion, OCR and chunking are never called from here. Every failure
path falls back to plain search, so the experimental layer can never stop the
product from working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from document_finder import config
from document_finder.experiments.query_understanding import CorpusProfile, analyze_query
from document_finder.experiments.query_understanding.analyzer import Clarification, ESCAPE_OPTION


# Building a corpus profile reads every chunk's text, which is far too much work
# to repeat per request. The cache is keyed on the database's identity and
# mtime, so a re-index is picked up automatically.
_PROFILE_CACHE: dict[tuple[str, int, int], CorpusProfile] = {}
_CACHE_LIMIT = 4


@dataclass(frozen=True)
class ClarificationOption:
    """One answer the user can pick. `value` is what the client sends back."""

    label: str
    value: str
    document_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedQuery:
    """The decision for one query: search now, or ask one question first."""

    query: str
    needs_clarification: bool
    question: str | None = None
    options: tuple[ClarificationOption, ...] = ()
    # Internal diagnostics. Never returned to the browser.
    reason: str = ""
    candidates_before: int = 0
    largest_option_candidates: int = 0
    facet: str = ""

    @property
    def reduction(self) -> float:
        if self.candidates_before < 1:
            return 0.0
        return round(1 - self.largest_option_candidates / self.candidates_before, 4)


def corpus_profile(database_path: Path | str | None = None) -> CorpusProfile:
    """Load (and cache) the read-only corpus profile the analyzer reasons over."""
    path = Path(database_path) if database_path else config.database_path()
    stat = path.stat()
    key = (str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
    cached = _PROFILE_CACHE.get(key)
    if cached is None:
        if len(_PROFILE_CACHE) >= _CACHE_LIMIT:
            _PROFILE_CACHE.clear()
        cached = _PROFILE_CACHE[key] = CorpusProfile.from_sqlite(path)
    return cached


def clear_cache() -> None:
    _PROFILE_CACHE.clear()


def _worth_asking(clarification: Clarification) -> tuple[bool, float]:
    """Judge a clarification by how much of the candidate set it removes.

    Reuses the Phase 13 signals rather than recomputing them: the analyzer
    already requires every option to select a strict subset, and already reports
    the largest option. The worst case is what matters — a question whose least
    helpful answer barely narrows anything is not worth asking, which is why a
    domain split like "SOP" (16 candidates down to 14) is declined here even
    though the analyzer is willing to offer it.
    """
    if not clarification.reduces_search_space:
        return False, 0.0
    before = clarification.candidates_before
    if before < 1:
        return False, 0.0
    reduction = 1 - clarification.largest_option_candidates / before
    return reduction >= config.min_clarification_reduction(), reduction


def _options(clarification: Clarification) -> tuple[ClarificationOption, ...]:
    """Narrowing options only. The escape route is always offered by the UI."""
    return tuple(
        ClarificationOption(label, label, tuple(clarification.option_documents.get(label, ())))
        for label in clarification.options
        if label != ESCAPE_OPTION
    )


def prepare(query: str, database_path: Path | str | None = None) -> PreparedQuery:
    """Decide whether `query` should be clarified before searching.

    Never raises: if anything about the experimental layer fails, the answer is
    "search normally".
    """
    text = query if isinstance(query, str) else ""
    if not config.query_understanding_enabled():
        return PreparedQuery(text, False, reason="disabled")
    try:
        profile = corpus_profile(database_path)
        understanding = analyze_query(text, profile)
    except Exception:
        # Deliberately broad: a missing index, an unreadable database, or a bug
        # in the experiment must degrade to plain search, not an error page.
        return PreparedQuery(text, False, reason="unavailable")

    clarification = understanding.clarification
    if not understanding.needs_clarification or clarification is None:
        return PreparedQuery(text, False, reason=f"direct:{understanding.ambiguity}")

    useful, reduction = _worth_asking(clarification)
    options = _options(clarification)
    if not useful or len(options) < 2:
        return PreparedQuery(
            text, False, reason="reduction_too_small",
            candidates_before=clarification.candidates_before,
            largest_option_candidates=clarification.largest_option_candidates,
            facet=clarification.facet,
        )
    return PreparedQuery(
        text, True, question=clarification.question, options=options, reason="clarify",
        candidates_before=clarification.candidates_before,
        largest_option_candidates=clarification.largest_option_candidates,
        facet=clarification.facet,
    )


def documents_for_choice(
    query: str, choice: str, database_path: Path | str | None = None
) -> tuple[str, ...] | None:
    """Document identities selected by the user's answer, or None to not narrow.

    The analyzer is deterministic, so the same query yields the same options and
    the client only has to send back the label it was shown. An unrecognised or
    stale choice narrows nothing rather than failing the search.
    """
    if not choice or not isinstance(choice, str):
        return None
    prepared = prepare(query, database_path)
    if not prepared.needs_clarification:
        return None
    for option in prepared.options:
        if option.value == choice:
            return option.document_ids or None
    return None
