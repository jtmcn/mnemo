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
    find_front_matter_isbn,
    lookup_by_isbn,
    parse_edition,
    same_text,
    search_by_title_author,
    validate_isbn,
)
from mnemo.models import Book


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
        from mnemo.mcp.tools_metadata import _enrich_book_impl

        result = _enrich_book_impl("abc")
        assert result.startswith("Error:")

    @patch("mnemo.mcp.tools_metadata.get_connection")
    @patch("mnemo.mcp.tools_metadata.init_db")
    @patch("mnemo.mcp.tools_metadata.BookRepository")
    def test_book_not_found(
        self, mock_repo_cls: MagicMock, mock_init: MagicMock, mock_conn: MagicMock
    ) -> None:
        from mnemo.mcp.tools_metadata import _enrich_book_impl

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
        from mnemo.mcp.tools_metadata import _enrich_book_impl
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
        from mnemo.mcp.tools_metadata import _enrich_book_impl
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

        # Unchanged fields are passed as None, which update() treats as "leave alone".
        mock_repo_cls.return_value.update.assert_called_once_with(
            book_id="abc123",
            isbn="9780134685991",
            publisher=None,
            year=None,
            description=None,
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
        from mnemo.mcp.tools_metadata import _enrich_book_impl
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


class TestFindFrontMatterIsbn:
    """ISBNs printed on a book's copyright page, as real publishers format them."""

    def test_oreilly_unlabelled_isbn(self) -> None:
        text = (
            "See http://oreilly.com/catalog/errata.csp?isbn=9781098150761 for release details.\n"
            "978-1-098-15076-1 [LSI]"
        )
        assert find_front_matter_isbn(text) == ("9781098150761", ["9781098150761"])

    def test_isbn10_and_isbn13_of_one_book_count_once(self) -> None:
        text = "ISBN-13: 978-0-13-475759-9 ISBN-10: 0-13-475759-9 1 18"
        assert find_front_matter_isbn(text) == ("9780134757599", ["9780134757599"])

    def test_prefers_the_single_electronic_isbn(self) -> None:
        text = "ISBN 978-3-319-98091-1 e-ISBN 978-3-319-98092-8"
        isbn, candidates = find_front_matter_isbn(text)
        assert isbn == "9783319980928"
        assert candidates == ["9783319980911", "9783319980928"]

    def test_several_electronic_isbns_are_ambiguous(self) -> None:
        text = (
            "ISBN, print ed. 9798898161392 ISBN, Kindle ed. 9798898161408 "
            "ISBN, PDF ed. 9798898161415 Library of Congress"
        )
        isbn, candidates = find_front_matter_isbn(text)
        assert isbn is None
        assert len(candidates) == 3

    def test_bad_checksum_ignored(self) -> None:
        assert find_front_matter_isbn("ISBN 978-1-80181-593-3") == (None, [])

    def test_unlabelled_isbn10_ignored(self) -> None:
        assert find_front_matter_isbn("Call 0-13-475759-9 now") == (None, [])


class TestParseEdition:
    def test_word_ordinal(self) -> None:
        assert parse_edition("Refactoring: Improving the Design, Second Edition") == 2

    def test_numeric_ordinal(self) -> None:
        assert parse_edition("Machine Learning Engineering with Python (2nd Edition)") == 2

    def test_abbreviated_ed(self) -> None:
        assert parse_edition("Refactoring, 2nd ed.") == 2

    def test_short_form_in_filename(self) -> None:
        assert parse_edition("Terraform Up and Running 3e Yevgeniy Brikman.epub") == 3
        assert parse_edition("Refactoring-Improving the Design of Existing Code2E.epub") == 2

    def test_no_edition(self) -> None:
        assert parse_edition("Clean Code.epub") is None
        assert parse_edition("Python 3 Cookbook.epub") is None
        assert parse_edition(None) is None


class TestSameText:
    """Found values that differ only cosmetically must not be offered."""

    def test_spacing_and_case(self) -> None:
        assert same_text("Terraform: Up and Running", "Terraform : up and Running")
        assert same_text("Policy as Code", "Policy As Code")

    def test_diacritics(self) -> None:
        assert same_text("Tomaž Bratanič", "Tomaž Bratanic")

    def test_real_difference(self) -> None:
        assert not same_text("Refactoring", "Refactoring Databases")


class TestRecordEdition:
    """External records carry the edition their title or edition name states."""

    @patch("mnemo.epub.enrich.httpx.get")
    def test_open_library_edition_name(self, mock_get: MagicMock) -> None:
        resp = MagicMock()
        resp.json.return_value = {
            "title": "Refactoring",
            "edition_name": "2nd ed.",
            "isbn_13": ["9780134757599"],
        }
        mock_get.return_value = resp

        result = _open_library_by_isbn("9780134757599")
        assert result is not None
        assert result.edition == 2

    @patch("mnemo.epub.enrich.httpx.get")
    def test_google_search_subtitle(self, mock_get: MagicMock) -> None:
        resp = _mock_google_response("9781837631964")
        resp.json.return_value["items"][0]["volumeInfo"]["subtitle"] = "Second Edition"
        mock_get.return_value = resp

        result = _google_books_search("Machine Learning Engineering with Python")
        assert result is not None
        assert result.edition == 2


class TestEditionGuard:
    """Title search must not hand back another edition's ISBN."""

    @patch("mnemo.epub.enrich._backfill_description")
    @patch("mnemo.epub.enrich._open_library_search")
    @patch("mnemo.epub.enrich._google_books_search")
    def test_rejects_unconfirmed_edition(
        self, mock_google: MagicMock, mock_ol: MagicMock, mock_backfill: MagicMock
    ) -> None:
        mock_google.return_value = None
        mock_ol.return_value = EnrichmentResult(
            validated_isbn="9780201485677", source="openlibrary", title="Refactoring"
        )

        result = search_by_title_author("Refactoring", ["Martin Fowler"], edition=2)

        assert result.validated_isbn is None
        assert result.error is not None
        assert "edition 2" in result.error

    @patch("mnemo.epub.enrich._backfill_description")
    @patch("mnemo.epub.enrich._open_library_search")
    @patch("mnemo.epub.enrich._google_books_search")
    def test_accepts_confirmed_edition(
        self, mock_google: MagicMock, mock_ol: MagicMock, mock_backfill: MagicMock
    ) -> None:
        mock_google.return_value = None
        mock_ol.return_value = EnrichmentResult(
            validated_isbn="9781837631964", source="openlibrary", edition=2
        )

        result = search_by_title_author("ML Engineering with Python", [], edition=2)

        assert result.validated_isbn == "9781837631964"

    @patch("mnemo.epub.enrich._backfill_description")
    @patch("mnemo.epub.enrich._open_library_search")
    @patch("mnemo.epub.enrich._google_books_search")
    def test_rejects_later_edition_when_first_wanted(
        self, mock_google: MagicMock, mock_ol: MagicMock, mock_backfill: MagicMock
    ) -> None:
        mock_google.return_value = None
        mock_ol.return_value = EnrichmentResult(validated_isbn="9781837631964", edition=2)

        result = search_by_title_author("Some Book, First Edition", [], edition=1)

        assert result.validated_isbn is None

    @patch("mnemo.epub.enrich.search_by_title_author")
    def test_edition_read_from_filename(self, mock_search: MagicMock) -> None:
        mock_search.return_value = EnrichmentResult(error="none")

        enrich_book_metadata(
            None,
            "Machine Learning Engineering with Python",
            [],
            file_name="Machine Learning Engineering with Python (2nd Edition).epub",
        )

        assert mock_search.call_args.kwargs["edition"] == 2


class TestIsbnChoice:
    """Which ISBN enrichment proposes for the book."""

    @patch("mnemo.epub.enrich.lookup_by_isbn")
    def test_valid_stored_isbn_kept_when_record_lists_another(self, mock_lookup: MagicMock) -> None:
        mock_lookup.return_value = EnrichmentResult(
            validated_isbn="9781250280541", source="openlibrary", publisher="St. Martin's"
        )

        result = enrich_book_metadata("9781250280558", "Cloud Warriors", ["Thomas E. Weber"])

        assert result.validated_isbn == "9781250280558"
        assert result.metadata_trusted is True

    @patch("mnemo.epub.enrich.search_by_title_author")
    @patch("mnemo.epub.enrich.lookup_by_isbn")
    def test_front_matter_isbn_used_when_stored_missing(
        self, mock_lookup: MagicMock, mock_search: MagicMock
    ) -> None:
        mock_lookup.return_value = EnrichmentResult(
            validated_isbn="9781801815932", source="openlibrary", year="2022"
        )

        result = enrich_book_metadata(
            None,
            "Data Lakehouse in Action",
            [],
            front_matter="Birmingham B3 2PB, UK. ISBN 978-1-80181-593-2 www.packt.com",
        )

        mock_lookup.assert_called_once_with("9781801815932")
        mock_search.assert_not_called()
        assert result.validated_isbn == "9781801815932"
        assert result.isbn_source == "copyright page"

    @patch("mnemo.epub.enrich.search_by_title_author")
    @patch("mnemo.epub.enrich.lookup_by_isbn")
    def test_front_matter_isbn_kept_when_lookups_miss(
        self, mock_lookup: MagicMock, mock_search: MagicMock
    ) -> None:
        mock_lookup.return_value = EnrichmentResult(error="No metadata found")
        mock_search.return_value = EnrichmentResult(error="No results found")

        result = enrich_book_metadata(
            None, "Data Lakehouse in Action", [], front_matter="ISBN 978-1-80181-593-2"
        )

        assert result.validated_isbn == "9781801815932"
        assert result.isbn_source == "copyright page"

    @patch("mnemo.epub.enrich.search_by_title_author")
    @patch("mnemo.epub.enrich.lookup_by_isbn")
    def test_ambiguous_front_matter_noted(
        self, mock_lookup: MagicMock, mock_search: MagicMock
    ) -> None:
        mock_search.return_value = EnrichmentResult(error="No results found")

        result = enrich_book_metadata(
            None,
            "Ontology Pipeline",
            [],
            front_matter="ISBN, Kindle ed. 9798898161408 ISBN, PDF ed. 9798898161415",
        )

        mock_lookup.assert_not_called()
        assert any("9798898161408" in n and "9798898161415" in n for n in result.notes)

    @patch("mnemo.epub.enrich.search_by_title_author")
    @patch("mnemo.epub.enrich.lookup_by_isbn")
    def test_title_fallback_metadata_untrusted_for_known_isbn(
        self, mock_lookup: MagicMock, mock_search: MagicMock
    ) -> None:
        mock_lookup.return_value = EnrichmentResult(error="No metadata found")
        mock_search.return_value = EnrichmentResult(
            validated_isbn="9798898161392", source="google", publisher="Technics"
        )

        result = enrich_book_metadata("9798898161415", "Ontology Pipeline", [])

        assert result.validated_isbn == "9798898161415"
        assert result.metadata_trusted is False

    @patch("mnemo.epub.enrich.search_by_title_author")
    @patch("mnemo.epub.enrich.lookup_by_isbn")
    def test_both_misses_reported(self, mock_lookup: MagicMock, mock_search: MagicMock) -> None:
        mock_lookup.return_value = EnrichmentResult(
            error="No metadata found for ISBN 9798898161415"
        )
        mock_search.return_value = EnrichmentResult(error="No results found for: Ontology")

        result = enrich_book_metadata("9798898161415", "Ontology Pipeline", [])

        assert result.error is not None
        assert "9798898161415" in result.error
        assert "No results found for: Ontology" in result.error


def _book(**overrides: object) -> Book:
    fields: dict[str, object] = {
        "id": "abc123",
        "title": "Terraform: Up and Running",
        "authors": ["Yevgeniy Brikman"],
        "isbn": "9781098116743",
        "file_hash": "a" * 64,
        "added_at": "2024-01-01T00:00:00",
    }
    fields.update(overrides)
    return Book.model_validate(fields)


class TestPlanUpdates:
    """The one change set that both preview and apply use."""

    def test_valid_isbn_never_replaced(self) -> None:
        from mnemo.mcp.tools_metadata import plan_updates

        result = EnrichmentResult(validated_isbn="9781098116736", source="openlibrary")
        assert "isbn" not in plan_updates(_book(), result)

    def test_invalid_isbn_replaced(self) -> None:
        from mnemo.mcp.tools_metadata import plan_updates

        result = EnrichmentResult(validated_isbn="9780134685991")
        plan = plan_updates(_book(isbn="9781234567890"), result)
        assert plan["isbn"] == "9780134685991"

    def test_only_empty_fields_filled(self) -> None:
        from mnemo.mcp.tools_metadata import plan_updates

        result = EnrichmentResult(publisher="de Gruyter GmbH, Walter", year="2022")
        plan = plan_updates(_book(publisher="Packt Publishing"), result)
        assert plan == {"year": "2022"}

    def test_untrusted_metadata_not_applied(self) -> None:
        from mnemo.mcp.tools_metadata import plan_updates

        result = EnrichmentResult(
            publisher="Someone", publisher_confirmed=True, year="1999", metadata_trusted=False
        )
        assert plan_updates(_book(), result) == {}

    def test_unconfirmed_publisher_not_applied(self) -> None:
        from mnemo.mcp.tools_metadata import plan_updates

        result = EnrichmentResult(publisher="O'Reilly Media, Incorporated")
        assert plan_updates(_book(), result) == {}

    def test_confirmed_publisher_applied(self) -> None:
        from mnemo.mcp.tools_metadata import plan_updates

        result = EnrichmentResult(publisher="Packt Publishing", publisher_confirmed=True)
        assert plan_updates(_book(), result) == {"publisher": "Packt Publishing"}

    def test_stub_description_not_applied(self) -> None:
        from mnemo.mcp.tools_metadata import plan_updates

        result = EnrichmentResult(description="2nd edition")
        assert plan_updates(_book(), result) == {}


class TestPublisherConfirmation:
    """A publisher applies only when the book's own front matter names it."""

    def test_named_on_copyright_page(self) -> None:
        from mnemo.epub.enrich import publisher_in_text

        fm = "Published by O’Reilly Media, Inc., 1005 Gravenstein Highway North"
        assert publisher_in_text("O'Reilly Media, Incorporated", fm)

    def test_distributor_not_named(self) -> None:
        from mnemo.epub.enrich import publisher_in_text

        fm = "Published by Packt Publishing Ltd. Livery Place 35 Livery Street"
        assert not publisher_in_text("de Gruyter GmbH, Walter", fm)

    def test_misspelt_publisher(self) -> None:
        from mnemo.epub.enrich import publisher_in_text

        assert not publisher_in_text("Addision-Wesley", "Boston: Addison-Wesley, 2019")

    def test_only_generic_words(self) -> None:
        from mnemo.epub.enrich import publisher_in_text

        assert not publisher_in_text("The Press", "The Press")

    @patch("mnemo.epub.enrich.lookup_by_isbn")
    def test_enrichment_sets_confirmation(self, mock_lookup: MagicMock) -> None:
        mock_lookup.return_value = EnrichmentResult(publisher="Packt Publishing, Limited")

        result = enrich_book_metadata(
            "9781835462140", "Big Data on Kubernetes", [], front_matter="Packt Publishing Ltd."
        )

        assert result.publisher_confirmed is True


class TestEnrichBookPreview:
    @patch("mnemo.mcp.tools_metadata.ChunkRepository")
    @patch("mnemo.mcp.tools_metadata.get_connection")
    @patch("mnemo.mcp.tools_metadata.init_db")
    @patch("mnemo.mcp.tools_metadata.BookRepository")
    @patch("mnemo.epub.enrich.enrich_book_metadata")
    def test_cosmetic_title_and_author_hidden(
        self,
        mock_enrich: MagicMock,
        mock_repo_cls: MagicMock,
        mock_init: MagicMock,
        mock_conn: MagicMock,
        mock_chunks: MagicMock,
    ) -> None:
        from mnemo.mcp.tools_metadata import _enrich_book_impl

        mock_repo_cls.return_value.get.return_value = _book(authors=["Tomaž Bratanič"])
        mock_chunks.return_value.get_chunk_range.return_value = []
        mock_enrich.return_value = EnrichmentResult(
            validated_isbn="9781098116743",
            isbn_valid=True,
            source="openlibrary",
            title="Terraform : up and Running",
            authors=["Tomaž Bratanic"],
        )

        out = _enrich_book_impl("abc123")

        assert "Found title" not in out
        assert "Found authors" not in out

    @patch("mnemo.mcp.tools_metadata.ChunkRepository")
    @patch("mnemo.mcp.tools_metadata.get_connection")
    @patch("mnemo.mcp.tools_metadata.init_db")
    @patch("mnemo.mcp.tools_metadata.BookRepository")
    @patch("mnemo.epub.enrich.enrich_book_metadata")
    def test_preview_lists_exact_changes_and_passes_front_matter(
        self,
        mock_enrich: MagicMock,
        mock_repo_cls: MagicMock,
        mock_init: MagicMock,
        mock_conn: MagicMock,
        mock_chunks: MagicMock,
    ) -> None:
        from mnemo.mcp.tools_metadata import _enrich_book_impl
        from mnemo.models import Chunk, ContentType

        mock_repo_cls.return_value.get.return_value = _book(
            isbn=None, publisher="O'Reilly Media", file_path="/books/Terraform 3e.epub"
        )
        mock_chunks.return_value.get_chunk_range.return_value = [
            Chunk(
                book_id="abc123",
                content="978-1-098-11674-3 [LSI]",
                content_type=ContentType.TEXT,
                token_count=5,
                section_path=["Copyright"],
                sequence=0,
            )
        ]
        mock_enrich.return_value = EnrichmentResult(
            validated_isbn="9781098116743",
            isbn_source="copyright page",
            source="openlibrary",
            publisher="O'Reilly",
            year="2022",
        )

        out = _enrich_book_impl("abc123")

        kwargs = mock_enrich.call_args.kwargs
        assert "978-1-098-11674-3" in kwargs["front_matter"]
        assert kwargs["file_name"] == "Terraform 3e.epub"
        assert "Would update: isbn, year" in out
        mock_repo_cls.return_value.update.assert_not_called()

    @patch("mnemo.mcp.tools_metadata.ChunkRepository")
    @patch("mnemo.mcp.tools_metadata.get_connection")
    @patch("mnemo.mcp.tools_metadata.init_db")
    @patch("mnemo.mcp.tools_metadata.BookRepository")
    @patch("mnemo.epub.enrich.enrich_book_metadata")
    def test_apply_keeps_valid_isbn_and_existing_publisher(
        self,
        mock_enrich: MagicMock,
        mock_repo_cls: MagicMock,
        mock_init: MagicMock,
        mock_conn: MagicMock,
        mock_chunks: MagicMock,
    ) -> None:
        from mnemo.mcp.tools_metadata import _enrich_book_impl

        mock_repo_cls.return_value.get.return_value = _book(
            isbn="9781250280558", publisher="St. Martin's Press", year="2023"
        )
        mock_chunks.return_value.get_chunk_range.return_value = []
        mock_enrich.return_value = EnrichmentResult(
            validated_isbn="9781250280541",
            isbn_valid=True,
            source="openlibrary",
            publisher="de Gruyter GmbH, Walter",
        )

        out = _enrich_book_impl("abc123", apply=True)

        mock_repo_cls.return_value.update.assert_not_called()
        assert "no changes" in out.lower()
