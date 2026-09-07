# Document Finder — Project Status

## Goal

Build an internal document finder for manufacturing/engineering SOP and
process documentation.

Users should be able to type a natural-language description of the process
they are looking for and receive the relevant document filename and supporting
section, then open the original file.

The system is a document retrieval system, not a generative question-answering
system.

## Current Status

The prototype is end-to-end functional.

Current capabilities:

- DOCX ingestion
- Local OCR for image-based DOCX
- PDF ingestion implementation in progress / Phase 10
- SQLite metadata storage
- SQLite FTS5 lexical retrieval
- Qwen/Qwen3-Embedding-0.6B semantic embeddings
- FAISS vector retrieval
- Document-level result aggregation
- FastAPI search API
- Static web frontend
- Safe server-side document opening
- Evaluation framework
- Automated tests

## Current Architecture

User
  ↓
Frontend
  ↓
FastAPI
  ↓
Qwen3-Embedding-0.6B
  ↓
FAISS vector search
  ↓
Document aggregation
  ↓
Filename + relevant section + page
  ↓
Open original document

## AI Components

### Qwen3-Embedding-0.6B

Used as the semantic embedding model.

It converts document chunks and user queries into vectors so that natural
language queries can retrieve semantically related SOP content.

It is NOT used to generate answers.

### RapidOCR / local OCR

Used for image-based documents when native text extraction is insufficient.

OCR-derived content is marked with OCR provenance.

## Retrieval Decision

Vector-only retrieval is currently the primary retrieval approach.

Lexical FTS5 was evaluated as a baseline.

Hybrid vector + lexical RRF retrieval was also evaluated but performed worse
than vector-only on the fixed evaluation set.

Do not change the primary retrieval approach without evaluation.

## Current Evaluation

### General 32-query evaluation

Vector retrieval after OCR expansion:

- Recall@1: 0.906
- Recall@3: 1.000
- Recall@5: 1.000
- MRR: 0.948

### OCR-specific 18-query evaluation

- Recall@1: 0.667
- Recall@3: 1.000
- Recall@5: 1.000
- MRR: 0.806

### Cross-document 30-query evaluation

- Recall@1: 0.933
- Recall@3: 1.000
- Recall@5: 1.000
- MRR: 0.961

These are prototype measurements on the current evaluation sets, not
production-scale performance claims.

## Current Corpus

Current prototype corpus, as measured from `data/document_finder.sqlite3`:

- 36 documents (22 PDF, 14 DOCX)
- 125 sections
- 441 searchable chunks, 441 persisted embeddings
- 58 OCR-derived chunks

One DOCX document (`PR-ECR-ECN-ACN Process.docx`) is image-based, has zero
native text, and required OCR; its OCR status is `completed`.

The corpus is deliberately heterogeneous. Alongside the manufacturing/PLM
process documentation it contains unrelated internal IT material (backend and
Bajaj chatbot deployment documents, Iraje PAM, AWS daily report SOP) and one
vendor reference (Windchill+ battlecard). This mix is representative of what a
real Windchill repository will contain and is treated as a problem to solve, not
as noise to exclude.

Note: the 8-document / 121-chunk figures in earlier revisions of this file and in
`docs/retrieval-evaluation.md` predate the corpus expansion. The retrieval metric
values recorded below were measured on the earlier, smaller corpus and have not
been re-measured against the current 36-document corpus.

## Important Design Decisions

- Do not use a generative LLM for document identification.
- Do not hard-code filenames or query-specific ranking rules.
- Do not fabricate page numbers.
- Preserve source provenance.
- Keep ingestion idempotent using source hashing.
- Keep source documents unchanged.
- Do not expose raw filesystem paths through the API/UI.
- Open documents through a server-side validated reference.
- Keep lexical and hybrid retrieval available for experimentation, but use
  vector retrieval as the current primary method.

## Evaluation Sets

- `evaluation/queries.json`
  - 32 general human-labelled queries

- `evaluation/ocr_queries.json`
  - 18 OCR-document queries

- `evaluation/cross_document_queries.json`
  - 30 queries designed to test confusion between similar SOPs

## Phase History

### Phase 1
DOCX ingestion, section extraction, chunking, SQLite metadata,
idempotency, tests.

### Phase 2A
SQLite FTS5 lexical retrieval baseline.

### Phase 2B
32-query evaluation framework.

### Phase 3
Qwen3-Embedding-0.6B + persistent FAISS vector retrieval.

### Phase 4
Hybrid RRF experiment. Vector-only remained stronger.

### Phase 5
Local OCR fallback for image-based DOCX.

### Phase 6
OCR-specific retrieval evaluation.

### Phase 7
Cross-document retrieval evaluation.

### Phase 8
FastAPI search API.

### Phase 9
Static frontend and safe document-opening endpoint.

### Phase 10
PDF ingestion and scanned-PDF OCR support.
Current work must be inspected and verified before considering Phase 10 complete.

### Phase 13 — EXPERIMENT ONLY (not production)

Query-understanding experiment over the 36-document corpus. Investigated whether
an ambiguous or underspecified query can be recognised and answered with a useful
clarification question instead of an immediate long result list.

**This is an experiment, not a production integration.** It is deliberately NOT
connected to retrieval:

- retrieval, ranking, ingestion, OCR, chunking, the API, and the frontend are unchanged
- the existing evaluation datasets are unchanged
- `document_finder.experiments.query_understanding` is imported by nothing in
  `api/`, `search/`, or `ingestion/`; a test asserts this
- the experiment reads the SQLite index read-only and never touches FAISS or the
  embedding model

Approach: deterministic and corpus-derived. **No generative LLM and no embedding
model were required**, and no model was downloaded. Intent comes from ordered
surface markers; ambiguity is computed from how many corpus candidates a query
admits, which is what lets a 4-character query like `MS3` be treated as
unambiguous while `SOP` is not.

Measured on 60 self-authored labelled queries (`evaluation/query_understanding/`):
domain 0.967, intent 0.900, ambiguity 0.833, clarification-needed 0.867,
primary-category 0.983. All 12 generated clarifications provably narrow the
candidate set, but worst-case reduction averages only 33% and is as low as 12.5%
for skewed facets.

**The labels were authored by the same agent that wrote the classifier** (the
dataset named in the phase brief did not exist in the repository). They were
frozen in git before the implementation was written, but these figures remain a
consistency check, not independent validation. Expert re-labelling is a
prerequisite for treating them as real results. See
`evaluation/query_understanding/LABELS.md` and `REPORT.md`.

The demo taxonomy (10 categories, 2 domains) describes this 36-document corpus
only. It is not a proposed taxonomy for the eventual Windchill repository.

## Current Next Task

Finish and verify Phase 10.

Requirements:

- text PDF extraction
- page-by-page provenance
- scanned PDF detection
- local OCR fallback
- OCR provenance
- DOCX behavior must not regress
- idempotent ingestion
- tests for PDF behavior

Do not redesign retrieval.

Do not add a generative LLM.

Do not tune ranking.

## Handoff Instructions

When continuing this project:

1. Read this file.
2. Read README.md.
3. Inspect the existing implementation before changing anything.
4. Do not rewrite working components unnecessarily.
5. Run the existing tests before making architectural changes.
6. Preserve the evaluation datasets unless explicitly asked to modify them.
7. Report measured results rather than making assumptions.