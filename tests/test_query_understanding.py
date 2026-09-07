"""Isolated tests for the Phase 13 query-understanding experiment.

These build a synthetic corpus profile so they do not depend on `data/` being
present, and they assert that the experiment stays disconnected from the
production retrieval pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from document_finder.experiments.query_understanding import (
    CorpusProfile,
    DocumentProfile,
    analyze_query,
)
from document_finder.experiments.query_understanding.analyzer import ESCAPE_OPTION


@pytest.fixture(scope="module")
def profile() -> CorpusProfile:
    """A miniature stand-in for the real corpus, including its awkward cases."""
    return CorpusProfile.from_profiles([
        # Change management: several documents of differing document type.
        DocumentProfile("BEL_SOP_Change Management Process_PRR ECR ECN_V0.pdf", (), "raise an ecr and ecn"),
        DocumentProfile("PR-ECR-ECN-ACN Process.docx", (), "problem report change request"),
        DocumentProfile("User Guide_Company standard document Change Management Process Document.docx",
                        ("Change Request Creation:",), "change notice creation"),
        DocumentProfile("BEL_SOP_Change Task Deletion & Undo Reservation Activity Process_V0.pdf", (),
                        "delete a change task"),
        # BOM / part. Mirrors the real corpus, which holds several BOM documents
        # and a part document that genuinely also covers BOM structure.
        DocumentProfile("BEL_SOP_BOM Creation Using Excel Template Sheet_V0.pdf", (), "bom creation"),
        DocumentProfile("BEL_SOP_BOM Creation Using Copy Paste Function and Modification of BOM_V0.pdf", (),
                        "bom creation copy paste"),
        DocumentProfile("BEL_SOP_Copy BOM Structure from Concept FG Code to Final FG Code_V0.pdf", (),
                        "copy bom structure fg code"),
        DocumentProfile("Part Creation & EBOM Process.docx",
                        ("Significance of 5 Segments", "Adding BOM Structure"),
                        "part creation ebom bill of material bom structure"),
        # Exactly one procurement document: a short query here is NOT ambiguous.
        DocumentProfile("Procurement Kit Process Document.docx", ("Procurement Kit Creation Steps:",),
                        "procurement kit"),
        # Enumerable discriminator in the filenames.
        *[DocumentProfile(f"NPD MS process in PLM - MS{index} gate (V1).pdf", (), "npd milestone gate")
          for index in range(4)],
        # IT domain, and the real cross-domain collision: "BOM" in an IT heading.
        DocumentProfile("Deployment_Document_for_Bajaj_Chatbot_Version_01.docx",
                        ("A) Multi-Level BOM Extraction Deployment",), "java utility deployment"),
        DocumentProfile("Deployment_Document_for_Bajaj_Chatbot_Version_02.docx",
                        ("Java Utility Deployment",), "java utility deployment"),
        DocumentProfile("Deployment_Document_for_Bajaj_Chatbot_Version_03.docx",
                        ("Compilation & Server Restart",), "chatbot utility"),
        DocumentProfile("Iraje_PAM_SOP.docx", ("Step 1: Update Host File",), "iraje pam privileged access"),
    ])


def test_clearly_procedural_query_is_not_clarified(profile: CorpusProfile) -> None:
    result = analyze_query("how do I create an ECR?", profile)
    assert result.intent == "procedural"
    assert result.domain == "plm"
    assert "Change Management" in result.candidate_categories
    assert result.needs_clarification is False
    assert result.clarification is None


def test_category_specific_query_resolves_to_one_category(profile: CorpusProfile) -> None:
    result = analyze_query("steps to create a procurement kit", profile)
    assert result.intent == "procedural"
    assert result.candidate_categories == ("Procurement",)
    assert result.ambiguity == "low"
    assert result.needs_clarification is False


def test_ambiguous_short_query_requests_clarification(profile: CorpusProfile) -> None:
    result = analyze_query("gate", profile)
    assert result.intent == "unknown"
    assert result.ambiguity == "high"
    assert result.needs_clarification is True
    assert result.clarification is not None
    assert ESCAPE_OPTION in result.clarification.options
    # The offered options must genuinely narrow the candidate set.
    assert result.clarification.reduces_search_space is True
    assert result.clarification.largest_option_candidates < len(result.candidate_documents)


def test_short_but_specific_query_must_not_be_clarified(profile: CorpusProfile) -> None:
    """Shortness alone must never trigger a clarification prompt."""
    result = analyze_query("procurement", profile)
    assert result.ambiguity == "low"
    assert result.needs_clarification is False


def test_natural_language_query_is_understood(profile: CorpusProfile) -> None:
    result = analyze_query("what are the 5 segments of a part number?", profile)
    assert result.intent == "informational"
    assert result.needs_clarification is False
    assert "Part / WTPart / CAD" in result.candidate_categories


def test_cross_domain_term_is_detected_and_clarified(profile: CorpusProfile) -> None:
    """'BOM' occurs in both the PLM documents and an IT deployment heading."""
    result = analyze_query("BOM", profile)
    assert result.domain == "cross_domain"
    assert result.needs_clarification is True
    assert result.clarification is not None
    assert result.clarification.facet == "domain"
    assert result.clarification.reduces_search_space is True


def test_domain_router_is_not_fooled_by_a_plm_looking_token(profile: CorpusProfile) -> None:
    """A distinctive IT phrase containing 'BOM' must stay in the IT domain."""
    result = analyze_query("multi-level BOM extraction", profile)
    assert "IT Deployment" in result.candidate_categories
    assert result.candidate_documents[0].startswith("Deployment_Document_for_Bajaj_Chatbot")


def test_out_of_corpus_query_is_low_confidence_and_not_clarified(profile: CorpusProfile) -> None:
    """Clarification cannot rescue a query with no corpus match; say so instead."""
    result = analyze_query("how do I file a travel expense claim?", profile)
    assert result.domain == "none"
    assert result.candidate_categories == ()
    assert result.candidate_documents == ()
    assert result.confidence <= 0.2
    assert result.needs_clarification is False


@pytest.mark.parametrize("query", ["", "   ", "???", None])
def test_empty_and_invalid_queries_are_handled(profile: CorpusProfile, query: object) -> None:
    result = analyze_query(query, profile)  # type: ignore[arg-type]
    assert result.intent == "unknown"
    assert result.domain == "none"
    assert result.needs_clarification is False
    assert result.candidate_categories == ()
    assert result.to_dict()["needs_clarification"] is False


def test_confidence_is_lower_when_clarifying_than_when_searching(profile: CorpusProfile) -> None:
    ambiguous = analyze_query("gate", profile)
    specific = analyze_query("steps to create a procurement kit", profile)
    assert ambiguous.confidence < specific.confidence


def test_output_is_deterministic_and_reproducible(profile: CorpusProfile) -> None:
    for query in ["ECR", "gate", "BOM", "how do I create an ECR?", "", "procurement"]:
        first = analyze_query(query, profile).to_dict()
        second = analyze_query(query, profile).to_dict()
        assert first == second
        # Rebuilding the profile from the same documents must not change results.
        rebuilt = CorpusProfile.from_profiles([document.profile for document in profile.documents])
        assert analyze_query(query, rebuilt).to_dict() == first
        json.dumps(first)  # the structured result must be JSON-serialisable


def test_required_output_schema_is_present(profile: CorpusProfile) -> None:
    payload = analyze_query("gate", profile).to_dict()
    for key in (
        "original_query", "topic", "intent", "candidate_categories",
        "confidence", "ambiguity", "needs_clarification",
    ):
        assert key in payload, key
    assert {"clarification_question", "clarification_options"} <= set(payload)
    assert 0.0 <= payload["confidence"] <= 1.0

    direct = analyze_query("steps to create a procurement kit", profile).to_dict()
    assert "clarification_question" not in direct
    assert "clarification_options" not in direct


def test_document_categories_retain_genuine_overlap(profile: CorpusProfile) -> None:
    """A part-and-BOM document must keep both categories rather than be forced into one."""
    part_document = next(
        document for document in profile.documents
        if document.filename == "Part Creation & EBOM Process.docx"
    )
    assert "Part / WTPart / CAD" in part_document.categories
    assert "BOM / EBOM" in part_document.categories


def test_experiment_stays_isolated_from_production_retrieval() -> None:
    """Phase 13 must not be wired into ingestion, retrieval, or the API."""
    from document_finder.experiments.query_understanding import analyzer, corpus

    for module in (analyzer, corpus):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "document_finder.search" not in source
        assert "faiss" not in source
        assert "embeddings" not in source

    production = Path("src/document_finder")
    for relative in ("api/routes.py", "api/app.py", "search/vector.py",
                     "search/lexical.py", "search/hybrid.py", "ingestion/pipeline.py"):
        source = (production / relative).read_text(encoding="utf-8")
        assert "experiments" not in source, f"{relative} must not import the experiment"


def test_real_corpus_profile_loads_when_available() -> None:
    database = Path("data/document_finder.sqlite3")
    if not database.is_file():
        pytest.skip("indexed corpus is not present in this checkout")
    real = CorpusProfile.from_sqlite(database)
    assert len(real.documents) > 0
    assert all(document.categories or document.types for document in real.documents)
    # Read-only access must not have created a stray journal file.
    assert not Path("data/document_finder.sqlite3-journal").exists()
