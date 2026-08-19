# Retrieval Evaluation Report

## 1. Problem definition

The application is a document finder for internal manufacturing and engineering process documentation. Its primary task is to map a user query to the most relevant SOP/process document and its strongest supporting section, so that the user can open the original file.

It is not a generative answer system. The retrieval experiments below evaluate document-level ranking only.

## 2. Corpus description

The current prototype corpus contains eight real DOCX SOP/process documents:

- `Change Management Process_.docx`
- `Part Creation & EBOM Process.docx`
- `PR-ECR-ECN-ACN Process.docx`
- `Procurement Kit Process Document.docx`
- `User Guide_Company standard document Change Management Process Document.docx`
- `Work Request CRE Combustion Process Document_v2.docx`
- `Work Request CRE Process Document - KOEL.docx`
- `Work Request NVH Process Document.docx`

The corpus includes process documentation for change management, part creation/EBOM, procurement kits, company-standard-document changes, and CRE/combustion/NVH work requests. One document (`PR-ECR-ECN-ACN Process.docx`) has no native extractable text and is marked as requiring OCR; it does not provide searchable chunks in the current experiment.

## 3. Ingestion architecture

The Phase 1 ingestion pipeline discovers DOCX files without modifying their source files. For each document it extracts paragraphs, Word heading styles, lists, tables, core metadata, and detectable embedded images.

Headings are used to construct a section hierarchy. Chunks stay within those logical sections whenever possible and retain the document ID, section ID, heading path, source text, OCR flag, and page when known. DOCX paragraph-level page numbers are not fabricated; current DOCX chunk pages are therefore `null`.

SQLite stores document, section, chunk, and ingestion-run metadata. SQLite FTS5 indexes searchable chunk text and heading paths. Source-file SHA-256 hashing prevents duplicate indexing of unchanged files.

## 4. Lexical baseline

The lexical baseline uses SQLite FTS5 over chunk text and heading paths, with document title/filename considered as a low-weight fallback. Matching chunks are aggregated to one document result per filename, retaining the strongest supporting section/chunk.

This is an experimental implementation detail, not a claim that lexical matching understands informal wording. In the evaluation, 12 natural-language/task-focused queries returned no lexical results.

## 5. Semantic retrieval approach

The vector-only experiment uses `Qwen/Qwen3-Embedding-0.6B`. Every searchable chunk is embedded once and persisted in SQLite together with the embedding model name, configuration, chunk ID, vector dimension, and embedding bytes.

A persisted FAISS inner-product index searches normalized embeddings. Query embeddings retrieve candidate chunks, which are aggregated to one document result per filename. The best matching chunk provides the returned section and source metadata.

No lexical score, hybrid fusion, reranking, generative model, API, or UI is part of the vector-only retrieval experiment.

## 6. Hybrid retrieval experiment

The hybrid experiment combines the existing vector and lexical rankings using Reciprocal Rank Fusion (RRF). It also applies generic, configurable heading/title evidence for exact, phrase, and token-prefix matches. It does not contain query-specific or BOM-specific logic.

This was an experiment alongside vector-only retrieval, not the current baseline.

## 7. Evaluation methodology

The fixed evaluation set contains 32 human-labelled queries grounded in the eight supplied documents. It includes exact terminology, informal natural-language wording, short keywords, abbreviations, task-oriented queries, and cases with multiple valid documents.

Each case identifies one or more expected document filenames; a result is relevant when any expected filename appears in the returned ranking. Expected sections are recorded where the source structure supports a reliable label, but the reported metrics are document-level.

The same 32 cases were used unchanged for lexical, vector, and hybrid evaluation. The metrics are Recall@1, Recall@3, Recall@5, and mean reciprocal rank (MRR).

## 8. Measured results

| Retrieval approach | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---:|---:|---:|---:|
| Lexical (FTS5) | 0.625 | 0.625 | 0.625 | 0.625 |
| Vector (Qwen) | 0.969 | 1.000 | 1.000 | 0.984 |
| Hybrid | 0.812 | 0.969 | 1.000 | 0.892 |

Experimental finding: vector retrieval recovered all 12 queries that returned no results under lexical retrieval. Vector retrieval had no top-five failures on the 32-query set.

## 9. `add BOM structure` analysis

For the query `add BOM structure`, the labelled document is `Part Creation & EBOM Process.docx`, with the relevant section `Adding BOM Structure`.

In the vector-only experiment, that document ranked second. The top result was `Change Management Process_.docx`, supported by a `Problem Report Production BOM Creation` section. The retrieved evidence indicates that the embedding associated the query's BOM terminology with that production-BOM heading more strongly than the explicit structure-addition procedure.

In the hybrid experiment, `Part Creation & EBOM Process.docx` ranked first, with `Adding BOM Structure` as the strongest supporting section. However, the aggregate hybrid results were worse than vector-only retrieval at Recall@1 and MRR.

## 10. Conclusion

Experimental conclusion: vector-only retrieval is the strongest retrieval approach evaluated so far and is the current baseline for the application.

The corpus description and implementation architecture above describe the current prototype. The metric values and query-recovery statements are measured findings from the fixed 32-query evaluation set. No broader production-scale performance claim is made by these experiments.
