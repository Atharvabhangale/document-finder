"""SQLite persistence behind a repository boundary for future storage replacement."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from document_finder.storage.models import ChunkDraft, ParsedDocument, SectionDraft


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    title TEXT,
    metadata_json TEXT NOT NULL,
    native_text_characters INTEGER NOT NULL,
    embedded_image_count INTEGER NOT NULL,
    ocr_required INTEGER NOT NULL,
    ocr_status TEXT NOT NULL DEFAULT 'pending',
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sections (
    section_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    parent_section_id INTEGER REFERENCES sections(section_id) ON DELETE CASCADE,
    heading TEXT NOT NULL,
    heading_level INTEGER NOT NULL,
    section_path_json TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    UNIQUE(document_id, ordinal)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    section_id INTEGER NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
    heading_path_json TEXT NOT NULL,
    chunk_ordinal INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    ocr_flag INTEGER NOT NULL DEFAULT 0,
    page INTEGER,
    source_location TEXT,
    UNIQUE(section_id, chunk_ordinal)
);
CREATE TABLE IF NOT EXISTS ingest_runs (
    ingest_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT REFERENCES documents(document_id) ON DELETE SET NULL,
    source_path TEXT NOT NULL,
    content_sha256 TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    sections_created INTEGER NOT NULL DEFAULT 0,
    chunks_created INTEGER NOT NULL DEFAULT 0,
    warnings_json TEXT NOT NULL,
    error_text TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    source_text, heading_path_json, content='chunks', content_rowid='chunk_id'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, source_text, heading_path_json)
    VALUES (new.chunk_id, new.source_text, new.heading_path_json);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, source_text, heading_path_json)
    VALUES ('delete', old.chunk_id, old.source_text, old.heading_path_json);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, source_text, heading_path_json)
    VALUES ('delete', old.chunk_id, old.source_text, old.heading_path_json);
    INSERT INTO chunks_fts(rowid, source_text, heading_path_json)
    VALUES (new.chunk_id, new.source_text, new.heading_path_json);
END;
"""


