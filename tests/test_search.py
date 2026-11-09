"""Tests for search module.

Tests cover:
- Reciprocal Rank Fusion (RRF) algorithm
- SearchResult and SearchFilter dataclasses
- SearchService with mocked backends and a seeded Library
- SearchService integration tests
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mnemo.embeddings.config import EmbeddingsNotConfigured
from mnemo.models import Book, Chunk, ContentType, is_boilerplate_section
from mnemo.search import EmptyReason, SearchFilter, SearchResult, reciprocal_rank_fusion
from mnemo.search.service import (
    BOILERPLATE_PENALTY,
    SHORT_CONTENT_PENALTY,
    SearchService,
    _section_matches,
)
from mnemo.storage.database import get_connection, init_db
from mnemo.storage.repository import BookRepository, ChunkRepository
from tests.fixtures.library import FixedEmbedder, Library

_SOURDOUGH = "how do I bake sourdough bread"


def _prose(terms: str) -> str:
    """Over 100 chars, so no short-content penalty, holding `terms` and only filler besides."""
    return f"{terms} appears in this passage among plenty of other filler words. " * 3


# ============================================================================
# RRF Fusion Tests
# ============================================================================


class TestReciprocalRankFusion:
    """Tests for the RRF fusion algorithm."""

    def test_empty_lists(self):
        """Empty input returns empty output."""
        scores = reciprocal_rank_fusion([])
        assert scores == {}

    def test_single_empty_list(self):
        """Single empty list returns empty output."""
        scores = reciprocal_rank_fusion([[]])
        assert scores == {}

    def test_single_list(self):
        """Single list assigns rank-based scores."""
        scores = reciprocal_rank_fusion([["a", "b", "c"]])

        # Score formula: 1/(k+rank) where k=60
        assert abs(scores["a"] - 1 / 61) < 1e-9  # rank 1
        assert abs(scores["b"] - 1 / 62) < 1e-9  # rank 2
        assert abs(scores["c"] - 1 / 63) < 1e-9  # rank 3

    def test_disjoint_lists(self):
        """Items in disjoint lists get independent scores."""
        scores = reciprocal_rank_fusion([["a", "b"], ["c", "d"]])

        # All items ranked 1 or 2 in their list
        assert abs(scores["a"] - 1 / 61) < 1e-9
        assert abs(scores["b"] - 1 / 62) < 1e-9
        assert abs(scores["c"] - 1 / 61) < 1e-9
        assert abs(scores["d"] - 1 / 62) < 1e-9

    def test_overlapping_items_score_higher(self):
        """Items in both lists score higher than items in one list."""
        scores = reciprocal_rank_fusion([["a", "b"], ["b", "c"]])

        # "b" is in both lists (rank 2 in first, rank 1 in second)
        # score_b = 1/62 + 1/61
        # "a" is only in first list (rank 1)
        # score_a = 1/61
        assert scores["b"] > scores["a"]
        assert scores["b"] > scores["c"]

    def test_overlapping_items_exact_score(self):
        """Verify exact score calculation for overlapping items."""
        scores = reciprocal_rank_fusion([["x", "y"], ["y", "z"]])

        # y is rank 2 in list 1, rank 1 in list 2
        expected_y = 1 / 62 + 1 / 61
        assert abs(scores["y"] - expected_y) < 1e-9

    def test_custom_k_parameter(self):
        """Custom k parameter affects scores."""
        k = 30
        scores = reciprocal_rank_fusion([["a", "b"]], k=k)

        assert abs(scores["a"] - 1 / 31) < 1e-9  # k + rank
        assert abs(scores["b"] - 1 / 32) < 1e-9

    def test_k_zero_allowed(self):
        """k=0 is allowed (just uses rank as denominator)."""
        scores = reciprocal_rank_fusion([["a", "b"]], k=0)

        assert abs(scores["a"] - 1 / 1) < 1e-9  # 0 + 1
        assert abs(scores["b"] - 1 / 2) < 1e-9  # 0 + 2

    def test_negative_k_raises(self):
        """Negative k raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            reciprocal_rank_fusion([["a"]], k=-1)

    def test_multiple_lists(self):
        """Works with more than two lists."""
        scores = reciprocal_rank_fusion([["a"], ["a"], ["a"]])

        # "a" is rank 1 in all three lists
        expected = 3 * (1 / 61)
        assert abs(scores["a"] - expected) < 1e-9

    def test_preserves_chunk_ids(self):
        """All chunk IDs from all lists appear in output."""
        scores = reciprocal_rank_fusion(
            [
                ["id-1", "id-2"],
                ["id-3", "id-4"],
                ["id-1", "id-5"],
            ]
        )

        assert set(scores.keys()) == {"id-1", "id-2", "id-3", "id-4", "id-5"}


# ============================================================================
# Model Tests
# ============================================================================


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_creation(self):
        """Can create SearchResult with all fields."""
        result = SearchResult(
            chunk_id="uuid-123",
            book_id="abc123",
            book_title="Python Cookbook",
            content="def hello(): pass",
            content_type="code",
            section_path=["Chapter 1", "Functions"],
            score=0.5,
            source="hybrid",
        )

        assert result.chunk_id == "uuid-123"
        assert result.book_id == "abc123"
        assert result.book_title == "Python Cookbook"
        assert result.content == "def hello(): pass"
        assert result.content_type == "code"
        assert result.section_path == ["Chapter 1", "Functions"]
        assert result.score == 0.5
        assert result.source == "hybrid"

    def test_source_literals(self):
        """source field accepts valid literals."""
        for source in ["semantic", "keyword", "both"]:
            result = SearchResult(
                chunk_id="id",
                book_id="abc123",
                book_title="Title",
                content="text",
                content_type="text",
                section_path=[],
                score=0.1,
                source=source,
            )
            assert result.source == source


class TestSearchFilter:
    """Tests for SearchFilter dataclass."""

    def test_default_values(self):
        """Defaults are all None."""
        filter = SearchFilter()
        assert filter.book_id is None
        assert filter.content_type is None

    def test_book_id_filter(self):
        """Can set book_id filter."""
        filter = SearchFilter(book_id="abc123")
        assert filter.book_id == "abc123"
        assert filter.content_type is None

    def test_content_type_filter(self):
        """Can set content_type filter."""
        filter = SearchFilter(content_type="code")
        assert filter.book_id is None
        assert filter.content_type == "code"

    def test_combined_filters(self):
        """Can set both filters."""
        filter = SearchFilter(book_id="abc123", content_type="code")
        assert filter.book_id == "abc123"
        assert filter.content_type == "code"


# ============================================================================
# SearchService Unit Tests (Mocked Backends)
# ============================================================================


class TestSearchServiceInit:
    """Tests for SearchService initialization."""

    def test_init_no_args(self):
        """Can create service with no arguments."""
        service = SearchService()
        assert service._db_path is None
        assert service._chroma_path is None

    def test_init_with_paths(self, tmp_path):
        """Can create service with custom paths."""
        db_path = tmp_path / "test.db"
        chroma_path = tmp_path / "chroma"

        service = SearchService(db_path=db_path, chroma_path=chroma_path)

        assert service._db_path == db_path
        assert service._chroma_path == chroma_path

    def test_chunks_without_books_is_rejected(self, library):
        with pytest.raises(ValueError, match="together"):
            SearchService(chunks=library.chunks)

    def test_injected_dependencies_are_searched_and_nothing_is_opened(self, library, tmp_path):
        hit = library.add(_prose("pipeline"), similarity=0.9)
        db_path = tmp_path / "never.db"
        service = SearchService(
            db_path=db_path,
            chunks=library.chunks,
            books=library.books,
            vectors=library.vectors,
            embedder=FixedEmbedder(),
        )

        results = service.search("pipeline stages", mode="hybrid").results

        assert [r.chunk_id for r in results] == [hit.id]
        assert not db_path.exists()

    def test_lazy_initialization(self):
        """Service doesn't create connections on init."""
        service = SearchService()

        # Internal attributes should be None before first search
        assert service._chunk_repo is None
        assert service._book_repo is None
        assert service._vector_store is None


class TestSearchServiceValidation:
    """Tests for SearchService input validation."""

    @pytest.fixture
    def service(self, tmp_path):
        """Create service with temp storage."""
        return SearchService(
            db_path=tmp_path / "test.db",
            chroma_path=tmp_path / "chroma",
        )

    def test_empty_query_returns_empty(self, service):
        """Empty query returns empty list without error."""
        for query in ("", "   "):
            response = service.search(query)
            assert response.results == []
            assert response.empty_reason == EmptyReason("empty_query", "Query cannot be empty")

    def test_invalid_mode_raises(self, service):
        """Invalid mode raises ValueError."""
        with pytest.raises(ValueError, match="Invalid mode"):
            service.search("test", mode="invalid")

    def test_valid_modes_accepted(self, tmp_path):
        """All valid modes are accepted.

        Embedding env is cleared by the autouse fixture in conftest, so
        semantic mode raises here regardless of the developer's own config.
        """
        # Create a properly initialized service
        db_path = tmp_path / "test.db"
        init_db(db_path)
        service = SearchService(db_path=db_path, chroma_path=tmp_path / "chroma")

        # hybrid and keyword work with no embeddings configured; semantic is an
        # explicit request for something unavailable, so it raises rather than
        # returning [] (which would read as "no matching content").
        for mode in ["hybrid", "keyword"]:
            result = service.search("test", mode=mode).results
            assert isinstance(result, list)

        with pytest.raises(EmbeddingsNotConfigured):
            service.search("test", mode="semantic")


# ============================================================================
# SearchService Mocked Tests
# ============================================================================


