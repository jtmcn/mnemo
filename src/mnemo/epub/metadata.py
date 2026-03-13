"""Dublin Core metadata extraction from EPUB files.

Extracts standard EPUB metadata including title, authors, ISBN, and language.
Handles missing metadata gracefully with appropriate fallbacks.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import ebooklib
from ebooklib import epub

if TYPE_CHECKING:
    from mnemo.models import Book

logger = logging.getLogger(__name__)


def normalize_isbn(raw_isbn: str) -> str | None:
    """Normalize ISBN to standard format (digits and X only).

    Handles various ISBN formats:
    - ISBN-10: 10 digits (last may be X)
    - ISBN-13: 13 digits
    - URN format: urn:isbn:XXXX
    - With hyphens/spaces

    Args:
        raw_isbn: Raw ISBN string from metadata

    Returns:
        Normalized ISBN string or None if invalid
    """
    if not raw_isbn:
        return None

    # Remove URN prefix if present
    isbn = raw_isbn.lower()
    if isbn.startswith("urn:isbn:"):
        isbn = isbn[9:]

    # Remove all non-alphanumeric characters
    isbn = re.sub(r"[^0-9xX]", "", isbn)

    # Normalize X to uppercase
    isbn = isbn.upper()

    # Validate length (ISBN-10 or ISBN-13)
    if len(isbn) == 10:
        # ISBN-10: 9 digits + check digit (digit or X)
        if re.match(r"^\d{9}[\dX]$", isbn):
            return isbn
    elif len(isbn) == 13:
        # ISBN-13: 13 digits only
        if re.match(r"^\d{13}$", isbn):
            return isbn

    logger.warning("Invalid ISBN format: %s", raw_isbn)
    return None


def extract_metadata(epub_path: Path | str) -> "Book":
    """Extract Dublin Core metadata from an EPUB file.

    Parses EPUB metadata and creates a Book model with:
    - Title from dc:title or filename fallback
    - Authors from dc:creator (multiple allowed)
    - ISBN from dc:identifier with ISBN scheme
    - File hash for deduplication
    - Generated book ID

    Args:
        epub_path: Path to the EPUB file

    Returns:
        Book model with extracted metadata (structure_source not set)

    Raises:
        FileNotFoundError: If EPUB file doesn't exist
        ebooklib.epub.EpubException: If file is not a valid EPUB
    """
    from mnemo.models import Book

    epub_path = Path(epub_path)

    if not epub_path.exists():
        raise FileNotFoundError(f"EPUB file not found: {epub_path}")

    # Read EPUB file
    epub_book = epub.read_epub(str(epub_path), options={"ignore_ncx": False})

    # Read raw bytes for hashing
    content_bytes = epub_path.read_bytes()
    file_hash = hashlib.sha256(content_bytes).hexdigest()

    # Extract title
    title = _extract_title(epub_book, epub_path)

    # Extract authors
    authors = _extract_authors(epub_book)

    # Extract ISBN
    isbn = _extract_isbn(epub_book)

    # Extract default language hint
    default_language = _extract_language(epub_book)

    # Create Book model
    return Book.from_metadata(
        title=title,
        authors=authors,
        file_hash=file_hash,
        content_bytes=content_bytes,
        isbn=isbn,
        default_language=default_language,
    )


def _extract_title(epub_book: epub.EpubBook, epub_path: Path) -> str:
    """Extract title from EPUB metadata with filename fallback.

    Args:
        epub_book: Parsed EPUB book object
        epub_path: Path to EPUB file (for fallback)

    Returns:
        Book title string
    """
    title = epub_book.get_metadata("DC", "title")
    if title and title[0] and title[0][0]:
        return str(title[0][0]).strip()

    # Fallback to filename
    fallback_title = epub_path.stem
    logger.warning("Missing title metadata. Using filename: %s", fallback_title)
    return fallback_title


def _extract_authors(epub_book: epub.EpubBook) -> list[str]:
    """Extract author list from EPUB metadata.

    Handles semicolon-delimited creator strings (e.g. "Smith, Alice; Jones, Bob;")
    by splitting on semicolons and filtering empty parts after stripping.

    Args:
        epub_book: Parsed EPUB book object

    Returns:
        List of author names (may be empty list with ["Unknown"] fallback)
    """
    creators = epub_book.get_metadata("DC", "creator")
    if creators:
        raw_strings = [str(c[0]).strip() for c in creators if c and c[0]]
        authors: list[str] = []
        for raw in raw_strings:
            parts = [p.strip() for p in raw.split(";")]
            authors.extend(p for p in parts if p)
        if authors:
            return authors

    logger.warning("Missing author metadata. Using 'Unknown'")
    return ["Unknown"]


def _extract_isbn(epub_book: epub.EpubBook) -> str | None:
    """Extract ISBN from EPUB identifier metadata.

    Looks for identifiers with ISBN scheme or containing ISBN patterns.

    Args:
        epub_book: Parsed EPUB book object

    Returns:
        Normalized ISBN string or None if not found
    """
    identifiers = epub_book.get_metadata("DC", "identifier")
    if not identifiers:
        return None

    for identifier in identifiers:
        if not identifier or not identifier[0]:
            continue

        value = str(identifier[0])
        attrs = identifier[1] if len(identifier) > 1 else {}

        # Check for explicit ISBN scheme
        scheme = attrs.get("{http://www.idpf.org/2007/opf}scheme", "").lower()
        if scheme == "isbn":
            isbn = normalize_isbn(value)
            if isbn:
                return isbn

        # Check for URN format or ISBN prefix
        if "isbn" in value.lower():
            isbn = normalize_isbn(value)
            if isbn:
                return isbn

        # Try to parse as ISBN anyway (some EPUBs omit scheme)
        isbn = normalize_isbn(value)
        if isbn:
            return isbn

    return None


def _extract_language(epub_book: epub.EpubBook) -> str | None:
    """Extract language hint from EPUB metadata.

    Maps book language to likely programming language for code blocks.
    This is a very rough heuristic based on common technical book patterns.

    Args:
        epub_book: Parsed EPUB book object

    Returns:
        Language hint string or None
    """
    # Get the book's primary language
    languages = epub_book.get_metadata("DC", "language")
    if not languages or not languages[0]:
        return None

    # For now, we don't infer programming language from natural language
    # The book title or explicit configuration should be used instead
    # This is just returning the natural language which could be used
    # for text processing hints
    return None
