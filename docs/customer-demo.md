# Customer demo workflow

How to point Document Finder at a customer's own folder of documents, index it,
serve it, and open the exact original file from a search result.

**This is filesystem-based corpus loading. It is not Windchill integration** —
see the note at the end.

## 1. Where do the customer documents go?

Anywhere on disk. They do **not** need to be copied into the repository's `data/`
folder. Point the application at the folder they already live in; the folder is
only ever read, never modified.

Supported formats are unchanged: `.docx` and `.pdf`, discovered recursively
through nested subfolders.

## 2. Configure the corpus

One environment variable names the corpus:

```powershell
$env:DOCUMENT_FINDER_DATA_ROOT = "C:\customer\documents"
```

```bash
export DOCUMENT_FINDER_DATA_ROOT=/customer/documents
```

Two optional variables move the index artifacts if the corpus folder must stay
pristine (read-only share, for instance):

| Variable | Default |
|---|---|
| `DOCUMENT_FINDER_DATA_ROOT` | `data` |
| `DOCUMENT_FINDER_DATABASE` | `<data root>/document_finder.sqlite3` |
| `DOCUMENT_FINDER_INDEX` | `<data root>/vector/qwen3_embedding_0_6b.faiss` |

With nothing set the behaviour is exactly as before: the corpus is `data/`.

## 3. Index it

```bash
export DOCUMENT_FINDER_DATA_ROOT=/customer/documents
python -m pip install -e ".[dev,vector,ocr]"     # before the first index
python -m document_finder.corpus
```

The folder argument is optional — with none given it indexes the configured
corpus root, which is what keeps indexing and serving in step. Passing a
different folder explicitly still works and prints a warning that the API will
not serve it.

## 4. Start the application

```bash
export DOCUMENT_FINDER_DATA_ROOT=/customer/documents
uvicorn document_finder.api.app:app
```

Open `http://127.0.0.1:8000` and search.

`GET /health` reports what is being served without revealing any filesystem
path:

```json
{"status": "ok", "corpus": "ok", "documents": 36}
```

`corpus` is `ok`, `unindexed` (nothing indexed for this root yet), or
`mismatch`.

### Indexing and serving can never silently disagree

The indexed folder is recorded inside the index. If the application is
configured for a different folder than the index was built from, `/search` and
both document routes refuse with HTTP 503 and an explanatory message instead of
serving the wrong corpus. Set the same `DOCUMENT_FINDER_DATA_ROOT` for both
commands and this never arises.

An index built before this metadata existed cannot be checked and is accepted,
so existing local setups keep working.

## 5. Repeat indexing and updates

Re-run the same command. Unchanged documents are skipped on their content hash
and their embeddings are reused, so nothing is re-embedded needlessly:

| Change in the folder | Result |
|---|---|
| Nothing changed | every document skipped, no re-embedding |
| Document added | only that document parsed and embedded |
| Document edited | re-parsed; the old revision's chunks and embeddings are removed first |
| Document deleted | removed from the index and from search results |
| Document replaced | treated as an edit if the filename is the same, otherwise an add plus a delete |

To remove documents, delete them from the folder and re-run. Pruning is refused
when the scan finds nothing at all, or when more than half the index would go,
unless `--allow-full-prune` confirms it. `--no-prune` keeps everything.

## 6. How a user opens a result

Each search result carries an opaque `document_id` — the index's own stable
identifier. The browser sends only that identifier:

```
GET /documents/by-id/<document_id>
```

The server looks the identifier up in the index, joins the stored
**corpus-relative** path to the configured root, confirms the result is still
inside that root, confirms the file exists, and only then serves it. The browser
never supplies or receives a filesystem path. Unknown identifiers, malformed
identifiers, documents whose file has since been deleted, and any path that
would escape the corpus root are all rejected with 404.

## 7. Duplicate filenames

Two documents can share a filename in different folders — common in exported
repositories. They are two separate documents throughout:

- distinct identities (identity is the source path, never the filename)
- **two separate search results**, not one collapsed row
- each result shows its corpus-relative folder so a user can tell them apart:

```
procedure.docx
Engineering

procedure.docx
Quality
```

- each opens its own file via its own identifier

The older `GET /documents/{filename}` route still exists for unambiguous names
and still returns 404 rather than guessing when a filename matches more than one
document. The frontend no longer uses it.

## Demo checklist

```bash
export DOCUMENT_FINDER_DATA_ROOT=/customer/documents
python -m document_finder.corpus          # index (repeatable, incremental)
curl localhost:8000/health                # after starting uvicorn: corpus "ok"
uvicorn document_finder.api.app:app       # serve
```

Then: search a process in natural language → pick a result → **Open Document**.

## Relationship to the future Windchill work

```
Today:     customer folder  ->  Document Finder
Future:    Windchill / WRS  ->  (staged files)  ->  Document Finder
```

Windchill remains paused; nothing here contacts it and no credentials are
required. This configuration layer is deliberately compatible with that future:
document identity is already independent of the filename, so a Windchill-sourced
document can keep a stable identity across revisions and repeated filenames
without changing the API or the frontend. The eventual synchronizer's job is to
stage content into a folder (or to supply its own source adapter); the identity,
containment, and refresh semantics documented here do not need to change for it.
