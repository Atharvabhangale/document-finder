"""Native DOCX extraction with document-order paragraphs and tables."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.document import Document as DocumentType
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from document_finder.storage.models import ParsedDocument, SourceBlock


def _iter_block_items(parent: DocumentType | _Cell) -> Iterator[Paragraph | Table]:
    """Yield immediate paragraphs/tables in the XML order in which Word stores them."""
    parent_element = parent.element.body if isinstance(parent, DocumentType) else parent._tc
    for child in parent_element.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style
    if style is None:
        return None
    # Style IDs can be locale/customized; Word's outline level is the robust signal.
    if style.type == WD_STYLE_TYPE.PARAGRAPH:
        outline = style.element.xpath("./w:pPr/w:outlineLvl/@w:val")
        if outline:
            return int(outline[0]) + 1
    name = (style.name or "").strip().lower()
    if name.startswith("heading "):
        suffix = name.removeprefix("heading ").strip()
        if suffix.isdigit():
            return int(suffix)
    return None


def _is_list(paragraph: Paragraph) -> bool:
    style_name = (paragraph.style.name if paragraph.style else "") or ""
    return style_name.lower().startswith("list") or paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None


def _has_drawing(paragraph: Paragraph) -> bool:
    return bool(paragraph._p.xpath(".//w:drawing | .//w:pict | .//w:object"))


def _table_text(table: Table) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells = [" ".join(cell.text.split()) for cell in row.cells]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _embedded_image_count(path: Path) -> int:
    with ZipFile(path) as archive:
        return sum(1 for name in archive.namelist() if name.startswith("word/media/"))


def parse_docx(path: Path, source_path: str) -> ParsedDocument:
    """Parse a DOCX without changing it. Pages are intentionally unknown for DOCX."""
    document = Document(path)
    blocks: list[SourceBlock] = []
    native_chars = 0
    ordinal = 0

    for item in _iter_block_items(document):
        ordinal += 1
        if isinstance(item, Paragraph):
            text = " ".join(item.text.split())
            if not text and not _has_drawing(item):
                continue
            style_name = item.style.name if item.style else None
            blocks.append(
                SourceBlock(
                    ordinal=ordinal,
                    kind="list" if _is_list(item) else "paragraph",
                    text=text,
                    style_name=style_name,
                    heading_level=_heading_level(item),
                    has_embedded_image=_has_drawing(item),
                )
            )
            native_chars += len(text)
        else:
            text = _table_text(item)
            if text:
                blocks.append(SourceBlock(ordinal=ordinal, kind="table", text=text))
                native_chars += len(text)

    core = document.core_properties
    metadata = {
        "author": core.author,
        "category": core.category,
        "comments": core.comments,
        "created": core.created.isoformat() if core.created else None,
        "keywords": core.keywords,
        "last_modified_by": core.last_modified_by,
        "modified": core.modified.isoformat() if core.modified else None,
        "subject": core.subject,
        "title": core.title,
        "revision": core.revision,
    }
    image_count = _embedded_image_count(path)
    # A textless image document needs OCR; the threshold also flags near-empty scans.
    ocr_required = image_count > 0 and native_chars < 80
    warnings = []
    if ocr_required:
        warnings.append("OCR required: DOCX has embedded images but little/no native extractable text.")

    return ParsedDocument(
        filename=path.name,
        source_path=source_path,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        title=core.title or None,
        metadata=metadata,
        blocks=blocks,
        native_text_characters=native_chars,
        embedded_image_count=image_count,
        ocr_required=ocr_required,
        warnings=warnings,
    )
