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

### Phase 14 — Corpus loading and refresh

Validated the customer-demo workflow: a customer supplies a folder of documents,
one command indexes it, and the corpus is immediately searchable.

**This is filesystem-based corpus loading, not Windchill synchronization.**
Windchill integration remains paused and untouched; exported documents are
treated as ordinary files on disk.

Added `python -m document_finder.corpus <FOLDER>`, which orchestrates existing
components only:

    discover -> ingest (hash-skip unchanged) -> prune removed -> embed missing -> build FAISS -> verify

Ingestion, chunking, OCR, the embedding model, FAISS, retrieval, ranking, the
API, and the frontend are all unchanged, as are every evaluation dataset and the
isolated Phase 13 experiment.

Two real defects were found and fixed:

- **Deleted documents were never removed.** A document deleted from the folder
  stayed in SQLite and kept appearing in search results. It is now pruned, only
  when it is absent from both the scan and the disk, with guards that refuse an
  empty-scan or greater-than-half prune unless explicitly confirmed.
- **No consistency check existed.** Searchable chunks, persisted embeddings, and
  FAISS vector IDs are now compared as sets after every run.

Two pre-existing caveats are documented rather than silently changed:

- **Duplicate filenames**: internal identity is safe (`sha256(source_path)`, and
  `source_path` is unique), but search aggregates by filename and
  `GET /documents/{filename}` returns 404 rather than guessing between two
  same-named documents. Windchill exports commonly repeat filenames, so this is
  the most likely demo surprise. Fixing it needs an API/frontend change.
- **OCR failures are sticky**: `is_unchanged` treats a failed OCR status as
  settled, so such a document is skipped forever. Default behaviour is
  unchanged; `--retry-failed-ocr` clears the stored hash to force a retry.

Real-corpus validation on a throwaway copy (production `data/` untouched):
repeat refresh skipped 36/36 with zero re-embedding in 0.36s, verifying
**441 chunks = 441 embeddings = 441 FAISS vectors**; deleting one document
pruned it cleanly to **414 = 414 = 414**. First-run embedding cost was NOT
measured — `torch`/`transformers` are not installed in that environment.

**The served application still assumes a fixed corpus path.** `api/routes.py`
hardcodes `data/` with no override, so the demo corpus must live at `data/`
even though the indexing command accepts any folder.

No production-scale performance claim is made. See `docs/corpus-refresh.md` for
measured behaviour, timings, caveats, and the scale analysis.

### Phase 15 — Customer corpus configuration and safe document opening

Made the prototype deployable against a customer's own document folder, and
resolved the duplicate-filename ambiguity Phase 14 documented.

**Corpus root is now configuration, not code.** `DOCUMENT_FINDER_DATA_ROOT`
selects the folder the application indexes and serves, with
`DOCUMENT_FINDER_DATABASE` and `DOCUMENT_FINDER_INDEX` available to relocate the
index artifacts. With nothing set the behaviour is byte-for-byte the previous
`data/` layout, so existing local workflows are unaffected. Customers no longer
copy documents into the repository.

**Indexing and serving cannot silently disagree.** The indexed folder is
recorded in the index (`index_metadata`). If the application is configured for a
different folder, `/search` and both document routes return HTTP 503 with an
explanatory message rather than serving the wrong corpus. Indexes written before
this metadata existed are accepted, so legacy databases keep working.

**Document identity is now end-to-end.** Search results are aggregated per
document identity instead of per filename, and each result carries an opaque
64-hex `document_id` plus its corpus-relative `folder`.
`GET /documents/by-id/{document_id}` resolves the identifier through the index,
joins the stored relative path to the configured root, verifies containment and
existence, and only then serves the file. The browser never supplies or receives
a filesystem path; unknown/malformed identifiers, deleted files, traversal, and
absolute stored paths are all rejected. The older
`GET /documents/{filename}` route remains for unambiguous names and still
refuses rather than guessing.

Two same-named documents in different folders are therefore now two search
results, distinguishable by folder, each opening its own file. The frontend
change was minimal: show the folder line, open by identifier.

Retrieval quality, ranking, Qwen embeddings, FAISS, lexical and hybrid
retrieval, OCR, chunking, the evaluation datasets, and the isolated Phase 13
experiment are all unchanged. The only retrieval-path edit is the aggregation
key in `search/vector.py`; because the 36-document corpus contains no duplicate
filenames, document identity maps one-to-one onto filename there and the ordering
key is unchanged, so its ranking is provably identical.

