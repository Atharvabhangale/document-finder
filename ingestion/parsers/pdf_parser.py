"""Page-aware PDF parsing with a safe fallback for scanned PDFs."""

from __future__ import annotations

from pathlib import Path

import fitz

from document_finder.storage.models import ParsedDocument, SourceBlock


def parse_pdf(path: Path, source_path: str) -> ParsedDocument:
    document = fitz.open(path)
    try:
        blocks: list[SourceBlock] = []
        native_characters = 0
        for page_number, page in enumerate(document, start=1):
            text = "\n".join(line.strip() for line in page.get_text("text").splitlines() if line.strip())
            if text:
                blocks.append(SourceBlock(
                    ordinal=page_number, kind="paragraph", text=text,
                    source_location=f"page:{page_number}", page=page_number,
                ))
                native_characters += len(text)
        metadata = dict(document.metadata or {})
        metadata["page_count"] = document.page_count
        image_count = sum(len(page.get_images(full=True)) for page in document)
    finally:
        document.close()
    ocr_required = native_characters < 80 and image_count > 0
    warnings = ["OCR required: PDF has embedded images but little/no native extractable text."] if ocr_required else []
    return ParsedDocument(
        filename=path.name, source_path=source_path, mime_type="application/pdf",
        title=metadata.get("title") or None, metadata=metadata, blocks=blocks,
        native_text_characters=native_characters, embedded_image_count=image_count,
        ocr_required=ocr_required, warnings=warnings,
    )
