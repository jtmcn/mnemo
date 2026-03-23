"""Search service coordinating FTS5 and ChromaDB backends.

Provides a unified search interface that:
- Combines keyword (FTS5) and semantic (ChromaDB) search
- Merges results using Reciprocal Rank Fusion (RRF)
- Returns attributed results with book metadata
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mnemo.models import ContentType
from mnemo.search.hybrid import reciprocal_rank_fusion
from mnemo.search.models import SearchResult

if TYPE_CHECKING:
    from mnemo.storage.repository import BookRepository, ChunkRepository
    from mnemo.vectors.store import VectorStore

logger = logging.getLogger(__name__)

BACKMATTER_SECTIONS = frozenset(
    {
        "index",
        "bibliography",
        "glossary",
        "colophon",
        "about the authors",
        "about the author",
        "references",
        "further reading",
    }
)
FRONTMATTER_SECTIONS = frozenset(
    {
        "copyright",
        "title page",
        "dedication",
        "half title",
        "cover",
        "table of contents",
        "contents",
    }
)
BOILERPLATE_PENALTY = 0.3
SEMANTIC_FLOOR = 0.45
SHORT_CONTENT_THRESHOLD = 100
SHORT_CONTENT_PENALTY = 0.5


def _section_matches(query_norm: str, target_norm: str) -> bool:
    """Check if a section query matches a target section path string.

    When the query ends with a digit, uses regex with a word boundary to
    prevent "Chapter 6" from matching "Chapter 60". Otherwise falls back
    to plain substring match.
    """
    if not query_norm:
        return False
    if query_norm[-1].isdigit():
        return bool(re.search(re.escape(query_norm) + r"(?=[\W.]|$)", target_norm))
    return query_norm in target_norm


def normalize_unicode(s: str) -> str:
    """Normalize Unicode to ASCII-like form for accent-insensitive matching.

    Decomposes characters (e.g., ï -> i + combining diaeresis) then strips
    combining marks, so "naïve" becomes "naive".
    """
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


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
        context_window: int = 0,
    ) -> list[SearchResult] | list[dict]:
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
            context_window: Number of neighboring chunks to include around each
                match (default 0 = no expansion). Expansion stops at section
                boundaries and overlapping windows are deduplicated.

        Returns:
            If context_window == 0: list of SearchResult (unchanged behavior).
            If context_window >= 1: list of dicts with expanded context chunks.
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
        fetch_k = top_k * 5 if section else top_k

        # Initialize backends on first use
        self._ensure_initialized()

        # Execute search based on mode
        if mode == "keyword":
            results = self._keyword_search(query, fetch_k, book_id, content_type_enum)
        elif mode == "semantic":
            results = self._semantic_search(query, fetch_k, book_id, content_type)
        else:  # hybrid
            results = self._hybrid_search(query, fetch_k, book_id, content_type, content_type_enum)

        # Apply quality penalties before filtering/trimming
        results = self._apply_quality_penalties(results)

        # Apply section post-filter (with Unicode normalization for accented names)
        if section:
            section_norm = normalize_unicode(section)
            results = [
                r
                for r in results
                if r.section_path
                and _section_matches(section_norm, normalize_unicode(" > ".join(r.section_path)))
            ]

        # Cross-book diversity re-ranking (only when not filtering to a single book)
        if not book_id:
            results = self._diversify_results(results, top_k)

        # Trim to original top_k
        results = results[:top_k]

        # Context window expansion
        if context_window >= 1:
            expanded = [self._expand_result_context(r, context_window) for r in results]
            return self._deduplicate_expanded_results(expanded)

        return results

    def _expand_result_context(self, result: SearchResult, window: int) -> dict:
        """Expand a search result with neighboring chunks within same section.

        Args:
            result: The search result to expand
            window: Number of chunks before/after to include

        Returns:
            Dict with matched_chunk_id, book_id, start_seq, end_seq, chunks,
            matched_chunk_ids set, and the original result.
        """
        assert self._chunk_repo is not None

        chunk = self._chunk_repo.get(result.chunk_id)
        if chunk is None:
            return {
                "matched_chunk_id": result.chunk_id,
                "book_id": result.book_id,
                "start_seq": 0,
                "end_seq": 0,
                "chunks": [],
                "matched_chunk_ids": {result.chunk_id},
                "result": result,
            }

        # Fetch candidate neighbors
        candidates = self._chunk_repo.get_chunk_range(
            chunk.book_id, chunk.sequence - window, chunk.sequence + window
        )

        # Filter to same section_path, walking outward from matched chunk
        matched_section = chunk.section_path
        filtered: list = []

        # Sort candidates by sequence
        candidates_sorted = sorted(candidates, key=lambda c: c.sequence)

        # Find the matched chunk index
        matched_idx = None
        for i, c in enumerate(candidates_sorted):
            if c.id == chunk.id:
                matched_idx = i
                break

        if matched_idx is None:
            # Matched chunk not in range (shouldn't happen), return just it
            return {
                "matched_chunk_id": result.chunk_id,
                "book_id": chunk.book_id,
                "start_seq": chunk.sequence,
                "end_seq": chunk.sequence,
                "chunks": [chunk],
                "matched_chunk_ids": {result.chunk_id},
                "result": result,
            }

        # Walk backwards from matched chunk
        before = []
        for i in range(matched_idx - 1, -1, -1):
            if candidates_sorted[i].section_path == matched_section:
                before.append(candidates_sorted[i])
            else:
                break
        before.reverse()

        # Walk forwards from matched chunk
        after = []
        for i in range(matched_idx + 1, len(candidates_sorted)):
            if candidates_sorted[i].section_path == matched_section:
                after.append(candidates_sorted[i])
            else:
                break

        filtered = before + [candidates_sorted[matched_idx]] + after

        return {
            "matched_chunk_id": result.chunk_id,
            "book_id": chunk.book_id,
            "start_seq": filtered[0].sequence if filtered else chunk.sequence,
            "end_seq": filtered[-1].sequence if filtered else chunk.sequence,
            "chunks": filtered,
            "matched_chunk_ids": {result.chunk_id},
            "result": result,
        }

    def _deduplicate_expanded_results(self, expanded: list[dict]) -> list[dict]:
        """Merge overlapping expanded result windows.

        Groups by book_id, sorts by start_seq, and merges overlapping or
        adjacent ranges. Preserves all matched_chunk_ids and keeps the
        highest-scoring result as primary.

        Args:
            expanded: List of expanded result dicts from _expand_result_context

        Returns:
            Deduplicated list of expanded result dicts
        """
        if not expanded:
            return []

        # Group by book_id
        by_book: dict[str, list[dict]] = {}
        for exp in expanded:
            by_book.setdefault(exp["book_id"], []).append(exp)

        merged_all: list[dict] = []

        for _book_id, group in by_book.items():
            # Sort by start_seq
            group.sort(key=lambda x: x["start_seq"])

            merged: list[dict] = [group[0]]

            for current in group[1:]:
                prev = merged[-1]
                # Overlap or adjacent: merge
                if current["start_seq"] <= prev["end_seq"] + 1:
                    # Extend range
                    prev["end_seq"] = max(prev["end_seq"], current["end_seq"])
                    # Union matched IDs
                    prev["matched_chunk_ids"] = (
                        prev["matched_chunk_ids"] | current["matched_chunk_ids"]
                    )
                    # Merge chunks (deduplicate by id)
                    existing_ids = {c.id for c in prev["chunks"]}
                    for c in current["chunks"]:
                        if c.id not in existing_ids:
                            prev["chunks"].append(c)
                            existing_ids.add(c.id)
                    # Sort chunks by sequence
                    prev["chunks"].sort(key=lambda c: c.sequence)
                    # Keep highest-scoring result
                    if current["result"].score > prev["result"].score:
                        prev["result"] = current["result"]
                else:
                    merged.append(current)

            merged_all.extend(merged)

        return merged_all

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

        # Compute RRF-style scores and normalize to 0-1 range
        raw_scores = [1.0 / (60 + rank) for rank in range(1, len(chunks) + 1)]
        max_score = raw_scores[0] if raw_scores else 0.0

        results = []
        for i, chunk in enumerate(chunks):
            book_title = self._get_book_title(chunk.book_id)
            score = raw_scores[i] / max_score if max_score > 0 else 0.0
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
                    sequence=chunk.sequence,
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
                    sequence=chunk.sequence,
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
            # Filter out low-quality semantic results (cosine distance > 1.0
            # means similarity < 0, i.e. essentially unrelated content)
            vector_results = [vr for vr in vector_results if vr["distance"] <= 1.0]
            semantic_ids = [vr["id"] for vr in vector_results]
        except Exception as e:
            logger.warning(f"Semantic search failed, using keyword-only: {e}")

        # If no semantic results, fall back to keyword-only
        if not semantic_ids:
            return self._keyword_search(query, top_k, book_id, content_type_enum)

        # Compute RRF scores
        rrf_scores = reciprocal_rank_fusion([keyword_ids, semantic_ids])

        # Build semantic similarity map for absolute relevance signal
        semantic_sim_map = {
            vr["id"]: max(0.0, min(1.0, 1.0 - vr["distance"])) for vr in vector_results
        }

        # Filter keyword-only results that ranked poorly (beyond top_k in keyword list).
        # These are long-tail matches on common words that add noise.
        keyword_set = set(keyword_ids)
        semantic_set = set(semantic_ids)
        keyword_top = set(keyword_ids[:top_k])
        for chunk_id in list(rrf_scores.keys()):
            if (
                chunk_id in keyword_set
                and chunk_id not in semantic_set
                and chunk_id not in keyword_top
            ):
                del rrf_scores[chunk_id]

        # Blend normalized RRF rank with raw semantic similarity so scores
        # reflect absolute relevance (not just relative ranking).
        max_rrf = max(rrf_scores.values()) if rrf_scores else 0.0
        for chunk_id in rrf_scores:
            norm_rrf = rrf_scores[chunk_id] / max_rrf if max_rrf > 0 else 0.0
            raw_sim = semantic_sim_map.get(chunk_id, 0.0)
            if raw_sim >= SEMANTIC_FLOOR:
                rrf_scores[chunk_id] = 0.5 * norm_rrf + 0.5 * raw_sim
            elif raw_sim > 0:
                # Weak semantic match: discount to prevent keyword-driven false positives
                rrf_scores[chunk_id] = 0.3 * norm_rrf + 0.2 * raw_sim
            else:
                # Keyword-only hit: discount since we can't verify semantic relevance
                rrf_scores[chunk_id] = 0.3 * norm_rrf

        # Minimum score threshold: if best blended score is very low, the query
        # is likely gibberish and all results are noise.
        if rrf_scores and max(rrf_scores.values()) < 0.25:
            return []

        # Sort by score descending and take top_k
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:top_k]

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
                    sequence=chunk.sequence,
                )
            )

        return results

    @staticmethod
    def _diversify_results(results: list[SearchResult], top_k: int) -> list[SearchResult]:
        """Re-rank results using round-robin interleaving by book_id.

        Groups results by book, then picks one per book per round.
        Book order each round is determined by best remaining score.
        Within-book ordering (by score) is preserved.

        Args:
            results: Scored search results, already sorted by score descending
            top_k: Maximum results to return

        Returns:
            Diversified list of up to top_k results
        """
        if not results:
            return results

        # Group by book_id, preserving score order within each group
        groups: dict[str, list[SearchResult]] = {}
        for r in results:
            groups.setdefault(r.book_id, []).append(r)

        # If only one book, no diversification needed
        if len(groups) <= 1:
            return results

        # Round-robin interleaving
        diversified: list[SearchResult] = []
        while len(diversified) < top_k:
            # Remove exhausted groups
            groups = {bid: g for bid, g in groups.items() if g}
            if not groups:
                break

            # Order books by their best remaining score (descending)
            ordered_books = sorted(
                groups.keys(), key=lambda bid: groups[bid][0].score, reverse=True
            )

            for bid in ordered_books:
                if len(diversified) >= top_k:
                    break
                diversified.append(groups[bid].pop(0))

        return diversified

    @staticmethod
    def _apply_quality_penalties(results: list[SearchResult]) -> list[SearchResult]:
        """Demote low-quality results: boilerplate and very short chunks.

        Multiplies scores by BOILERPLATE_PENALTY for results whose section_path
        contains a known front-matter or back-matter section, and by
        SHORT_CONTENT_PENALTY for chunks below SHORT_CONTENT_THRESHOLD chars.
        Re-sorts by score after applying penalties.
        """
        for r in results:
            if r.section_path:
                for element in r.section_path:
                    el_lower = element.lower()
                    if (
                        el_lower in BACKMATTER_SECTIONS
                        or el_lower in FRONTMATTER_SECTIONS
                        or el_lower.startswith("appendix")
                    ):
                        r.score *= BOILERPLATE_PENALTY
                        break

            if len(r.content.strip()) < SHORT_CONTENT_THRESHOLD:
                r.score *= SHORT_CONTENT_PENALTY

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def suggest_sections(
        self, section_query: str, book_id: str | None = None, max_suggestions: int = 5
    ) -> list[str]:
        """Suggest section names similar to the given query.

        Uses difflib fuzzy matching against all distinct section names in the
        library (or a specific book). Useful when a section filter yields zero
        results.

        Args:
            section_query: The section name the user tried
            book_id: Optional book ID to scope suggestions
            max_suggestions: Maximum suggestions to return

        Returns:
            List of similar section names, best match first
        """
        self._ensure_initialized()
        assert self._chunk_repo is not None

        all_sections = self._chunk_repo.get_distinct_sections(book_id)
        if not all_sections:
            return []

        query_lower = section_query.lower()
        # First try substring containment (catches "Chapter 6" matching
        # "Chapter 6. Enriching Knowledge Graphs")
        contained = [s for s in all_sections if query_lower in s.lower()]
        if contained:
            return contained[:max_suggestions]

        # Fall back to fuzzy matching
        return difflib.get_close_matches(section_query, all_sections, n=max_suggestions, cutoff=0.4)

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
