"""Search service coordinating FTS5 and ChromaDB backends.

Provides a unified search interface that:
- Combines keyword (FTS5) and semantic (ChromaDB) search
- Merges results using Reciprocal Rank Fusion (RRF)
- Returns attributed results with book metadata
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mnemo.models import ContentType
from mnemo.search.hybrid import reciprocal_rank_fusion
from mnemo.search.models import SearchResult

if TYPE_CHECKING:
    from mnemo.storage.repository import BookRepository, ChunkRepository
    from mnemo.vectors.store import VectorStore

logger = logging.getLogger(__name__)


class SearchService:
    """Coordinates FTS5 and ChromaDB search with RRF fusion.

    Uses lazy initialization to avoid import-time side effects and
    credential requirements. Connections are established on first search.

    Supports three search modes:
    - "hybrid": Combines keyword + semantic search with RRF (default)
    - "semantic": Vector similarity search only
    - "keyword": FTS5 full-text search only

    Example:
        >>> service = SearchService()
        >>> results = service.search("async generators in Python", top_k=5)
        >>> for r in results:
        ...     print(f"{r.book_title}: {r.section_path}")
    """

    def __init__(
        self,
        db_path: Path | None = None,
        chroma_path: Path | None = None,
    ) -> None:
        """Initialize search service with storage paths.

        Args:
            db_path: Path to SQLite database (default: ~/.mnemo/mnemo.db)
            chroma_path: Path to ChromaDB storage (default: ~/.mnemo/chroma)

        Note:
            Connections are NOT created here - lazy initialization happens
            on first search to avoid import-time side effects.
        """
        self._db_path = db_path
        self._chroma_path = chroma_path

        # Lazy-initialized components
        self._chunk_repo: ChunkRepository | None = None
        self._book_repo: BookRepository | None = None
        self._vector_store: VectorStore | None = None
        self._embedder = None  # DatabricksEmbedder, imported lazily

        # Cache for book lookups to avoid repeated queries
        self._book_cache: dict[str, str] = {}  # book_id -> title

    def search(
        self,
        query: str,
        top_k: int = 10,
        book_id: str | None = None,
        content_type: str | None = None,
        mode: Literal["hybrid", "semantic", "keyword"] = "hybrid",
        section: str | None = None,
    ) -> list[SearchResult]:
        """Search books with optional filters and mode selection.

        Args:
            query: Search query (natural language or keywords)
            top_k: Maximum results to return (default 10)
            book_id: Optional filter to specific book (6-char hex)
            content_type: Optional filter (text, code, table, diagram, math)
            mode: Search mode - "hybrid", "semantic", or "keyword"
            section: Optional section name to filter results (e.g., 'Chapter 3',
                'Generators'). Case-insensitive substring match against section
                hierarchy.

        Returns:
            List of SearchResult objects sorted by relevance (highest first).
            Empty list if query is empty or no matches found.

        Raises:
            ValueError: If mode is not one of the valid options
        """
        # Validate inputs
        if not query or not query.strip():
            return []

        if mode not in ("hybrid", "semantic", "keyword"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'hybrid', 'semantic', or 'keyword'")

        # Convert content_type string to ContentType enum if provided
        content_type_enum = None
        if content_type:
            try:
                content_type_enum = ContentType(content_type)
            except ValueError:
                logger.warning(f"Invalid content_type '{content_type}', ignoring filter")

        # Over-fetch when section filter active to compensate for post-filter reduction
        fetch_k = top_k * 3 if section else top_k

        # Initialize backends on first use
        self._ensure_initialized()

        # Execute search based on mode
        if mode == "keyword":
            results = self._keyword_search(query, fetch_k, book_id, content_type_enum)
        elif mode == "semantic":
            results = self._semantic_search(query, fetch_k, book_id, content_type)
        else:  # hybrid
            results = self._hybrid_search(query, fetch_k, book_id, content_type, content_type_enum)

        # Apply section post-filter
        if section:
            section_lower = section.lower()
            results = [
                r for r in results
                if r.section_path and any(section_lower in s.lower() for s in r.section_path)
            ]

        # Trim to original top_k
        return results[:top_k]

    def _keyword_search(
        self,
        query: str,
        top_k: int,
        book_id: str | None,
        content_type: ContentType | None,
    ) -> list[SearchResult]:
        """Execute keyword-only search via FTS5."""
        assert self._chunk_repo is not None

        chunks = self._chunk_repo.search_fts(
            query=query,
            book_id=book_id,
            content_type=content_type,
            limit=top_k,
        )

        results = []
        for rank, chunk in enumerate(chunks, start=1):
            book_title = self._get_book_title(chunk.book_id)
            score = 1.0 / (60 + rank)  # RRF-style score for consistency
            results.append(
                SearchResult(
                    chunk_id=chunk.id,
                    book_id=chunk.book_id,
                    book_title=book_title,
                    content=chunk.content,
                    content_type=chunk.content_type.value,
                    section_path=chunk.section_path,
                    score=score,
                    source="keyword",
                )
            )

        return results

    def _semantic_search(
        self,
        query: str,
        top_k: int,
        book_id: str | None,
        content_type: str | None,
    ) -> list[SearchResult]:
        """Execute semantic-only search via ChromaDB."""
        assert self._vector_store is not None
        assert self._chunk_repo is not None

        # Get query embedding
        try:
            query_embedding = self._get_query_embedding(query)
        except Exception as e:
            logger.warning(f"Failed to generate query embedding: {e}")
            logger.info("Semantic search unavailable, returning empty results")
            return []

        # Query vector store
        vector_results = self._vector_store.query(
            query_embedding=query_embedding,
            n_results=top_k,
            book_id=book_id,
            content_type=content_type,
        )

        results = []
        for vr in vector_results:
            # Load full chunk data from SQLite
            chunk = self._chunk_repo.get(vr["id"])
            if chunk is None:
                logger.warning(f"Chunk {vr['id']} in vector store but not in SQLite")
                continue

            book_title = self._get_book_title(chunk.book_id)
            # Convert cosine distance (0-2) to similarity (0-1), clamped
            score = max(0.0, min(1.0, 1.0 - vr["distance"]))

            results.append(
                SearchResult(
                    chunk_id=chunk.id,
                    book_id=chunk.book_id,
                    book_title=book_title,
                    content=chunk.content,
                    content_type=chunk.content_type.value,
                    section_path=chunk.section_path,
                    score=score,
                    source="semantic",
                )
            )

        return results

    def _hybrid_search(
        self,
        query: str,
        top_k: int,
        book_id: str | None,
        content_type: str | None,
        content_type_enum: ContentType | None,
    ) -> list[SearchResult]:
        """Execute hybrid search combining keyword + semantic with RRF."""
        assert self._chunk_repo is not None
        assert self._vector_store is not None

        # Request 2x results from each backend for better RRF fusion
        fetch_k = top_k * 2

        # Keyword search
        keyword_chunks = self._chunk_repo.search_fts(
            query=query,
            book_id=book_id,
            content_type=content_type_enum,
            limit=fetch_k,
        )
        keyword_ids = [c.id for c in keyword_chunks]

        # Semantic search (may fail if embeddings unavailable)
        semantic_ids: list[str] = []
        try:
            query_embedding = self._get_query_embedding(query)
            vector_results = self._vector_store.query(
                query_embedding=query_embedding,
                n_results=fetch_k,
                book_id=book_id,
                content_type=content_type,
            )
            semantic_ids = [vr["id"] for vr in vector_results]
        except Exception as e:
            logger.warning(f"Semantic search failed, using keyword-only: {e}")

        # If no semantic results, fall back to keyword-only
        if not semantic_ids:
            return self._keyword_search(query, top_k, book_id, content_type_enum)

        # Compute RRF scores
        rrf_scores = reciprocal_rank_fusion([keyword_ids, semantic_ids])

        # Sort by score descending and take top_k
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:top_k]

        # Determine which source(s) each result came from
        keyword_set = set(keyword_ids)
        semantic_set = set(semantic_ids)

        # Build chunk lookup from keyword results (already loaded)
        chunk_map = {c.id: c for c in keyword_chunks}

        results = []
        for chunk_id in sorted_ids:
            # Load chunk if not in keyword results
            if chunk_id not in chunk_map:
                chunk = self._chunk_repo.get(chunk_id)
                if chunk is None:
                    logger.warning(f"Chunk {chunk_id} not found in SQLite")
                    continue
                chunk_map[chunk_id] = chunk

            chunk = chunk_map[chunk_id]
            book_title = self._get_book_title(chunk.book_id)

            # Determine source
            in_keyword = chunk_id in keyword_set
            in_semantic = chunk_id in semantic_set
            if in_keyword and in_semantic:
                source: Literal["semantic", "keyword", "both"] = "both"
            elif in_keyword:
                source = "keyword"
            else:
                source = "semantic"

            results.append(
                SearchResult(
                    chunk_id=chunk.id,
                    book_id=chunk.book_id,
                    book_title=book_title,
                    content=chunk.content,
                    content_type=chunk.content_type.value,
                    section_path=chunk.section_path,
                    score=rrf_scores[chunk_id],
                    source=source,
                )
            )

        return results

    def _ensure_initialized(self) -> None:
        """Lazy initialization of database connections and vector store."""
        if self._chunk_repo is None:
            from mnemo.storage.database import get_connection, init_db
            from mnemo.storage.repository import BookRepository, ChunkRepository

            # Ensure database exists
            init_db(self._db_path)
            conn = get_connection(self._db_path)

            self._chunk_repo = ChunkRepository(conn)
            self._book_repo = BookRepository(conn)

        if self._vector_store is None:
            from mnemo.vectors.config import VectorConfig
            from mnemo.vectors.store import VectorStore

            config = VectorConfig(persist_path=self._chroma_path)
            self._vector_store = VectorStore(config)

    def _get_query_embedding(self, query: str) -> list[float]:
        """Generate embedding for search query.

        Lazy imports DatabricksEmbedder to avoid credential requirement at import time.
        """
        if self._embedder is None:
            from mnemo.embeddings.client import DatabricksEmbedder

            self._embedder = DatabricksEmbedder()

        return self._embedder.embed_one(query)

    def invalidate_cache(self) -> None:
        """Clear the book title cache after mutations."""
        self._book_cache.clear()

    def _get_book_title(self, book_id: str) -> str:
        """Get book title with caching to avoid repeated lookups."""
        if book_id in self._book_cache:
            return self._book_cache[book_id]

        assert self._book_repo is not None
        book = self._book_repo.get(book_id)
        title = book.title if book else "Unknown book"
        self._book_cache[book_id] = title
        return title
