# Corpus loading and refresh (Phase 14)

How a customer-supplied document folder becomes a searchable corpus, what the
current implementation guarantees, and where it will strain as the corpus grows.

**This is filesystem-based corpus loading. It is not Windchill synchronization.**
Windchill integration remains paused; documents exported from Windchill are
treated here as ordinary files on disk.

## The customer-demo workflow

```powershell
python -m pip install -e ".[dev,vector,ocr]"
python -m document_finder.corpus "C:\path\to\customer\documents"
uvicorn document_finder.api.app:app --reload
```

Then open `http://127.0.0.1:8000` and search. Re-running the middle command after
the folder changes is the whole refresh story — put documents in the folder, run
one command, search.

Install the `vector` and `ocr` extras **before the first run.** See
"OCR failures are sticky" below for why that ordering matters.

Useful flags: `--no-prune` (keep documents that left the folder), `--allow-full-prune`
(confirm a bulk removal), `--retry-failed-ocr`, `--no-build` (ingest only), `--json`.

## Why a new command

The pieces already existed but had to be run in the right order, and two things
were missing entirely:

| Step | Before | Now |
|---|---|---|
| Ingest new/changed documents | `document_finder.ingestion.pipeline <ROOT>` | same code, called for you |
| Embed + rebuild FAISS | `document_finder.search.vector --build` | same code, called for you |
| Remove documents deleted from the folder | **did not exist** | pruned, with safety guards |
| Verify SQLite/embeddings/FAISS agree | **did not exist** | verified and reported |

`document_finder.corpus` only orchestrates. Discovery, parsing, chunking, OCR,
the embedding model, FAISS, retrieval, ranking, and the API are unchanged.

## Measured behaviour

Verified by `tests/test_corpus_refresh.py` (temporary folders, stub embedding
model, no model download) and against the real 36-document corpus on a
throwaway copy.

| Scenario | Behaviour |
|---|---|
| **Initial load** | Recursive scan; DOCX and PDF ingested; chunks, embeddings and FAISS built; counts reported. |
| **Repeat load** | All documents skipped on the SHA-256 content hash. **Zero re-embedding.** |
| **Add** | Only the new document is parsed; only its chunks are embedded; FAISS rebuilt consistent. |
| **Modify** | Change detected by hash. The old revision's chunks *and* their embeddings are removed by the schema cascade, then the document is re-parsed and only its chunks re-embedded. No orphans. |
| **Delete** | **Was broken.** The document stayed in SQLite and kept appearing in search results. Now pruned, and gone from search. |
| **Duplicate filenames** | Kept as two distinct documents — identity is the source path, never the filename. See the caveat below. |
| **Duplicate content** | Both kept. Identical bytes under two names are *not* deduplicated, so each customer document stays individually openable. |

### Delete safety

Pruning only removes a document when it is absent from the scan **and** absent
from disk, so a transient discovery problem cannot delete indexed content. Two
further guards refuse to act on a suspicious scan:

- a scan that finds no supported documents at all will not prune the index
- a run that would prune more than half the index will not proceed

Both print why, and both require `--allow-full-prune` to override. Every removal
is recorded in `ingest_runs` with outcome `pruned`.

### Consistency

After every run the searchable chunks, the persisted embeddings for the active
model configuration, and the FAISS vector IDs are compared as sets, not just
counted. Mismatches are reported and the command exits non-zero.

Real-corpus results (temporary copy; production `data/` untouched):

| Run | Discovered | Processed | Skipped | Pruned | Embeddings created | Chunks = Embeddings = FAISS | Total time |
|---|---:|---:|---:|---:|---:|---|---:|
| From-scratch ingest, no embeddings (`--no-build`) | 36 | 36 | 0 | 0 | 0 | 383 chunks, 0 embedded → correctly reported INCONSISTENT | 3.29s |
| Refresh against existing index | 36 | 0 | 36 | 0 | 0 | **441 = 441 = 441** ✓ | 0.36s |
| Same again | 36 | 0 | 36 | 0 | 0 | **441 = 441 = 441** ✓ | 0.34s |
| After deleting one document | 35 | 0 | 35 | 1 | 0 | **414 = 414 = 414** ✓ | 0.43s |

The from-scratch run produced 383 chunks rather than 441 because the `ocr` extra
is not installed in this environment, so the one image-only DOCX
(`PR-ECR-ECN-ACN Process.docx`) contributed nothing. 383 + its 58 OCR chunks =
441, matching the existing index exactly.

**Embedding generation was not re-measured.** `torch`/`transformers` are absent
here, so first-run embedding cost for the real corpus is unknown and is *not*
included in the timings above. On the repeat runs the embedding cache meant no
model was needed at all.

## Known caveats

### Duplicate filenames are ambiguous at the edges

Internal identity is safe — `document_id = sha256(source_path)`, and
`source_path` is unique — so two same-named files in different folders remain
two documents and neither is lost or overwritten. But the *filename* is the
user-facing handle, and two consequences follow:

