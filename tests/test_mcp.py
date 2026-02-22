"""Tests for MCP server and tools.

Tests the FastMCP server setup and tool implementations:
- Server imports without side effects
- Tools are properly registered
- Tool input validation
- Output formatting
- Integration with storage (using temp paths)
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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
        """Verify all six tools are registered with the server."""
        from mnemo.mcp.server import mcp

        # FastMCP stores tools in _tool_manager
        tool_names = list(mcp._tool_manager._tools.keys())
        assert "search_books" in tool_names
        assert "list_available_books" in tool_names
        assert "get_book_info" in tool_names
        assert "update_book_metadata" in tool_names
        assert "remove_book" in tool_names
        assert "add_book" in tool_names


class TestToolAnnotations:
    """Tests verifying ToolAnnotations on all six MCP tools.

    Guards against regression of annotations added in Plan 07-01.
    """

    def test_read_only_tools_have_annotations(self):
        """Read-only tools (search, list, get_info) have correct hints."""
        from mnemo.mcp.server import mcp

        for name in ["search_books", "list_available_books", "get_book_info"]:
            tool = mcp._tool_manager._tools[name]
            assert tool.annotations is not None, f"{name} missing annotations"
            assert tool.annotations.readOnlyHint is True, f"{name} readOnlyHint"
            assert tool.annotations.destructiveHint is False, f"{name} destructiveHint"
            assert tool.annotations.openWorldHint is False, f"{name} openWorldHint"

    def test_remove_book_has_destructive_annotation(self):
        """remove_book is marked destructive and non-idempotent."""
        from mnemo.mcp.server import mcp

        tool = mcp._tool_manager._tools["remove_book"]
        assert tool.annotations is not None
        assert tool.annotations.destructiveHint is True
        assert tool.annotations.idempotentHint is False
        assert tool.annotations.openWorldHint is False

    def test_update_book_has_idempotent_annotation(self):
        """update_book_metadata is marked idempotent."""
        from mnemo.mcp.server import mcp

        tool = mcp._tool_manager._tools["update_book_metadata"]
        assert tool.annotations is not None
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False

    def test_add_book_has_correct_annotations(self):
        """add_book has only openWorldHint=False (no special hints)."""
        from mnemo.mcp.server import mcp

        tool = mcp._tool_manager._tools["add_book"]
        assert tool.annotations is not None
        assert tool.annotations.openWorldHint is False


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

    def test_update_invalid_isbn(self):
        """Invalid ISBN should return error."""
        from mnemo.mcp.tools import _update_book_metadata_impl

        result = _update_book_metadata_impl("abc123", isbn="garbage")
        assert "Error" in result
        assert "ISBN" in result


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

            assert "Search failed" in result
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
        """After update, SearchService.invalidate_cache should be called."""
        from mnemo.mcp import tools

        original_conn = tools._db_connection
        original_service = tools._search_service

        tools._db_connection = temp_db["conn"]

        # Set up a mock search service with a populated cache
        mock_service = MagicMock()
        tools._search_service = mock_service

        try:
            tools._update_book_metadata_impl("abc123", title="New Title")

            mock_service.invalidate_cache.assert_called()
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

    def test_update_valid_isbn_normalized(self, temp_db):
        """Valid ISBN with hyphens should be stored normalized (digits only)."""
        from mnemo.mcp import tools
        from mnemo.storage import BookRepository

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            tools._update_book_metadata_impl("abc123", isbn="978-0-13-468599-1")
            # Verify stored as normalized (no hyphens)
            book_repo = BookRepository(temp_db["conn"])
            book = book_repo.get("abc123")
            assert book.isbn == "9780134685991"
        finally:
            tools._db_connection = original_conn


class TestRemoveBookValidation:
    """Tests for remove_book input validation."""

    def test_remove_book_empty_id(self):
        """Empty book_id should return error."""
        from mnemo.mcp.tools import _remove_book_impl

        result = _remove_book_impl("")
        assert "Error" in result

    def test_remove_book_short_id(self):
        """book_id < 6 chars should return error."""
        from mnemo.mcp.tools import _remove_book_impl

        result = _remove_book_impl("abc")
        assert "Error" in result

    def test_remove_book_long_id(self):
        """book_id > 6 chars should return error."""
        from mnemo.mcp.tools import _remove_book_impl

        result = _remove_book_impl("abcdefgh")
        assert "Error" in result


class TestRemoveBookIntegration:
    """Integration tests for remove_book with temp database."""

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

    def test_remove_book_success(self, temp_db):
        """Remove existing book returns confirmation with book details."""
        from unittest.mock import patch

        from mnemo.mcp import tools

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            with patch("mnemo.ingest.remove_book") as mock_pipeline:
                mock_pipeline.return_value = True
                result = tools._remove_book_impl("abc123")

            assert "Removed" in result
            assert "Test Python Book" in result
            assert "John Doe" in result
            assert "3 chunks deleted" in result
        finally:
            tools._db_connection = original_conn

    def test_remove_book_not_found(self, temp_db):
        """Remove nonexistent book returns not-found error."""
        from mnemo.mcp import tools

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            result = tools._remove_book_impl("xyz789")

            assert "Error" in result
            assert "not found" in result.lower()
        finally:
            tools._db_connection = original_conn

    def test_remove_book_clears_search_cache(self, temp_db):
        """After removal, SearchService.invalidate_cache should be called."""
        from unittest.mock import patch

        from mnemo.mcp import tools

        original_conn = tools._db_connection
        original_service = tools._search_service

        tools._db_connection = temp_db["conn"]

        # Set up a mock search service with a populated cache
        mock_service = MagicMock()
        tools._search_service = mock_service

        try:
            with patch("mnemo.ingest.remove_book") as mock_pipeline:
                mock_pipeline.return_value = True
                tools._remove_book_impl("abc123")

            mock_service.invalidate_cache.assert_called()
        finally:
            tools._db_connection = original_conn
            tools._search_service = original_service

    def test_remove_book_delegates_to_pipeline(self, temp_db):
        """remove_book should delegate to ingest.remove_book with correct book_id."""
        from unittest.mock import patch

        from mnemo.mcp import tools

        original_conn = tools._db_connection
        tools._db_connection = temp_db["conn"]

        try:
            with patch("mnemo.ingest.remove_book") as mock_pipeline:
                mock_pipeline.return_value = True
                tools._remove_book_impl("abc123")

            mock_pipeline.assert_called_once_with("abc123")
        finally:
            tools._db_connection = original_conn


class TestAddBookValidation:
    """Tests for add_book input validation (no DB or real files needed)."""

    def test_add_book_file_not_found(self):
        """Non-existent path should return file-not-found error."""
        from mnemo.mcp.tools import _add_book_impl

        result = _add_book_impl("/nonexistent/path/book.epub", pre_parsed=MagicMock())
        assert "Error" in result
        assert "not found" in result.lower()

    def test_add_book_not_epub(self, tmp_path):
        """Non-EPUB file should return extension validation error."""
        from mnemo.mcp.tools import _add_book_impl

        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("some content")
        result = _add_book_impl(str(txt_file), pre_parsed=MagicMock())
        assert "Error" in result
        assert "epub" in result.lower()

    def test_add_book_not_epub_case_insensitive(self, tmp_path):
        """PDF file (not EPUB) should return extension validation error."""
        from mnemo.mcp.tools import _add_book_impl

        pdf_file = tmp_path / "book.PDF"
        pdf_file.write_bytes(b"fake pdf content")
        result = _add_book_impl(str(pdf_file), pre_parsed=MagicMock())
        assert "Error" in result


class TestAddBookIntegration:
    """Integration tests for add_book with mocked ingest pipeline."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database for add_book tests."""
        from mnemo.storage.database import get_connection, init_db

        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)

        yield {"path": db_path, "conn": conn}

        conn.close()

    def _make_mock_book(self, **overrides):
        """Create a mock Book object for testing."""
        defaults = dict(
            id="abc123",
            title="Test Book",
            authors=["Author One"],
            isbn=None,
            file_hash="a" * 64,
            default_language=None,
            structure_source="toc",
            added_at=datetime(2026, 1, 20, tzinfo=timezone.utc),
        )
        defaults.update(overrides)
        return Book(**defaults)

    def _make_conn_factory(self, temp_db):
        """Create a factory that returns new connections to the temp DB."""
        from mnemo.storage.database import get_connection

        return lambda: get_connection(temp_db["path"])

    def test_add_book_success(self, tmp_path, temp_db):
        """Successful add returns book details and chunk count."""
        from mnemo.mcp import tools

        epub_file = tmp_path / "book.epub"
        epub_file.write_bytes(b"fake epub content")

        mock_pre_parsed = self._make_mock_book(file_hash="b" * 64)
        mock_result_book = self._make_mock_book(
            id="de0456", file_hash="b" * 64, title="Test Book", authors=["Author One"]
        )

        with (
            patch(
                "mnemo.mcp.tools.get_connection",
                side_effect=self._make_conn_factory(temp_db),
            ),
            patch("mnemo.mcp.tools.init_db"),
            patch(
                "mnemo.ingest.ingest_book",
                return_value=(mock_result_book, 42),
            ),
        ):
            result = tools._add_book_impl(str(epub_file), False, mock_pre_parsed)

        assert "Added" in result
        assert "Test Book" in result
        assert "42 chunks" in result

    def test_add_book_duplicate_detected(self, tmp_path, temp_db):
        """Duplicate book (same hash) returns error with existing book info."""
        from mnemo.mcp import tools
        from mnemo.storage import BookRepository

        epub_file = tmp_path / "book.epub"
        epub_file.write_bytes(b"fake epub content")

        # Add an existing book with known hash
        existing_book = self._make_mock_book(
            id="eee111", title="Existing Book", authors=["Old Author"], file_hash="c" * 64
        )
        book_repo = BookRepository(temp_db["conn"])
        book_repo.add(existing_book)

        mock_pre_parsed = self._make_mock_book(file_hash="c" * 64)

        with (
            patch(
                "mnemo.mcp.tools.get_connection",
                side_effect=self._make_conn_factory(temp_db),
            ),
            patch("mnemo.mcp.tools.init_db"),
        ):
            result = tools._add_book_impl(str(epub_file), False, mock_pre_parsed)

        assert "Error" in result
        assert "already exists" in result.lower()
        assert "Existing Book" in result
        assert "eee111" in result
        assert "force=true" in result.lower()

    def test_add_book_force_reindex(self, tmp_path, temp_db):
        """force=True allows re-indexing of duplicate book."""
        from mnemo.mcp import tools
        from mnemo.storage import BookRepository

        epub_file = tmp_path / "book.epub"
        epub_file.write_bytes(b"fake epub content")

        # Add an existing book with known hash
        existing_book = self._make_mock_book(
            id="eee111", title="Existing Book", authors=["Old Author"], file_hash="d" * 64
        )
        book_repo = BookRepository(temp_db["conn"])
        book_repo.add(existing_book)

        mock_pre_parsed = self._make_mock_book(file_hash="d" * 64)
        mock_result_book = self._make_mock_book(
            id="eee111", file_hash="d" * 64, title="Existing Book", authors=["Old Author"]
        )

        with (
            patch(
                "mnemo.mcp.tools.get_connection",
                side_effect=self._make_conn_factory(temp_db),
            ),
            patch("mnemo.mcp.tools.init_db"),
            patch(
                "mnemo.ingest.ingest_book",
                return_value=(mock_result_book, 42),
            ),
        ):
            result = tools._add_book_impl(str(epub_file), True, mock_pre_parsed)

        assert "Added" in result
        assert "Error" not in result

    def test_add_book_clears_search_cache(self, tmp_path, temp_db):
        """Successful add calls invalidate_cache on the search service."""
        from mnemo.mcp import tools

        epub_file = tmp_path / "book.epub"
        epub_file.write_bytes(b"fake epub content")

        mock_pre_parsed = self._make_mock_book(file_hash="e" * 64)
        mock_result_book = self._make_mock_book(
            id="aaa123", file_hash="e" * 64, title="New Book", authors=["Author"]
        )

        original_service = tools._search_service

        # Set up mock search service
        mock_service = MagicMock()
        tools._search_service = mock_service

        try:
            with (
                patch(
                    "mnemo.mcp.tools.get_connection",
                    side_effect=self._make_conn_factory(temp_db),
                ),
                patch("mnemo.mcp.tools.init_db"),
                patch(
                    "mnemo.ingest.ingest_book",
                    return_value=(mock_result_book, 10),
                ),
            ):
                tools._add_book_impl(str(epub_file), False, mock_pre_parsed)

            mock_service.invalidate_cache.assert_called()
        finally:
            tools._search_service = original_service

    def test_add_book_cleans_up_on_failure(self, tmp_path, temp_db):
        """Failed ingestion cleans up partial data."""
        from mnemo.mcp import tools
        from mnemo.storage import BookRepository

        epub_file = tmp_path / "book.epub"
        epub_file.write_bytes(b"fake epub content")

        mock_pre_parsed = self._make_mock_book(file_hash="f" * 64)

        # Simulate ingest_book storing a partial book record before failing
        # during embedding. The side_effect adds the book to the DB then raises.
        partial_book = self._make_mock_book(
            id="bbb001", file_hash="f" * 64, title="Partial Book"
        )

        def ingest_side_effect(*args, **kwargs):
            book_repo = BookRepository(temp_db["conn"])
            book_repo.add(partial_book)
            raise Exception("Embedding failed")

        with (
            patch(
                "mnemo.mcp.tools.get_connection",
                side_effect=self._make_conn_factory(temp_db),
            ),
            patch("mnemo.mcp.tools.init_db"),
            patch(
                "mnemo.ingest.ingest_book",
                side_effect=ingest_side_effect,
            ),
            patch("mnemo.ingest.remove_book") as mock_remove,
        ):
            result = tools._add_book_impl(str(epub_file), False, mock_pre_parsed)

        assert "Error" in result
        assert "Embedding failed" in result
        mock_remove.assert_called_once_with("bbb001")


