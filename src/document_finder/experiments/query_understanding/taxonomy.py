"""Demo taxonomy and lexical markers for the Phase 13 query-understanding experiment.

The category seed terms below are vocabulary observed in the current
36-document corpus (filenames, section headings, and chunk text). They are the
only human-supplied input to the experiment: document-to-category assignment is
computed from the corpus, so adding documents re-derives assignments without
editing this file.

This is a DEMO taxonomy for a DEMO corpus. It is not a proposed taxonomy for the
eventual Windchill repository.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


PLM = "plm"
IT = "it"
CROSS_DOMAIN = "cross_domain"
NO_DOMAIN = "none"

DOMAIN_LABELS = {
    PLM: "Manufacturing / PLM process documentation",
    IT: "Internal IT (deployment, infrastructure, operations)",
}


@dataclass(frozen=True)
class Category:
    name: str
    domain: str
    seed_terms: tuple[str, ...]


# Ordered for deterministic iteration.
CATEGORIES: tuple[Category, ...] = (
    Category("Change Management", PLM, (
        "change management", "change request", "change notice", "change task",
        "problem report", "undo reservation", "ecr", "ecn", "acn", "prr",
    )),
    Category("BOM / EBOM", PLM, (
        "bom", "ebom", "bill of material", "bom structure", "proto bom",
        "production bom", "excel template", "copy paste", "fg code",
    )),
    Category("Part / WTPart / CAD", PLM, (
        "part", "wtpart", "cad", "part creation", "imported parts",
        "mass calculation", "promotion request", "segments",
    )),
    Category("Procurement", PLM, (
        "procurement", "procurement kit", "quantity tracking", "hold tag",
    )),
    Category("Work Request", PLM, (
        "work request", "cre", "nvh", "combustion", "koel",
        "test report", "assembly report",
    )),
    Category("NPD / Project", PLM, (
        "npd", "gate", "milestone", "project creation", "npd request",
        "ms0", "ms1", "ms2", "ms3", "ms4", "ms5", "ms6",
    )),
    Category("Windchill Navigation & Admin", PLM, (
        "folder navigation", "navigation", "illum", "solidworks",
        "user separation", "workspace",
    )),
    Category("Product Reference", PLM, (
        "battlecard", "windchill+",
    )),
    Category("IT Deployment", IT, (
        "deployment", "deploy", "chatbot", "java utility", "rest domain",
        "backend", "custom actions", "compilation", "patch",
    )),
    Category("IT Infrastructure & Operations", IT, (
        "iraje", "pam", "aws", "host file", "daily report",
        "it infrastructure", "privileged access",
    )),
)

CATEGORY_BY_NAME = {category.name: category for category in CATEGORIES}


# Document-type facet, derived from filename vocabulary. Used to build a
# clarification question when candidates share one category but differ in kind.
DOCUMENT_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SOP / Work Instruction", ("sop",)),
    ("User Guide / Manual", ("user guide", "user manual", "manual", "guide")),
    ("Process Document", ("process",)),
    ("Reference / Battlecard", ("battlecard",)),
)


# Intent markers. Evaluated in this order; the first match wins, so
# "what is the process for..." resolves to procedural rather than informational.
PROCEDURAL_MARKERS: tuple[str, ...] = (
    "how do i", "how to", "how can i", "how does one", "how is",
    "steps to", "steps for", "step by step",
    "procedure to", "procedure for", "procedure of",
    "process to", "process for", "process of changing",
    "what is the process", "i need the process", "need the process",
    "instructions for", "instructions to", "guide me",
)

INFORMATIONAL_MARKERS: tuple[str, ...] = (
    "what is", "what are", "what's", "which ", "who ", "why ", "when ",
    "difference between", "meaning of", "definition of",
)

REFERENCE_MARKERS: tuple[str, ...] = (
    "user guide", "user manual", "manual", "battlecard", "sop",
    "process document", "document", "doc", "datasheet", "specification",
)

INTENT_PROCEDURAL = "procedural"
INTENT_REFERENCE = "reference"
INTENT_INFORMATIONAL = "informational"
INTENT_UNKNOWN = "unknown"

AMBIGUITY_LOW = "low"
AMBIGUITY_MEDIUM = "medium"
AMBIGUITY_HIGH = "high"


# Query words that carry no corpus topic signal.
STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could",
    "do", "does", "for", "from", "get", "give", "how", "i", "in", "into", "is",
    "it", "its", "me", "my", "need", "of", "on", "one", "or", "please", "s",
    "should", "some", "the", "their", "then", "there", "this", "to", "up",
    "want", "was", "what", "when", "where", "which", "while", "who", "why",
    "will", "with", "would", "you", "your",
})

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, in order, deterministically."""
    return _TOKEN_PATTERN.findall((text or "").lower())


def normalize(text: str) -> str:
    """Collapse to lowercase single-spaced text for multi-word phrase matching."""
    return " ".join(tokenize(text))


def content_terms(query: str) -> list[str]:
    """Query tokens with stopwords removed, order preserved, deduplicated."""
    seen: dict[str, None] = {}
    for token in tokenize(query):
        if token not in STOPWORDS:
            seen.setdefault(token, None)
    return list(seen)


def detect_intent(query: str) -> str:
    """Deterministic, order-sensitive intent classification from surface markers."""
    text = f" {normalize(query)} "
    if not text.strip():
        return INTENT_UNKNOWN
    for marker in PROCEDURAL_MARKERS:
        if marker in text:
            return INTENT_PROCEDURAL
    for marker in INFORMATIONAL_MARKERS:
        if marker in text:
            return INTENT_INFORMATIONAL
    for marker in REFERENCE_MARKERS:
        if f" {marker.strip()} " in text:
            return INTENT_REFERENCE
    return INTENT_UNKNOWN


def document_types(filename: str) -> list[str]:
    """Derive document-type labels from a filename, for the clarification facet."""
    text = normalize(filename)
    matched = [label for label, markers in DOCUMENT_TYPES if any(marker in text for marker in markers)]
    return matched or ["Process Document"]
