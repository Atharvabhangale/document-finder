"""Local OCR fallback for image-based DOCX documents."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol
from zipfile import ZipFile

import numpy as np
from PIL import Image

from document_finder.storage.models import SourceBlock


class OcrProvider(Protocol):
    def extract_docx_images(self, path: Path, start_ordinal: int) -> list[SourceBlock]: ...
    def extract_pdf_pages(self, path: Path, start_ordinal: int) -> list[SourceBlock]: ...


class OcrExtractionError(RuntimeError):
    pass


@dataclass
class RapidOcrProvider:
    """Offline RapidOCR adapter; models are installed with rapidocr-onnxruntime."""

    min_confidence: float = 0.35

    def __post_init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as error:
            raise OcrExtractionError(
                "OCR dependency missing. Install with: python -m pip install -e '.[ocr]'"
            ) from error
        self.engine = RapidOCR()

    def extract_docx_images(self, path: Path, start_ordinal: int) -> list[SourceBlock]:
        blocks: list[SourceBlock] = []
        with ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.startswith("word/media/")]
            for image_index, name in enumerate(names, start=1):
                try:
                    image = Image.open(BytesIO(archive.read(name))).convert("RGB")
                    result, _ = self.engine(np.asarray(image))
                except Exception as error:
                    raise OcrExtractionError(f"Could not OCR {name}: {error}") from error
                lines = [item[1] for item in (result or []) if item[2] >= self.min_confidence and item[1].strip()]
                text = "\n".join(lines).strip()
                if text:
                    blocks.append(SourceBlock(
                        ordinal=start_ordinal + image_index, kind="ocr", text=text, ocr_flag=True,
                        source_location=name,
                    ))
        if not blocks:
            raise OcrExtractionError("OCR completed but no usable text was recovered from embedded images.")
        return blocks

    def extract_pdf_pages(self, path: Path, start_ordinal: int) -> list[SourceBlock]:
        import fitz
        blocks: list[SourceBlock] = []
        document = fitz.open(path)
        try:
            for page_number, page in enumerate(document, start=1):
                try:
                    image = Image.open(BytesIO(page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png"))).convert("RGB")
                    result, _ = self.engine(np.asarray(image))
                except Exception as error:
                    raise OcrExtractionError(f"Could not OCR PDF page {page_number}: {error}") from error
                lines = [item[1] for item in (result or []) if item[2] >= self.min_confidence and item[1].strip()]
                text = "\n".join(lines).strip()
                if text:
                    blocks.append(SourceBlock(
                        ordinal=start_ordinal + page_number, kind="ocr", text=text, ocr_flag=True,
                        source_location=f"page:{page_number}", page=page_number,
                    ))
        finally:
            document.close()
        if not blocks:
            raise OcrExtractionError("OCR completed but no usable text was recovered from PDF pages.")
        return blocks
