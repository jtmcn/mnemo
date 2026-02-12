"""Tests for MCP server and tools.

Tests the FastMCP server setup and tool implementations:
- Server imports without side effects
- Tools are properly registered
- Tool input validation
- Output formatting
- Integration with storage (using temp paths)
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from mnemo.models import Book, Chunk, ContentType
from mnemo.search.models import SearchResult


class TestServerSetup:
    """Tests for MCP server initialization."""

    def test_server_imports_without_side_effects(self):
        """Verify server can be imported without creating connections."""
        from mnemo.mcp.server import mcp

        assert mcp.name == "mnemo"

    def test_tools_registered(self):
        """Verify all four tools are registered with the server."""
        from mnemo.mcp.server import mcp

        # FastMCP stores tools in _tool_manager
        tool_names = list(mcp._tool_manager._tools.keys())
        assert "search_books" in tool_names
        assert "list_available_books" in tool_names
        assert "get_book_info" in tool_names
        assert "update_book_metadata" in tool_names


class TestSearchBooksValidation:
    """Tests for search_books input validation."""

    def test_search_books_empty_query(self):
        """Empty query should return error message."""
        from mnemo.mcp.tools import _search_books_impl

        result = _search_books_impl("")
        assert "Error" in result or "empty" in result.lower()

    def test_search_books_whitespace_query(self):
        """Whitespace-only query should return error message."""
        from mnemo.mcp.tools import _search_books_impl

        result = _search_books_impl("   ")
        assert "Error" in result or "empty" in result.lower()

    def test_search_books_clamps_top_k_high(self):
        """top_k > 50 should be clamped to 50."""
        from mnemo.mcp import tools

        # Mock the SearchService to capture the top_k value
        mock_service = MagicMock()
        mock_service.search.return_value = []

        # Reset the cached service
        original_service = tools._search_service
        tools._search_service = mock_service

        try:
            tools._search_books_impl("test query", top_k=100)
            # Should have clamped to 50
            mock_service.search.assert_called_once()
            call_kwargs = mock_service.search.call_args[1]
            assert call_kwargs["top_k"] == 50
        finally:
            tools._search_service = original_service

    def test_search_books_clamps_top_k_low(self):
        """top_k < 1 should be clamped to 1."""
        from mnemo.mcp import tools

        mock_service = MagicMock()
        mock_service.search.return_value = []

        original_service = tools._search_service
        tools._search_service = mock_service

        try:
            tools._search_books_impl("test query", top_k=-5)
            mock_service.search.assert_called_once()
            call_kwargs = mock_service.search.call_args[1]
            assert call_kwargs["top_k"] == 1
        finally:
            tools._search_service = original_service


class TestGetBookInfoValidation:
    """Tests for get_book_info input validation."""

    def test_get_book_info_empty_id(self):
        """Empty book_id should return error."""
        from mnemo.mcp.tools import _get_book_info_impl

        result = _get_book_info_impl("")
        assert "Error" in result

    def test_get_book_info_short_id(self):
        """book_id < 6 chars should return error."""
        from mnemo.mcp.tools import _get_book_info_impl

        result = _get_book_info_impl("abc")
        assert "Error" in result

    def test_get_book_info_long_id(self):
        """book_id > 6 chars should return error."""
        from mnemo.mcp.tools import _get_book_info_impl

        result = _get_book_info_impl("abcdefgh")
        assert "Error" in result


class TestUpdateBookMetadataValidation:
    """Tests for update_book_metadata input validation."""

    def test_update_empty_book_id(self):
        """Empty book_id should return error."""
        from mnemo.mcp.tools import _update_book_metadata_impl

        result = _update_book_metadata_impl("", title="New")
        assert "Error" in result

    def test_update_short_book_id(self):
        """book_id < 6 chars should return error."""
        from mnemo.mcp.tools import _update_book_metadata_impl

        result = _update_book_metadata_impl("abc", title="New")
        assert "Error" in result

    def test_update_no_fields(self):
        """No fields provided should return error."""
        from mnemo.mcp.tools import _update_book_metadata_impl

        result = _update_book_metadata_impl("abc123")
        assert "Error" in result
        assert "at least one" in result.lower()

    def test_update_empty_title(self):
        """Empty title should return error."""
        from mnemo.mcp.tools import _update_book_metadata_impl

        result = _update_book_metadata_impl("abc123", title="")
        assert "Error" in result
        assert "empty" in result.lower()

    def test_update_empty_title_whitespace(self):
        """Whitespace-only title should return error."""
        from mnemo.mcp.tools import _update_book_metadata_impl

        result = _update_book_metadata_impl("abc123", title="   ")
        assert "Error" in result


class TestOutputFormatting:
    """Tests for result formatting functions."""

    def test_format_search_results_includes_attribution(self):
        """Formatted results should include book title and section path."""
        from mnemo.mcp.tools import _format_search_results

        result = SearchResult(
            chunk_id="test-uuid",
            book_id="abc123",
            book_title="Python Cookbook",
            content="Some example code",
            content_type="text",
            section_path=["Chapter 1", "Introduction"],
            score=0.032,
            source="both",
        )

        output = _format_search_results([result])

        assert "Source:" in output
        assert "Python Cookbook" in output
        assert "Chapter 1" in output
        assert "Introduction" in output
        assert "abc123" in output

    def test_format_search_results_code_has_fence(self):
        """Code results should be wrapped in markdown fences."""
        from mnemo.mcp.tools import _format_search_results

        result = SearchResult(
            chunk_id="test-uuid",
            book_id="abc123",
            book_title="Python Cookbook",
            content="def hello():\n    print('hello')",
            content_type="code",
            section_path=["Chapter 1"],
            score=0.032,
            source="semantic",
        )

        output = _format_search_results([result])

        assert "```" in output
        assert "def hello():" in output

    def test_format_search_results_truncates_long_content(self):
        """Content > 2000 chars should be truncated."""
        from mnemo.mcp.tools import _format_search_results

        long_content = "x" * 3000
        result = SearchResult(
            chunk_id="test-uuid",
            book_id="abc123",
            book_title="Big Book",
            content=long_content,
            content_type="text",
            section_path=[],
            score=0.01,
            source="keyword",
        )

        output = _format_search_results([result])

        assert "[truncated...]" in output
        # Should have roughly 2000 chars of content, not 3000
        assert len(output) < 2500

    def test_format_search_results_empty_section_path(self):
        """Results with empty section_path should show 'Unknown section'."""
        from mnemo.mcp.tools import _format_search_results

        result = SearchResult(
            chunk_id="test-uuid",
            book_id="abc123",
            book_title="Test Book",
            content="Some content",
            content_type="text",
            section_path=[],
            score=0.01,
            source="keyword",
        )

        output = _format_search_results([result])

        assert "Unknown section" in output

    def test_format_search_results_shows_count(self):
        """Formatted output should show result count."""
        from mnemo.mcp.tools import _format_search_results

        results = [
            SearchResult(
                chunk_id=f"uuid-{i}",
                book_id="abc123",
                book_title="Test Book",
                content=f"Content {i}",
                content_type="text",
                section_path=["Chapter 1"],
                score=0.01 * i,
                source="keyword",
            )
            for i in range(3)
        ]

        output = _format_search_results(results)

        assert "Found 3 results" in output


class TestIntegrationWithTempStorage:
    """Integration tests using temporary database."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database with test data."""
        from mnemo.storage.database import get_connection, init_db

        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)

        # Add a test book
        from mnemo.storage import BookRepository, ChunkRepository

        book_repo = BookRepository(conn)
        chunk_repo = ChunkRepository(conn)

        book = Book(
            id="abc123",
            title="Test Python Book",
            authors=["John Doe"],
            isbn="978-1234567890",
            file_hash="a" * 64,
            default_language="python",
            structure_source="toc",
            added_at=datetime(2026, 1, 20, tzinfo=timezone.utc),
        )
        book_repo.add(book)

        chunks = [
            Chunk(
                id=f"chunk-{i}",
                book_id="abc123",
                content=f"Test content {i}",
                content_type=ContentType.TEXT,
                token_count=10,
                section_path=["Chapter 1", f"Section {i}"],
                sections=["Chapter 1"],
                language=None,
                sequence=i,
            )
            for i in range(3)
        ]
        chunk_repo.add_many(chunks)

        yield {"path": db_path, "conn": conn, "book": book}

        conn.close()

    def test_list_available_books_with_data(self, temp_db):
        """list_available_books should return books from temp database."""
        from mnemo.mcp import tools

        # Reset the connection to use our temp db
        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            result = tools._list_available_books_impl()

            assert "Test Python Book" in result
            assert "abc123" in result
            assert "John Doe" in result
            assert "2026-01-20" in result
        finally:
            tools._db_connection = original_conn

    def test_list_available_books_empty_library(self, tmp_path):
        """list_available_books with empty db should return help message."""
        from mnemo.storage.database import get_connection, init_db

        from mnemo.mcp import tools

        db_path = tmp_path / "empty.db"
        init_db(db_path)
        conn = get_connection(db_path)

        original_conn = tools._db_connection
        tools._db_connection = conn

        try:
            result = tools._list_available_books_impl()

            assert "No books indexed" in result
            assert "mnemo add" in result
        finally:
            tools._db_connection = original_conn
            conn.close()

    def test_get_book_info_found(self, temp_db):
        """get_book_info should return book details."""
        from mnemo.mcp import tools

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            result = tools._get_book_info_impl("abc123")

            assert "Test Python Book" in result
            assert "abc123" in result
            assert "John Doe" in result
            assert "978-1234567890" in result
            assert "Chunks:" in result
            assert "3" in result  # 3 chunks
        finally:
            tools._db_connection = original_conn

    def test_get_book_info_not_found(self, temp_db):
        """get_book_info with unknown id should return not found message."""
        from mnemo.mcp import tools

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            result = tools._get_book_info_impl("xyz789")

            assert "not found" in result.lower()
        finally:
            tools._db_connection = original_conn


