"""A seeded library for search tests: real SQLite, in-memory vectors, a fixed query vector.

Ranking tests seed chunks with a chosen similarity to the query and assert on
what search returns, instead of faking how search calls its repositories.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from mnemo.models import Book, Chunk, ContentType
from mnemo.search.service import SearchService
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db
from mnemo.vectors.store import QueryResult

QUERY_VECTOR = [1.0, 0.0]


def at_similarity(similarity: float) -> list[float]:
    """A unit vector whose cosine similarity to QUERY_VECTOR is `similarity`."""
    return [similarity, math.sqrt(max(0.0, 1.0 - similarity**2))]


class MemoryVectors:
    """In-memory VectorBackend with Chroma's cosine distance and metadata filters."""

    def __init__(self) -> None:
        self._rows: dict[str, tuple[list[float], dict[str, Any], str | None]] = {}

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str] | None = None,
    ) -> None:
        for i, chunk_id in enumerate(ids):
            norm = math.sqrt(sum(x * x for x in embeddings[i])) or 1.0
            vector = [x / norm for x in embeddings[i]]
            self._rows[chunk_id] = (vector, metadatas[i], documents[i] if documents else None)

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        book_id: str | None = None,
        content_type: str | None = None,
    ) -> list[QueryResult]:
        norm = math.sqrt(sum(x * x for x in query_embedding)) or 1.0
        q = [x / norm for x in query_embedding]
        hits: list[QueryResult] = [
            {
                "id": chunk_id,
                "distance": 1.0 - sum(a * b for a, b in zip(q, vector, strict=False)),
                "metadata": meta,
                "document": doc,
            }
            for chunk_id, (vector, meta, doc) in self._rows.items()
            if (book_id is None or meta.get("book_id") == book_id)
            and (content_type is None or meta.get("content_type") == content_type)
        ]
        return sorted(hits, key=lambda h: h["distance"])[:n_results]

    def delete_by_book(self, book_id: str) -> int:
        doomed = [k for k, (_, meta, _) in self._rows.items() if meta.get("book_id") == book_id]
        for k in doomed:
            del self._rows[k]
        return len(doomed)

    def count(self, book_id: str | None = None) -> int:
        return sum(1 for _, m, _ in self._rows.values() if book_id in (None, m.get("book_id")))

    def close(self) -> None:
        return None


class FixedEmbedder:
    """Embeds every query as QUERY_VECTOR."""

    def embed_one(self, text: str) -> list[float]:
        del text  # every query embeds the same
        return list(QUERY_VECTOR)


class Library:
    """Books and chunks in a temp SQLite database, with vectors at chosen similarities."""

    def __init__(self, tmp_path: Path) -> None:
        db_path = tmp_path / "library.db"
        init_db(db_path)
        self._conn = get_connection(db_path)
        self.books = BookRepository(self._conn)
        self.chunks = ChunkRepository(self._conn)
        self.vectors = MemoryVectors()
        self._sequence = 0
        self.add_book("abc123", "Test Book")

    def add_book(self, book_id: str, title: str, collection: str | None = None) -> None:
        self.books.add(
            Book(
                id=book_id,
                title=title,
                file_hash=(book_id * 11)[:64],
                collection=collection,
            )
        )

    def add(
        self,
        content: str,
        *,
        similarity: float | None = None,
        section: list[str] | None = None,
        kind: ContentType = ContentType.TEXT,
        book_id: str = "abc123",
    ) -> Chunk:
        """Store a chunk; with `similarity`, also a vector that close to the query."""
        chunk = Chunk(
            book_id=book_id,
            content=content,
            content_type=kind,
            token_count=max(1, len(content) // 4),
            section_path=section if section is not None else ["Ch1"],
            sequence=self._sequence,
        )
        self._sequence += 1
        self.chunks.add_many([chunk])
        if similarity is not None:
            self.vectors.add(
                [chunk.id],
                [at_similarity(similarity)],
                [{"book_id": book_id, "content_type": kind.value}],
            )
        return chunk

    def service(self) -> SearchService:
        return SearchService(
            chunks=self.chunks,
            books=self.books,
            vectors=self.vectors,
            embedder=FixedEmbedder(),
        )

    def close(self) -> None:
        self._conn.close()
