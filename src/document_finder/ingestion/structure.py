"""Section tree extraction from parser blocks."""

from __future__ import annotations

from document_finder.storage.models import ParsedDocument, SectionDraft


def extract_sections(document: ParsedDocument) -> list[SectionDraft]:
    """Build a hierarchy from Word heading levels and attach content to its nearest section."""
    sections: list[SectionDraft] = []
    stack: list[SectionDraft] = []
    preamble: SectionDraft | None = None

    def section_for_preamble(ordinal: int) -> SectionDraft:
        nonlocal preamble
        if preamble is None:
            preamble = SectionDraft(
                local_id=len(sections), heading="Document preamble", heading_level=0,
                parent_local_id=None, path=["Document preamble"], ordinal=ordinal,
            )
            sections.append(preamble)
        return preamble

    for block in document.blocks:
        if block.heading_level is not None and block.text:
            while stack and stack[-1].heading_level >= block.heading_level:
                stack.pop()
            parent = stack[-1] if stack else None
            section = SectionDraft(
                local_id=len(sections),
                heading=block.text,
                heading_level=block.heading_level,
                parent_local_id=parent.local_id if parent else None,
                path=[*(parent.path if parent else []), block.text],
                ordinal=block.ordinal,
            )
            sections.append(section)
            stack.append(section)
        elif block.text:
            target = stack[-1] if stack else section_for_preamble(block.ordinal)
            target.blocks.append(block)

    return sections
