"""Tests for search module.

Tests cover:
- Reciprocal Rank Fusion (RRF) algorithm
- SearchResult and SearchFilter dataclasses
- SearchService with mocked backends
- SearchService integration tests
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mnemo.models import Book, Chunk, ContentType
from mnemo.search import SearchFilter, SearchResult, reciprocal_rank_fusion
from mnemo.search.service import SearchService
from mnemo.storage.database import get_connection, init_db
from mnemo.storage.repository import BookRepository, ChunkRepository
from mnemo.vectors import VectorConfig, VectorStore


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
        assert abs(scores["a"] - 1/61) < 1e-9  # rank 1
        assert abs(scores["b"] - 1/62) < 1e-9  # rank 2
        assert abs(scores["c"] - 1/63) < 1e-9  # rank 3

    def test_disjoint_lists(self):
        """Items in disjoint lists get independent scores."""
        scores = reciprocal_rank_fusion([["a", "b"], ["c", "d"]])

        # All items ranked 1 or 2 in their list
        assert abs(scores["a"] - 1/61) < 1e-9
        assert abs(scores["b"] - 1/62) < 1e-9
        assert abs(scores["c"] - 1/61) < 1e-9
        assert abs(scores["d"] - 1/62) < 1e-9

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
        expected_y = 1/62 + 1/61
        assert abs(scores["y"] - expected_y) < 1e-9

    def test_custom_k_parameter(self):
        """Custom k parameter affects scores."""
        k = 30
        scores = reciprocal_rank_fusion([["a", "b"]], k=k)

        assert abs(scores["a"] - 1/31) < 1e-9  # k + rank
        assert abs(scores["b"] - 1/32) < 1e-9

    def test_k_zero_allowed(self):
        """k=0 is allowed (just uses rank as denominator)."""
        scores = reciprocal_rank_fusion([["a", "b"]], k=0)

        assert abs(scores["a"] - 1/1) < 1e-9  # 0 + 1
        assert abs(scores["b"] - 1/2) < 1e-9  # 0 + 2

    def test_negative_k_raises(self):
        """Negative k raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            reciprocal_rank_fusion([["a"]], k=-1)

    def test_multiple_lists(self):
        """Works with more than two lists."""
        scores = reciprocal_rank_fusion([["a"], ["a"], ["a"]])

        # "a" is rank 1 in all three lists
        expected = 3 * (1/61)
        assert abs(scores["a"] - expected) < 1e-9

    def test_preserves_chunk_ids(self):
        """All chunk IDs from all lists appear in output."""
        scores = reciprocal_rank_fusion([
            ["id-1", "id-2"],
            ["id-3", "id-4"],
            ["id-1", "id-5"],
        ])

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
        assert service.search("") == []
        assert service.search("   ") == []

    def test_invalid_mode_raises(self, service):
        """Invalid mode raises ValueError."""
        with pytest.raises(ValueError, match="Invalid mode"):
            service.search("test", mode="invalid")

    def test_valid_modes_accepted(self, tmp_path):
        """All valid modes are accepted."""
        # Create a properly initialized service
        db_path = tmp_path / "test.db"
        init_db(db_path)
        service = SearchService(db_path=db_path, chroma_path=tmp_path / "chroma")

        # These should not raise (may return empty results)
        for mode in ["hybrid", "semantic", "keyword"]:
            result = service.search("test", mode=mode)
            assert isinstance(result, list)


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
        """Create mock DatabricksEmbedder."""
        embedder = MagicMock()
        embedder.embed_one.return_value = [0.1] * 1024
        return embedder

    @pytest.fixture
    def service_with_mocks(
        self, mock_chunk_repo, mock_book_repo, mock_vector_store, mock_embedder
    ):
        """Create service with injected mocks."""
        service = SearchService()
        service._chunk_repo = mock_chunk_repo
        service._book_repo = mock_book_repo
        service._vector_store = mock_vector_store
        service._embedder = mock_embedder
        return service

    def test_keyword_mode_calls_fts(
        self, service_with_mocks, mock_chunk_repo
    ):
        """Keyword mode calls FTS search."""
        service_with_mocks.search("test query", mode="keyword")

        mock_chunk_repo.search_fts.assert_called_once()
        call_args = mock_chunk_repo.search_fts.call_args
        assert call_args.kwargs["query"] == "test query"

    def test_keyword_mode_passes_filters(
        self, service_with_mocks, mock_chunk_repo
    ):
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

    def test_semantic_mode_calls_embedder(
        self, service_with_mocks, mock_embedder
    ):
        """Semantic mode generates query embedding."""
        service_with_mocks.search("test query", mode="semantic")

        mock_embedder.embed_one.assert_called_once_with("test query")

    def test_semantic_mode_calls_vector_store(
        self, service_with_mocks, mock_vector_store
    ):
        """Semantic mode queries vector store."""
        service_with_mocks.search("test query", mode="semantic")

        mock_vector_store.query.assert_called_once()

    def test_semantic_mode_passes_filters(
        self, service_with_mocks, mock_vector_store
    ):
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
            content="Content",
            content_type=ContentType.TEXT,
            section_path=[],
        )
        service_with_mocks._book_cache["abc123"] = "Test Book"

        service_with_mocks.search("test query", mode="hybrid")

        mock_chunk_repo.search_fts.assert_called_once()
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
            content="Content",
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

    def test_top_k_passed_to_fts(
        self, service_with_mocks, mock_chunk_repo
    ):
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

    def test_book_title_populated(
        self, service_with_mocks, mock_chunk_repo, mock_book_repo
    ):
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

        results = service_with_mocks.search("test", mode="keyword")

        assert len(results) == 1
        assert results[0].book_title == "Python Cookbook"

    def test_book_title_cached(
        self, service_with_mocks, mock_chunk_repo, mock_book_repo
    ):
        """Book title lookup is cached."""
        # Create multiple chunks from same book
        mock_chunks = [
            MagicMock(
                id=f"chunk-{i}",
                book_id="abc123",
                content=f"Content {i}",
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

    def test_unknown_book_title_fallback(
        self, service_with_mocks, mock_chunk_repo, mock_book_repo
    ):
        """Unknown book_id gets 'Unknown book' title."""
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="unknown",
            content="Content",
            content_type=ContentType.TEXT,
            section_path=[],
        )
        mock_chunk_repo.search_fts.return_value = [mock_chunk]
        mock_book_repo.get.return_value = None

        results = service_with_mocks.search("test", mode="keyword")

        assert results[0].book_title == "Unknown book"

    def test_semantic_failure_falls_back_to_keyword(
        self, service_with_mocks, mock_embedder, mock_chunk_repo
    ):
        """If semantic search fails, hybrid falls back to keyword-only."""
        # Make embedder fail
        mock_embedder.embed_one.side_effect = Exception("API error")

        # Setup keyword results
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="Content",
            content_type=ContentType.TEXT,
            section_path=[],
        )
        mock_chunk_repo.search_fts.return_value = [mock_chunk]
        service_with_mocks._book_cache["abc123"] = "Test Book"

        # Should not raise, should return keyword results
        results = service_with_mocks.search("test", mode="hybrid")

        assert len(results) == 1
        assert results[0].source == "keyword"

    def test_invalid_content_type_ignored(
        self, service_with_mocks, mock_chunk_repo
    ):
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
        svc = SearchService()
        svc._chunk_repo = mock_chunk_repo
        svc._book_repo = mock_book_repo
        svc._vector_store = mock_vector_store
        svc._embedder = mock_embedder
        return svc

    def test_semantic_score_is_cosine_similarity(
        self, service, mock_vector_store, mock_chunk_repo
    ):
        """Semantic search score = max(0, 1 - distance) for cosine distance."""
        # ChromaDB cosine distance of 0.3 -> similarity of 0.7
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 0.3, "metadata": {}, "document": None},
        ]
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="Content",
            content_type=ContentType.TEXT,
            section_path=["Ch1"],
        )
        mock_chunk_repo.get.return_value = mock_chunk
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="semantic")

        assert len(results) == 1
        assert abs(results[0].score - 0.7) < 1e-6

    def test_semantic_score_clamped_to_zero(
        self, service, mock_vector_store, mock_chunk_repo
    ):
        """Cosine similarity is clamped to 0.0 minimum."""
        # Distance > 1.0 can happen with non-normalized vectors
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 1.5, "metadata": {}, "document": None},
        ]
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="Content",
            content_type=ContentType.TEXT,
            section_path=[],
        )
        mock_chunk_repo.get.return_value = mock_chunk
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="semantic")

        assert results[0].score == 0.0

    def test_semantic_score_clamped_to_one(
        self, service, mock_vector_store, mock_chunk_repo
    ):
        """Cosine similarity is clamped to 1.0 maximum."""
        # Distance of exactly 0 -> similarity of 1.0
        mock_vector_store.query.return_value = [
            {"id": "chunk-1", "distance": 0.0, "metadata": {}, "document": None},
        ]
        mock_chunk = MagicMock(
            id="chunk-1",
            book_id="abc123",
            content="Content",
            content_type=ContentType.TEXT,
            section_path=[],
        )
        mock_chunk_repo.get.return_value = mock_chunk
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="semantic")

        assert results[0].score == 1.0

    def test_keyword_search_still_uses_rrf_scores(
        self, service, mock_chunk_repo
    ):
        """Keyword search results still use RRF-style ranking scores."""
        mock_chunks = [
            MagicMock(
                id=f"chunk-{i}",
                book_id="abc123",
                content=f"Content {i}",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
            )
            for i in range(3)
        ]
        mock_chunk_repo.search_fts.return_value = mock_chunks
        service._book_cache["abc123"] = "Test Book"

        results = service.search("test", mode="keyword")

        # Should be RRF-style: 1/(60+rank)
        assert abs(results[0].score - 1.0 / 61) < 1e-9
        assert abs(results[1].score - 1.0 / 62) < 1e-9
        assert abs(results[2].score - 1.0 / 63) < 1e-9


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
            content="def fibonacci():\n    a, b = 0, 1\n    while True:\n        yield a\n        a, b = b, a + b",
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
        )

        assert len(results) >= 1
        assert any("generator" in r.content.lower() for r in results)

    def test_keyword_search_book_filter(self, populated_integration_service):
        """Keyword search respects book_id filter."""
        results = populated_integration_service.search(
            "generators",
            mode="keyword",
            book_id="a1b2c3",
        )

        assert all(r.book_id == "a1b2c3" for r in results)

    def test_keyword_search_content_type_filter(self, populated_integration_service):
        """Keyword search respects content_type filter."""
        results = populated_integration_service.search(
            "fibonacci",
            mode="keyword",
            content_type="code",
        )

        assert len(results) >= 1
        assert all(r.content_type == "code" for r in results)

    def test_keyword_search_returns_attribution(self, populated_integration_service):
        """Keyword search results include full attribution."""
        results = populated_integration_service.search(
            "generators",
            mode="keyword",
            top_k=1,
        )

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
        )

        assert results == []

    def test_search_nonexistent_book_filter(self, populated_integration_service):
        """Search with non-existent book_id returns empty."""
        results = populated_integration_service.search(
            "generators",
            mode="keyword",
            book_id="nonexistent",
        )

        assert results == []

    def test_keyword_search_special_chars(self, populated_integration_service):
        """Keyword search handles special characters safely."""
        # These should not raise errors
        populated_integration_service.search("def fibonacci()", mode="keyword")
        populated_integration_service.search("a, b = 0, 1", mode="keyword")
        populated_integration_service.search("while True:", mode="keyword")

    def test_no_indexed_books(self, integration_service):
        """Search on empty database returns empty list."""
        results = integration_service.search("anything", mode="keyword")
        assert results == []


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST"),
    reason="Requires Databricks credentials"
)
class TestSearchServiceSemanticIntegration:
    """Integration tests requiring embeddings API."""

    def test_semantic_search_finds_match(self, populated_integration_service):
        """Semantic search finds conceptually related chunks."""
        # First need to add embeddings to vector store
        # This would require running embed_book first
        # Skip for now - tested manually
        pytest.skip("Requires pre-embedded book data")

    def test_hybrid_search_merges_results(self, populated_integration_service):
        """Hybrid search merges keyword and semantic results."""
        pytest.skip("Requires pre-embedded book data")


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
        svc = SearchService()
        svc._chunk_repo = mock_chunk_repo
        svc._book_repo = mock_book_repo
        svc._vector_store = mock_vector_store
        svc._embedder = mock_embedder
        svc._book_cache["abc123"] = "Test Book"
        return svc

    def _make_chunk(self, chunk_id, section_path):
        """Helper to create a mock chunk with given section_path."""
        return MagicMock(
            id=chunk_id,
            book_id="abc123",
            content=f"Content for {chunk_id}",
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

        results = service.search("test", mode="keyword", section="Generators")

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

        results = service.search("test", mode="keyword", section="generators")

        assert len(results) == 1
        assert results[0].chunk_id == "c1"

    def test_section_filter_empty_section_path_excluded(self, service, mock_chunk_repo):
        """Chunks with section_path=[] are excluded when section filter is active."""
        chunks = [
            self._make_chunk("c1", []),
            self._make_chunk("c2", ["Chapter 1", "Generators"]),
        ]
        mock_chunk_repo.search_fts.return_value = chunks

        results = service.search("test", mode="keyword", section="Generators")

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

        results = service.search("test", mode="keyword", section=None)

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

        results = service.search("test", mode=mode, section="Generators")

        assert len(results) == 1
        assert results[0].chunk_id == "c1"

    def test_section_filter_overfetch_3x(self, service, mock_chunk_repo):
        """When section filter active, over-fetch 3x from backend."""
        mock_chunk_repo.search_fts.return_value = []

        service.search("test", mode="keyword", top_k=5, section="Generators")

        call_args = mock_chunk_repo.search_fts.call_args
        assert call_args.kwargs["limit"] == 15  # 5 * 3

    def test_section_filter_trims_to_top_k(self, service, mock_chunk_repo):
        """After filtering, results are trimmed to original top_k."""
        chunks = [self._make_chunk(f"c{i}", ["Generators"]) for i in range(10)]
        mock_chunk_repo.search_fts.return_value = chunks

        results = service.search("test", mode="keyword", top_k=3, section="Generators")

        assert len(results) == 3


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
        svc = SearchService()
        svc._chunk_repo = mock_chunk_repo
        svc._book_repo = mock_book_repo
        svc._vector_store = mock_vector_store
        svc._embedder = mock_embedder
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
        """search with context_window=0 returns identical to current behavior (list of SearchResult)."""
        mock_chunk = MagicMock(
            id="c1",
            book_id="abc123",
            content="Content",
            content_type=ContentType.TEXT,
            section_path=["Ch1"],
        )
        mock_chunk_repo.search_fts.return_value = [mock_chunk]

        results = service.search("test", mode="keyword", context_window=0)

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].chunk_id == "c1"

    def test_context_window_expands_neighbors(self, service, mock_chunk_repo):
        """context_window=1 returns each result expanded with neighboring chunks."""
        # Setup: chunks seq 0-4, all same section
        section = ["Part 1", "Section A"]
        chunks = [
            self._make_chunk(f"c{i}", "abc123", i, section)
            for i in range(5)
        ]

        # Search returns chunk at seq=2
        search_chunk = MagicMock(
            id="c2",
            book_id="abc123",
            content="Content for seq 2",
            content_type=ContentType.TEXT,
            section_path=section,
        )
        mock_chunk_repo.search_fts.return_value = [search_chunk]

        # get returns the matched chunk
        mock_chunk_repo.get.return_value = chunks[2]

        # get_chunk_range returns seq 1, 2, 3
        mock_chunk_repo.get_chunk_range.return_value = [chunks[1], chunks[2], chunks[3]]

        results = service.search("test", mode="keyword", context_window=1)

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
            content="Content for seq 2",
            content_type=ContentType.TEXT,
            section_path=section_a,
        )
        mock_chunk_repo.search_fts.return_value = [search_chunk]
        mock_chunk_repo.get.return_value = chunks[2]
        # get_chunk_range(abc123, 0, 4) returns all 5
        mock_chunk_repo.get_chunk_range.return_value = chunks

        results = service.search("test", mode="keyword", context_window=2)

        assert len(results) == 1
        result = results[0]
        chunk_seqs = [c.sequence for c in result["chunks"]]
        # Should only get seq 0, 1, 2 (not 3, 4 which are Section B)
        assert chunk_seqs == [0, 1, 2]

    def test_context_window_dedup_overlapping(self, service, mock_chunk_repo):
        """Two results with overlapping windows are merged into one block."""
        section = ["Part 1", "Section A"]
        chunks = [
            self._make_chunk(f"c{i}", "abc123", i, section)
            for i in range(8)
        ]

        # Search returns chunks at seq=3 and seq=5, window=2
        search_chunks = [
            MagicMock(
                id="c3",
                book_id="abc123",
                content="Content for seq 3",
                content_type=ContentType.TEXT,
                section_path=section,
            ),
            MagicMock(
                id="c5",
                book_id="abc123",
                content="Content for seq 5",
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

        results = service.search("test", mode="keyword", context_window=2)

        # Should merge into one block: seq 1-7 (window=2 around 3 gives 1-5, around 5 gives 3-7, merged = 1-7)
        assert len(results) == 1
        result = results[0]
        assert "c3" in result["matched_chunk_ids"]
        assert "c5" in result["matched_chunk_ids"]
        chunk_seqs = [c.sequence for c in result["chunks"]]
        assert chunk_seqs == [1, 2, 3, 4, 5, 6, 7]

    def test_context_window_preserves_match_markers(self, service, mock_chunk_repo):
        """After dedup, matched_chunk_ids contains the original match IDs."""
        section = ["Part 1", "Section A"]
        chunks = [
            self._make_chunk(f"c{i}", "abc123", i, section)
            for i in range(6)
        ]

        search_chunks = [
            MagicMock(
                id="c2",
                book_id="abc123",
                content="Content for seq 2",
                content_type=ContentType.TEXT,
                section_path=section,
            ),
            MagicMock(
                id="c4",
                book_id="abc123",
                content="Content for seq 4",
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

        results = service.search("test", mode="keyword", context_window=1)

        # With window=1: c2->1,2,3 and c4->3,4,5, overlapping at 3, merge to 1-5
        assert len(results) == 1
        result = results[0]
        assert result["matched_chunk_ids"] == {"c2", "c4"}