Real-corpus validation on a temporary copy (production `data/` verified
untouched, and still without the new table): the configured root was honoured
for all three artifacts, the index reported 36 documents / 441 chunks /
441 embeddings / 441 FAISS vectors consistent, `/health` reported
`{"corpus": "ok", "documents": 36}`, and **all 36 real documents opened by
identifier with zero byte mismatches**. Modifying a file inside the configured
root changed what the API served, proving it reads from configuration rather
than `data/`. A duplicate-filename scenario built from real documents returned
both `procedure.docx` documents as distinct results (folders `Engineering` and
`Quality`) and opened each byte-exactly (11.5 MB vs 6.1 MB).

No production-scale performance claim is made; retrieval quality was not
re-measured, since `torch`/`transformers` are unavailable in this environment.

See `docs/customer-demo.md` for the demo workflow.

### Phase 16 — Query understanding integrated as an optional decision layer

The Phase 13 experiment now sits in front of search in the product, deciding per
query whether one clarification question is worth asking.

    query -> analyze -> worth asking? --no--> search (unchanged)
                              |
                             yes -> one question -> answer -> search scoped to it
                                         (or "Search all documents")

**Retrieval is untouched.** No change to Qwen embeddings, embedding generation,
persisted embeddings, the FAISS index, similarity, lexical search, hybrid
search, ingestion, OCR or chunking. `search/`, `ingestion/`, `storage/`,
`embeddings/`, `sources/` and every evaluation dataset are byte-unchanged this
phase. `/search` without a `clarification` field takes exactly the previous code
path.

**The Phase 13 analyzer's decisions are provably unchanged.** Two additive
changes were made to it — documents carry their index identity, and a
clarification records which documents each option selects — so a caller can act
on the user's answer without duplicating facet logic. The frozen 60-query
evaluation output is byte-identical before and after (verified by diff), and its
labels and dataset were not touched.

**The usefulness rule is the substance of this phase.** The analyzer already
required each option to select a strict subset; the integration layer adds one
test, reusing the analyzer's own reported numbers:

    reduction = 1 - largest_option_candidates / candidates_before

A question is asked only when the *worst-case* reduction meets
`QUERY_UNDERSTANDING_MIN_REDUCTION` (default 0.5 — "a question must at least
halve the work"). This is what makes `SOP` (16 candidates to 14, which Phase 13
itself called useless) decline to ask, while `gate` (7 to 1) asks. The default
is a round, explainable rule, not fitted to the frozen labels.

Configuration: `QUERY_UNDERSTANDING_ENABLED` (default true; `false` restores
exact pre-Phase-16 behaviour) and `QUERY_UNDERSTANDING_MIN_REDUCTION`.

New `POST /query-understanding` returns only `{query, needs_clarification,
question, options}` — no intent, confidence, ambiguity or candidate counts reach
the client. `POST /search` gains one optional `clarification` field. Answers
scope results to the documents that answer selects (a restriction over document
identity, documented and justified: retrieval, scoring and ordering are
unchanged, retrieval goes deeper first, and an empty scope falls back to the
unscoped results).

Every failure path falls back to plain search: layer disabled, missing index,
analyzer exception, unreachable endpoint, or unknown answer.

Measured on the real 36-document corpus (recorded, not tuned): 4 of 16 probe
queries clarify — `gate` 86%, `chatbot` 67%, `user guide` 60%,
`change management` 50% reduction — and the rest go direct, including
`SOP` 12%, `NPD` 12%, `BOM` 17%, `work request` 40%. End-to-end on a corpus
copy, `gate` narrowed 20 results to exactly 1 per option and every narrowed
document opened byte-exactly.