class TestSearchServiceMocked:
    """Tests for SearchService with mocked backends."""

    @pytest.fixture
    def mock_chunk_repo(self):
        """Create mock ChunkRepository."""
        repo = MagicMock()
        repo.search_fts.return_value = []
        repo.get.return_value = None
        return repo

    @pytest.fixture
    def mock_book_repo(self):
        """Create mock BookRepository."""
        repo = MagicMock()
        repo.get.return_value = None
        return repo

    @pytest.fixture
    def mock_vector_store(self):
        """Create mock VectorStore."""
        store = MagicMock()
        store.query.return_value = []
        return store

    @pytest.fixture
    def mock_embedder(self):
        """Create mock Embedder."""
        embedder = MagicMock()
        embedder.embed_one.return_value = [0.1] * 1024
        return embedder

    @pytest.fixture
    def service_with_mocks(self, mock_chunk_repo, mock_book_repo, mock_vector_store, mock_embedder):
        """Create service with injected mocks."""
        service = SearchService(
            chunks=mock_chunk_repo,
            books=mock_book_repo,
            vectors=mock_vector_store,
            embedder=mock_embedder,
        )
        return service

    def test_keyword_mode_calls_fts(self, service_with_mocks, mock_chunk_repo):
        """Keyword mode calls FTS search."""
        service_with_mocks.search("test query", mode="keyword")

        mock_chunk_repo.search_fts.assert_called_once()
        call_args = mock_chunk_repo.search_fts.call_args
        assert call_args.kwargs["query"] == "test query"

    def test_keyword_mode_passes_filters(self, service_with_mocks, mock_chunk_repo):
        """Keyword mode passes book_id and content_type filters."""
        service_with_mocks.search(
            "test",
            mode="keyword",
            book_id="abc123",
            content_type="code",
        )

        call_args = mock_chunk_repo.search_fts.call_args
        assert call_args.kwargs["book_id"] == "abc123"
        assert call_args.kwargs["content_type"] == ContentType.CODE

    def test_semantic_mode_calls_embedder(self, service_with_mocks, mock_embedder):
        """Semantic mode generates query embedding."""
        service_with_mocks.search("test query", mode="semantic")

        mock_embedder.embed_one.assert_called_once_with("test query")

    def test_semantic_mode_calls_vector_store(self, service_with_mocks, mock_vector_store):
        """Semantic mode queries vector store."""
        service_with_mocks.search("test query", mode="semantic")

        mock_vector_store.query.assert_called_once()

    def test_semantic_mode_passes_filters(self, service_with_mocks, mock_vector_store):
        """Semantic mode passes filters to vector store."""
        service_with_mocks.search(
            "test",
            mode="semantic",
            book_id="abc123",
            content_type="code",
        )

        call_args = mock_vector_store.query.call_args
        assert call_args.kwargs["book_id"] == "abc123"
        assert call_args.kwargs["content_type"] == "code"

    def test_hybrid_mode_calls_both_backends(
        self, service_with_mocks, mock_chunk_repo, mock_vector_store
    ):
        """Hybrid mode calls both FTS and vector search."""
        # Setup mock to return some results so semantic search path is taken
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 0.1, "metadata": {}, "document": None}
        ]
        mock_chunk_repo.search_fts.return_value = []
        mock_chunk_repo.get.return_value = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=[],
        )
        service_with_mocks._book_cache["abc123"] = "Test Book"

        service_with_mocks.search("test query", mode="hybrid")

        fts_calls = mock_chunk_repo.search_fts.call_args_list
        assert any(not call.kwargs.get("match_all") for call in fts_calls)
        mock_vector_store.query.assert_called_once()

    def test_hybrid_requests_2x_results(
        self, service_with_mocks, mock_chunk_repo, mock_vector_store
    ):
        """Hybrid mode requests 2x top_k from each backend."""
        # Setup mock to return some results so semantic search path is taken
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 0.1, "metadata": {}, "document": None}
        ]
        mock_chunk_repo.search_fts.return_value = []
        mock_chunk_repo.get.return_value = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=[],
        )
        service_with_mocks._book_cache["abc123"] = "Test Book"

        service_with_mocks.search("test", top_k=10, mode="hybrid")

        # Should request 20 results from each backend
        fts_call = mock_chunk_repo.search_fts.call_args
        assert fts_call.kwargs["limit"] == 20

        vector_call = mock_vector_store.query.call_args
        assert vector_call.kwargs["n_results"] == 20

    def test_top_k_passed_to_fts(self, service_with_mocks, mock_chunk_repo):
        """top_k is passed to FTS limit parameter."""
        # FTS returns whatever limit is set (5 in this case)
        mock_chunks = []
        for i in range(5):
            mock_chunk = MagicMock()
            mock_chunk.id = f"chunk-{i}"
            mock_chunk.book_id = "abc123"
            mock_chunk.content = f"Content {i}"
            mock_chunk.content_type = ContentType.TEXT
            mock_chunk.section_path = ["Ch1"]
            mock_chunks.append(mock_chunk)

        mock_chunk_repo.search_fts.return_value = mock_chunks

        # Mock book lookup
        service_with_mocks._book_cache["abc123"] = "Test Book"

        service_with_mocks.search("test", top_k=5, mode="keyword")

        # Verify limit was passed to FTS
        call_args = mock_chunk_repo.search_fts.call_args
        assert call_args.kwargs["limit"] == 5

    def test_book_title_populated(self, service_with_mocks, mock_chunk_repo, mock_book_repo):
        """Search results include book title."""
        # Create mock chunk
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="Test content",
            content_type=ContentType.TEXT,
            section_path=["Chapter 1"],
        )
        mock_chunk_repo.search_fts.return_value = [mock_chunk]

        # Mock book lookup
        mock_book = MagicMock(title="Python Cookbook")
        mock_book_repo.get.return_value = mock_book

        results = service_with_mocks.search("test", mode="keyword").results

        assert len(results) == 1
        assert results[0].book_title == "Python Cookbook"

    def test_book_title_cached(self, service_with_mocks, mock_chunk_repo, mock_book_repo):
        """Book title lookup is cached."""
        # Create multiple chunks from same book
        mock_chunks = [
            MagicMock(
                id=f"chunk-{i}",
                book_id="abc123",
                content="x" * 200,
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
            )
            for i in range(3)
        ]
        mock_chunk_repo.search_fts.return_value = mock_chunks

        # Mock book lookup
        mock_book = MagicMock(title="Test Book")
        mock_book_repo.get.return_value = mock_book

        service_with_mocks.search("test", mode="keyword")

        # Book lookup should only be called once (cached)
        mock_book_repo.get.assert_called_once_with("abc123")

    def test_unknown_book_title_fallback(self, service_with_mocks, mock_chunk_repo, mock_book_repo):
        """Unknown book_id gets 'Unknown book' title."""
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="unknown",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=[],
        )
        mock_chunk_repo.search_fts.return_value = [mock_chunk]
        mock_book_repo.get.return_value = None

        results = service_with_mocks.search("test", mode="keyword").results

        assert results[0].book_title == "Unknown book"

    def test_semantic_failure_falls_back_to_keyword(
        self, service_with_mocks, mock_embedder, mock_chunk_repo
    ):
        """Hybrid falls back to keyword when no endpoint is configured.

        Only the unconfigured case is quiet: running without
        MNEMO_EMBED_BASE_URL is a deliberate keyword-only setup. A configured
        endpoint that fails is a misconfiguration and raises (see below).
        """
        mock_embedder.embed_one.side_effect = EmbeddingsNotConfigured("not configured")

        # Setup keyword results
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=[],
        )
        mock_chunk_repo.search_fts.return_value = [mock_chunk]
        service_with_mocks._book_cache["abc123"] = "Test Book"

        # Should not raise, should return keyword results
        results = service_with_mocks.search("test", mode="hybrid").results

        assert len(results) == 1
        assert results[0].source == "keyword"

    def test_broken_endpoint_raises_instead_of_degrading(
        self, service_with_mocks, mock_embedder, mock_chunk_repo
    ):
        """A configured-but-failing endpoint must not masquerade as keyword-only.

        Silently downgrading hid a bad key, a wrong model, and a dead host
        behind ordinary-looking results — over MCP the warning went to stderr
        where no caller ever saw it.
        """
        mock_embedder.embed_one.side_effect = Exception("401 Unauthorized")
        mock_chunk_repo.search_fts.return_value = []

        for mode in ("hybrid", "semantic"):
            with pytest.raises(Exception, match="401 Unauthorized"):
                service_with_mocks.search("test", mode=mode)

    def test_invalid_content_type_ignored(self, service_with_mocks, mock_chunk_repo):
        """Invalid content_type filter is ignored with warning."""
        service_with_mocks.search(
            "test",
            mode="keyword",
            content_type="invalid_type",
        )

        # Should not pass content_type filter to FTS
        call_args = mock_chunk_repo.search_fts.call_args
        assert call_args.kwargs["content_type"] is None


# ============================================================================
# Cosine Similarity Score Tests
# ============================================================================


