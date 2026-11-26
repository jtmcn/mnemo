"""ISBN validation and metadata enrichment via external services.

Uses isbnlib for local ISBN validation (checksum, format conversion) and
httpx for direct API calls to Google Books and Open Library.
"""

from __future__ import annotations

import logging
import re
import unicodedata
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
_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}
_EDITION_PATTERNS = (
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s+ed(?:ition)?\b", re.IGNORECASE),
    re.compile(rf"\b({'|'.join(_ORDINALS)})\s+edition\b", re.IGNORECASE),
    # Filename shorthand: "Running 3e", "Code2E"
    re.compile(r"(?<!\d)(\d{1,2})e\b", re.IGNORECASE),
)
# Hyphens only between digits; a space would let an ISBN swallow a page number.
_ISBN13_RE = re.compile(r"(?<![\d-])97[89](?:-?\d){10}(?!\d)")
_ISBN10_RE = re.compile(r"ISBN(?:-?10)?\s*:?\s*(\d[\d-]{8,11}[\dXx])(?![\dXx-])")
_ELECTRONIC_RE = re.compile(
    r"\be-?isbn|\be-?book|\bepub|\bpdf|\bkindle|\bdigital|\belectronic|\bonline",
    re.IGNORECASE,
)
_PAREN_LABEL_RE = re.compile(r"\s*\(([^)]{0,30})\)")


@dataclass
class EnrichmentResult:
    """Result of an ISBN enrichment attempt.

    validated_isbn is the ISBN proposed for the book; isbn_source says where it
    came from. metadata_trusted is False when publisher/year/description describe
    a record whose ISBN is not the book's, so they must not be applied.
    publisher_confirmed is True only when the book's front matter names the publisher.
    """

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
    edition: int | None = None
    isbn_source: str | None = None
    metadata_trusted: bool = True
    publisher_confirmed: bool = False
    notes: list[str] = field(default_factory=list)


def parse_edition(text: str | None) -> int | None:
    """Edition number stated in a title, filename or edition name, if any."""
    if not text:
        return None
    for pattern in _EDITION_PATTERNS:
        m = pattern.search(text)
        if m:
            word = m.group(1).lower()
            number = _ORDINALS.get(word) or int(word)
            if number > 0:
                return number
    return None


def _edition_matches(wanted: int | None, found: int | None) -> bool:
    if wanted is None:
        return True
    if wanted == 1:
        return found in (None, 1)
    # Unmarked records are usually first editions, so they can't confirm a later one.
    return found == wanted


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if c.isalnum()).casefold()


def same_text(a: str, b: str) -> bool:
    """True when a and b differ only in case, spacing, punctuation or diacritics."""
    return _fold(a) == _fold(b)


_GENERIC_PUBLISHER_WORDS = frozenset(
    {
        "and",
        "book",
        "books",
        "company",
        "corp",
        "corporation",
        "gmbh",
        "group",
        "house",
        "inc",
        "incorporated",
        "international",
        "limited",
        "llc",
        "ltd",
        "media",
        "press",
        "publications",
        "publisher",
        "publishers",
        "publishing",
        "the",
    }
)


def publisher_in_text(publisher: str, text: str) -> bool:
    """True when every distinctive word of publisher appears in text.

    Catalogues often name a distributor ("de Gruyter GmbH, Walter" for Packt)
    or misspell the imprint, so a publisher counts only if the book names it.
    """
    words = (_fold(w) for w in re.split(r"[\s,;/&]+", publisher))
    distinctive = [w for w in words if len(w) >= 3 and w not in _GENERIC_PUBLISHER_WORDS]
    folded = _fold(text)
    return bool(distinctive) and all(w in folded for w in distinctive)


def find_front_matter_isbn(text: str) -> tuple[str | None, list[str]]:
    """Find the book's own ISBN in its front matter (usually the copyright page).

    Returns (isbn13, all distinct ISBN-13s found). When several are printed,
    the single one labelled electronic wins; otherwise the choice is None.
    """
    found: dict[str, bool] = {}  # isbn13 -> labelled electronic
    prev_end = 0
    hits = [(m.start(), m.end(), m.group(0)) for m in _ISBN13_RE.finditer(text)]
    hits += [(m.start(1), m.end(1), m.group(1)) for m in _ISBN10_RE.finditer(text)]
    for start, end, raw in sorted(hits):
        valid, isbn13 = validate_isbn(raw.replace("-", "").upper())
        if not valid or isbn13 is None:
            continue
        label = text[max(prev_end, start - 40) : start]
        paren = _PAREN_LABEL_RE.match(text, end)
        if paren:
            label += paren.group(1)
        found[isbn13] = found.get(isbn13, False) or bool(_ELECTRONIC_RE.search(label))
        prev_end = end

    candidates = list(found)
    if len(candidates) == 1:
        return candidates[0], candidates
    electronic = [isbn for isbn, is_electronic in found.items() if is_electronic]
    if len(electronic) == 1:
        return electronic[0], candidates
    return None, candidates


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
        edition=_google_edition(info),
    )