Known gaps: `ECR` does not clarify (only two documents name it, below the
analyzer's 3-candidate floor); `BOM`/`SOP` have one dominant branch so their
worst case fails the bar even though the other branch narrows sharply; the
filename-token facet caps at five options, so `gate` omits MS5/MS6 behind
"Search all documents". Retrieval quality was **not** re-measured
(`torch`/`transformers` unavailable), the end-to-end narrowing check used a stub
embedder, and no ranking improvement is claimed.

See `docs/query-understanding-integration.md`.

### Phase 17 — Clarification facets ranked, not taken first-come

The decision layer took the first viable facet on the ladder, which is not always
the most useful one. Facets are now ranked by **option coverage first, then
worst-case split, then ladder order**; the filename-token facet remains last
resort. No query is special-cased — both signals are computed from the corpus.

- `bom` matches six documents that domain splits 5/1 (a 17% worst case the
  usefulness rule rightly rejects) while document type splits them 3/3. `bom`
  now clarifies.
- Ranking on the split alone would have picked `sop`'s document-type facet,
  whose 81% reduction came entirely from its dominant bucket being dropped for
  covering all sixteen candidates; its options reached only 5. Coverage ranking
  chooses the full-coverage category facet instead.

`gate`, `chatbot` and `change management` are unchanged; `work request`,
`procurement`, `how do I create an ECR?` and `engine 37 hp 2900 rpm` stay
direct. Every Phase 13 labelled metric is identical and `needs_clarification` is
unchanged for all 60 queries. `analyzer.py` was the only source file touched.

### Phase 18 — EXPERIMENT ONLY: "partial-but-meaningful" clarification

Tested whether a clarification should expose **only the genuinely useful
branches** of a facet instead of requiring the whole facet to partition the
candidate set — the natural next step Phase 16 had named for `work request`,
`NPD` and `ECR`.

**Outcome: DO NOT IMPLEMENT. Production behaviour is unchanged**, and no
production source file carries a diff this phase. What was added is an isolated
diagnostic and prototype
(`experiments/query_understanding/partial_branch.py`), a reproducible
comparison (`evaluation/query_understanding/phase18_partial_branch.py`) and 46
tests pinning what was found.

The deciding finding is structural, not corpus-specific: **the dominant branch
is the on-topic branch.** Candidates are selected because they match the query,
so the facet branch grouping the documents the query is about is normally the
largest. Dropping "the branch that narrows too little" therefore drops what the
user asked for — `work request` would be answered with the two documents that
are *not* work requests, `BOM` with the three that are *not* about BOM.

Measured over 65 queries (8 probes, the Phase 16/17 regression probes, the
frozen 60-query dataset), each strategy against the real production decision:

| Strategy | Differs on | Required-preserved probes broken |
|---|---:|---|
| drop weak branches, no coverage guard | 7 | `work request`, `NPD`, `BOM`, `SOP`, `deployment` |
| drop weak branches, coverage as a hard floor | 6 | `work request`, `NPD`, `BOM`, `deployment` |
| drop weak branches, coverage as Phase 17's rank bucket | 6 | `work request`, `NPD`, `BOM`, `deployment` |
| never answer with filename tokens | 4 | `BOM`, `gate`, `chatbot` |
| keep every branch, relax the question rule | 2 | none |

`ECR` is confirmed unreachable at any threshold: two candidates, one narrowing
branch, and the only facet that could ask answers with the fragments PR, PRR,
ACN, Change and Management — which collapse to two distinct selections, one per
document. `NPD`'s only sharply-narrowing option set is `Creation, MS0, MS1, MS2,
MS3`, a fragment beside an incomplete family.

The one new question worth asking that the experiment found anywhere —
`work request` → `Work Request` / `NPD / Project` / `Part / WTPart / CAD`,
complete coverage, nothing synthesised — comes from *keeping* the dominant
branch, which is the opposite of the proposal, and needs **no new code**:
`QUERY_UNDERSTANDING_MIN_REDUCTION=0.4` produces it today and changes no other
decision on this corpus. The default stays 0.5 rather than being fitted to one
query.

Also recorded, not fixed: `analyzer._finalize` can build clarifications with
two options selecting the identical document set (`NPD`, `deployment`, and one
natural-language query). All three are declined by the reduction bar before
being asked, so no user can see a duplicate option; a characterisation test
fails if that stops being true.

Full suite: **165 passed** (119 before, 46 added). The Phase 13 evaluation
output is byte-identical to the pre-phase baseline, and its frozen dataset and
labels were not touched. Vector and hybrid retrieval evaluations could not be
run — `torch`/`transformers` are unavailable — so no retrieval metric is
claimed; no retrieval code was touched. See
`docs/phase18-partial-branch-experiment.md`.

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