class TestSearchBooksIntegration:
    """Integration tests for search_books with mocked services."""

    def test_search_books_returns_formatted_results(self):
        """search_books should return markdown-formatted results."""
        from mnemo.mcp import tools

        mock_service = MagicMock()
        mock_service.search.return_value = [
            SearchResult(
                chunk_id="test-uuid",
                book_id="abc123",
                book_title="Python Cookbook",
                content="Example async code",
                content_type="code",
                section_path=["Chapter 5", "Async"],
                score=0.032,
                source="both",
            )
        ]

        original_service = tools._search_service
        tools._search_service = mock_service

        try:
            result = tools._search_books_impl("async python")

            assert "Python Cookbook" in result
            assert "Chapter 5" in result
            assert "async" in result.lower()
            assert "---" in result  # Separator
        finally:
            tools._search_service = original_service

    def test_search_books_no_results(self):
        """search_books with no matches should return helpful message."""
        from mnemo.mcp import tools

        mock_service = MagicMock()
        mock_service.search.return_value = []

        original_service = tools._search_service
        tools._search_service = mock_service

        try:
            result = tools._search_books_impl("nonexistent query")

            assert "No results found" in result
            assert "nonexistent query" in result
        finally:
            tools._search_service = original_service

    def test_search_books_passes_filters(self):
        """search_books should pass all filters to SearchService."""
        from mnemo.mcp import tools

        mock_service = MagicMock()
        mock_service.search.return_value = []

        original_service = tools._search_service
        tools._search_service = mock_service

        try:
            tools._search_books_impl(
                query="test",
                book_id="abc123",
                content_type="code",
                top_k=5,
                mode="semantic",
            )

            mock_service.search.assert_called_once_with(
                query="test",
                top_k=5,
                book_id="abc123",
                content_type="code",
                mode="semantic",
            )
        finally:
            tools._search_service = original_service

    def test_search_books_handles_exception(self):
        """search_books should return error message on exception."""
        from mnemo.mcp import tools

        mock_service = MagicMock()
        mock_service.search.side_effect = Exception("Database connection failed")

        original_service = tools._search_service
        tools._search_service = mock_service

        try:
            result = tools._search_books_impl("test query")

            assert "Search error" in result
            assert "Database connection failed" in result
        finally:
            tools._search_service = original_service


