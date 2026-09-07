"""One-command corpus loading and refresh for a customer-supplied document folder.

    python -m document_finder.corpus <DOCUMENT_ROOT>

This orchestrates the components that already exist — it does not replace them
and does not change how any of them behave:

    discover -> ingest (hash-skip unchanged) -> prune removed -> embed missing -> build FAISS -> verify

The two steps a customer would otherwise have to remember and run in the right
order (`document_finder.ingestion.pipeline` then `document_finder.search.vector
--build`) are combined here, plus the two things neither of them did: removing
documents that are no longer in the supplied folder, and verifying that SQLite
and FAISS actually agree afterwards.

Retrieval, ranking, chunking, OCR, the embedding model, and the API are
untouched by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from document_finder import config
from document_finder.embeddings.model import EmbeddingModel, configuration_key, get_default_model
from document_finder.ingestion.discover import discover_documents
from document_finder.ingestion.pipeline import ingest_directory
from document_finder.search.vector import build_vector_index, _manifest_path

# Refuse to prune more than this fraction of the index in one run unless the
# caller explicitly opts in. A corpus folder that is mostly missing is far more
# likely to be a wrong path or an unmounted share than a real bulk deletion.
MAX_AUTOMATIC_PRUNE_FRACTION = 0.5

# Stored in the index so the serving application can verify it is looking at the
# corpus this index was built from.
DOCUMENT_ROOT_KEY = "document_root"


@dataclass
class RefreshSummary:
    """Everything a demo operator needs to see after one refresh."""

    source_root: str
    database_path: str
    index_path: str
    discovered: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    pruned: int = 0
    retried_failed_ocr: int = 0
    ocr_documents: int = 0
    sections: int = 0
    chunks: int = 0
    embeddings_created: int = 0
    embeddings_total: int = 0
    faiss_vectors: int = 0
    consistent: bool = False
    index_built: bool = False
    prune_skipped_reason: str | None = None
    index_error: str | None = None
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seconds_ingest: float = 0.0
    seconds_index: float = 0.0
    seconds_total: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _configuration_hash(model: EmbeddingModel) -> str:
    return hashlib.sha256(configuration_key(model).encode()).hexdigest()


def _faiss_ids(index_path: Path) -> set[int] | None:
    """Chunk IDs actually present in the persisted FAISS index, if readable."""
    if not index_path.is_file():
        return None
    try:
        import faiss
    except ImportError:
        return None
    index = faiss.read_index(str(index_path))
    try:
        return {int(value) for value in faiss.vector_to_array(index.id_map)}
    except AttributeError:
        return None


def index_consistency(
    database_path: Path, index_path: Path, model: EmbeddingModel
) -> dict[str, Any]:
    """Compare searchable chunks, persisted embeddings, and FAISS vectors.

    Under the current architecture every stored chunk is searchable and should
    have exactly one embedding for the active model configuration, and the FAISS
    index should hold exactly those chunk IDs.
    """
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        chunk_ids = {row[0] for row in connection.execute("SELECT chunk_id FROM chunks")}
        try:
            embedded_ids = {
                row[0]
                for row in connection.execute(
                    "SELECT chunk_id FROM chunk_embeddings WHERE model_name = ? AND configuration_hash = ?",
                    (model.model_name, _configuration_hash(model)),
                )
            }
        except sqlite3.OperationalError:
            embedded_ids = set()
    finally:
        connection.close()

    faiss_ids = _faiss_ids(index_path)
    problems: list[str] = []
    if chunk_ids != embedded_ids:
        problems.append(
            f"{len(chunk_ids - embedded_ids)} chunk(s) have no embedding for this model configuration; "
            f"{len(embedded_ids - chunk_ids)} embedding(s) reference chunks that no longer exist"
        )
    if faiss_ids is None:
        # No index file. That is correct only when there is nothing to index.
        if embedded_ids:
            problems.append("FAISS index is absent or its IDs could not be read")
    elif faiss_ids != embedded_ids:
        problems.append(
            f"FAISS holds {len(faiss_ids - embedded_ids)} stale vector(s) and is missing "
            f"{len(embedded_ids - faiss_ids)} embedded chunk(s)"
        )
    return {
        "searchable_chunks": len(chunk_ids),
        "embedded_chunks": len(embedded_ids),
        "faiss_vectors": len(faiss_ids) if faiss_ids is not None else 0,
        "consistent": not problems,
        "problems": problems,
    }


def _prunable(source_root: Path, discovered: set[str], indexed: list[str]) -> list[str]:
    """Indexed documents that are absent from the scan AND absent from disk.

    Requiring both keeps a transient discovery hiccup (an unreadable directory,
    a changed suffix) from silently deleting indexed content.
    """
    return [
        source_path
        for source_path in indexed
        if source_path not in discovered and not (source_root / source_path).exists()
    ]


def refresh_corpus(
    source_root: Path | str,
    database_path: Path | str | None = None,
    index_path: Path | str | None = None,
    model: EmbeddingModel | None = None,
    prune: bool = True,
    allow_full_prune: bool = False,
    retry_failed_ocr: bool = False,
    build_index: bool = True,
) -> RefreshSummary:
    """Bring the index in line with the documents currently in `source_root`."""
    started = time.monotonic()
    from document_finder.storage.repository import SQLiteRepository

    root = Path(source_root).resolve()
    database = Path(database_path) if database_path else root / config.DATABASE_FILENAME
    index = Path(index_path) if index_path else root / config.VECTOR_INDEX_RELATIVE
    summary = RefreshSummary(str(root), str(database), str(index))

    # A failed scan must never be read as "the corpus is empty".
    discovered_documents = discover_documents(root)
    discovered_paths = {document.relative_path for document in discovered_documents}

    repository = SQLiteRepository(database)
    try:
        indexed = repository.indexed_sources()
        if retry_failed_ocr:
            failed_ocr = repository.sources_with_failed_ocr()
            summary.retried_failed_ocr = repository.mark_for_reprocessing(failed_ocr)
            if failed_ocr:
                summary.warnings.append(
                    f"Re-processing {len(failed_ocr)} document(s) whose OCR previously failed."
                )

        repository.set_metadata(DOCUMENT_ROOT_KEY, str(root))
        prunable = _prunable(root, discovered_paths, indexed) if prune else []
        if prune and prunable:
            if not discovered_paths and not allow_full_prune:
                summary.prune_skipped_reason = (
                    "the scan found no supported documents at all; refusing to prune the whole "
                    "index (check the folder path, or re-run with --allow-full-prune to confirm)"
                )
            elif len(prunable) > MAX_AUTOMATIC_PRUNE_FRACTION * max(len(indexed), 1) and not allow_full_prune:
                summary.prune_skipped_reason = (
                    f"{len(prunable)} of {len(indexed)} indexed documents are missing from the folder, "
                    "which exceeds the safety limit; re-run with --allow-full-prune to confirm"
                )
            else:
                summary.pruned = repository.delete_documents(prunable)
    finally:
        repository.close()

    ingest_started = time.monotonic()
    ingestion = ingest_directory(root, database)
    summary.seconds_ingest = round(time.monotonic() - ingest_started, 3)

    summary.discovered = ingestion.discovered
    summary.processed = ingestion.processed
    summary.skipped = ingestion.skipped
    summary.failed = ingestion.failed
    summary.sections = ingestion.sections_created
    summary.chunks = ingestion.chunks_created
    summary.failures = [
        f"{result.filename}: {result.error}" for result in ingestion.results if result.outcome == "failed"
    ]
    summary.ocr_documents = sum(
        1 for result in ingestion.results
        if any(warning.startswith("OCR") for warning in result.warnings)
    )
    summary.warnings.extend(
        f"{result.filename}: {warning}"
        for result in ingestion.results
        for warning in result.warnings
        if warning.startswith("OCR failed")
    )

    model = model or get_default_model()
    if build_index:
        index_started = time.monotonic()
        try:
            counts = build_vector_index(database, index, model)
            summary.embeddings_created = counts["embedded"]
            summary.embeddings_total = counts["indexed"]
            summary.index_built = True
        except RuntimeError as error:
            # Missing vector extras, or no chunks to index at all.
            summary.index_error = str(error)
        finally:
            summary.seconds_index = round(time.monotonic() - index_started, 3)

    consistency = index_consistency(database, index, model)
    if consistency["searchable_chunks"] == 0 and consistency["embedded_chunks"] == 0 and index.is_file():
        # Every document was pruned. `build_vector_index` cannot write an empty
        # index, so the previous file would otherwise linger and misreport the
        # corpus. Search already returns nothing (the chunk rows are gone), but
        # the stale file is removed so the index matches the corpus on disk.
        index.unlink()
        manifest = _manifest_path(index)
        if manifest.is_file():
            manifest.unlink()
        summary.index_error = None
        consistency = index_consistency(database, index, model)

    summary.faiss_vectors = consistency["faiss_vectors"]
    summary.consistent = consistency["consistent"]
    summary.warnings.extend(consistency["problems"])
    if not summary.embeddings_total:
        summary.embeddings_total = consistency["embedded_chunks"]
    summary.seconds_total = round(time.monotonic() - started, 3)
    return summary


def print_summary(summary: RefreshSummary) -> None:
    print(f"Corpus folder:  {summary.source_root}")
    print(f"Index database: {summary.database_path}")
    print(f"Vector index:   {summary.index_path}")
    print()
    print(f"Documents found in folder: {summary.discovered}")
    print(f"  newly indexed or updated: {summary.processed}")
    print(f"  unchanged, skipped:       {summary.skipped}")
    print(f"  removed from index:       {summary.pruned}")
    print(f"  failed:                   {summary.failed}")
    if summary.retried_failed_ocr:
        print(f"  retried after OCR failure:{summary.retried_failed_ocr:>3}")
    print(f"  documents needing OCR:    {summary.ocr_documents}")
    print()
    print(f"Sections: {summary.sections}   Chunks created this run: {summary.chunks}")
    print(f"Embeddings created this run: {summary.embeddings_created}")
    print(f"Embeddings in index total:   {summary.embeddings_total}")
    print(f"FAISS vectors:               {summary.faiss_vectors}")
    print()
    print(f"Timing: ingest {summary.seconds_ingest}s, embed+index {summary.seconds_index}s, total {summary.seconds_total}s")
    print()
    if summary.prune_skipped_reason:
        print(f"NOT PRUNED: {summary.prune_skipped_reason}")
    if summary.index_error:
        print(f"VECTOR INDEX NOT BUILT: {summary.index_error}")
    for failure in summary.failures:
        print(f"FAILED: {failure}")
    for warning in summary.warnings:
        print(f"WARNING: {warning}")
    print()
    print("SQLite, embeddings and FAISS agree — the corpus is searchable."
          if summary.consistent else
          "INCONSISTENT: the search index does not match the stored corpus (see warnings above).")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load or refresh a document corpus from a folder, then update the search index.",
    )
    parser.add_argument("source_directory", type=Path, nargs="?",
                        help="Folder containing the customer's documents "
                             "(default: the configured corpus root)")
    parser.add_argument("--database", type=Path, help="SQLite index (default: <folder>/document_finder.sqlite3)")
    parser.add_argument("--index", type=Path, help="FAISS index (default: <folder>/vector/...)")
    parser.add_argument("--no-prune", action="store_true", help="Keep documents that are no longer in the folder")
    parser.add_argument("--allow-full-prune", action="store_true",
                        help="Permit removing more than half the index in one run")
    parser.add_argument("--retry-failed-ocr", action="store_true",
                        help="Re-process documents whose OCR failed on an earlier run")
    parser.add_argument("--no-build", action="store_true", help="Ingest only; do not embed or build FAISS")
    parser.add_argument("--json", action="store_true", help="Print the machine-readable summary")
    args = parser.parse_args()
    source_directory = args.source_directory or config.data_root()

    # Indexing one folder while the application serves another is the failure this
    # phase exists to prevent, so say so at index time as well as at serve time.
    if Path(source_directory).resolve() != config.resolved_data_root():
        print(
            f"NOTE: indexing {Path(source_directory).resolve()}, but the application is "
            f"configured to serve {config.resolved_data_root()}.\n"
            f"      Set {config.DATA_ROOT_VARIABLE} to the folder you are indexing before "
            "starting the API, or it will refuse to serve this index.\n"
        )

    try:
        summary = refresh_corpus(
            source_directory,
            database_path=args.database,
            index_path=args.index,
            prune=not args.no_prune,
            allow_full_prune=args.allow_full_prune,
            retry_failed_ocr=args.retry_failed_ocr,
            build_index=not args.no_build,
        )
    except ValueError as error:
        # Most often a mistyped or unmounted corpus folder.
        print(f"Cannot read the document folder: {error}")
        return 2
    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))
    else:
        print_summary(summary)
    return 0 if summary.failed == 0 and summary.consistent else 1


if __name__ == "__main__":
    raise SystemExit(main())
