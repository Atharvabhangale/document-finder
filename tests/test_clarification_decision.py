"""Clarification decision-layer regression tests (Phase 17).

Pins the manually observed production behaviour for the eight probe queries and
documents the decision path they exercise.

The path under test, as it actually works:

1. `analyzer._candidates` selects documents covering >= 50% of the query's
   content terms, matching at least one term in a filename or heading (body text
   alone is too weak), and scoring within 35% of the best match.
2. Queries with fewer than `MIN_CANDIDATES_FOR_CLARIFICATION` candidates get no
   clarification at all: listing two documents beats asking about them.
3. `analyzer._build_clarification` walks a facet ladder — domain, category,
   document type, then filename token — and each facet keeps only options that
   select a strict, non-empty subset (an option covering every candidate teaches
   nothing and is dropped). A facet is viable when >= 2 such options survive.
   Semantic facets are preferred over the filename-token facet.
4. `understanding._worth_asking` then requires the *worst-case* reduction
   (1 - largest_option / candidates_before) to reach
   QUERY_UNDERSTANDING_MIN_REDUCTION, default 0.5.
"""

from __future__ import annotations

import pytest

from document_finder import config, understanding
from document_finder.experiments.query_understanding import CorpusProfile, DocumentProfile, analyze_query
from document_finder.experiments.query_understanding.analyzer import ESCAPE_OPTION


# A synthetic corpus mirroring the real 36-document corpus for these queries:
# same filenames, so the same categories, document types and filename tokens are
# derived. Hermetic — no SQLite, no ingestion, no embedding model.
CORPUS = CorpusProfile.from_profiles([
    # Change management family (ECR / change management).
    DocumentProfile("BEL_SOP_Change Management Process_PRR ECR ECN_V0.pdf", (), "raise an ecr ecn", "d01"),
    DocumentProfile("PR-ECR-ECN-ACN Process.docx", (), "problem report change request ecr", "d02"),
    DocumentProfile("Change Management Process_.docx", ("Problem Report Proto BOM",),
                    "change management proto bom production bom", "d03"),
    DocumentProfile("User Guide_Company standard document Change Management Process Document.docx",
                    ("Change Request Creation:",), "change notice creation", "d04"),
    DocumentProfile("BEL_SOP_Change Task Deletion & Undo Reservation Activity Process_V0.pdf", (),
                    "delete a change task", "d05"),
    # BOM family.
    DocumentProfile("BEL_SOP_BOM Creation Using Copy Paste Function and Modification of BOM_V0.pdf", (),
                    "bom creation copy paste", "d06"),
    DocumentProfile("BEL_SOP_BOM Creation Using Excel Template Sheet_V0.pdf", (), "bom creation excel", "d07"),
    DocumentProfile("BEL_SOP_Copy BOM Structure from Concept FG Code to Final FG Code_V0.pdf", (),
                    "copy bom structure fg code", "d08"),
    DocumentProfile("Part Creation & EBOM Process.docx", ("Adding BOM Structure", "Significance of 5 Segments"),
                    "part creation ebom bom structure", "d09"),
    # NPD gates (strong enumerable discriminator).
    *[DocumentProfile(f"NPD MS process in PLM - MS{gate} gate (V1).pdf", (), "npd milestone gate", f"g{gate}")
      for gate in range(7)],
    # IT deployment (versioned discriminator, and the BOM cross-domain collision).
    DocumentProfile("Deployment_Document_for_Bajaj_Chatbot_Version_01.docx",
                    ("A) Multi-Level BOM Extraction Deployment",), "java utility deployment", "d10"),
    DocumentProfile("Deployment_Document_for_Bajaj_Chatbot_Version_02.docx", ("Java Utility Deployment",),
                    "java utility deployment", "d11"),
    DocumentProfile("Deployment_Document_for_Bajaj_Chatbot_Version_03.docx", ("Compilation & Server Restart",),
                    "chatbot utility", "d12"),
    # Work request family.
    DocumentProfile("Work Request CRE Combustion Process Document_v2.docx", (), "cre combustion work request", "d13"),
    DocumentProfile("Work Request CRE Process Document - KOEL.docx", (), "cre koel work request", "d14"),
    DocumentProfile("Work Request NVH Process Document.docx", (), "nvh work request", "d15"),
    DocumentProfile("BEL_SOP_NPD Request Creation User Manual_V0.pdf", (), "npd request creation", "d16"),
    DocumentProfile("BEL_SOP_Promotion Request to Released WTPart and CAD Parts_V0.pdf", (),
                    "promotion request wtpart cad", "d17"),
    # Single unambiguous document.
    DocumentProfile("Procurement Kit Process Document.docx", ("Procurement Kit Creation Steps:",),
                    "procurement kit creation", "d18"),
])


@pytest.fixture
def synthetic(monkeypatch: pytest.MonkeyPatch):
    """Run the real `prepare()` path against the synthetic corpus."""
    monkeypatch.delenv(config.QUERY_UNDERSTANDING_VARIABLE, raising=False)
    monkeypatch.delenv(config.MIN_REDUCTION_VARIABLE, raising=False)
    monkeypatch.setattr(understanding, "corpus_profile", lambda *a, **k: CORPUS)
    return CORPUS


def labels(prepared) -> list[str]:
    return [option.label for option in prepared.options]


# ------------------------------------------------------- must keep clarifying


