"""CLI orchestration for Phase 1 ingestion/indexing preparation."""

from __future__ import annotations

import argparse
import traceback
from dataclasses import dataclass, field, replace
from pathlib import Path

from document_finder.ingestion.chunking import build_chunks
from document_finder.ingestion.discover import discover_documents
from document_finder.ingestion.parsers import parse_docx, parse_pdf
from document_finder.ingestion.ocr import OcrExtractionError, OcrProvider, RapidOcrProvider
from document_finder.ingestion.structure import extract_sections
from document_finder.storage.repository import SQLiteRepository, sha256_file


@dataclass
class DocumentResult:
    filename: str
    outcome: str
    sections: int = 0
    chunks: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class IngestionSummary:
    discovered: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    sections_created: int = 0
    chunks_created: int = 0
    results: list[DocumentResult] = field(default_factory=list)


def ingest_directory(source_root: Path, database_path: Path | None = None, ocr_provider: OcrProvider | None = None) -> IngestionSummary:
    source_root = source_root.resolve()
    database_path = database_path or source_root / "document_finder.sqlite3"
    repository = SQLiteRepository(database_path)
    summary = IngestionSummary()
    try:
        for discovered in discover_documents(source_root):
            summary.discovered += 1
            content_sha256: str | None = None
            try:
                content_sha256 = sha256_file(discovered.path)
                if repository.is_unchanged(discovered.relative_path, content_sha256):
                    repository.record_skip(discovered.relative_path, content_sha256)
                    summary.skipped += 1
                    summary.results.append(DocumentResult(discovered.path.name, "skipped"))
                    continue
                parsed = parse_docx(discovered.path, discovered.relative_path) if discovered.path.suffix.lower() == ".docx" else parse_pdf(discovered.path, discovered.relative_path)
                if parsed.ocr_required:
                    try:
                        provider = ocr_provider or RapidOcrProvider()
                        ocr_blocks = (provider.extract_docx_images(discovered.path, len(parsed.blocks))
                                      if discovered.path.suffix.lower() == ".docx"
                                      else provider.extract_pdf_pages(discovered.path, len(parsed.blocks)))
                        parsed = replace(
                            parsed, blocks=[*parsed.blocks, *ocr_blocks], ocr_status="completed",
                            warnings=[*parsed.warnings, f"OCR completed: {len(ocr_blocks)} image text blocks recovered."],
                        )
                    except OcrExtractionError as error:
                        parsed = replace(parsed, ocr_status="failed", warnings=[*parsed.warnings, f"OCR failed: {error}"])
                sections = extract_sections(parsed)
                chunks = build_chunks(sections)
                _, section_count, chunk_count = repository.replace_document(parsed, content_sha256, sections, chunks)
                summary.processed += 1
                summary.sections_created += section_count
                summary.chunks_created += chunk_count
                summary.results.append(DocumentResult(
                    discovered.path.name, "processed", section_count, chunk_count, parsed.warnings
                ))
            except Exception as error:  # retain one failed source while continuing the batch
                repository.record_failure(discovered.relative_path, content_sha256, traceback.format_exc())
                summary.failed += 1
                summary.results.append(DocumentResult(discovered.path.name, "failed", error=str(error)))
    finally:
        repository.close()
    return summary


def _print_summary(summary: IngestionSummary) -> None:
    print(f"Documents discovered: {summary.discovered}")
    print(f"Documents processed: {summary.processed}")
    print(f"Documents skipped: {summary.skipped}")
    print(f"Documents failed: {summary.failed}")
    print(f"Sections created: {summary.sections_created}")
    print(f"Chunks created: {summary.chunks_created}")
    print("Document details:")
    for result in summary.results:
        detail = f"  - {result.filename}: {result.outcome}"
        if result.outcome == "processed":
            detail += f"; sections={result.sections}; chunks={result.chunks}"
        if result.warnings:
            detail += f"; warnings={' | '.join(result.warnings)}"
        if result.error:
            detail += f"; error={result.error}"
        print(detail)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest DOCX process documents into SQLite.")
    parser.add_argument("source_directory", type=Path, help="Directory containing source documents")
    parser.add_argument("--database", type=Path, help="SQLite destination (default: <source>/document_finder.sqlite3)")
    args = parser.parse_args()
    summary = ingest_directory(args.source_directory, args.database)
    _print_summary(summary)
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