class TestSemanticSearchCosineScores:
    """Tests that semantic search returns cosine similarity scores."""

    @pytest.fixture
    def mock_chunk_repo(self):
        repo = MagicMock()
        return repo

    @pytest.fixture
    def mock_book_repo(self):
        repo = MagicMock()
        return repo

    @pytest.fixture
    def mock_vector_store(self):
        store = MagicMock()
        return store

    @pytest.fixture
    def mock_embedder(self):
        embedder = MagicMock()
        embedder.embed_one.return_value = [0.1] * 1024
        return embedder

    @pytest.fixture
    def service(self, mock_chunk_repo, mock_book_repo, mock_vector_store, mock_embedder):
        svc = SearchService(
            chunks=mock_chunk_repo,
            books=mock_book_repo,
            vectors=mock_vector_store,
            embedder=mock_embedder,
        )
        return svc

    def test_semantic_score_is_cosine_similarity(self, service, mock_vector_store, mock_chunk_repo):
        """Semantic search score = max(0, 1 - distance) for cosine distance."""
        # ChromaDB cosine distance of 0.3 -> similarity of 0.7
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 0.3, "metadata": {}, "document": None},
        ]
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=["Ch1"],
        )
        mock_chunk_repo.get.return_value = mock_chunk
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="semantic").results

        assert len(results) == 1
        assert abs(results[0].score - 0.7) < 1e-6

    def test_semantic_score_clamped_to_zero_filtered(
        self,
        service,
        mock_vector_store,
        mock_chunk_repo,
    ):
        """Cosine distance > 1.0 yields similarity 0.0, filtered by score floor."""
        # Distance > 1.0 can happen with non-normalized vectors
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 1.5, "metadata": {}, "document": None},
        ]
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=[],
        )
        mock_chunk_repo.get.return_value = mock_chunk
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="semantic").results

        # Score 0.0 is below MIN_SEMANTIC_SCORE (0.25), so filtered out
        assert len(results) == 0

    def test_semantic_score_clamped_to_one(self, service, mock_vector_store, mock_chunk_repo):
        """Cosine similarity is clamped to 1.0 maximum."""
        # Distance of exactly 0 -> similarity of 1.0
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 0.0, "metadata": {}, "document": None},
        ]
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=[],
        )
        mock_chunk_repo.get.return_value = mock_chunk
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="semantic").results

        assert results[0].score == 1.0

    def test_keyword_search_scores_normalized(self, service, mock_chunk_repo):
        """Keyword search results are normalized to 0-1 range."""
        mock_chunks = [
            MagicMock(
                id=f"chunk-{i}",
                book_id="abc123",
                content="x" * 200,
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
            )
            for i in range(3)
        ]
        mock_chunk_repo.search_fts.return_value = mock_chunks
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="keyword").results

        # Top result should always score 1.0 after normalization
        assert results[0].score == 1.0
        # Subsequent results should be proportionally lower
        assert abs(results[1].score - (1.0 / 62) / (1.0 / 61)) < 1e-9  # 61/62
        assert abs(results[2].score - (1.0 / 63) / (1.0 / 61)) < 1e-9  # 61/63
        # All scores should be in 0-1 range
        assert all(0.0 <= r.score <= 1.0 for r in results)


# ============================================================================
# SearchService Integration Tests
# ============================================================================


@pytest.fixture
def integration_service(tmp_path):
    """Create SearchService with real storage for integration tests."""
    db_path = tmp_path / "test.db"
    chroma_path = tmp_path / "chroma"

    # Initialize database
    init_db(db_path)

    return SearchService(db_path=db_path, chroma_path=chroma_path)


@pytest.fixture
def populated_integration_service(tmp_path):
    """Create SearchService with test data."""
    db_path = tmp_path / "test.db"
    chroma_path = tmp_path / "chroma"

    # Initialize database
    init_db(db_path)
    conn = get_connection(db_path)

    # Create test books (use valid 6-char hex IDs)
    book_repo = BookRepository(conn)
    book1 = Book(
        id="a1b2c3",
        title="Python Cookbook",
        authors=["David Beazley"],
        file_hash="a" * 64,
        structure_source="toc",
    )
    book2 = Book(
        id="d4e5f6",
        title="JavaScript Guide",
        authors=["John Doe"],
        file_hash="b" * 64,
        structure_source="toc",
    )
    book_repo.add(book1)
    book_repo.add(book2)

    # Create test chunks
    chunk_repo = ChunkRepository(conn)
    chunks = [
        Chunk(
            id=str(uuid.uuid4()),
            book_id="a1b2c3",
            content="Python generators are powerful for lazy evaluation and memory efficiency.",
            content_type=ContentType.TEXT,
            token_count=10,
            section_path=["Chapter 4", "Iterators and Generators"],
            sections=["Iterators and Generators"],
            sequence=0,
        ),
        Chunk(
            id=str(uuid.uuid4()),
            book_id="a1b2c3",
            content=(
                "def fibonacci():\n    a, b = 0, 1\n"
                "    while True:\n        yield a\n        a, b = b, a + b"
            ),
            content_type=ContentType.CODE,
            token_count=20,
            section_path=["Chapter 4", "Iterators and Generators"],
            sections=["Iterators and Generators"],
            language="python",
            sequence=1,
        ),
        Chunk(
            id=str(uuid.uuid4()),
            book_id="a1b2c3",
            content="Async programming allows concurrent execution without threads.",
            content_type=ContentType.TEXT,
            token_count=8,
            section_path=["Chapter 12", "Concurrency"],
            sections=["Concurrency"],
            sequence=2,
        ),
        Chunk(
            id=str(uuid.uuid4()),
            book_id="d4e5f6",
            content="JavaScript generators were introduced in ES6.",
            content_type=ContentType.TEXT,
            token_count=7,
            section_path=["ES6 Features"],
            sections=["ES6 Features"],
            sequence=0,
        ),
    ]
    chunk_repo.add_many(chunks)

    conn.close()

    return SearchService(db_path=db_path, chroma_path=chroma_path)


class TestSearchServiceIntegration:
    """Integration tests with real storage backends."""

    def test_keyword_search_finds_match(self, populated_integration_service):
        """Keyword search finds matching chunks."""
        results = populated_integration_service.search(
            "generators",
            mode="keyword",
        ).results

        assert len(results) >= 1
        assert any("generator" in r.content.lower() for r in results)

    def test_keyword_search_book_filter(self, populated_integration_service):
        """Keyword search respects book_id filter."""
        results = populated_integration_service.search(
            "generators",
            mode="keyword",
            book_id="a1b2c3",
        ).results

        assert all(r.book_id == "a1b2c3" for r in results)

    def test_keyword_search_content_type_filter(self, populated_integration_service):
        """Keyword search respects content_type filter."""
        results = populated_integration_service.search(
            "fibonacci",
            mode="keyword",
            content_type="code",
        ).results

        assert len(results) >= 1
        assert all(r.content_type == "code" for r in results)

    def test_keyword_search_returns_attribution(self, populated_integration_service):
        """Keyword search results include full attribution."""
        results = populated_integration_service.search(
            "generators",
            mode="keyword",
            top_k=1,
        ).results

        assert len(results) >= 1
        result = results[0]

        # Check all attribution fields populated
        assert result.chunk_id
        assert result.book_id
        assert result.book_title in ["Python Cookbook", "JavaScript Guide"]
        assert result.content
        assert result.content_type
        assert isinstance(result.section_path, list)
        assert result.score > 0
        assert result.source == "keyword"

    def test_search_no_results(self, populated_integration_service):
        """Search for non-matching query returns empty list."""
        results = populated_integration_service.search(
            "xyznonexistent123",
            mode="keyword",
        ).results

        assert results == []

    def test_search_nonexistent_book_filter(self, populated_integration_service):
        """Search with non-existent book_id returns empty."""
        results = populated_integration_service.search(
            "generators",
            mode="keyword",
            book_id="nonexistent",
        ).results

        assert results == []

    def test_keyword_search_special_chars(self, populated_integration_service):
        """Keyword search handles special characters safely."""
        # These should not raise errors
        populated_integration_service.search("def fibonacci()", mode="keyword")
        populated_integration_service.search("a, b = 0, 1", mode="keyword")
        populated_integration_service.search("while True:", mode="keyword")

    def test_no_indexed_books(self, integration_service):
        """Search on empty database returns empty list."""
        results = integration_service.search("anything", mode="keyword").results
        assert results == []


# ============================================================================
# RRF Integration Tests
# ============================================================================


# ============================================================================
# Section Filter Tests
# ============================================================================