def _google_edition(info: dict[str, str]) -> int | None:
    return parse_edition(f"{info.get('title', '')} {info.get('subtitle', '')}")


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
        edition=parse_edition(
            " ".join(book.get(k) or "" for k in ("title", "subtitle", "edition_name"))
        ),
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
        edition=_google_edition(info),
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


def search_by_title_author(
    title: str,
    authors: list[str],
    edition: int | None = None,
) -> EnrichmentResult:
    """Search for ISBN by title and author when ISBN is missing or invalid.

    Args:
        title: Book title
        authors: List of author names
        edition: Edition the book states; hits that don't confirm it are rejected

    Returns:
        EnrichmentResult with the best match, or error if none found
    """
    author_str = " ".join(authors) if authors and authors != ["Unknown"] else ""
    clean_title = _normalize_title(title)
    query = f"{clean_title} {author_str}".strip()
    queries = [query]
    # Retry with subtitle stripped if title has a colon
    if ":" in clean_title:
        short_query = f"{clean_title.split(':')[0].strip()} {author_str}".strip()
        if short_query != query:
            queries.append(short_query)

    rejected: list[str] = []
    for q in queries:
        for fn in (_google_books_search, _open_library_search):
            result = fn(q)
            if not result:
                continue
            if not _edition_matches(edition, result.edition):
                rejected.append(result.validated_isbn or "?")
                continue
            if not result.description and result.validated_isbn:
                _backfill_description(result, result.validated_isbn)
            return result

    if rejected:
        return EnrichmentResult(
            error=(
                f"No match confirmed as edition {edition} for: {query} "
                f"(rejected {', '.join(dict.fromkeys(rejected))})"
            ),
        )
    return EnrichmentResult(
        error=f"No results found for: {query}",
    )


def enrich_book_metadata(
    isbn: str | None,
    title: str,
    authors: list[str],
    *,
    file_name: str | None = None,
    front_matter: str = "",
) -> EnrichmentResult:
    """Main enrichment entry point.

    The book's ISBN is, in order: the stored one if its checksum is valid
    (never replaced), else the one on the copyright page in front_matter, else
    a title search hit that confirms any edition the title or file_name states.
    The known ISBN is then looked up; if that misses, a title search fills in
    metadata, flagged untrusted unless it matches the known ISBN.

    Args:
        isbn: Current ISBN from EPUB (may be None or have bad checksum)
        title: Book title
        authors: List of author names
        file_name: Source file name, checked for an edition marker
        front_matter: Text of the book's first chunks

    Returns:
        EnrichmentResult with validated ISBN and metadata
    """
    is_valid, isbn13 = validate_isbn(isbn)
    edition = parse_edition(title) or parse_edition(file_name)
    notes: list[str] = []

    known: str | None = None
    isbn_source: str | None = None
    if is_valid and isbn13:
        known, isbn_source = isbn13, "stored"
    else:
        printed, candidates = find_front_matter_isbn(front_matter)
        if printed:
            known, isbn_source = printed, "copyright page"
        elif len(candidates) > 1:
            notes.append(
                "Copyright page lists several ISBNs, none clearly this file's: "
                + ", ".join(candidates)
            )

    if known:
        result = lookup_by_isbn(known)
        if result.error:
            fallback = search_by_title_author(title, authors, edition=edition)
            if not fallback.error:
                result = fallback
                result.metadata_trusted = fallback.validated_isbn == known
            elif isbn_source == "stored":
                result.error = f"{result.error}; title search: {fallback.error}"
            else:
                # The printed ISBN is still worth proposing without metadata.
                notes.append(f"{result.error}; title search: {fallback.error}")
                result = EnrichmentResult()
        result.validated_isbn = known
        result.isbn_source = isbn_source
    else:
        result = search_by_title_author(title, authors, edition=edition)
        result.isbn_source = result.source

    result.original_isbn = isbn
    result.isbn_valid = is_valid
    result.publisher_confirmed = bool(
        result.publisher and publisher_in_text(result.publisher, front_matter)
    )
    result.notes = notes + result.notes
    return result
