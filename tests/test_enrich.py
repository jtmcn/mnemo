"""Tests for ISBN validation and metadata enrichment."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mnemo.epub.enrich import (
    EnrichmentResult,
    _google_books_by_isbn,
    _google_books_search,
    _normalize_title,
    _open_library_by_isbn,
    _open_library_search,
    enrich_book_metadata,
    lookup_by_isbn,
    search_by_title_author,
    validate_isbn,
)


class TestValidateIsbn:
    """Tests for ISBN checksum validation."""

    def test_valid_isbn13(self) -> None:
        is_valid, isbn13 = validate_isbn("9780134685991")
        assert is_valid is True
        assert isbn13 == "9780134685991"

    def test_valid_isbn10_converts_to_13(self) -> None:
        is_valid, isbn13 = validate_isbn("0596007124")
        assert is_valid is True
        assert isbn13 is not None
        assert len(isbn13) == 13

    def test_invalid_checksum(self) -> None:
        is_valid, isbn13 = validate_isbn("9781234567890")
        assert is_valid is False
        assert isbn13 is None

    def test_none_input(self) -> None:
        is_valid, isbn13 = validate_isbn(None)
        assert is_valid is False
        assert isbn13 is None

    def test_empty_string(self) -> None:
        is_valid, isbn13 = validate_isbn("")
        assert is_valid is False
        assert isbn13 is None


class TestNormalizeTitle:
    """Tests for title normalization."""

    def test_strips_second_edition(self) -> None:
        assert (
            _normalize_title("Refactoring: Improving the Design of Existing Code, Second Edition")
            == "Refactoring: Improving the Design of Existing Code"
        )

    def test_strips_2nd_edition(self) -> None:
        assert _normalize_title("Some Book, 2nd Edition") == "Some Book"

    def test_strips_third_edition(self) -> None:
        assert _normalize_title("Title Third Edition") == "Title"

    def test_strips_4th_edition(self) -> None:
        assert _normalize_title("Algorithms, 4th Edition") == "Algorithms"

    def test_no_edition_unchanged(self) -> None:
        assert _normalize_title("Clean Code") == "Clean Code"

    def test_case_insensitive(self) -> None:
        assert _normalize_title("Book SECOND EDITION") == "Book"


def _mock_google_response(isbn13: str = "9780134685991") -> MagicMock:
    """Create a mock httpx response for Google Books API."""
    resp = MagicMock()
    resp.json.return_value = {
        "items": [
            {
                "volumeInfo": {
                    "title": "Effective Java",
                    "authors": ["Joshua Bloch"],
                    "publisher": "Addison-Wesley",
                    "publishedDate": "2018-01-06",
                    "industryIdentifiers": [
                        {"type": "ISBN_13", "identifier": isbn13},
                    ],
                }
            }
        ]
    }
    return resp


def _mock_openlibrary_isbn_response() -> MagicMock:
    """Create a mock httpx response for Open Library ISBN endpoint."""
    resp = MagicMock()
    resp.json.return_value = {
        "title": "Effective Java",
        "isbn_13": ["9780134685991"],
        "authors": [{"key": "/authors/OL123A"}],
        "publishers": ["Addison-Wesley"],
        "publish_date": "2018",
    }
    return resp


class TestGoogleBooksByIsbn:
    """Tests for Google Books ISBN lookup."""

    @patch("mnemo.epub.enrich.httpx.get")
    def test_success(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_google_response()

        result = _google_books_by_isbn("9780134685991")

        assert result is not None
        assert result.validated_isbn == "9780134685991"
        assert result.source == "google"
        assert result.title == "Effective Java"
        assert result.authors == ["Joshua Bloch"]

    @patch("mnemo.epub.enrich.httpx.get")
    def test_no_results(self, mock_get: MagicMock) -> None:
        resp = MagicMock()
        resp.json.return_value = {"items": []}
        mock_get.return_value = resp

        assert _google_books_by_isbn("9780134685991") is None

    @patch("mnemo.epub.enrich.httpx.get")
    def test_network_error(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = Exception("timeout")

        assert _google_books_by_isbn("9780134685991") is None


class TestOpenLibraryByIsbn:
    """Tests for Open Library ISBN lookup."""

    @patch("mnemo.epub.enrich.httpx.get")
    def test_success(self, mock_get: MagicMock) -> None:
        author_resp = MagicMock()
        author_resp.json.return_value = {"name": "Joshua Bloch"}

        mock_get.side_effect = [_mock_openlibrary_isbn_response(), author_resp]

        result = _open_library_by_isbn("9780134685991")

        assert result is not None
        assert result.source == "openlibrary"
        assert result.title == "Effective Java"

    @patch("mnemo.epub.enrich.httpx.get")
    def test_network_error(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = Exception("timeout")

        assert _open_library_by_isbn("9780134685991") is None


class TestGoogleBooksSearch:
    """Tests for Google Books title/author search."""

    @patch("mnemo.epub.enrich.httpx.get")
    def test_finds_match(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_google_response()

        result = _google_books_search("Effective Java Joshua Bloch")

        assert result is not None
        assert result.validated_isbn == "9780134685991"
        assert result.source == "google"

    @patch("mnemo.epub.enrich.httpx.get")
    def test_no_isbn_in_result(self, mock_get: MagicMock) -> None:
        resp = MagicMock()
        resp.json.return_value = {
            "items": [{"volumeInfo": {"title": "Some Book", "industryIdentifiers": []}}]
        }
        mock_get.return_value = resp

        assert _google_books_search("Some Book") is None


class TestOpenLibrarySearch:
    """Tests for Open Library title/author search."""

    @patch("mnemo.epub.enrich._open_library_by_isbn")
    @patch("mnemo.epub.enrich.httpx.get")
    def test_finds_match_with_isbn_followup(
        self, mock_get: MagicMock, mock_isbn_lookup: MagicMock
    ) -> None:
        resp = MagicMock()
        resp.json.return_value = {
            "docs": [
                {
                    "title": "How to Take Smart Notes",
                    "author_name": ["Sönke Ahrens"],
                    "isbn": ["9783982438801"],
                    "publisher": ["Sönke Ahrens"],
                    "first_publish_year": 2017,
                }
            ]
        }
        mock_get.return_value = resp
        mock_isbn_lookup.return_value = EnrichmentResult(
            validated_isbn="9783982438801",
            source="openlibrary",
            title="How to Take Smart Notes",
            authors=["Sönke Ahrens"],
            publisher="Sönke Ahrens",
            year="2017",
            description="A great book about note-taking.",
        )

        result = _open_library_search("How to Take Smart Notes")

        assert result is not None
        assert result.source == "openlibrary"
        assert result.description == "A great book about note-taking."
        mock_isbn_lookup.assert_called_once_with("9783982438801")

    @patch("mnemo.epub.enrich._open_library_by_isbn")
    @patch("mnemo.epub.enrich.httpx.get")
    def test_isbn_followup_fails_returns_search_result(
        self, mock_get: MagicMock, mock_isbn_lookup: MagicMock
    ) -> None:
        resp = MagicMock()
        resp.json.return_value = {
            "docs": [
                {
                    "title": "How to Take Smart Notes",
                    "author_name": ["Sönke Ahrens"],
                    "isbn": ["9783982438801"],
                    "publisher": ["Sönke Ahrens"],
                    "first_publish_year": 2017,
                }
            ]
        }
        mock_get.return_value = resp
        mock_isbn_lookup.return_value = None

        result = _open_library_search("How to Take Smart Notes")

        assert result is not None
        assert result.source == "openlibrary"
        assert result.title == "How to Take Smart Notes"
        assert result.description is None


class TestLookupByIsbn:
    """Tests for ISBN-based metadata lookup with fallback."""

    @patch("mnemo.epub.enrich._google_books_by_isbn")
    def test_google_success(self, mock_google: MagicMock) -> None:
        mock_google.return_value = EnrichmentResult(validated_isbn="9780134685991", source="google")

        result = lookup_by_isbn("9780134685991")
        assert result.source == "google"

    @patch("mnemo.epub.enrich._open_library_by_isbn")
    @patch("mnemo.epub.enrich._google_books_by_isbn")
    def test_fallback_to_openlibrary(self, mock_google: MagicMock, mock_ol: MagicMock) -> None:
        mock_google.return_value = None
        mock_ol.return_value = EnrichmentResult(
            validated_isbn="9780134685991", source="openlibrary"
        )

        result = lookup_by_isbn("9780134685991")
        assert result.source == "openlibrary"

    @patch("mnemo.epub.enrich._open_library_by_isbn")
    @patch("mnemo.epub.enrich._google_books_by_isbn")
    def test_all_fail(self, mock_google: MagicMock, mock_ol: MagicMock) -> None:
        mock_google.return_value = None
        mock_ol.return_value = None

        result = lookup_by_isbn("9780134685991")
        assert result.error is not None

    @patch("mnemo.epub.enrich._open_library_by_isbn")
    @patch("mnemo.epub.enrich._google_books_by_isbn")
    def test_backfill_description_from_google(
        self,
        mock_google: MagicMock,
        mock_ol: MagicMock,
    ) -> None:
        """When OpenLibrary wins without description, backfill from Google."""
        mock_google.side_effect = [
            None,  # First call: Google lookup fails
            EnrichmentResult(  # Second call: backfill succeeds
                source="google",
                description="A great book.",
            ),
        ]
        mock_ol.return_value = EnrichmentResult(
            validated_isbn="9780134685991",
            source="openlibrary",
            publisher="O'Reilly",
        )

        result = lookup_by_isbn("9780134685991")
        assert result.source == "openlibrary"
        assert result.description == "A great book."

    @patch("mnemo.epub.enrich._google_books_by_isbn")
    def test_no_backfill_when_google_wins(
        self,
        mock_google: MagicMock,
    ) -> None:
        """When Google wins, no redundant backfill call."""
        mock_google.return_value = EnrichmentResult(
            validated_isbn="9780134685991",
            source="google",
            description="Already has one.",
        )

        result = lookup_by_isbn("9780134685991")
        assert result.description == "Already has one."
        mock_google.assert_called_once()

    @patch("mnemo.epub.enrich._open_library_by_isbn")
    @patch("mnemo.epub.enrich._google_books_by_isbn")
    def test_no_backfill_when_description_present(
        self,
        mock_google: MagicMock,
        mock_ol: MagicMock,
    ) -> None:
        """When OpenLibrary already has a description, skip backfill."""
        mock_google.return_value = None
        mock_ol.return_value = EnrichmentResult(
            validated_isbn="9780134685991",
            source="openlibrary",
            description="OL description.",
        )

        result = lookup_by_isbn("9780134685991")
        assert result.description == "OL description."
        # Google was called once (and failed), no backfill call
        mock_google.assert_called_once()


class TestSearchByTitleAuthor:
    """Tests for title/author-based ISBN search."""

    @patch("mnemo.epub.enrich._google_books_search")
    def test_finds_match(self, mock_search: MagicMock) -> None:
        mock_search.return_value = EnrichmentResult(validated_isbn="9780134685991", source="google")

        result = search_by_title_author("Effective Java", ["Joshua Bloch"])
        assert result.validated_isbn == "9780134685991"

    @patch("mnemo.epub.enrich._open_library_search")
    @patch("mnemo.epub.enrich._google_books_search")
    def test_no_results(self, mock_google: MagicMock, mock_ol: MagicMock) -> None:
        mock_google.return_value = None
        mock_ol.return_value = None

        result = search_by_title_author("Nonexistent Book", ["Nobody"])
        assert result.error is not None

    @patch("mnemo.epub.enrich._google_books_search")
    def test_unknown_author_excluded_from_query(self, mock_search: MagicMock) -> None:
        mock_search.return_value = None

        search_by_title_author("Some Book", ["Unknown"])

        # First call args — query should just be the title
        call_args = mock_search.call_args[0]
        assert call_args[0] == "Some Book"

    @patch("mnemo.epub.enrich._google_books_search")
    def test_edition_stripped_from_query(
        self,
        mock_search: MagicMock,
    ) -> None:
        """Edition markers should be stripped before searching."""
        mock_search.return_value = EnrichmentResult(
            validated_isbn="9780134757599",
            source="google",
        )

        search_by_title_author(
            "Refactoring, Second Edition",
            ["Martin Fowler"],
        )

        query = mock_search.call_args[0][0]
        assert "Second Edition" not in query
        assert "Refactoring" in query

    @patch("mnemo.epub.enrich._open_library_search")
    @patch("mnemo.epub.enrich._google_books_search")
    def test_subtitle_retry_on_failure(
        self,
        mock_google: MagicMock,
        mock_ol: MagicMock,
    ) -> None:
        """When full title fails, retry with just the main title."""
        # First round: both fail
        # Second round: Google finds it with short title
        mock_google.side_effect = [
            None,
            EnrichmentResult(
                validated_isbn="9780134757599",
                source="google",
                description="A classic.",
            ),
        ]
        mock_ol.return_value = None

        result = search_by_title_author(
            "Refactoring: Improving the Design of Existing Code",
            ["Martin Fowler"],
        )

        assert result.validated_isbn == "9780134757599"
        # Google was called twice: full query, then short query
        assert mock_google.call_count == 2
        short_query = mock_google.call_args_list[1][0][0]
        assert short_query == "Refactoring Martin Fowler"


class TestEnrichBookMetadata:
    """Tests for the main enrichment entry point."""

    @patch("mnemo.epub.enrich.lookup_by_isbn")
    def test_valid_isbn_does_lookup(self, mock_lookup: MagicMock) -> None:
        mock_lookup.return_value = EnrichmentResult(
            validated_isbn="9780134685991",
            isbn_valid=True,
            source="google",
            title="Effective Java",
        )

        result = enrich_book_metadata("9780134685991", "Effective Java", ["Joshua Bloch"])

        mock_lookup.assert_called_once_with("9780134685991")
        assert result.isbn_valid is True
        assert result.original_isbn == "9780134685991"

    @patch("mnemo.epub.enrich.search_by_title_author")
    def test_invalid_isbn_searches_by_title(self, mock_search: MagicMock) -> None:
        mock_search.return_value = EnrichmentResult(
            validated_isbn="9780134685991",
            isbn_valid=False,
            source="google",
        )

        result = enrich_book_metadata("9781234567890", "Effective Java", ["Joshua Bloch"])

        mock_search.assert_called_once()
        assert result.isbn_valid is False
        assert result.original_isbn == "9781234567890"

    @patch("mnemo.epub.enrich.search_by_title_author")
    def test_missing_isbn_searches_by_title(self, mock_search: MagicMock) -> None:
        mock_search.return_value = EnrichmentResult(
            validated_isbn="9780134685991",
            source="google",
        )

        result = enrich_book_metadata(None, "Effective Java", ["Joshua Bloch"])

        mock_search.assert_called_once()
        assert result.original_isbn is None

    @patch("mnemo.epub.enrich.search_by_title_author")
    @patch("mnemo.epub.enrich.lookup_by_isbn")
    def test_valid_isbn_falls_back_to_title_search(
        self, mock_lookup: MagicMock, mock_search: MagicMock
    ) -> None:
        """When ISBN is valid but lookup finds nothing, fall back to title/author search."""
        mock_lookup.return_value = EnrichmentResult(
            error="No metadata found for ISBN 9781914549090",
        )
        mock_search.return_value = EnrichmentResult(
            validated_isbn="9781914549090",
            source="google",
            title="Personal Knowledge Graphs",
            authors=["Ivo Velitchkov"],
            publisher="Some Publisher",
        )

        result = enrich_book_metadata(
            "9781914549090", "Personal Knowledge Graphs", ["Ivo Velitchkov"]
        )

        mock_lookup.assert_called_once()
        mock_search.assert_called_once()
        assert result.source == "google"
        assert result.isbn_valid is True
        assert result.original_isbn == "9781914549090"

    @patch("mnemo.epub.enrich.search_by_title_author")
    @patch("mnemo.epub.enrich.lookup_by_isbn")
    def test_valid_isbn_fallback_also_fails(
        self, mock_lookup: MagicMock, mock_search: MagicMock
    ) -> None:
        """When both ISBN lookup and title search fail, return the original ISBN error."""
        mock_lookup.return_value = EnrichmentResult(
            error="No metadata found for ISBN 9781914549090",
        )
        mock_search.return_value = EnrichmentResult(
            error="No results found for: Personal Knowledge Graphs",
        )

        result = enrich_book_metadata(
            "9781914549090", "Personal Knowledge Graphs", ["Ivo Velitchkov"]
        )

        assert result.error is not None
        assert "ISBN" in result.error


class TestEnrichBookImpl:
    """Tests for the MCP tool implementation function."""

    def test_invalid_book_id(self) -> None:
        from mnemo.mcp.tools import _enrich_book_impl

        result = _enrich_book_impl("abc")
        assert result.startswith("Error:")

    @patch("mnemo.mcp.tools_metadata.get_connection")
    @patch("mnemo.mcp.tools_metadata.init_db")
    @patch("mnemo.mcp.tools_metadata.BookRepository")
    def test_book_not_found(
        self, mock_repo_cls: MagicMock, mock_init: MagicMock, mock_conn: MagicMock
    ) -> None:
        from mnemo.mcp.tools import _enrich_book_impl

        mock_repo_cls.return_value.get.return_value = None

        result = _enrich_book_impl("abc123")
        assert "not found" in result

    @patch("mnemo.mcp.tools_metadata.get_connection")
    @patch("mnemo.mcp.tools_metadata.init_db")
    @patch("mnemo.mcp.tools_metadata.BookRepository")
    @patch("mnemo.epub.enrich.enrich_book_metadata")
    def test_enrichment_with_result(
        self,
        mock_enrich: MagicMock,
        mock_repo_cls: MagicMock,
        mock_init: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        from mnemo.mcp.tools import _enrich_book_impl
        from mnemo.models import Book

        mock_book = Book(
            id="abc123",
            title="Test Book",
            authors=["Author"],
            isbn="9781234567890",
            file_hash="a" * 64,
            default_language=None,
            structure_source="toc",
            added_at="2024-01-01T00:00:00",
            file_path=None,
        )
        mock_repo_cls.return_value.get.return_value = mock_book
        mock_enrich.return_value = EnrichmentResult(
            original_isbn="9781234567890",
            validated_isbn="9780134685991",
            isbn_valid=False,
            source="google",
            title="Effective Java",
            authors=["Joshua Bloch"],
            publisher="Addison-Wesley",
            year="2018",
        )

        result = _enrich_book_impl("abc123")

        assert "invalid checksum" in result
        assert "9780134685991" in result
        assert "google" in result
        assert "apply=true" in result.lower() or "apply" in result.lower()

    @patch("mnemo.mcp.tools_metadata.get_connection")
    @patch("mnemo.mcp.tools_metadata.init_db")
    @patch("mnemo.mcp.tools_metadata.BookRepository")
    @patch("mnemo.epub.enrich.enrich_book_metadata")
    def test_enrichment_apply(
        self,
        mock_enrich: MagicMock,
        mock_repo_cls: MagicMock,
        mock_init: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        from mnemo.mcp.tools import _enrich_book_impl
        from mnemo.models import Book

        mock_book = Book(
            id="abc123",
            title="Test Book",
            authors=["Author"],
            isbn="9781234567890",
            file_hash="a" * 64,
            default_language=None,
            structure_source="toc",
            added_at="2024-01-01T00:00:00",
            file_path=None,
        )
        mock_repo_cls.return_value.get.return_value = mock_book
        mock_enrich.return_value = EnrichmentResult(
            original_isbn="9781234567890",
            validated_isbn="9780134685991",
            isbn_valid=False,
            source="google",
        )

        result = _enrich_book_impl("abc123", apply=True)

        mock_repo_cls.return_value.update.assert_called_once_with(
            book_id="abc123", isbn="9780134685991"
        )
        assert "updated" in result.lower()

    @patch("mnemo.mcp.tools_metadata.get_connection")
    @patch("mnemo.mcp.tools_metadata.init_db")
    @patch("mnemo.mcp.tools_metadata.BookRepository")
    @patch("mnemo.epub.enrich.enrich_book_metadata")
    def test_prompt_shown_when_metadata_differs_but_isbn_matches(
        self,
        mock_enrich: MagicMock,
        mock_repo_cls: MagicMock,
        mock_init: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Apply prompt should appear when metadata differs, even if ISBN matches."""
        from mnemo.mcp.tools import _enrich_book_impl
        from mnemo.models import Book

        mock_book = Book(
            id="abc123",
            title="Test Book",
            authors=["Author"],
            isbn="9780134685991",
            file_hash="a" * 64,
            default_language=None,
            structure_source="toc",
            added_at="2024-01-01T00:00:00",
            file_path=None,
        )
        mock_repo_cls.return_value.get.return_value = mock_book
        mock_enrich.return_value = EnrichmentResult(
            original_isbn="9780134685991",
            validated_isbn="9780134685991",
            isbn_valid=True,
            source="google",
            publisher="Addison-Wesley",
            year="2018",
        )

        result = _enrich_book_impl("abc123")

        assert "apply=true" in result.lower() or "apply" in result.lower()
