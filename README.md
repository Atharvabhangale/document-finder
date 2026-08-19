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
Update the project documentation before continuing Phase 10.

Create:
PROJECT_STATUS.md

Use it as the canonical engineering handoff/current-state document.

It should document:
- project goal
- current architecture
- DOCX ingestion
- local OCR
- PDF ingestion status
- SQLite
- FTS5
- Qwen/Qwen3-Embedding-0.6B
- FAISS
- FastAPI
- frontend
- safe document opening
- current evaluation results
- evaluation datasets
- completed phases
- current Phase 10 status
- important architectural decisions/constraints
- next task

Do not invent information. Inspect the repository and use the actual current implementation.

Also completely update README.md so it reflects the CURRENT application rather than the original Phase 1 state.

README.md should contain:

1. Project overview
2. Current capabilities
3. Architecture overview
4. Supported document formats
5. DOCX/OCR behavior
6. PDF behavior and current Phase 10 status
7. Installation
8. Ingestion command
9. How to start the API/frontend
10. Example search
11. Evaluation commands
12. Test command
13. Current retrieval approach
14. Important limitations
15. Project structure
16. Link/reference to PROJECT_STATUS.md for detailed engineering history

Remove obsolete statements such as:
- "does not expose an API"
- "does not have a FAISS index"
- "embeddings are deferred"
- "OCR is a future adapter"

Do not change application code for this task.

Do not change retrieval behavior.

Do not modify evaluation datasets.

After updating both files, show me the resulting README.md and PROJECT_STATUS.md contents and stop.
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