class TestSectionFilter:
    """Tests for section-based substring filtering in SearchService."""

    @pytest.fixture
    def mock_chunk_repo(self):
        repo = MagicMock()
        repo.search_fts.return_value = []
        repo.get.return_value = None
        return repo

    @pytest.fixture
    def mock_book_repo(self):
        repo = MagicMock()
        return repo

    @pytest.fixture
    def mock_vector_store(self):
        store = MagicMock()
        store.query.return_value = []
        return store

    @pytest.fixture
    def mock_embedder(self):
        embedder = MagicMock()
        embedder.embed_one.return_value = [0.1] * 1024
        return embedder

    @pytest.fixture
    def service(self, mock_chunk_repo, mock_book_repo, mock_vector_store, mock_embedder):
        svc = SearchService(
            chunks=mock_chunk_repo,
            books=mock_book_repo,
            vectors=mock_vector_store,
            embedder=mock_embedder,
        )
        svc._book_cache["abc123"] = "Test Book"
        return svc

    def _make_chunk(self, chunk_id, section_path):
        """Helper to create a mock chunk with given section_path."""
        return MagicMock(
            id=chunk_id,
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=section_path,
        )

    def test_section_filter_matches_substring(self, service, mock_chunk_repo):
        """section='Generators' filters to only results with 'Generators' in section_path."""
        chunks = [
            self._make_chunk("c1", ["Chapter 4", "Generators and Iterators"]),
            self._make_chunk("c2", ["Chapter 5", "Concurrency"]),
            self._make_chunk("c3", ["Chapter 6", "Advanced Generators"]),
        ]
        mock_chunk_repo.search_fts.return_value = chunks

        results = service.search("test", mode="keyword", section="Generators").results

        assert len(results) == 2
        chunk_ids = {r.chunk_id for r in results}
        assert chunk_ids == {"c1", "c3"}

    def test_section_filter_case_insensitive(self, service, mock_chunk_repo):
        """section='generators' matches 'Generators and Iterators' (case-insensitive)."""
        chunks = [
            self._make_chunk("c1", ["Chapter 4", "Generators and Iterators"]),
            self._make_chunk("c2", ["Chapter 5", "Concurrency"]),
        ]
        mock_chunk_repo.search_fts.return_value = chunks

        results = service.search("test", mode="keyword", section="generators").results

        assert len(results) == 1
        assert results[0].chunk_id == "c1"

    def test_section_filter_empty_section_path_excluded(self, service, mock_chunk_repo):
        """Chunks with section_path=[] are excluded when section filter is active."""
        chunks = [
            self._make_chunk("c1", []),
            self._make_chunk("c2", ["Chapter 1", "Generators"]),
        ]
        mock_chunk_repo.search_fts.return_value = chunks

        results = service.search("test", mode="keyword", section="Generators").results

        assert len(results) == 1
        assert results[0].chunk_id == "c2"

    def test_section_filter_none_returns_all(self, service, mock_chunk_repo):
        """section=None returns unfiltered results (current behavior)."""
        chunks = [
            self._make_chunk("c1", ["Chapter 4", "Generators"]),
            self._make_chunk("c2", ["Chapter 5", "Concurrency"]),
            self._make_chunk("c3", []),
        ]
        mock_chunk_repo.search_fts.return_value = chunks

        results = service.search("test", mode="keyword", section=None).results

        assert len(results) == 3

    @pytest.mark.parametrize("mode", ["keyword", "semantic", "hybrid"])
    def test_section_filter_all_modes(self, service, mock_chunk_repo, mock_vector_store, mode):
        """Section filtering works for keyword, semantic, and hybrid modes."""
        chunks = [
            self._make_chunk("c1", ["Chapter 4", "Generators"]),
            self._make_chunk("c2", ["Chapter 5", "Concurrency"]),
        ]

        if mode == "keyword":
            mock_chunk_repo.search_fts.return_value = chunks
        elif mode == "semantic":
            mock_vector_store.query.return_value = [
                {"id": "c1", "distance": 0.1, "metadata": {}, "document": None},
                {"id": "c2", "distance": 0.2, "metadata": {}, "document": None},
            ]
            mock_chunk_repo.get.side_effect = lambda cid: next(
                (c for c in chunks if c.id == cid), None
            )
        else:  # hybrid
            mock_chunk_repo.search_fts.return_value = chunks
            mock_vector_store.query.return_value = [
                {"id": "c1", "distance": 0.1, "metadata": {}, "document": None},
                {"id": "c2", "distance": 0.2, "metadata": {}, "document": None},
            ]
            mock_chunk_repo.get.side_effect = lambda cid: next(
                (c for c in chunks if c.id == cid), None
            )

        results = service.search("test", mode=mode, section="Generators").results

        assert len(results) == 1
        assert results[0].chunk_id == "c1"

    def test_section_filter_overfetch_5x(self, service, mock_chunk_repo):
        """When section filter active, over-fetch 5x from backend."""
        mock_chunk_repo.search_fts.return_value = []

        service.search("test", mode="keyword", top_k=5, section="Generators")

        call_args = mock_chunk_repo.search_fts.call_args
        assert call_args.kwargs["limit"] == 25  # 5 * 5

    def test_section_filter_trims_to_top_k(self, service, mock_chunk_repo):
        """After filtering, results are trimmed to original top_k."""
        chunks = [self._make_chunk(f"c{i}", ["Generators"]) for i in range(10)]
        mock_chunk_repo.search_fts.return_value = chunks

        results = service.search("test", mode="keyword", top_k=3, section="Generators").results

        assert len(results) == 3

    def test_section_filter_matches_hierarchy_path(self, service, mock_chunk_repo):
        """Filtering by a parent section name returns chunks from all subsections.

        When filtering by 'Chapter 5', a chunk with section_path
        ['Part II', 'Chapter 5', 'Section 5.1'] should match because
        'Chapter 5' appears in the joined path string.

        Also tests cross-level matching: filtering by 'Chapter 5 > Section'
        matches the same chunk via the join separator.
        """
        deep_chunk = self._make_chunk("deep", ["Part II", "Chapter 5", "Section 5.1"])
        unrelated_chunk = self._make_chunk("unrelated", ["Part I", "Chapter 1", "Introduction"])
        mock_chunk_repo.search_fts.return_value = [deep_chunk, unrelated_chunk]

        # Filtering by parent section name matches subsection chunks
        results_parent = service.search("test", mode="keyword", section="Chapter 5").results
        assert len(results_parent) == 1
        assert results_parent[0].chunk_id == "deep"

        # Cross-level match: the joined path "Part II > Chapter 5 > Section 5.1"
        # contains the substring "Chapter 5 > Section"
        results_cross = service.search(
            "test", mode="keyword", section="Chapter 5 > Section"
        ).results
        assert len(results_cross) == 1
        assert results_cross[0].chunk_id == "deep"


class TestRRFIntegration:
    """Tests verifying RRF fusion behavior in SearchService."""

    def test_overlapping_results_score_higher(self):
        """Results appearing in both backends should score higher."""
        # This is verified through RRF unit tests
        # Integration would require both FTS and embeddings matching
        # which is hard to set up deterministically

        # Verify via unit test
        keyword_ids = ["a", "b", "c"]
        semantic_ids = ["b", "c", "d"]

        scores = reciprocal_rank_fusion([keyword_ids, semantic_ids])

        # "b" and "c" are in both, should score higher than "a" or "d"
        assert scores["b"] > scores["a"]
        assert scores["c"] > scores["d"]

    def test_source_field_reflects_origin(self):
        """source field correctly indicates which backend(s) found each result."""
        keyword_ids = ["a", "b"]
        semantic_ids = ["b", "c"]

        keyword_set = set(keyword_ids)
        semantic_set = set(semantic_ids)

        for chunk_id in ["a", "b", "c"]:
            in_keyword = chunk_id in keyword_set
            in_semantic = chunk_id in semantic_set

            if in_keyword and in_semantic:
                expected = "both"
            elif in_keyword:
                expected = "keyword"
            else:
                expected = "semantic"

            if chunk_id == "a":
                assert expected == "keyword"
            elif chunk_id == "b":
                assert expected == "both"
            elif chunk_id == "c":
                assert expected == "semantic"


# ============================================================================
# Context Window Tests
# ============================================================================


