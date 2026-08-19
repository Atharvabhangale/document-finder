"""Persistent FAISS vector retrieval, intentionally separate from lexical/hybrid search."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from document_finder.embeddings.model import EmbeddingModel, configuration_key, get_default_model
from document_finder.search.lexical import DEFAULT_DATABASE_PATH


DEFAULT_INDEX_PATH = Path("data/vector/qwen3_embedding_0_6b.faiss")


class VectorIndexBackend(Protocol):
    def search(self, query: np.ndarray, limit: int) -> list[tuple[int, float]]: ...


class FaissVectorIndex:
    def __init__(self, index_path: Path):
        self.index_path = index_path
        self._index = None

    def build(self, vectors: np.ndarray, chunk_ids: Sequence[int]) -> None:
        try:
            import faiss
        except ImportError as error:
            raise RuntimeError("Install vector dependencies with: python -m pip install -e '.[vector]'") from error
        if len(vectors) != len(chunk_ids):
            raise ValueError("Vector and chunk ID counts differ.")
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(vectors.shape[1]))
        index.add_with_ids(np.ascontiguousarray(vectors, dtype=np.float32), np.asarray(chunk_ids, dtype=np.int64))
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self.index_path))
        self._index = index

    def load(self) -> None:
        import faiss
        self._index = faiss.read_index(str(self.index_path))

    def search(self, query: np.ndarray, limit: int) -> list[tuple[int, float]]:
        if self._index is None:
            self.load()
        scores, ids = self._index.search(np.ascontiguousarray(query.reshape(1, -1), dtype=np.float32), limit)
        return [(int(chunk_id), float(score)) for chunk_id, score in zip(ids[0], scores[0]) if chunk_id >= 0]


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS chunk_embeddings (
            chunk_id INTEGER NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
            model_name TEXT NOT NULL,
            configuration_json TEXT NOT NULL,
            configuration_hash TEXT NOT NULL,
            dimension INTEGER NOT NULL,
            embedding BLOB NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(chunk_id, model_name, configuration_hash)
        )
    """)
    connection.commit()


def _manifest_path(index_path: Path) -> Path:
    return index_path.with_suffix(index_path.suffix + ".json")


def _embedding_input(row: sqlite3.Row) -> str:
    return f"Section: {row['heading_path_json']}\n\n{row['source_text']}"


def build_vector_index(
    database_path: Path | str = DEFAULT_DATABASE_PATH,
    index_path: Path | str = DEFAULT_INDEX_PATH,
    model: EmbeddingModel | None = None,
) -> dict[str, int]:
    """Generate only missing chunk embeddings and persist a complete FAISS index."""
    model = model or get_default_model()
    database_path, index_path = Path(database_path), Path(index_path)
    config_json = configuration_key(model)
    config_hash = hashlib.sha256(config_json.encode()).hexdigest()
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        _ensure_schema(connection)
        chunks = connection.execute("SELECT chunk_id, heading_path_json, source_text FROM chunks ORDER BY chunk_id").fetchall()
        existing_ids = {row[0] for row in connection.execute(
            "SELECT chunk_id FROM chunk_embeddings WHERE model_name = ? AND configuration_hash = ?",
            (model.model_name, config_hash),
        )}
        missing = [row for row in chunks if row["chunk_id"] not in existing_ids]
        if missing:
            vectors = model.embed_documents([_embedding_input(row) for row in missing])
            if len(vectors) != len(missing):
                raise RuntimeError("Embedding model returned an unexpected number of vectors.")
            with connection:
                connection.executemany(
                    """INSERT OR REPLACE INTO chunk_embeddings
                       (chunk_id, model_name, configuration_json, configuration_hash, dimension, embedding)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [(row["chunk_id"], model.model_name, config_json, config_hash, int(vector.shape[0]), vector.astype(np.float32).tobytes())
                     for row, vector in zip(missing, vectors)],
                )
        stored = connection.execute(
            "SELECT chunk_id, dimension, embedding FROM chunk_embeddings WHERE model_name = ? AND configuration_hash = ? ORDER BY chunk_id",
            (model.model_name, config_hash),
        ).fetchall()
        if not stored:
            raise RuntimeError("No searchable chunks were available for vector indexing.")
        dimension = stored[0]["dimension"]
        vectors = np.vstack([np.frombuffer(row["embedding"], dtype=np.float32, count=dimension) for row in stored])
        FaissVectorIndex(index_path).build(vectors, [row["chunk_id"] for row in stored])
        _manifest_path(index_path).write_text(json.dumps({
            "model_name": model.model_name, "configuration_hash": config_hash,
            "dimension": dimension, "chunk_count": len(stored),
        }, indent=2), encoding="utf-8")
        return {"embedded": len(missing), "indexed": len(stored)}
    finally:
        connection.close()


def search_vector(
    query: str, limit: int = 10, database_path: Path | str | None = None,
    index_path: Path | str | None = None, model: EmbeddingModel | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(query, str) or not query.strip() or limit < 1:
        return []
    model = model or get_default_model()
    db_path, idx_path = Path(database_path or DEFAULT_DATABASE_PATH), Path(index_path or DEFAULT_INDEX_PATH)
    config_hash = hashlib.sha256(configuration_key(model).encode()).hexdigest()
    manifest = _manifest_path(idx_path)
    current_manifest = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
    if not idx_path.is_file() or current_manifest.get("configuration_hash") != config_hash:
        build_vector_index(db_path, idx_path, model)
    candidates = FaissVectorIndex(idx_path).search(model.embed_queries([query])[0], limit * 20)
    if not candidates:
        return []
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            f"""SELECT c.chunk_id, c.document_id, c.page, s.heading, s.section_path_json, d.filename
                FROM chunks c JOIN sections s ON s.section_id=c.section_id
                JOIN documents d ON d.document_id=c.document_id
                WHERE c.chunk_id IN ({','.join('?' for _ in candidates)})""",
            [chunk_id for chunk_id, _ in candidates],
        ).fetchall()
    finally:
        connection.close()
    by_id = {row['chunk_id']: row for row in rows}
    best: dict[str, dict[str, Any]] = {}
    for chunk_id, similarity in candidates:
        row = by_id.get(chunk_id)
        if row is None:
            continue
        path = json.loads(row['section_path_json'])
        result = {"document_id": row['document_id'], "filename": row['filename'], "score": (similarity + 1) / 2,
                  "section": path[-1] if path else row['heading'], "page": row['page'], "chunk_id": str(chunk_id)}
        prior = best.get(result['filename'])
        if prior is None or result['score'] > prior['score']:
            best[result['filename']] = result
    return sorted(best.values(), key=lambda result: (-result['score'], result['filename']))[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or query the persistent Qwen/FAISS vector index.")
    parser.add_argument("query", nargs="?")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH)
    args = parser.parse_args()
    if args.build:
        print(build_vector_index(args.database, args.index))
    if args.query:
        print(json.dumps(search_vector(args.query, database_path=args.database, index_path=args.index), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
