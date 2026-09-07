# Document Finder — Phase 1

This repository currently implements ingestion and indexing preparation only. It
does not expose an API, UI, hybrid ranking, FAISS index, or generative model.

## Run ingestion

```powershell
python -m pip install -e .
python -m document_finder.ingestion.pipeline data/
```

The command discovers DOCX files recursively, stores metadata and chunks in
`data/document_finder.sqlite3`, and leaves source documents untouched.

## Lexical baseline

```powershell
python -m document_finder.search "procurement kit"
```

This Phase 2A command uses SQLite FTS5 and returns one best-evidence result per
original filename. It performs no semantic retrieval or reranking.

## Retrieval evaluation

```powershell
python evaluation/evaluate.py
```

The 32 human-labelled cases in `evaluation/queries.json` measure the current
lexical baseline using Recall@1, Recall@3, Recall@5, and MRR. Failed top-five
queries include their returned ranking for inspection.

## Local API

```powershell
uvicorn document_finder.api.app:app --reload
```

`POST /search` accepts a query and an optional bounded limit (1–20). `GET /health`
returns the local service status. The API returns retrieval metadata only; it does
not expose source paths or generate answers.

## Frontend

The lightweight frontend is served by the same local API process. Start it with:

```powershell
uvicorn document_finder.api.app:app --reload
```

Open `http://127.0.0.1:8000` in a browser, enter a process query such as
`how do I create a new part?`, and select **Open Document** from a result. The
server validates the returned filename against indexed metadata before serving a
source document; the browser never submits a filesystem path.

## OCR

DOCX files with little or no native text are marked `ocr_required`; no simulated
OCR text is stored. A future OCR adapter can use Tesseract or a hosted/internal
OCR service and write chunks with `ocr_flag = 1`.

## Future semantic indexing

`ingestion/embeddings.py` contains a provider boundary only. Embeddings and the
FAISS index are intentionally deferred until the semantic-search phase.
