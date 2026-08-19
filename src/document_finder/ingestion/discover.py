"""Document discovery. Parsers are selected by suffix so PDF can be added later."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SUPPORTED_SUFFIXES = {".docx", ".pdf"}


@dataclass(frozen=True)
class DiscoveredDocument:
    path: Path
    source_root: Path

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(self.source_root).as_posix()


def discover_documents(source_root: Path) -> list[DiscoveredDocument]:
    """Return supported documents in stable path order without modifying sources."""
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise ValueError(f"Input directory does not exist: {source_root}")
    return [
        DiscoveredDocument(path=path, source_root=source_root)
        for path in sorted(source_root.rglob("*"), key=lambda item: item.as_posix().lower())
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