1. **Search collapses them.** Results are aggregated to one row per filename, so
   two different documents named `Report.docx` appear as a single result. This is
   long-standing intentional behaviour, not introduced here.
2. **Opening them is refused.** `GET /documents/{filename}` matches on filename;
   when that matches more than one indexed document it returns **404 rather than
   guessing**. Safe, but it means a document with a repeated filename cannot be
   opened from the UI at all.

This is the most likely functional surprise in a customer demo, because
Windchill exports commonly repeat filenames across folders. Fixing it properly
means giving the API a document identifier instead of a filename — an API and
frontend change deliberately left out of this phase.

### OCR failures are sticky

`is_unchanged` treats any non-`pending` OCR status as settled. A document whose
OCR failed is therefore stored with `ocr_status = 'failed'` and **skipped on
every later run**, even after the `ocr` extra is installed. It never becomes
searchable on its own.

Default behaviour is unchanged. `--retry-failed-ocr` clears the stored hash for
those documents so the next run re-parses them. Best practice remains: install
the extras before the first ingest.

### The application still assumes a fixed corpus path

`api/routes.py` hardcodes `DEFAULT_DOCUMENT_ROOT = Path("data")` and
`search/lexical.py` hardcodes `DEFAULT_DATABASE_PATH = Path("data/document_finder.sqlite3")`.
There is no environment or config override, and both are *relative*, so the API
must also be started from the repository root.

So while `document_finder.corpus` can index any folder, **the served application
can only read `data/`.** For a demo the corpus must live at `data/`, or the
constants must be edited. Pointing the product at a customer folder without a
code change needs those two constants to become configuration (an env var read
at startup would be enough). Not implemented here — this phase does not modify
the API or frontend.

### Stale index between the two older commands

Running `ingestion.pipeline` alone leaves FAISS behind: new chunks are not
searchable and the index can briefly hold vectors for chunks that no longer
exist (`search_vector` silently drops those, so results stay correct but
incomplete). `search_vector` only rebuilds when the index file is missing or the
model configuration changed — it does not detect that the corpus moved on. The
single `document_finder.corpus` command exists to close that window; the
staleness detection in `search_vector` was deliberately **not** changed, to keep
retrieval behaviour identical.

## Scale: what happens with thousands of documents

Measured throughput on this corpus: hashing ≈ **287 MB/s**, parsing + chunking ≈
**25 MB/s** (82.4 MB, 36 documents). Extrapolations below are arithmetic from
those figures, not measurements.

**Scales linearly and stays cheap**
- Directory scan, per-document hashing, parsing, chunking, SQLite inserts.
- Repeat runs cost a full re-hash of every byte: ~24s for a 7 GB corpus. Acceptable, but it never gets cheaper — nothing uses size/mtime as a pre-filter.

**Becomes the bottleneck**
- **First-run embedding.** Qwen3-Embedding-0.6B on CPU, batch 8, `max_length` 4096, one pass per chunk. At ~12 chunks/document, 3 000 documents is ~35 000 chunks. This dominates the first load by orders of magnitude over everything else here, and was not measured.
- **OCR**, for any scanned-PDF-heavy corpus: every page is rendered at 2× and run through detection. Expect it to rival or exceed embedding cost, and note that OCR runs inside the same single-threaded ingest loop.
- **FAISS rebuild is all-or-nothing.** `build_vector_index` reads *every* stored embedding, `np.vstack`s them, and writes a brand-new index on every run, even when one chunk changed. There is no incremental add or delete.

**Memory**
- The FAISS rebuild is the peak: 1024-dim float32 → ~145 MB at 3 000 documents, ~484 MB at 10 000, roughly doubled momentarily by the contiguous copy. This is the first hard wall.
- `index_consistency` holds all chunk IDs in sets (~40 MB per million chunks) — fine, but worth knowing.

**Search**
- `IndexFlatIP` is exact brute force: query cost grows linearly with chunk count. Fine into the tens of thousands; an approximate index (IVF/HNSW) becomes necessary well before a million chunks.

**SQLite**
- Adequate for this architecture: single-process ingestion, one writer, FTS5 for the lexical baseline. Embeddings stored as BLOBs make the file grow ~4 KB/chunk (~140 MB at 35 000 chunks), which is fine but makes the database the largest artifact.
- `ingest_runs` grows by one row per document per run, including skips — 228 rows after 4 runs of 36 documents. Daily refreshes of a 3 000-document corpus add ~1M rows/year. Harmless for a while; it needs pruning or an index eventually.

**Risks for a several-thousand-document corpus**
1. Repeated filenames breaking document opening (above) — most likely to be noticed in a demo.
2. First-load wall-clock time driven by embedding and OCR, with no progress output, no resumability, and no parallelism. An interrupted first load leaves ingestion done and embeddings partial — recoverable by re-running, but only because the caches are per-chunk.
3. Peak memory during FAISS rebuild.
4. A single failing document is contained (recorded, batch continues), but a failing *OCR* document is then permanently skipped.
5. Everything is single-threaded and single-process; there is no concurrency control if two refreshes run at once.

None of this was optimized in this phase, by design.