class TestLifecycle:
    """End-to-end lifecycle: add -> search -> update -> verify update in info -> remove -> verify removal."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database."""
        from mnemo.storage.database import get_connection, init_db

        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        yield {"path": db_path, "conn": conn}
        conn.close()

    def test_full_lifecycle(self, tmp_path, temp_db):
        """Full lifecycle: add, search, update, verify, remove, verify gone."""
        from mnemo.mcp import tools
        from mnemo.storage import BookRepository, ChunkRepository

        # Prepare a fake EPUB file
        epub_file = tmp_path / "lifecycle.epub"
        epub_file.write_bytes(b"fake epub content")

        # Mock book that ingest_book "creates"
        lifecycle_book = Book(
            id="aaa001",
            title="Lifecycle Test Book",
            authors=["Test Author"],
            isbn="978-0000000000",
            file_hash="a" * 64,
            default_language="python",
            structure_source="toc",
            added_at=datetime(2026, 2, 16, tzinfo=timezone.utc),
        )

        # Mock pre-parsed metadata (extract_metadata result)
        mock_pre_parsed = MagicMock()
        mock_pre_parsed.file_hash = lifecycle_book.file_hash
        mock_pre_parsed.title = lifecycle_book.title

        # --- Setup: wire tools to temp DB ---
        original_conn = tools._db_connection
        original_service = tools._search_service
        tools._db_connection = temp_db["conn"]
        tools._search_service = None  # Reset so it gets replaced below

        try:
            # --- Step 1: Add book ---
            # Mock ingest_book to insert the book into our temp DB and return it
            def mock_ingest(path, embed=True, force=False):
                book_repo = BookRepository(temp_db["conn"])
                book_repo.add(lifecycle_book)
                # Also add chunks so search and get_book_info work
                chunk_repo = ChunkRepository(temp_db["conn"])
                chunks = [
                    Chunk(
                        id=f"lc-chunk-{i}",
                        book_id="aaa001",
                        content=f"Lifecycle content about Python decorators part {i}",
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
                return lifecycle_book, 3

            from mnemo.storage.database import get_connection as db_get_conn

            conn_factory = lambda: db_get_conn(temp_db["path"])

            with (
                patch(
                    "mnemo.mcp.tools.get_connection", side_effect=conn_factory
                ),
                patch("mnemo.mcp.tools.init_db"),
                patch("mnemo.ingest.ingest_book", side_effect=mock_ingest),
            ):
                add_result = tools._add_book_impl(str(epub_file), False, mock_pre_parsed)

            assert "Added" in add_result
            assert "Lifecycle Test Book" in add_result
            assert "3 chunks" in add_result

            # --- Step 2: Search for content ---
            # Use keyword search against the real FTS5 table (no embeddings needed)
            from mnemo.search.service import SearchService

            temp_search = SearchService(
                db_path=temp_db["path"],
                chroma_path=tmp_path / "chroma",
            )
            tools._search_service = temp_search

            search_result = tools._search_books_impl(
                "Python decorators", mode="keyword"
            )
            assert "decorators" in search_result.lower()
            assert "aaa001" in search_result

            # --- Step 3: Update metadata ---
            update_result = tools._update_book_metadata_impl(
                "aaa001", title="Updated Lifecycle Book"
            )
            assert "Updated Lifecycle Book" in update_result

            # --- Step 4: Verify metadata reflected in get_book_info ---
            info_result = tools._get_book_info_impl("aaa001")
            assert "Updated Lifecycle Book" in info_result
            assert "Test Author" in info_result

            # --- Step 5: Remove book ---
            # Mock remove_book to actually delete from our temp DB
            def mock_remove(book_id):
                book_repo = BookRepository(temp_db["conn"])
                book_repo.delete(book_id)

            with patch(
                "mnemo.ingest.remove_book", side_effect=mock_remove
            ):
                remove_result = tools._remove_book_impl("aaa001")

            assert "Removed" in remove_result
            assert "Updated Lifecycle Book" in remove_result

            # --- Step 6: Verify removal ---
            gone_result = tools._get_book_info_impl("aaa001")
            assert "not found" in gone_result.lower()

        finally:
            tools._db_connection = original_conn
            tools._search_service = original_service
