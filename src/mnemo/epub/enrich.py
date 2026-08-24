"""ISBN validation and metadata enrichment via external services.

Uses isbnlib for local ISBN validation (checksum, format conversion) and
httpx for direct API calls to Google Books and Open Library.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx
import isbnlib  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_TIMEOUT = 10  # seconds per HTTP request
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_EDITION_RE = re.compile(
    r",?\s*\b(?:\d+\w*\s+edition"
    r"|(?:first|second|third|fourth|fifth|sixth|seventh"
    r"|eighth|ninth|tenth)\s+edition)\b",
    re.IGNORECASE,
)


@dataclass
class EnrichmentResult:
    """Result of an ISBN enrichment attempt."""

    original_isbn: str | None = None
    validated_isbn: str | None = None
    isbn_valid: bool = False
    source: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    publisher: str | None = None
    year: str | None = None
    description: str | None = None
    error: str | None = None


def validate_isbn(isbn: str | None) -> tuple[bool, str | None]:
    """Validate ISBN checksum and normalize to ISBN-13.

    Args:
        isbn: ISBN-10 or ISBN-13 string (digits only, no hyphens)

    Returns:
        Tuple of (is_valid, isbn_13_or_none). If valid, returns the
        ISBN-13 form. If invalid or None, returns (False, None).
    """
    if not isbn:
        return False, None

    if isbnlib.is_isbn13(isbn):
        return True, isbn
    if isbnlib.is_isbn10(isbn):
        return True, isbnlib.to_isbn13(isbn)

    return False, None


def _normalize_title(title: str) -> str:
    """Strip edition markers from a title for cleaner search queries."""
    return _EDITION_RE.sub("", title).strip()


def _extract_year(date_str: str | None) -> str | None:
    """Extract a 4-digit year from a date string like '2021', '2018-01-06', or 'May 2021'."""
    if not date_str:
        return None
    m = _YEAR_RE.search(date_str)
    return m.group(1) if m else None


def _google_books_by_isbn(isbn: str) -> EnrichmentResult | None:
    """Query Google Books API by ISBN."""
    try:
        resp = httpx.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": f"isbn:{isbn}", "maxResults": 1},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.debug("Google Books ISBN lookup failed for %s", isbn, exc_info=True)
        return None

    items = data.get("items", [])
    if not items:
        return None

    info = items[0].get("volumeInfo", {})
    isbn13 = None
    for ident in info.get("industryIdentifiers", []):
        if ident.get("type") == "ISBN_13":
            isbn13 = ident["identifier"]
            break

    return EnrichmentResult(
        original_isbn=isbn,
        validated_isbn=isbn13 or isbn,
        isbn_valid=True,
        source="google",
        title=info.get("title"),
        authors=info.get("authors", []),
        publisher=info.get("publisher"),
        year=_extract_year(info.get("publishedDate")),
        description=info.get("description"),
    )


def _open_library_by_isbn(isbn: str) -> EnrichmentResult | None:
    """Query Open Library API by ISBN."""
    try:
        resp = httpx.get(
            f"https://openlibrary.org/isbn/{isbn}.json",
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
        book = resp.json()
    except Exception:
        logger.debug("Open Library ISBN lookup failed for %s", isbn, exc_info=True)
        return None

    # Get ISBN-13 from the response
    isbn13 = None
    for i in book.get("isbn_13", []):
        isbn13 = i
        break

    # Get authors (requires separate request per author key)
    authors = []
    for author_ref in book.get("authors", []):
        key = author_ref.get("key")
        if key:
            try:
                a_resp = httpx.get(
                    f"https://openlibrary.org{key}.json",
                    timeout=_TIMEOUT,
                )
                a_resp.raise_for_status()
                authors.append(a_resp.json().get("name", ""))
            except Exception:
                pass

    # Get description from the works endpoint
    description = None
    works = book.get("works", [])
    if works:
        work_key = works[0].get("key")
        if work_key:
            try:
                w_resp = httpx.get(
                    f"https://openlibrary.org{work_key}.json",
                    timeout=_TIMEOUT,
                )
                w_resp.raise_for_status()
                work = w_resp.json()
                desc = work.get("description")
                if isinstance(desc, dict):
                    desc = desc.get("value")
                if isinstance(desc, str):
                    description = desc
            except Exception:
                pass

    return EnrichmentResult(
        original_isbn=isbn,
        validated_isbn=isbn13 or isbn,
        isbn_valid=True,
        source="openlibrary",
        title=book.get("title"),
        authors=authors,
        publisher=book.get("publishers", [None])[0] if book.get("publishers") else None,
        year=_extract_year(book.get("publish_date")),
        description=description,
    )


def _google_books_search(query: str) -> EnrichmentResult | None:
    """Search Google Books API by title/author query."""
    try:
        resp = httpx.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": query, "maxResults": 1},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.debug("Google Books search failed for %r", query, exc_info=True)
        return None

    items = data.get("items", [])
    if not items:
        return None

    info = items[0].get("volumeInfo", {})
    isbn13 = None
    for ident in info.get("industryIdentifiers", []):
        if ident.get("type") == "ISBN_13":
            isbn13 = ident["identifier"]
            break

    if not isbn13:
        return None

    return EnrichmentResult(
        validated_isbn=isbn13,
        isbn_valid=bool(isbn13 and isbnlib.is_isbn13(isbn13)),
        source="google",
        title=info.get("title"),
        authors=info.get("authors", []),
        publisher=info.get("publisher"),
        year=_extract_year(info.get("publishedDate")),
        description=info.get("description"),
    )


def _open_library_search(query: str) -> EnrichmentResult | None:
    """Search Open Library by title/author query."""
    try:
        resp = httpx.get(
            "https://openlibrary.org/search.json",
            params={
                "q": query,
                "limit": 1,
                "fields": "title,author_name,isbn,publisher,first_publish_year",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.debug("Open Library search failed for %r", query, exc_info=True)
        return None

    docs = data.get("docs", [])
    if not docs:
        return None

    doc = docs[0]
    # Find a valid ISBN-13 from the list
    isbn13 = None
    for candidate in doc.get("isbn", []):
        if len(candidate) == 13 and isbnlib.is_isbn13(candidate):
            isbn13 = candidate
            break

    if not isbn13:
        return None

    # Follow up with ISBN lookup to get full metadata (especially description)
    full_result = _open_library_by_isbn(isbn13)
    if full_result:
        return full_result

    # Fall back to search-only data (no description available)
    year = doc.get("first_publish_year")
    return EnrichmentResult(
        validated_isbn=isbn13,
        isbn_valid=True,
        source="openlibrary",
        title=doc.get("title"),
        authors=doc.get("author_name", []),
        publisher=doc.get("publisher", [None])[0] if doc.get("publisher") else None,
        year=str(year) if year else None,
    )


def _backfill_description(
    result: EnrichmentResult,
    isbn: str,
) -> EnrichmentResult:
    """Try Google Books to fill in a missing description."""
    google = _google_books_by_isbn(isbn)
    if google and google.description:
        result.description = google.description
    return result


def lookup_by_isbn(isbn: str) -> EnrichmentResult:
    """Look up metadata by ISBN from Google Books, then Open Library.

    Args:
        isbn: Valid ISBN-10 or ISBN-13 string

    Returns:
        EnrichmentResult with metadata from the first successful service
    """
    for fn in (_google_books_by_isbn, _open_library_by_isbn):
        result = fn(isbn)
        if result:
            if not result.description and result.source != "google":
                _backfill_description(result, isbn)
            return result

    return EnrichmentResult(
        original_isbn=isbn,
        error=f"No metadata found for ISBN {isbn}",
    )


def search_by_title_author(title: str, authors: list[str]) -> EnrichmentResult:
    """Search for ISBN by title and author when ISBN is missing or invalid.

    Args:
        title: Book title
        authors: List of author names

    Returns:
        EnrichmentResult with the best match, or error if none found
    """
    author_str = " ".join(authors) if authors and authors != ["Unknown"] else ""
    clean_title = _normalize_title(title)
    query = f"{clean_title} {author_str}".strip()

    for fn in (_google_books_search, _open_library_search):
        result = fn(query)
        if result:
            if not result.description and result.validated_isbn:
                _backfill_description(result, result.validated_isbn)
            return result

    # Retry with subtitle stripped if title has a colon
    if ":" in clean_title:
        short_title = clean_title.split(":")[0].strip()
        short_query = f"{short_title} {author_str}".strip()
        if short_query != query:
            for fn in (_google_books_search, _open_library_search):
                result = fn(short_query)
                if result:
                    if not result.description and result.validated_isbn:
                        _backfill_description(
                            result,
                            result.validated_isbn,
                        )
                    return result

    return EnrichmentResult(
        error=f"No results found for: {query}",
    )


def enrich_book_metadata(
    isbn: str | None,
    title: str,
    authors: list[str],
) -> EnrichmentResult:
    """Main enrichment entry point.

    Strategy:
    1. ISBN present + valid checksum -> lookup_by_isbn for confirmation/extra metadata
    2. ISBN present + bad checksum -> search_by_title_author to find correct ISBN
    3. No ISBN -> search_by_title_author

    Args:
        isbn: Current ISBN from EPUB (may be None or have bad checksum)
        title: Book title
        authors: List of author names

    Returns:
        EnrichmentResult with validated ISBN and metadata
    """
    is_valid, isbn13 = validate_isbn(isbn)

    if is_valid and isbn13:
        # ISBN looks good — confirm via external lookup
        result = lookup_by_isbn(isbn13)
        result.original_isbn = isbn
        result.isbn_valid = True
        if result.error:
            # ISBN is valid but not found in any service — try title/author search
            fallback = search_by_title_author(title, authors)
            if not fallback.error:
                fallback.original_isbn = isbn
                fallback.isbn_valid = True
                return fallback
        return result

    # ISBN missing or invalid — search by title/author
    result = search_by_title_author(title, authors)
    result.original_isbn = isbn
    result.isbn_valid = False
    return result
