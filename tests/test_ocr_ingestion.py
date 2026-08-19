from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

from docx import Document

from document_finder.ingestion.ocr import OcrExtractionError
from document_finder.ingestion.pipeline import ingest_directory
from document_finder.storage.repository import sha256_file
from document_finder.storage.models import SourceBlock


def _image_doc(path: Path) -> None:
    image = path.with_suffix('.png')
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL92wAAAABJRU5ErkJggg=='))
    document = Document()
    document.add_picture(str(image))
    document.save(path)


class FakeOcr:
    def __init__(self) -> None:
        self.calls = 0

    def extract_docx_images(self, path: Path, start_ordinal: int) -> list[SourceBlock]:
        self.calls += 1
        return [SourceBlock(start_ordinal + 1, 'ocr', 'Recovered OCR process text', ocr_flag=True, source_location='word/media/image1.png')]


def test_ocr_fallback_metadata_and_cache(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    doc = source / 'Image only.docx'
    _image_doc(doc)
    original_hash = sha256_file(doc)
    provider, database = FakeOcr(), tmp_path / 'index.sqlite3'
    first = ingest_directory(source, database, provider)
    second = ingest_directory(source, database, provider)
    assert first.processed == 1 and second.skipped == 1 and provider.calls == 1
    assert sha256_file(doc) == original_hash
    connection = sqlite3.connect(database)
    try:
        assert connection.execute('SELECT ocr_status FROM documents').fetchone()[0] == 'completed'
        assert connection.execute('SELECT ocr_flag, source_location FROM chunks').fetchone() == (1, 'word/media/image1.png')
    finally:
        connection.close()


def test_failed_ocr_is_recorded_without_fake_chunks(tmp_path: Path) -> None:
    class FailingOcr:
        def extract_docx_images(self, path: Path, start_ordinal: int) -> list[SourceBlock]:
            raise OcrExtractionError('test failure')
    source = tmp_path / 'source'
    source.mkdir()
    _image_doc(source / 'Image only.docx')
    database = tmp_path / 'index.sqlite3'
    summary = ingest_directory(source, database, FailingOcr())
    assert summary.failed == 0 and summary.processed == 1
    connection = sqlite3.connect(database)
    try:
        assert connection.execute('SELECT ocr_status FROM documents').fetchone()[0] == 'failed'
        assert connection.execute('SELECT COUNT(*) FROM chunks').fetchone()[0] == 0
    finally:
        connection.close()
