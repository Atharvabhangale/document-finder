"""Storage-neutral models produced by ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceBlock:
    ordinal: int
    kind: str  # paragraph | list | table
    text: str
    style_name: str | None = None
    heading_level: int | None = None
    has_embedded_image: bool = False
    ocr_flag: bool = False
    source_location: str | None = None
    page: int | None = None


@dataclass
class SectionDraft:
    local_id: int
    heading: str
    heading_level: int
    parent_local_id: int | None
    path: list[str]
    ordinal: int
    blocks: list[SourceBlock] = field(default_factory=list)


@dataclass(frozen=True)
class ChunkDraft:
    section_local_id: int
    heading_path: list[str]
    ordinal: int
    source_text: str
    ocr_flag: bool = False
    page: int | None = None
    source_location: str | None = None


@dataclass(frozen=True)
class ParsedDocument:
    filename: str
    source_path: str
    mime_type: str
    title: str | None
    metadata: dict[str, Any]
    blocks: list[SourceBlock]
    native_text_characters: int
    embedded_image_count: int
    ocr_required: bool
    warnings: list[str]
    ocr_status: str = "not_required"
