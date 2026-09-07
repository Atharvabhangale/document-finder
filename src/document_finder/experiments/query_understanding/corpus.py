"""Read-only corpus profile for the query-understanding experiment.

This module only READS persisted metadata (filenames, section headings, chunk
text) from the existing SQLite index. It does not call lexical, vector, or
hybrid retrieval, does not touch the FAISS index or the embedding model, and
writes nothing. The retrieval pipeline is unaffected by anything here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from document_finder.experiments.query_understanding.taxonomy import (
    CATEGORIES,
    CATEGORY_BY_NAME,
    document_types,
    normalize,
    tokenize,
)


# Field weights: a filename match is far stronger evidence than a passing
# mention in body text.
FILENAME_WEIGHT = 3.0
HEADING_WEIGHT = 1.5
TEXT_WEIGHT = 0.5

# A document keeps every category scoring within this fraction of its best
# category, so genuine overlaps (a part document that is also a BOM document)
# are retained rather than forced into one bucket.
CATEGORY_RETENTION = 0.6


@dataclass(frozen=True)
class DocumentProfile:
    """One indexed document, reduced to the text fields used for matching."""

    filename: str
    headings: tuple[str, ...] = ()
    text: str = ""
    # Stable identity from the index. Optional so synthetic profiles stay terse;
    # populated from SQLite so a caller can resolve a document exactly.
    document_id: str = ""

    @property
    def filename_tokens(self) -> frozenset[str]:
        return frozenset(tokenize(self.filename))

    @property
    def heading_tokens(self) -> frozenset[str]:
        return frozenset(token for heading in self.headings for token in tokenize(heading))

    @property
    def text_tokens(self) -> frozenset[str]:
        return frozenset(tokenize(self.text))

    @property
    def normalized_filename(self) -> str:
        return normalize(self.filename)

    @property
    def normalized_body(self) -> str:
        return normalize(" ".join([*self.headings, self.text]))

    def term_weight(self, term: str) -> float:
        """Best field weight for one query term against this document."""
        if term in self.filename_tokens:
            return FILENAME_WEIGHT
        if term in self.heading_tokens:
            return HEADING_WEIGHT
        if term in self.text_tokens:
            return TEXT_WEIGHT
        return 0.0

    def phrase_weight(self, phrase: str) -> float:
        """Best field weight for a multi-word seed phrase."""
        if phrase in self.normalized_filename:
            return FILENAME_WEIGHT
        if phrase in self.normalized_body:
            return TEXT_WEIGHT if phrase not in normalize(" ".join(self.headings)) else HEADING_WEIGHT
        return 0.0

    def seed_weight(self, seed: str) -> float:
        return self.phrase_weight(seed) if " " in seed else self.term_weight(seed)


@dataclass(frozen=True)
class CategorizedDocument:
    """A document with its corpus-derived categories, primary domain, and types."""

    profile: DocumentProfile
    categories: tuple[str, ...]
    domains: tuple[str, ...]
    types: tuple[str, ...]
    category_scores: dict[str, float] = field(default_factory=dict)

    @property
    def filename(self) -> str:
        return self.profile.filename

    @property
    def document_id(self) -> str:
        return self.profile.document_id

    @property
    def primary_domain(self) -> str | None:
        return self.domains[0] if self.domains else None


def categorize(profile: DocumentProfile) -> CategorizedDocument:
    """Assign categories to one document from taxonomy seed terms in the corpus text."""
    scores: dict[str, float] = {}
    for category in CATEGORIES:
        score = sum(profile.seed_weight(seed) for seed in category.seed_terms)
        if score > 0:
            scores[category.name] = round(score, 3)
    if not scores:
        return CategorizedDocument(profile, (), (), tuple(document_types(profile.filename)), {})
    best = max(scores.values())
    kept = sorted(
        (name for name, score in scores.items() if score >= CATEGORY_RETENTION * best),
        key=lambda name: (-scores[name], name),
    )
    domains: list[str] = []
    for name in kept:
        domain = CATEGORY_BY_NAME[name].domain
        if domain not in domains:
            domains.append(domain)
    return CategorizedDocument(
        profile, tuple(kept), tuple(domains), tuple(document_types(profile.filename)), scores
    )


@dataclass(frozen=True)
class CorpusProfile:
    """The categorized corpus the experiment reasons over."""

    documents: tuple[CategorizedDocument, ...]

    @classmethod
    def from_profiles(cls, profiles: list[DocumentProfile]) -> "CorpusProfile":
        ordered = sorted(profiles, key=lambda profile: profile.filename.casefold())
        return cls(tuple(categorize(profile) for profile in ordered))

    @classmethod
    def from_sqlite(cls, database_path: Path | str) -> "CorpusProfile":
        """Load filenames, headings, and chunk text read-only from the SQLite index."""
        path = Path(database_path)
        if not path.is_file():
            raise FileNotFoundError(f"SQLite index does not exist: {path}")
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            documents = connection.execute(
                "SELECT document_id, filename FROM documents WHERE status = 'indexed' ORDER BY filename"
            ).fetchall()
            profiles: list[DocumentProfile] = []
            for document in documents:
                headings = [
                    row["heading"]
                    for row in connection.execute(
                        "SELECT heading FROM sections WHERE document_id = ? ORDER BY ordinal",
                        (document["document_id"],),
                    )
                ]
                text = " ".join(
                    row["source_text"]
                    for row in connection.execute(
                        "SELECT source_text FROM chunks WHERE document_id = ? ORDER BY chunk_id",
                        (document["document_id"],),
                    )
                )
                profiles.append(DocumentProfile(
                    document["filename"], tuple(headings), text, document["document_id"]
                ))
        finally:
            connection.close()
        return cls.from_profiles(profiles)

    def categories(self) -> list[str]:
        names = {name for document in self.documents for name in document.categories}
        return sorted(names)

    def documents_in_category(self, category: str) -> list[str]:
        return [document.filename for document in self.documents if category in document.categories]