def test_gate_clarifies_with_enumerable_gate_options(synthetic) -> None:
    prepared = understanding.prepare("gate")
    assert prepared.needs_clarification is True
    assert labels(prepared) == ["MS0", "MS1", "MS2", "MS3", "MS4"]
    assert ESCAPE_OPTION not in labels(prepared)


def test_chatbot_clarifies_with_version_options(synthetic) -> None:
    prepared = understanding.prepare("chatbot")
    assert prepared.needs_clarification is True
    assert labels(prepared) == ["Version 01", "Version 02", "Version 03"]


def test_change_management_clarifies_by_document_type(synthetic) -> None:
    """A semantic facet must win here, never the noisier filename-token facet."""
    prepared = understanding.prepare("change management")
    assert prepared.needs_clarification is True
    assert prepared.facet == "document_type"
    assert labels(prepared) == ["SOP / Work Instruction", "User Guide / Manual"]


# ------------------------------------------------- should clarify (the defect)


def test_bom_clarifies_with_a_meaningful_semantic_choice(synthetic) -> None:
    """BOM matches six documents across several categories and document types.

    The facet ladder returns the *first* viable facet, which is `domain` and
    splits 5/1 — a 17% worst-case reduction that the usefulness rule rightly
    rejects. A better semantic facet exists in the same corpus: document type
    splits those six documents 3/3. The decision layer should choose the facet
    that partitions best, not the first one that merely works.
    """
    prepared = understanding.prepare("bom")
    assert prepared.needs_clarification is True, (
        f"expected a clarification; got reason={prepared.reason!r} "
        f"facet={prepared.facet!r} reduction={prepared.reduction}"
    )
    assert prepared.facet in {"category", "document_type"}, "must be a semantic facet, not a filename token"
    assert len(prepared.options) >= 2
    # Options must be meaningful taxonomy/type names, not filename fragments.
    assert all(len(label) > 3 and label[0].isupper() for label in labels(prepared))
    # And each must select a real, strictly smaller subset.
    assert all(option.document_ids for option in prepared.options)


def test_bom_options_do_not_all_return_the_same_documents(synthetic) -> None:
    prepared = understanding.prepare("bom")
    selections = [frozenset(option.document_ids) for option in prepared.options]
    assert len(set(selections)) == len(selections), "each option must select a distinct document set"


# --------------------------------------------------------- must stay direct


def test_work_request_goes_direct(synthetic) -> None:
    """Best available facet still leaves 3 of 5 candidates: not worth a question."""
    prepared = understanding.prepare("work request")
    assert prepared.needs_clarification is False
    assert prepared.reason == "reduction_too_small"


def test_procurement_goes_direct(synthetic) -> None:
    prepared = understanding.prepare("procurement")
    assert prepared.needs_clarification is False


def test_procedural_ecr_query_goes_direct(synthetic) -> None:
    prepared = understanding.prepare("how do I create an ECR?")
    assert prepared.needs_clarification is False


def test_out_of_corpus_query_goes_direct(synthetic) -> None:
    prepared = understanding.prepare("engine 37 hp 2900 rpm")
    assert prepared.needs_clarification is False
    assert prepared.options == ()


def test_ecr_offers_no_noisy_filename_options(synthetic) -> None:
    """ECR must not be clarified with filename fragments.

    Only two documents name ECR in a filename or heading, and they admit no
    meaningful partition: the one document-type option that narrows is
    "SOP / Work Instruction" (1 of 2), while "Process Document" covers both and
    is therefore identical to searching everything. The only other facet is the
    filename token, whose options here would be PR, PRR, ACN, Change and
    Management — fragments, not choices. Listing both documents is better than
    asking, so this query stays direct.
    """
    prepared = understanding.prepare("ecr")
    assert prepared.needs_clarification is False
    for noise in ("PR", "PRR", "ACN", "Change", "Management"):
        assert noise not in labels(prepared)


# ------------------------------------------ facet quality invariant, corpus-wide


def test_semantic_facets_are_preferred_over_filename_tokens(synthetic) -> None:
    """Whenever a semantic facet is viable it must be chosen, even if a filename
    token would score a larger reduction (`change management`: 0.50 vs 0.75)."""
    for query in ("change management", "bom"):
        prepared = understanding.prepare(query)
        if prepared.needs_clarification:
            assert prepared.facet != "distinguishing_term", query


def test_chosen_facet_is_the_best_partitioning_semantic_facet(synthetic) -> None:
    """No other viable semantic facet may partition strictly better than the one chosen."""
    from document_finder.experiments.query_understanding import analyzer as A
    from document_finder.experiments.query_understanding.taxonomy import content_terms

    for query in ("bom", "work request", "change management"):
        terms = content_terms(query)
        candidates = A._candidates(CORPUS, terms)
        before = len(candidates)
        understanding_result = analyze_query(query, CORPUS)
        clarification = understanding_result.clarification
        if clarification is None or clarification.facet == "distinguishing_term":
            continue
        chosen = 1 - clarification.largest_option_candidates / before

        best = chosen
        for grouping in (
            {d: [c for c in candidates if d in c.domains] for d in {x for c in candidates for x in c.domains}},
            {k: [c for c in candidates if k in c.categories] for k in {x for c in candidates for x in c.categories}},
        ):
            narrowing = [len(v) for v in grouping.values() if 0 < len(v) < before]
            if len(narrowing) >= 2:
                best = max(best, 1 - max(narrowing) / before)
        assert chosen >= best - 1e-9, f"{query}: chose {chosen:.3f} but {best:.3f} was available"
