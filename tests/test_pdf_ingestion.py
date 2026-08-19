from __future__ import annotations

import sqlite3
from pathlib import Path

import fitz
from PIL import Image

from document_finder.ingestion.ocr import OcrExtractionError
from document_finder.ingestion.parsers import parse_pdf
from document_finder.ingestion.pipeline import ingest_directory
from document_finder.storage.models import SourceBlock
from document_finder.storage.repository import sha256_file


def _text_pdf(path: Path) -> None:
    document = fitz.open()
    for page_number in (1, 2):
        page = document.new_page()
        page.insert_text((72, 72), f"PDF process page {page_number} with procurement steps")
    document.save(path)
    document.close()


def _scanned_pdf(path: Path) -> None:
    image_path = path.with_suffix('.png')
    Image.new('RGB', (200, 100), 'white').save(image_path)
    document = fitz.open()
    page = document.new_page()
    page.insert_image(page.rect, filename=image_path)
    document.save(path)
    document.close()


class FakePdfOcr:
    def __init__(self) -> None:
        self.calls = 0
    def extract_docx_images(self, path: Path, start_ordinal: int) -> list[SourceBlock]:
        raise AssertionError('not a DOCX')
    def extract_pdf_pages(self, path: Path, start_ordinal: int) -> list[SourceBlock]:
        self.calls += 1
        return [SourceBlock(start_ordinal + 1, 'ocr', 'Recovered scanned PDF change notice', ocr_flag=True, source_location='page:1', page=1)]


def test_text_pdf_extraction_pages_and_idempotency(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    pdf = source / 'Process.pdf'
    _text_pdf(pdf)
    original_hash = sha256_file(pdf)
    parsed = parse_pdf(pdf, 'Process.pdf')
    assert parsed.ocr_required is False and [block.page for block in parsed.blocks] == [1, 2]
    database = tmp_path / 'index.sqlite3'
    first, second = ingest_directory(source, database), ingest_directory(source, database)
    assert first.processed == 1 and second.skipped == 1 and sha256_file(pdf) == original_hash
    connection = sqlite3.connect(database)
    try:
        assert [row[0] for row in connection.execute('SELECT page FROM chunks ORDER BY chunk_id')] == [1, 2]
    finally:
        connection.close()


def test_scanned_pdf_ocr_fallback_metadata(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    _scanned_pdf(source / 'Scan.pdf')
    parsed = parse_pdf(source / 'Scan.pdf', 'Scan.pdf')
    assert parsed.ocr_required is True
    provider, database = FakePdfOcr(), tmp_path / 'index.sqlite3'
    summary = ingest_directory(source, database, provider)
    assert summary.processed == 1 and provider.calls == 1
    connection = sqlite3.connect(database)
    try:
        assert connection.execute('SELECT ocr_flag, page, source_location FROM chunks').fetchone() == (1, 1, 'page:1')
    finally:
        connection.close()
