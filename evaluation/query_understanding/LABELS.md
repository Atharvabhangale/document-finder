# Query-understanding dataset — label definitions and provenance

## Provenance (read this before quoting any accuracy number)

The labels in `queries.json` were **authored by Claude (Phase 13), not by a human
domain expert.** The file did not exist when Phase 13 started; the phase brief
referred to it as supplied, but it was absent from the repository.

The labels were written and frozen (committed) **before** any query-understanding
code existed, specifically so that the labels were not fitted to an
implementation. That ordering is recorded in the git history: the dataset commit
precedes the classifier commit.

Even so, the same author wrote both the labels and the later classifier. These
figures are therefore a **consistency and regression check, not independent
validation.** They must not be presented as measured human-agreement accuracy.
Replacing these labels with expert-labelled ones is a prerequisite for treating
any number here as a real evaluation result.

## Corpus the labels are grounded in

36 documents (22 PDF, 14 DOCX), 125 sections, 441 chunks, as indexed in
`data/document_finder.sqlite3`. The labels describe what a user searching *this
36-document corpus* should get. They are demo labels for a demo corpus.

## Domain vocabulary (`expected_domain`)

The corpus is deliberately heterogeneous: it mixes manufacturing/PLM process
documentation with unrelated internal IT material. Domain is the coarse routing
decision — which slice of the corpus the query belongs to.

| Value          | Meaning |
|----------------|---------|
| `plm`          | Manufacturing / Windchill PLM process documentation |
| `it`           | Internal IT: application deployment, infrastructure, security, ops reporting |
| `cross_domain` | Query terms legitimately occur in **both** domains; domain cannot be resolved from the query alone |
| `none`         | Query matches no domain in this corpus (out-of-corpus, or empty/invalid input) |

## Intent vocabulary (`expected_intent`)

| Value           | Meaning | Typical shape |
|-----------------|---------|---------------|
| `procedural`    | Wants the steps to perform a task | "how do I create an ECR?" |
| `reference`     | Wants a specific named document | "solidworks windchill user manual" |
| `informational` | Wants a fact or explanation, not steps | "what are the 5 segments of a part number?" |
| `unknown`       | No intent signal — a bare topic or document-type term | "ECR", "SOP" |

## Ambiguity vocabulary (`expected_ambiguity`)

Ambiguity is labelled as a function of **how many corpus candidates the query
admits**, not merely how short the query is. A short query that maps to exactly
one document is not ambiguous.

| Value    | Meaning |
|----------|---------|
| `low`    | Resolves to one document, or to one clear category with clear intent |
| `medium` | Resolves to one category but spans several documents, or intent is unclear while topic is clear |
| `high`   | Spans several categories or domains, or admits many candidate documents with no intent signal |

## `expected_needs_clarification`

`true` only when asking a clarification question would **actually reduce the
search space** for this corpus. Deliberately `false` for:

- out-of-corpus queries — clarification cannot rescue a query with no matches;
  the honest response is "no match", not a menu
- empty/invalid input
- short-but-specific queries that already resolve to a single document
  (`MS3`, `NVH`, `Iraje PAM`) — these test that shortness alone must not trigger
  a clarification prompt

## Categories (`expected_categories`)

Derived only from the 36 documents present. Demo taxonomy for this corpus — **not**
a proposed taxonomy for the eventual Windchill repository.

PLM domain:
- `Change Management` — PR / ECR / ECN / ACN, change tasks (5 docs)
- `BOM / EBOM` — BOM creation, copy/paste, excel template, FG-code structure copy (4 docs)
- `Part / WTPart / CAD` — part creation, WTPart/CAD association, promotion, imported-part material (4 docs)
- `Procurement` — procurement kit (1 doc)
- `Work Request` — CRE / CRE-Combustion / NVH work requests (3 docs)
- `NPD / Project` — NPD MS0–MS6 gate process, NPD request creation, project creation (9 docs)
- `Windchill Navigation & Admin` — folder navigation, SolidWorks integration, user separation (4 docs)
- `Product Reference` — Windchill+ battlecard, vendor/marketing reference (1 doc)

IT domain:
- `IT Deployment` — backend deployment, Bajaj chatbot deployment v1–v3 (4 docs)
- `IT Infrastructure & Operations` — Iraje PAM, AWS daily report SOP (2 docs)

### Known taxonomy overlaps (reported, not forced away)

- `Part Creation & EBOM Process.docx` genuinely belongs to both `Part / WTPart / CAD`
  and `BOM / EBOM`.
- `Change Management Process_.docx` covers proto/production BOM inside a change-management
  document, overlapping `BOM / EBOM`.
- `BEL_SOP_Change Management Process_PRR ECR ECN_V0.pdf` and
  `User Guide_Company standard document Change Management Process Document.docx`
  describe the same process at different document types (SOP vs user guide).
- **Cross-domain term collision:** `Deployment_Document_for_Bajaj_Chatbot_Version_01.docx`
  contains a section "Multi-Level BOM Extraction Deployment", so the token "BOM"
  legitimately matches the IT domain as well as the PLM domain.

## Unlabelled fields — deliberately absent

`topic` and `confidence` are **not** labelled in this dataset.

- `topic` is free text; scoring it by string match would measure phrasing, not understanding.
- `confidence` has no objective ground truth a human could reliably assign.

Accuracy for these two fields therefore **cannot** be computed from this dataset, and
the evaluator does not report it. Confidence is reported only as a descriptive
distribution and as separation between clarified and non-clarified queries.
