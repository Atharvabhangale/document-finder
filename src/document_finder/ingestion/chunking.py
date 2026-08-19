"""Section-bounded chunking for later lexical and semantic indexing."""

from __future__ import annotations

from document_finder.storage.models import ChunkDraft, SectionDraft


def build_chunks(sections: list[SectionDraft], max_characters: int = 1_600) -> list[ChunkDraft]:
    """Split only oversized section content, preserving source block boundaries where possible."""
    if max_characters < 100:
        raise ValueError("max_characters must be at least 100")
    chunks: list[ChunkDraft] = []
    for section in sections:
        pieces: list[tuple[str, bool, str | None, int | None]] = []
        current = ""
        current_page: int | None = None
        current_source_location: str | None = None
        for block in section.blocks:
            text = block.text.strip()
            if not text:
                continue
            if block.page is not None and current and current_page != block.page:
                pieces.append((current, False, current_source_location, current_page))
                current = ""
            if block.ocr_flag:
                if current:
                    pieces.append((current, False, current_source_location, current_page))
                    current = ""
                for index in range(0, len(text), max_characters):
                    pieces.append((text[index:index + max_characters], True, block.source_location, block.page))
                continue
            if len(text) > max_characters:
                if current:
                    pieces.append((current, False, current_source_location, current_page))
                    current = ""
                pieces.extend((text[index:index + max_characters], False, block.source_location, block.page) for index in range(0, len(text), max_characters))
                continue
            separator = "\n" if current else ""
            if current and len(current) + len(separator) + len(text) > max_characters:
                pieces.append((current, False, current_source_location, current_page))
                current = text
            else:
                current += separator + text
            current_page = block.page
            current_source_location = block.source_location
        if current:
            pieces.append((current, False, current_source_location, current_page))
        for ordinal, (text, ocr_flag, source_location, page) in enumerate(pieces):
            chunks.append(ChunkDraft(
                section_local_id=section.local_id,
                heading_path=section.path,
                ordinal=ordinal,
                source_text=text,
                # Native DOCX extraction has no reliable paragraph-to-page mapping.
                ocr_flag=ocr_flag,
                page=page,
                source_location=source_location,
            ))
    return chunks