class TestUpdateBookMetadataIntegration:
    """Integration tests for update_book_metadata with temp database."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database with a test book."""
        from mnemo.storage.database import get_connection, init_db

        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)

        from mnemo.storage import BookRepository, ChunkRepository

        book_repo = BookRepository(conn)
        chunk_repo = ChunkRepository(conn)

        book = Book(
            id="abc123",
            title="Test Python Book",
            authors=["John Doe"],
            isbn="978-1234567890",
            file_hash="a" * 64,
            default_language="python",
            structure_source="toc",
            added_at=datetime(2026, 1, 20, tzinfo=timezone.utc),
        )
        book_repo.add(book)

        chunks = [
            Chunk(
                id=f"chunk-{i}",
                book_id="abc123",
                content=f"Test content {i}",
                content_type=ContentType.TEXT,
                token_count=10,
                section_path=["Chapter 1", f"Section {i}"],
                sections=["Chapter 1"],
                language=None,
                sequence=i,
            )
            for i in range(3)
        ]
        chunk_repo.add_many(chunks)

        yield {"path": db_path, "conn": conn, "book": book}

        conn.close()

    def test_update_title(self, temp_db):
        """update_book_metadata should update title and return book info."""
        from mnemo.mcp import tools

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            result = tools._update_book_metadata_impl("abc123", title="Updated Title")

            assert "Updated Title" in result
        finally:
            tools._db_connection = original_conn

    def test_update_authors(self, temp_db):
        """update_book_metadata should update authors."""
        from mnemo.mcp import tools

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            result = tools._update_book_metadata_impl(
                "abc123", authors=["New Author"]
            )

            assert "New Author" in result
        finally:
            tools._db_connection = original_conn

    def test_update_reflected_in_get_book_info(self, temp_db):
        """After update, get_book_info should reflect new values."""
        from mnemo.mcp import tools

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            tools._update_book_metadata_impl("abc123", title="Reflected Title")
            result = tools._get_book_info_impl("abc123")

            assert "Reflected Title" in result
        finally:
            tools._db_connection = original_conn

    def test_update_nonexistent_book(self, temp_db):
        """update_book_metadata for nonexistent book should return not found."""
        from mnemo.mcp import tools

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            result = tools._update_book_metadata_impl("xyz789", title="New")

            assert "not found" in result.lower()
        finally:
            tools._db_connection = original_conn

    def test_update_clears_search_cache(self, temp_db):
        """After update, SearchService._book_cache should be cleared."""
        from mnemo.mcp import tools

        original_conn = tools._db_connection
        original_service = tools._search_service

        tools._db_connection = temp_db["conn"]

        # Set up a mock search service with a populated cache
        mock_service = MagicMock()
        mock_service._book_cache = {"abc123": "Old Title"}
        tools._search_service = mock_service

        try:
            tools._update_book_metadata_impl("abc123", title="New Title")

            assert mock_service._book_cache == {}
        finally:
            tools._db_connection = original_conn
            tools._search_service = original_service

    def test_update_isbn_empty_string_clears(self, temp_db):
        """Empty string for isbn should clear it (show 'Not available')."""
        from mnemo.mcp import tools

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            tools._update_book_metadata_impl("abc123", isbn="")
            result = tools._get_book_info_impl("abc123")

            assert "Not available" in result
        finally:
            tools._db_connection = original_conn
