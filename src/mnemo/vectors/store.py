"""ChromaDB vector store for semantic search.

Handles vector persistence with cosine distance metric and L2 normalization
(required for GTE-large-en) and metadata filtering for book/content-type scoping.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict, cast

import chromadb
import numpy as np
from chromadb.api import ClientAPI

from mnemo.vectors.config import VectorConfig


class QueryResult(TypedDict):
    """Result from a vector query."""

    id: str
    distance: float
    metadata: dict[str, Any]
    document: str | None


class VectorStore:
    """ChromaDB wrapper for vector storage and retrieval.

    Handles:
    - L2 normalization (GTE-large-en returns unnormalized vectors)
    - Persistent storage across process restarts
    - Metadata filtering for book_id and content_type

    The collection is created on first use and persists to disk.
    Embedding dimension is locked to 1024 (GTE-large-en) on first insert.
    """

    EMBEDDING_DIM = 1024

    def __init__(
        self,
        config: VectorConfig | None = None,
        client: ClientAPI | None = None,
    ):
        self.config = config or VectorConfig()

        if client is not None:
            self.client = client
        else:
            persist_path = self.config.get_persist_path()
            self.client = chromadb.PersistentClient(path=str(persist_path))

        # No embedding_function - we provide embeddings explicitly
        self.collection = self.client.get_or_create_collection(
            name=self.config.collection_name,
            metadata={"hnsw:space": "cosine"},  # Cosine distance
        )

    def close(self) -> None:
        """Release ChromaDB resources (file descriptors)."""
        self.client.clear_system_cache()

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str] | None = None,
    ) -> None:
        """Add vectors with metadata.

        Embeddings are L2-normalized before storage.

        Args:
            ids: Unique IDs (use chunk UUIDs)
            embeddings: 1024-dim vectors from DatabricksEmbedder
            metadatas: Dicts with book_id, content_type, section_path, etc.
            documents: Optional original text (useful for debugging)

        Raises:
            ValueError: If inputs have mismatched lengths or wrong dimension
        """
        if not ids:
            return  # Nothing to add

        if len(ids) != len(embeddings) or len(ids) != len(metadatas):
            raise ValueError("ids, embeddings, and metadatas must have same length")

        if embeddings and len(embeddings[0]) != self.EMBEDDING_DIM:
            raise ValueError(f"Embeddings must be {self.EMBEDDING_DIM}-dimensional")

        normalized = self._normalize(embeddings)

        kwargs: dict[str, Any] = {
            "ids": ids,
            "embeddings": normalized,
            "metadatas": metadatas,
        }
        if documents:
            kwargs["documents"] = documents

        self.collection.add(**kwargs)

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        book_id: str | None = None,
        content_type: str | None = None,
    ) -> list[QueryResult]:
        """Query by embedding vector with optional filters.

        Args:
            query_embedding: 1024-dim query vector (will be normalized)
            n_results: Max results to return
            book_id: Filter to specific book
            content_type: Filter to content type (text, code, etc.)

        Returns:
            List of QueryResult dicts with id, distance, metadata, document
        """
        if len(query_embedding) != self.EMBEDDING_DIM:
            raise ValueError(f"Query embedding must be {self.EMBEDDING_DIM}-dimensional")

        normalized = self._normalize([query_embedding])

        # Build where clause for filtering
        where = self._build_where(book_id, content_type)

        results = self.collection.query(
            # cast: list is invariant, so list[list[float]] is not a
            # list[Sequence[float]] to mypy even though every element fits.
            query_embeddings=cast("list[Sequence[float]]", normalized),
            n_results=n_results,
            where=where,
            include=["metadatas", "documents", "distances"],
        )

        return self._format_results(results)

    def delete_by_book(self, book_id: str) -> int:
        """Delete all vectors for a book.

        Args:
            book_id: 6-char book identifier

        Returns:
            Number of vectors deleted
        """
        # ChromaDB doesn't return count, so we query first
        existing = self.collection.get(
            where={"book_id": book_id},
            include=[],
        )
        count = len(existing["ids"])

        if count > 0:
            self.collection.delete(where={"book_id": book_id})

        return count

    def count(self, book_id: str | None = None) -> int:
        """Count vectors, optionally filtered by book.

        Args:
            book_id: Optional filter to specific book

        Returns:
            Number of vectors
        """
        if book_id:
            result = self.collection.get(
                where={"book_id": book_id},
                include=[],
            )
            return len(result["ids"])
        return self.collection.count()

    def _normalize(self, embeddings: list[list[float]]) -> list[list[float]]:
        """L2 normalize embeddings.

        GTE-large-en does NOT return normalized embeddings, so we must
        normalize before storage for consistent similarity calculations.
        """
        arr = np.array(embeddings, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        # Avoid division by zero
        norms = np.maximum(norms, 1e-12)
        normalized = arr / norms
        result: list[list[float]] = normalized.tolist()
        return result

    def _build_where(
        self,
        book_id: str | None,
        content_type: str | None,
    ) -> dict[str, Any] | None:
        """Build ChromaDB where clause for filtering.

        Section filtering is deliberately absent: Chroma's $contains is a
        document operator, not a metadata one. SearchService post-filters
        section paths in Python instead.
        """
        conditions = []

        if book_id:
            conditions.append({"book_id": book_id})
        if content_type:
            conditions.append({"content_type": content_type})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def _format_results(self, results: Mapping[str, Any]) -> list[QueryResult]:
        """Format ChromaDB results into QueryResult list."""
        formatted: list[QueryResult] = []

        # Results come as parallel lists
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        documents = (
            results.get("documents", [[]])[0] if results.get("documents") else [None] * len(ids)
        )

        for i, id_ in enumerate(ids):
            formatted.append(
                QueryResult(
                    id=id_,
                    distance=distances[i] if i < len(distances) else 0.0,
                    metadata=metadatas[i] if i < len(metadatas) else {},
                    document=documents[i] if documents and i < len(documents) else None,
                )
            )

        return formatted