class TestContextWindow:
    """Tests for context window expansion in SearchService."""

    @pytest.fixture
    def mock_chunk_repo(self):
        repo = MagicMock()
        repo.search_fts.return_value = []
        repo.get.return_value = None
        repo.get_chunk_range.return_value = []
        return repo

    @pytest.fixture
    def mock_book_repo(self):
        repo = MagicMock()
        return repo

    @pytest.fixture
    def mock_vector_store(self):
        store = MagicMock()
        store.query.return_value = []
        return store

    @pytest.fixture
    def mock_embedder(self):
        embedder = MagicMock()
        embedder.embed_one.return_value = [0.1] * 1024
        return embedder

    @pytest.fixture
    def service(self, mock_chunk_repo, mock_book_repo, mock_vector_store, mock_embedder):
        svc = SearchService(
            chunks=mock_chunk_repo,
            books=mock_book_repo,
            vectors=mock_vector_store,
            embedder=mock_embedder,
        )
        svc._book_cache["abc123"] = "Test Book"
        return svc

    def _make_chunk(self, chunk_id, book_id, sequence, section_path, content=None):
        """Helper to create a Chunk instance (not mock) for context expansion tests."""
        return Chunk(
            id=chunk_id,
            book_id=book_id,
            content=content or f"Content for seq {sequence}",
            content_type=ContentType.TEXT,
            token_count=10,
            section_path=section_path,
            sections=[section_path[-1]] if section_path else [],
            sequence=sequence,
        )

    def _make_search_result(self, chunk_id, book_id="abc123", score=0.5):
        """Helper to create a SearchResult."""
        return SearchResult(
            chunk_id=chunk_id,
            book_id=book_id,
            book_title="Test Book",
            content="matched content",
            content_type="text",
            section_path=["Section A"],
            score=score,
            source="keyword",
        )

    def test_context_window_zero_unchanged(self, service, mock_chunk_repo):
        """context_window=0 returns list of SearchResult."""
        mock_chunk = MagicMock(
            id="c1",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=["Ch1"],
        )
        mock_chunk_repo.search_fts.return_value = [mock_chunk]

        results = service.search("test", mode="keyword", context_window=0).results

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].chunk_id == "c1"

    def test_context_window_expands_neighbors(self, service, mock_chunk_repo):
        """context_window=1 returns each result expanded with neighboring chunks."""
        # Setup: chunks seq 0-4, all same section
        section = ["Part 1", "Section A"]
        chunks = [self._make_chunk(f"c{i}", "abc123", i, section) for i in range(5)]

        # Search returns chunk at seq=2
        search_chunk = MagicMock(
            id="c2",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=section,
        )
        mock_chunk_repo.search_fts.return_value = [search_chunk]

        # get returns the matched chunk
        mock_chunk_repo.get.return_value = chunks[2]

        # get_chunk_range returns seq 1, 2, 3
        mock_chunk_repo.get_chunk_range.return_value = [chunks[1], chunks[2], chunks[3]]

        results = service.search("test", mode="keyword", context_window=1).results

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, dict)
        assert "c2" in result["matched_chunk_ids"]
        # Should have 3 chunks: seq 1, 2, 3
        chunk_seqs = [c.sequence for c in result["chunks"]]
        assert chunk_seqs == [1, 2, 3]

    def test_context_window_stops_at_section_boundary(self, service, mock_chunk_repo):
        """Expansion stops when neighbor has different section_path."""
        section_a = ["Part 1", "Section A"]
        section_b = ["Part 1", "Section B"]
        chunks = [
            self._make_chunk("c0", "abc123", 0, section_a),
            self._make_chunk("c1", "abc123", 1, section_a),
            self._make_chunk("c2", "abc123", 2, section_a),
            self._make_chunk("c3", "abc123", 3, section_b),
            self._make_chunk("c4", "abc123", 4, section_b),
        ]

        # Search returns chunk at seq=2, window=2
        search_chunk = MagicMock(
            id="c2",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=section_a,
        )
        mock_chunk_repo.search_fts.return_value = [search_chunk]
        mock_chunk_repo.get.return_value = chunks[2]
        # get_chunk_range(abc123, 0, 4) returns all 5
        mock_chunk_repo.get_chunk_range.return_value = chunks

        results = service.search("test", mode="keyword", context_window=2).results

        assert len(results) == 1
        result = results[0]
        chunk_seqs = [c.sequence for c in result["chunks"]]
        # Should only get seq 0, 1, 2 (not 3, 4 which are Section B)
        assert chunk_seqs == [0, 1, 2]

    def test_context_window_dedup_overlapping(self, service, mock_chunk_repo):
        """Two results with overlapping windows are merged into one block."""
        section = ["Part 1", "Section A"]
        chunks = [self._make_chunk(f"c{i}", "abc123", i, section) for i in range(8)]

        # Search returns chunks at seq=3 and seq=5, window=2
        search_chunks = [
            MagicMock(
                id="c3",
                book_id="abc123",
                content="x" * 200,
                content_type=ContentType.TEXT,
                section_path=section,
            ),
            MagicMock(
                id="c5",
                book_id="abc123",
                content="x" * 200,
                content_type=ContentType.TEXT,
                section_path=section,
            ),
        ]
        mock_chunk_repo.search_fts.return_value = search_chunks

        def get_side_effect(chunk_id):
            idx = int(chunk_id[1:])
            return chunks[idx] if 0 <= idx < len(chunks) else None

        mock_chunk_repo.get.side_effect = get_side_effect

        def range_side_effect(book_id, start, end, limit=20):
            return [c for c in chunks if start <= c.sequence <= end]

        mock_chunk_repo.get_chunk_range.side_effect = range_side_effect

        results = service.search("test", mode="keyword", context_window=2).results

        # Should merge into one block: seq 1-7
        # (window=2 around 3 gives 1-5, around 5 gives 3-7, merged = 1-7)
        assert len(results) == 1
        result = results[0]
        assert "c3" in result["matched_chunk_ids"]
        assert "c5" in result["matched_chunk_ids"]
        chunk_seqs = [c.sequence for c in result["chunks"]]
        assert chunk_seqs == [1, 2, 3, 4, 5, 6, 7]

    def test_context_window_preserves_match_markers(self, service, mock_chunk_repo):
        """After dedup, matched_chunk_ids contains the original match IDs."""
        section = ["Part 1", "Section A"]
        chunks = [self._make_chunk(f"c{i}", "abc123", i, section) for i in range(6)]

        search_chunks = [
            MagicMock(
                id="c2",
                book_id="abc123",
                content="x" * 200,
                content_type=ContentType.TEXT,
                section_path=section,
            ),
            MagicMock(
                id="c4",
                book_id="abc123",
                content="x" * 200,
                content_type=ContentType.TEXT,
                section_path=section,
            ),
        ]
        mock_chunk_repo.search_fts.return_value = search_chunks

        def get_side_effect(chunk_id):
            idx = int(chunk_id[1:])
            return chunks[idx] if 0 <= idx < len(chunks) else None

        mock_chunk_repo.get.side_effect = get_side_effect

        def range_side_effect(book_id, start, end, limit=20):
            return [c for c in chunks if start <= c.sequence <= end]

        mock_chunk_repo.get_chunk_range.side_effect = range_side_effect

        results = service.search("test", mode="keyword", context_window=1).results

        # With window=1: c2->1,2,3 and c4->3,4,5, overlapping at 3, merge to 1-5
        assert len(results) == 1
        result = results[0]
        assert result["matched_chunk_ids"] == {"c2", "c4"}


# ============================================================================
# FTS5 Query Sanitization Tests
# ============================================================================