FTS_SCHEMA = """
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    source_text, heading_path_json, content='chunks', content_rowid='chunk_id'
);
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, source_text, heading_path_json)
    VALUES (new.chunk_id, new.source_text, new.heading_path_json);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, source_text, heading_path_json)
    VALUES ('delete', old.chunk_id, old.source_text, old.heading_path_json);
END;
CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, source_text, heading_path_json)
    VALUES ('delete', old.chunk_id, old.source_text, old.heading_path_json);
    INSERT INTO chunks_fts(rowid, source_text, heading_path_json)
    VALUES (new.chunk_id, new.source_text, new.heading_path_json);
END;
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepository:
    """Persistence implementation. Future repositories retain this public contract."""

    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._migrate_columns()
        self._migrate_fts_if_needed()

    def _migrate_fts_if_needed(self) -> None:
        """Repair the Phase 1 pre-release FTS schema without touching source data."""
        row = self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'chunks_fts'"
        ).fetchone()
        if row and "heading_path_json" in row["sql"]:
            return
        with self.connection:
            self.connection.executescript("""
                DROP TRIGGER IF EXISTS chunks_ai;
                DROP TRIGGER IF EXISTS chunks_ad;
                DROP TRIGGER IF EXISTS chunks_au;
                DROP TABLE IF EXISTS chunks_fts;
            """)
            self.connection.executescript(FTS_SCHEMA)
            self.connection.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")

    def _migrate_columns(self) -> None:
        document_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(documents)")}
        chunk_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(chunks)")}
        with self.connection:
            if "ocr_status" not in document_columns:
                self.connection.execute("ALTER TABLE documents ADD COLUMN ocr_status TEXT NOT NULL DEFAULT 'pending'")
                self.connection.execute("UPDATE documents SET ocr_status='not_required' WHERE ocr_required=0")
            if "source_location" not in chunk_columns:
                self.connection.execute("ALTER TABLE chunks ADD COLUMN source_location TEXT")

    def close(self) -> None:
        self.connection.close()

    def is_unchanged(self, source_path: str, content_sha256: str) -> bool:
        row = self.connection.execute(
            "SELECT content_sha256, status, ocr_status FROM documents WHERE source_path = ?", (source_path,)
        ).fetchone()
        return bool(row and row["content_sha256"] == content_sha256 and row["status"] == "indexed" and row["ocr_status"] != "pending")

    def record_skip(self, source_path: str, content_sha256: str) -> None:
        now = _now()
        self.connection.execute(
            """INSERT INTO ingest_runs(source_path, content_sha256, started_at, finished_at, outcome, warnings_json)
               VALUES (?, ?, ?, ?, 'skipped', '[]')""",
            (source_path, content_sha256, now, now),
        )
        self.connection.commit()

    def replace_document(
        self, parsed: ParsedDocument, content_sha256: str, sections: list[SectionDraft], chunks: list[ChunkDraft]
    ) -> tuple[str, int, int]:
        document_id = hashlib.sha256(parsed.source_path.encode("utf-8")).hexdigest()
        now = _now()
        with self.connection:
            old = self.connection.execute(
                "SELECT document_id FROM documents WHERE source_path = ?", (parsed.source_path,)
            ).fetchone()
            if old:
                self.connection.execute("DELETE FROM documents WHERE document_id = ?", (old["document_id"],))
            self.connection.execute(
                """INSERT INTO documents(
                    document_id, source_path, filename, content_sha256, mime_type, title, metadata_json,
                    native_text_characters, embedded_image_count, ocr_required, ocr_status, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'indexed', ?)""",
                (
                    document_id, parsed.source_path, parsed.filename, content_sha256, parsed.mime_type,
                    parsed.title, json.dumps(parsed.metadata), parsed.native_text_characters,
                    parsed.embedded_image_count, int(parsed.ocr_required), parsed.ocr_status, now,
                ),
            )
            section_ids: dict[int, int] = {}
            for section in sections:
                parent_id = section_ids.get(section.parent_local_id)
                cursor = self.connection.execute(
                    """INSERT INTO sections(document_id, parent_section_id, heading, heading_level, section_path_json, ordinal)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (document_id, parent_id, section.heading, section.heading_level,
                     json.dumps(section.path), section.ordinal),
                )
                section_ids[section.local_id] = int(cursor.lastrowid)
            for chunk in chunks:
                self.connection.execute(
                    """INSERT INTO chunks(document_id, section_id, heading_path_json, chunk_ordinal, source_text, ocr_flag, page, source_location)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (document_id, section_ids[chunk.section_local_id], json.dumps(chunk.heading_path),
                     chunk.ordinal, chunk.source_text, int(chunk.ocr_flag), chunk.page, chunk.source_location),
                )
            self.connection.execute(
                """INSERT INTO ingest_runs(
                    document_id, source_path, content_sha256, started_at, finished_at, outcome,
                    sections_created, chunks_created, warnings_json
                ) VALUES (?, ?, ?, ?, ?, 'processed', ?, ?, ?)""",
                (document_id, parsed.source_path, content_sha256, now, now, len(sections), len(chunks),
                 json.dumps(parsed.warnings)),
            )
        return document_id, len(sections), len(chunks)

    def record_failure(self, source_path: str, content_sha256: str | None, error_text: str) -> None:
        now = _now()
        self.connection.execute(
            """INSERT INTO ingest_runs(source_path, content_sha256, started_at, finished_at, outcome, warnings_json, error_text)
               VALUES (?, ?, ?, ?, 'failed', '[]', ?)""",
            (source_path, content_sha256, now, now, error_text),
        )
        self.connection.commit()

    def document_summary(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT d.filename, d.source_path, d.status, d.ocr_required, d.native_text_characters,
                      COUNT(DISTINCT s.section_id) AS sections, COUNT(c.chunk_id) AS chunks
               FROM documents d
               LEFT JOIN sections s ON s.document_id = d.document_id
               LEFT JOIN chunks c ON c.document_id = d.document_id
               GROUP BY d.document_id ORDER BY d.filename COLLATE NOCASE"""
        ).fetchall()