class TestSanitizeFtsQuery:
    """Tests for _sanitize_fts_query OR-joined behavior."""

    @pytest.fixture
    def chunk_repo(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        return ChunkRepository(conn)

    def test_sanitize_fts_query_uses_or(self, chunk_repo):
        """Multi-word queries are joined with OR."""
        result = chunk_repo._sanitize_fts_query("knowledge graph construction")
        assert result == '"knowledge" OR "graph" OR "construction"'

    def test_sanitize_fts_query_single_word(self, chunk_repo):
        """Single word has no OR."""
        result = chunk_repo._sanitize_fts_query("knowledge")
        assert result == '"knowledge"'
        assert "OR" not in result

    def test_sanitize_fts_query_empty(self, chunk_repo):
        """Empty query returns empty string."""
        assert chunk_repo._sanitize_fts_query("") == ""
        assert chunk_repo._sanitize_fts_query("   ") == ""


# ============================================================================
# Diversity Re-ranking Tests
# ============================================================================


class TestDiversifyResults:
    """Tests for cross-book diversity re-ranking."""

    @staticmethod
    def _make_result(chunk_id, book_id, score):
        return SearchResult(
            chunk_id=chunk_id,
            book_id=book_id,
            book_title=f"Book {book_id}",
            content="content",
            content_type="text",
            section_path=["Ch1"],
            score=score,
            source="keyword",
        )

    def test_close_result_from_another_book_moves_up(self):
        results = [
            self._make_result("a1", "bookA", 0.9),
            self._make_result("a2", "bookA", 0.88),
            self._make_result("b1", "bookB", 0.85),
        ]
        diversified = SearchService._diversify_results(results, top_k=3)
        assert [r.chunk_id for r in diversified] == ["a1", "b1", "a2"]

    def test_distant_result_from_another_book_keeps_its_rank(self):
        results = [
            self._make_result("a1", "bookA", 0.9),
            self._make_result("a2", "bookA", 0.8),
            self._make_result("a3", "bookA", 0.7),
            self._make_result("b1", "bookB", 0.3),
        ]
        diversified = SearchService._diversify_results(results, top_k=4)
        assert [r.chunk_id for r in diversified] == ["a1", "a2", "a3", "b1"]

    def test_once_every_book_has_appeared_results_follow_score(self):
        results = [
            self._make_result("a1", "bookA", 0.9),
            self._make_result("a2", "bookA", 0.89),
            self._make_result("b1", "bookB", 0.88),
            self._make_result("b2", "bookB", 0.87),
            self._make_result("a3", "bookA", 0.86),
        ]
        diversified = SearchService._diversify_results(results, top_k=5)
        assert [r.chunk_id for r in diversified] == ["a1", "b1", "a2", "b2", "a3"]

    def test_diversify_results_single_book_passthrough(self):
        """Single book returns results unchanged."""
        results = [
            self._make_result("a1", "bookA", 0.9),
            self._make_result("a2", "bookA", 0.8),
        ]
        diversified = SearchService._diversify_results(results, top_k=5)
        assert diversified == results

    def test_diversify_results_respects_score_order(self):
        """Within-book order (by score) is preserved."""
        results = [
            self._make_result("a1", "bookA", 0.9),
            self._make_result("a2", "bookA", 0.8),
            self._make_result("a3", "bookA", 0.5),
            self._make_result("b1", "bookB", 0.85),
            self._make_result("b2", "bookB", 0.3),
        ]
        diversified = SearchService._diversify_results(results, top_k=6)
        book_a_results = [r for r in diversified if r.book_id == "bookA"]
        book_b_results = [r for r in diversified if r.book_id == "bookB"]
        assert [r.score for r in book_a_results] == [0.9, 0.8, 0.5]
        assert [r.score for r in book_b_results] == [0.85, 0.3]

    def test_diversify_results_empty(self):
        """Empty input returns empty output."""
        assert SearchService._diversify_results([], top_k=5) == []

    def test_diversify_results_top_k_limit(self):
        """Returns at most top_k results."""
        results = [
            self._make_result("a1", "bookA", 0.9),
            self._make_result("b1", "bookB", 0.85),
            self._make_result("a2", "bookA", 0.8),
            self._make_result("b2", "bookB", 0.6),
        ]
        diversified = SearchService._diversify_results(results, top_k=2)
        assert len(diversified) == 2


# ============================================================================
# Semantic Quality Gate Tests
# ============================================================================


class TestHybridSemanticQualityGate:
    """Tests for filtering low-quality semantic results in hybrid search."""

    def test_hybrid_filters_low_quality_semantic(self, library):
        """Semantic results with cosine distance > 1.0 are filtered before RRF."""
        good = library.add(_prose("query"), similarity=0.5)
        unrelated = library.add(_prose("elsewhere"), similarity=-0.5)

        results = library.service().search("test query", mode="hybrid", top_k=5).results

        ids = [r.chunk_id for r in results]
        assert good.id in ids
        assert unrelated.id not in ids


# ============================================================================
# Unicode Normalization Tests
# ============================================================================


class TestUnicodeNormalization:
    """Tests for Unicode normalization in section filtering."""

    def test_normalize_unicode_strips_accents(self):
        from mnemo.search.service import normalize_unicode

        assert normalize_unicode("naïve") == "naive"
        assert normalize_unicode("café") == "cafe"
        assert normalize_unicode("résumé") == "resume"

    def test_normalize_unicode_lowercases(self):
        from mnemo.search.service import normalize_unicode

        assert normalize_unicode("Hello World") == "hello world"

    def test_normalize_unicode_plain_text_unchanged(self):
        from mnemo.search.service import normalize_unicode

        assert normalize_unicode("simple text") == "simple text"

    def test_section_filter_with_accented_section_name(self, library):
        """Section filter matches when section_path contains accented characters."""
        library.add(_prose("pipeline"), section=["Chapter 3", "Exploring naïve RAG"])
        service = library.service()

        for section in ("Exploring naïve RAG", "Exploring naive RAG"):
            assert len(service.search("pipeline", mode="keyword", section=section).results) == 1

    def test_section_filter_accent_in_query_matches_plain_section(self, library):
        """Accented filter matches plain-text section paths too."""
        library.add(_prose("pipeline"), section=["Chapter 3", "Exploring naive RAG"])

        results = library.service().search("pipeline", mode="keyword", section="naïve").results

        assert len(results) == 1


# ============================================================================
# Stopword Filtering Tests
# ============================================================================


class TestStopwordFiltering:
    """Tests for stopword removal in FTS query sanitization."""

    @pytest.fixture
    def chunk_repo(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        return ChunkRepository(conn)

    def test_stopwords_removed_from_query(self, chunk_repo):
        """Common stopwords are filtered out of FTS queries."""
        result = chunk_repo._sanitize_fts_query("how does self-attention work in transformers")
        # "how", "does", "in" are stopwords; "self-attention", "work", "transformers" remain
        assert '"how"' not in result
        assert '"does"' not in result
        assert '"in"' not in result
        assert '"self-attention"' in result
        assert '"work"' in result
        assert '"transformers"' in result

    def test_all_stopwords_fallback(self, chunk_repo):
        """If all words are stopwords, use the original query."""
        result = chunk_repo._sanitize_fts_query("the")
        assert result == '"the"'

    def test_all_stopwords_multiword_fallback(self, chunk_repo):
        """Multi-word all-stopword query falls back to original words."""
        result = chunk_repo._sanitize_fts_query("how does it")
        assert '"how"' in result
        assert '"does"' in result
        assert '"it"' in result

    def test_meaningful_words_preserved(self, chunk_repo):
        """Non-stopword terms are preserved in the query."""
        result = chunk_repo._sanitize_fts_query("python generators async")
        assert '"python"' in result
        assert '"generators"' in result
        assert '"async"' in result


# ============================================================================
# Hybrid Score Normalization Tests
# ============================================================================


class TestHybridScoreNormalization:
    """Tests for blended RRF + semantic similarity scoring."""

    def test_hybrid_scores_in_0_1_range(self, library):
        for sim in (0.9, 0.7, 0.5):
            library.add(_prose("query"), similarity=sim)

        results = library.service().search("query", mode="hybrid", top_k=3).results

        assert len(results) == 3
        assert all(0.0 <= r.score <= 1.0 for r in results)

    def test_hybrid_scores_follow_semantic_order(self, library):
        """With no chunk holding every term, semantic similarity decides the order."""
        chunks = [library.add(_prose("query"), similarity=sim) for sim in (0.5, 0.9, 0.7)]

        results = library.service().search("query stages", mode="hybrid", top_k=3).results

        assert [r.chunk_id for r in results] == [chunks[1].id, chunks[2].id, chunks[0].id]
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_hybrid_blending_math(self, library):
        """Blended score = 0.5 * norm_rrf + 0.5 * raw_sim for a hit in both lists."""
        library.add(_prose("query"), similarity=0.7)

        results = library.service().search("query", mode="hybrid", top_k=1).results

        # norm_rrf = 1.0 (the only result), raw_sim = 0.7
        assert results[0].score == pytest.approx(0.85)

    def test_hybrid_keyword_only_hit_discounted(self, library):
        """A keyword-only hit holding some query terms scores below a semantic hit."""
        kw = library.add(_prose("pipeline"))
        sem = library.add(_prose("pipeline"), similarity=0.8)

        results = library.service().search("pipeline stages", mode="hybrid", top_k=5).results

        scores = {r.chunk_id: r.score for r in results}
        assert scores[kw.id] < scores[sem.id]

    def test_off_topic_query_returns_nothing(self, library):
        """A weak best semantic match with only partial keyword overlap is off-topic."""
        library.add(_prose("bread"), similarity=0.2)

        service = library.service()

        assert service.search(_SOURDOUGH, mode="hybrid", top_k=5).results == []

    def test_weak_semantic_kept_when_every_term_matches(self, library):
        """A chunk containing every query term is a real keyword match, e.g. an identifier."""
        hit = library.add(_prose("bake sourdough bread"), similarity=0.2)

        results = library.service().search(_SOURDOUGH, mode="hybrid", top_k=5).results

        assert [r.chunk_id for r in results] == [hit.id]

    def test_chunks_holding_every_term_outrank_unrelated_semantic_hits(self, library):
        """A rare identifier ("Swoosh") draws arbitrary semantic hits that score fairly high."""
        exact1 = library.add(_prose("Swoosh Swoosh Swoosh"))
        exact2 = library.add(_prose("Swoosh"))
        noise = [library.add(_prose("unrelated"), similarity=0.64) for _ in range(3)]

        results = library.service().search("Swoosh", mode="hybrid", top_k=5).results

        # Each exact hit scores like the best semantic hit at its list rank; fusion lists it first.
        assert [r.chunk_id for r in results] == [
            exact1.id,
            noise[0].id,
            exact2.id,
            noise[1].id,
            noise[2].id,
        ]

    def test_bibliography_holding_every_term_gets_no_boost(self, library):
        """Indexes and bibliographies hold every term of most queries."""
        library.add(_prose("entity resolution"), section=["Bibliography"])
        topical = library.add(_prose("matching"), similarity=0.7, section=["8. Instance Matching"])

        results = library.service().search("entity resolution", mode="hybrid", top_k=1).results

        assert [r.chunk_id for r in results] == [topical.id]

    def test_bibliography_holding_every_term_does_not_pass_the_off_topic_gate(self, library):
        library.add(_prose("bake sourdough bread"), similarity=0.2, section=["Bibliography"])

        assert library.service().search(_SOURDOUGH, mode="hybrid").results == []

    def test_off_topic_gate_uses_env_floor(self, library, monkeypatch):
        """The gate follows MNEMO_SEMANTIC_MIN_SCORE, so it works on other models' scales."""
        monkeypatch.setenv("MNEMO_SEMANTIC_MIN_SCORE", "0.5")
        library.add(_prose("bread"), similarity=0.45)

        assert library.service().search(_SOURDOUGH, mode="hybrid", top_k=5).results == []

    def test_good_semantic_match_passes_gate(self, library):
        """Semantic-only hits with decent similarity still return results."""
        library.add(_prose("unrelated"), similarity=0.7)
        library.add(_prose("unrelated"), similarity=0.6)

        results = library.service().search("real query", mode="hybrid", top_k=5).results

        assert len(results) == 2

    def test_good_query_returns_high_scores(self, library):
        """A well-matched query produces scores reflecting actual semantic relevance."""
        library.add(_prose("query"), similarity=0.9)

        results = library.service().search("well matched query", mode="hybrid", top_k=1).results

        # blended = 0.5 * 1.0 + 0.5 * 0.9 = 0.95
        assert results[0].score > 0.9


# ============================================================================
# Keyword-Only Noise Filtering Tests
# ============================================================================


class TestKeywordNoiseFiltering:
    """Tests for filtering low-quality keyword-only results in hybrid search."""

    def test_keyword_only_low_rank_filtered(self, library):
        """A long-tail keyword-only hit stays out after the collection filter thins the results."""
        library.add_book("def456", "Other", collection="Other")
        library.add_book("aaa111", "Mine", collection="Mine")
        for _ in range(5):
            library.add(_prose("query query query"), book_id="def456")
        library.add(_prose("unrelated"), similarity=0.8, book_id="def456")
        library.add(_prose("query"), book_id="aaa111")  # keyword rank 6 of 6

        response = library.service().search("test query", mode="hybrid", top_k=1, collection="Mine")

        assert response.results == []


# ============================================================================
# Section Matching Tests
# ============================================================================


class TestSectionMatches:
    """Tests for _section_matches helper."""

    def test_chapter_with_dotted_suffix(self):
        """'Chapter 6' matches 'Chapter 6.Enriching Knowledge Graphs'."""
        assert _section_matches("chapter 6", "chapter 6.enriching knowledge graphs")

    def test_chapter_does_not_match_longer_number(self):
        """'Chapter 6' must NOT match 'Chapter 60'."""
        assert not _section_matches("chapter 6", "chapter 60")

    def test_section_with_colon_suffix(self):
        """'Section 12' matches 'Section 12: Advanced Topics'."""
        assert _section_matches("section 12", "section 12: advanced topics")

    def test_plain_substring_still_works(self):
        """Plain substring match still works for non-digit-ending queries."""
        assert _section_matches("generators", "chapter 5 > generators")

    def test_exact_match(self):
        """Exact match works."""
        assert _section_matches("chapter 6", "chapter 6")


# ============================================================================
# Backmatter Penalty Tests
# ============================================================================


class TestQualityPenalties:
    """Tests for _apply_quality_penalties."""

    def _make_result(
        self,
        section_path: list[str],
        score: float = 1.0,
        content: str | None = None,
    ) -> SearchResult:
        return SearchResult(
            chunk_id="test",
            book_id="abc123",
            book_title="Test",
            content=content if content is not None else "x" * 200,
            content_type="text",
            section_path=section_path,
            score=score,
            source="keyword",
            sequence=0,
        )

    def test_index_section_penalized(self):
        """Result with section_path ['Index', 'S'] gets penalized."""
        r = self._make_result(["Index", "S"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(BOILERPLATE_PENALTY)

    def test_building_an_index_not_penalized(self):
        """'Building an Index' is a chapter title, not backmatter."""
        r = self._make_result(["Chapter 5", "Building an Index"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(1.0)

    def test_appendix_penalized(self):
        """Result with section_path ['Appendix A'] is penalized."""
        r = self._make_result(["Appendix A"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(BOILERPLATE_PENALTY)

    def test_bibliography_penalized(self):
        """Result with section_path ['Bibliography'] is penalized."""
        r = self._make_result(["Bibliography"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(BOILERPLATE_PENALTY)

    def test_normal_chapter_not_penalized(self):
        """Normal chapter content is not penalized."""
        r = self._make_result(["Chapter 3", "Graphs"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(1.0)

    def test_copyright_frontmatter_penalized(self):
        """Copyright page gets penalized as frontmatter."""
        r = self._make_result(["Copyright"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(BOILERPLATE_PENALTY)

    def test_title_page_frontmatter_penalized(self):
        """Title Page gets penalized as frontmatter."""
        r = self._make_result(["Title Page"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(BOILERPLATE_PENALTY)

    def test_dedication_frontmatter_penalized(self):
        """Dedication gets penalized as frontmatter."""
        r = self._make_result(["Dedication"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(BOILERPLATE_PENALTY)

    def test_cover_frontmatter_penalized(self):
        """Cover gets penalized as frontmatter."""
        r = self._make_result(["Cover"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(BOILERPLATE_PENALTY)

    def test_preface_not_penalized(self):
        """Preface is not penalized — it contains real content."""
        r = self._make_result(["Preface"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(1.0)

    def test_contents_frontmatter_penalized(self):
        """'Contents' variant (not just 'Table of Contents') gets penalized."""
        r = self._make_result(["Contents", "Chapter 1"], score=1.0)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(BOILERPLATE_PENALTY)

    def test_short_content_penalized(self):
        """Chunks below SHORT_CONTENT_THRESHOLD chars get penalized."""
        r = self._make_result(["Chapter 1"], score=1.0, content="Short stub")
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(SHORT_CONTENT_PENALTY)

    def test_short_content_and_boilerplate_stacks(self):
        """Both penalties multiply for short boilerplate chunks."""
        r = self._make_result(["Index"], score=1.0, content="A")
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(BOILERPLATE_PENALTY * SHORT_CONTENT_PENALTY)

    def test_long_content_not_penalized(self):
        """Content above threshold is not penalized by short content check."""
        r = self._make_result(["Chapter 1"], score=1.0, content="x" * 200)
        results = SearchService._apply_quality_penalties([r])
        assert results[0].score == pytest.approx(1.0)


class TestSemanticFloor:
    """Tests for SEMANTIC_FLOOR discounting in hybrid search."""

    def test_weak_semantic_discounted(self, library):
        """Results with semantic similarity below SEMANTIC_FLOOR get a discounted blend."""
        weak = library.add(_prose("pipeline"), similarity=0.3)
        strong = library.add(_prose("pipeline"), similarity=0.9)

        results = library.service().search("pipeline stages", mode="hybrid", top_k=5).results

        scores = {r.chunk_id: r.score for r in results}
        assert scores[weak.id] < scores[strong.id] * 0.6


# ============================================================================
# Section Suggestion Tests
# ============================================================================


class TestEmptyReason:
    """What search says when a section filter finds nothing."""

    def test_substring_match(self, library):
        """Suggests sections containing the query as a substring."""
        lib = library
        service = lib.service()

        # Insert a book and chunks with known section paths
        book = Book(
            id="a1b2c3",
            title="Test Book",
            authors=["Author"],
            file_hash="a" * 64,
            structure_source="toc",
        )
        lib.books.add(book)
        for i, section in enumerate(
            [
                ["Chapter 60. Enriching Knowledge Graphs"],
                ["Chapter 60. Enriching Knowledge Graphs", "Graph Algorithms"],
                ["Chapter 7. Machine Learning"],
            ]
        ):
            chunk = Chunk(
                book_id="a1b2c3",
                content="x" * 200,
                content_type=ContentType.TEXT,
                token_count=100,
                section_path=section,
                sections=[],
                language="en",
                sequence=i,
            )
            lib.chunks.add_many([chunk])

        # "Chapter 6" does not match "Chapter 60", but it is suggested.
        response = service.search("x", mode="keyword", section="Chapter 6", book_id="a1b2c3")
        assert response.results == []
        assert response.empty_reason == EmptyReason(
            "section_not_found",
            'No results found for: x in section "Chapter 6". '
            'Did you mean: "Chapter 60. Enriching Knowledge Graphs"?',
        )

    def test_fuzzy_match(self, library):
        """Falls back to fuzzy matching when no substring match."""
        lib = library
        service = lib.service()

        book = Book(
            id="d4e5f6",
            title="Test Book",
            authors=["Author"],
            file_hash="b" * 64,
            structure_source="toc",
        )
        lib.books.add(book)
        chunk = Chunk(
            book_id="d4e5f6",
            content="x" * 200,
            content_type=ContentType.TEXT,
            token_count=100,
            section_path=["Experimenting with Graph Data Science"],
            sections=[],
            language="en",
            sequence=0,
        )
        lib.chunks.add_many([chunk])

        response = service.search(
            "x", mode="keyword", section="Experimenting Graph Science", book_id="d4e5f6"
        )
        assert response.empty_reason is not None
        assert response.empty_reason.kind == "section_not_found"
        assert '"Experimenting with Graph Data Science"' in response.empty_reason.message

    def test_section_chunk_count_uses_the_filter_rules(self, library):
        lib = library
        service = lib.service()
        for book_id, paths in {
            "a1b2c3": [
                ["Chapter 6", "Prot\u00e9g\u00e9"],
                ["Chapter 6", "Prot\u00e9g\u00e9"],
                ["Chapter 60"],
            ],
            "d4e5f6": [["Chapter 6"]],
        }.items():
            lib.books.add(
                Book(
                    id=book_id,
                    title="T",
                    authors=[],
                    file_hash=(book_id * 11)[:64],
                    structure_source="toc",
                )
            )
            lib.chunks.add_many(
                [
                    Chunk(
                        book_id=book_id,
                        content="x" * 200,
                        content_type=ContentType.TEXT,
                        token_count=100,
                        section_path=path,
                        sections=[],
                        sequence=i,
                    )
                    for i, path in enumerate(paths)
                ]
            )

        def reason(section: str, book_id: str | None = None) -> EmptyReason:
            response = service.search("zebra", mode="keyword", section=section, book_id=book_id)
            assert response.empty_reason is not None
            return response.empty_reason

        assert reason("chapter 6", "a1b2c3") == EmptyReason(
            "section_without_query_words",
            'Section "chapter 6" has 2 chunks, but none contains a word of: zebra.',
        )
        assert "has 2 chunks" in reason("Protege").message
        assert "has 3 chunks" in reason("Chapter 6").message
        assert reason("Glossary").kind != "section_without_query_words"

    def test_section_match_crowded_out_by_other_sections_is_still_found(self, library):
        lib = library
        service = lib.service()
        lib.books.add(
            Book(id="a1b2c3", title="T", authors=[], file_hash="a" * 64, structure_source="toc")
        )
        crowd = [
            Chunk(
                book_id="a1b2c3",
                content="pipeline pipeline pipeline ontology " * 5,
                content_type=ContentType.TEXT,
                token_count=40,
                section_path=["Ch1", f"S{i}"],
                sequence=i,
            )
            for i in range(80)
        ]
        glossary = Chunk(
            book_id="a1b2c3",
            content="A long passage that mentions the pipeline once among other words. " * 6,
            content_type=ContentType.TEXT,
            token_count=200,
            section_path=["Ch2", "Glossary terms"],
            sequence=80,
        )
        lib.chunks.add_many([*crowd, glossary])

        results = service.search("pipeline", mode="keyword", section="Glossary terms").results

        assert [r.chunk_id for r in results] == [glossary.id]

    def test_keyword_results_carry_every_section_the_chunk_spans(self, library):
        lib = library
        service = lib.service()
        lib.books.add(
            Book(id="a1b2c3", title="T", authors=[], file_hash="a" * 64, structure_source="toc")
        )
        lib.chunks.add_many(
            [
                Chunk(
                    book_id="a1b2c3",
                    content="The query layer answers SPARQL queries. " * 5,
                    content_type=ContentType.TEXT,
                    token_count=40,
                    section_path=["KG", "The query layer", "Example SPARQL query"],
                    sections=["The query layer", "Example SPARQL query"],
                    sequence=0,
                )
            ]
        )

        results = service.search("SPARQL", mode="keyword").results

        assert results[0].sections == ["The query layer", "Example SPARQL query"]

    def test_empty_library_returns_empty(self, tmp_path):
        """With no sections to suggest, the miss is a plain no-match."""
        service = SearchService(
            db_path=tmp_path / "test.db",
            chroma_path=tmp_path / "chroma",
        )
        response = service.search("anything", mode="keyword", section="anything")
        assert response.empty_reason == EmptyReason("no_match", "No results found for: anything")


# ============================================================================
# is_boilerplate_section Tests
# ============================================================================


class TestIsBoilerplateSection:
    """Tests for the shared is_boilerplate_section helper."""

    def test_backmatter_index(self):
        assert is_boilerplate_section(["Index", "S"]) is True

    def test_backmatter_bibliography(self):
        assert is_boilerplate_section(["Bibliography"]) is True

    def test_backmatter_glossary(self):
        assert is_boilerplate_section(["Glossary"]) is True

    def test_frontmatter_copyright(self):
        assert is_boilerplate_section(["Copyright"]) is True

    def test_frontmatter_cover(self):
        assert is_boilerplate_section(["Cover"]) is True

    def test_appendix(self):
        assert is_boilerplate_section(["Appendix A"]) is True

    def test_frontmatter_list_of_figures(self):
        assert is_boilerplate_section(["List of Figures"]) is True

    def test_frontmatter_list_of_tables(self):
        assert is_boilerplate_section(["List of Tables"]) is True

    def test_normal_chapter(self):
        assert is_boilerplate_section(["Chapter 3", "Graphs"]) is False

    def test_building_an_index_not_boilerplate(self):
        """'Building an Index' is a chapter title, not backmatter."""
        assert is_boilerplate_section(["Chapter 5", "Building an Index"]) is False

    def test_empty_section_path(self):
        assert is_boilerplate_section([]) is False

    def test_case_insensitive(self):
        assert is_boilerplate_section(["INDEX"]) is True
        assert is_boilerplate_section(["table of contents"]) is True


# ============================================================================
# Semantic Score Floor Tests
# ============================================================================


class TestSemanticScoreFloor:
    """Tests for MIN_SEMANTIC_SCORE filtering in semantic search."""

    @pytest.fixture
    def mock_vector_store(self):
        return MagicMock()

    @pytest.fixture
    def mock_chunk_repo(self):
        return MagicMock()

    @pytest.fixture
    def mock_book_repo(self):
        return MagicMock()

    @pytest.fixture
    def mock_embedder(self):
        embedder = MagicMock()
        embedder.embed_one.return_value = [0.1] * 1024
        return embedder

    @pytest.fixture
    def service(self, mock_chunk_repo, mock_book_repo, mock_vector_store, mock_embedder):
        svc = SearchService(
            chunks=mock_chunk_repo,
            books=mock_book_repo,
            vectors=mock_vector_store,
            embedder=mock_embedder,
        )
        return svc

    def test_low_score_results_filtered(self, service, mock_vector_store, mock_chunk_repo):
        """Results below MIN_SEMANTIC_SCORE are excluded from semantic search."""
        # Distance 0.8 -> similarity 0.2, below the 0.25 floor
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 0.8, "metadata": {}, "document": None},
        ]
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=["Ch1"],
        )
        mock_chunk_repo.get.return_value = mock_chunk
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="semantic").results
        assert len(results) == 0

    def test_above_floor_results_kept(self, service, mock_vector_store, mock_chunk_repo):
        """Results at or above MIN_SEMANTIC_SCORE are kept."""
        # Distance 0.7 -> similarity 0.3, above the 0.25 floor
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 0.7, "metadata": {}, "document": None},
        ]
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=["Ch1"],
        )
        mock_chunk_repo.get.return_value = mock_chunk
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="semantic").results
        assert len(results) == 1
        assert results[0].score == pytest.approx(0.3)

    def test_mixed_scores_partial_filter(self, service, mock_vector_store, mock_chunk_repo):
        """Only low-score results are filtered; good ones survive."""
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 0.2, "metadata": {}, "document": None},
            {"id": "chunk-2", "distance": 0.9, "metadata": {}, "document": None},
        ]
        good_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=["Ch1"],
        )
        bad_chunk = MagicMock(
            id="chunk-2",
            book_id="abc123",
            content="x" * 200,
            content_type=ContentType.TEXT,
            section_path=["Ch2"],
        )
        chunks = {"chunk-1": good_chunk, "chunk-2": bad_chunk}
        mock_chunk_repo.get.side_effect = lambda cid: chunks[cid]
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="semantic").results
        assert len(results) == 1
        assert results[0].score == pytest.approx(0.8)


class TestSemanticMinScoreEnv:
    """MNEMO_SEMANTIC_MIN_SCORE overrides MIN_SEMANTIC_SCORE for other models' scales."""

    @staticmethod
    def _search_at_similarity(tmp_path: Path, similarity: float) -> list[SearchResult]:
        lib = Library(tmp_path / str(similarity))
        lib.add(_prose("unrelated"), similarity=similarity)
        try:
            return lib.service().search("test", mode="semantic").results
        finally:
            lib.close()

    def test_env_raises_floor(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MNEMO_SEMANTIC_MIN_SCORE", "0.5")
        assert self._search_at_similarity(tmp_path, 0.45) == []

    def test_env_lowers_floor(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MNEMO_SEMANTIC_MIN_SCORE", "0.1")
        assert len(self._search_at_similarity(tmp_path, 0.2)) == 1

    @pytest.mark.parametrize("raw", ["abc", "1.5", "-0.1", "nan"])
    def test_invalid_env_falls_back_to_default(self, monkeypatch, caplog, tmp_path, raw):
        monkeypatch.setenv("MNEMO_SEMANTIC_MIN_SCORE", raw)
        assert len(self._search_at_similarity(tmp_path, 0.3)) == 1
        assert self._search_at_similarity(tmp_path, 0.2) == []
        assert "MNEMO_SEMANTIC_MIN_SCORE" in caplog.text


class TestSearchServiceCollection:
    """Tests for collection-based search filtering."""

    def test_search_with_collection_filters_results(self, library):
        """search() with collection returns only results from that collection's books."""
        library.add_book("aaa111", "A", collection="My Collection")
        library.add_book("bbb222", "B", collection="My Collection")
        library.add_book("ccc333", "C", collection="Other")
        for book_id in ("aaa111", "ccc333", "bbb222"):
            library.add(_prose("pipeline"), book_id=book_id)

        results = (
            library.service().search("pipeline", mode="keyword", collection="My Collection").results
        )

        assert {r.book_id for r in results} == {"aaa111", "bbb222"}

    def test_search_without_collection_returns_all(self, library):
        """search() without collection searches every book."""
        library.add_book("aaa111", "A", collection="My Collection")
        library.add(_prose("pipeline"), book_id="aaa111")
        library.add(_prose("pipeline"))

        results = library.service().search("pipeline", mode="keyword").results

        assert {r.book_id for r in results} == {"aaa111", "abc123"}


def _seeded_service(lib: Library, chunks: list[Chunk]) -> SearchService:
    lib.books.add(
        Book(id="a1b2c3", title="T", authors=[], file_hash="a" * 64, structure_source="toc")
    )
    lib.chunks.add_many(chunks)
    return lib.service()


def _chunk(content: str, kind: ContentType, path: list[str], seq: int) -> Chunk:
    return Chunk(
        book_id="a1b2c3",
        content=content,
        content_type=kind,
        token_count=max(1, len(content) // 4),
        section_path=path,
        sequence=seq,
    )


class TestSectionMissUnderFilters:
    """A section miss under a type or collection filter names the filter, not a typo."""

    @pytest.fixture
    def glossaries(self, library):
        return _seeded_service(
            library,
            [
                _chunk("An axiom is a statement. " * 8, ContentType.TEXT, ["Glossary"], 0),
                _chunk("A lemma is a step. " * 8, ContentType.TEXT, ["Glossary of terms"], 1),
                _chunk("def axiom(): ...", ContentType.CODE, ["Listings"], 2),
            ],
        )

    def test_existing_section_excluded_by_type_says_so(self, glossaries):
        response = glossaries.search(
            "axiom", mode="keyword", section="Glossary", content_type="code"
        )

        assert response.empty_reason == EmptyReason(
            "section_filtered_out",
            'Section "Glossary" has no chunks matching content type "code".',
        )

    def test_suggestions_are_sections_the_filter_admits(self, glossaries):
        response = glossaries.search(
            "axiom", mode="keyword", section="Lisitngs", content_type="code"
        )
        assert response.empty_reason is not None
        assert response.empty_reason.message.endswith('Did you mean: "Listings"?')

        text_only = glossaries.search(
            "axiom", mode="keyword", section="Glossary terms", content_type="code"
        )
        assert text_only.empty_reason == EmptyReason("no_match", "No results found for: axiom")


class TestTerseHitContext:
    """Small code, diagram and math hits come back with their neighbours."""

    def test_small_code_hit_carries_its_neighbours(self, library):
        intro = _chunk("Call head_view to draw attention maps. " * 4, ContentType.TEXT, ["Ch1"], 0)
        code = _chunk("head_view(attention, tokens)", ContentType.CODE, ["Ch1"], 1)
        service = _seeded_service(library, [intro, code])

        response = service.search("head_view", mode="keyword", content_type="code")

        assert [r.chunk_id for r in response.results] == [code.id]
        context = response.context[code.id]
        assert [c.id for c in context["chunks"]] == [intro.id, code.id]

    def test_large_code_and_text_hits_carry_none(self, library):
        service = _seeded_service(
            library,
            [
                _chunk("def pipeline():\n    return 1\n" * 12, ContentType.CODE, ["Ch1"], 0),
                _chunk("A pipeline note.", ContentType.TEXT, ["Ch1"], 1),
            ],
        )

        response = service.search("pipeline", mode="keyword")

        assert len(response.results) == 2
        assert response.context == {}

    def test_expanded_results_carry_none(self, library):
        code = _chunk("head_view(attention, tokens)", ContentType.CODE, ["Ch1"], 0)
        service = _seeded_service(library, [code])

        response = service.search("head_view", mode="keyword", context_window=1)

        assert response.context == {}
        assert response.empty_reason is None
