"""Core data models for Mnemo.

Defines the fundamental data structures for representing books and their chunks:
- ContentType: Enum for classifying chunk content (text, code, diagram, etc.)
- Book: Metadata about an indexed book
- Chunk: A unit of content from a book with linking to adjacent chunks
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class ContentType(StrEnum):
    """Classification of chunk content types.

    Used to filter search results and handle content appropriately:
    - TEXT: Regular prose content
    - CODE: Code blocks, config files, shell commands
    - DIAGRAM: ASCII diagrams and visual representations
    - MATH: Mathematical formulas and expressions
    - TABLE: Tabular data converted to searchable text
    """

    TEXT = "text"
    CODE = "code"
    DIAGRAM = "diagram"
    MATH = "math"
    TABLE = "table"


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


def is_boilerplate_section(section_path: list[str]) -> bool:
    """Check if a section path indicates front/back-matter boilerplate."""
    for element in section_path:
        el_lower = element.lower()
        if (
            el_lower in BACKMATTER_SECTIONS
            or el_lower in FRONTMATTER_SECTIONS
            or el_lower.startswith("appendix")
        ):
            return True
    return False


class Book(BaseModel):
    """Metadata about an indexed book.

    The id is a 6-character hex hash derived from content for deduplication
    and human-friendly reference (e.g., mnemo remove a7f3b2).

    Attributes:
        id: 6-char hex hash for identification
        title: Book title from metadata or filename
        authors: List of author names
        isbn: ISBN if available in metadata
        file_hash: Full SHA256 of EPUB content for deduplication
        default_language: Default programming language for untagged code blocks
        structure_source: How chapter structure was determined
        added_at: When the book was indexed
    """

    id: str = Field(min_length=6, max_length=6, pattern=r"^[0-9a-f]{6}$")
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    isbn: str | None = None
    file_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    default_language: str | None = None
    structure_source: Literal["toc", "inferred"] = "toc"
    added_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    file_path: str | None = None
    publisher: str | None = None
    year: str | None = None
    description: str | None = None

    @staticmethod
    def generate_id(content_bytes: bytes, title: str, author: str | None = None) -> str:
        """Generate a 6-character hex ID from book content and metadata.

        Uses SHA256 of content + title + author to create a collision-resistant
        identifier at personal library scale (~thousands of books).

        Args:
            content_bytes: Raw bytes of the EPUB file
            title: Book title
            author: Primary author name (optional)

        Returns:
            6-character lowercase hex string (e.g., "a7f3b2")
        """
        hasher = hashlib.sha256()
        hasher.update(content_bytes)
        hasher.update(title.encode("utf-8"))
        if author:
            hasher.update(author.encode("utf-8"))
        return hasher.hexdigest()[:6]

    @classmethod
    def from_metadata(
        cls,
        title: str,
        authors: list[str],
        file_hash: str,
        content_bytes: bytes,
        isbn: str | None = None,
        default_language: str | None = None,
        structure_source: Literal["toc", "inferred"] = "toc",
    ) -> Book:
        """Create a Book instance from parsed metadata.

        Convenience constructor that handles ID generation automatically.

        Args:
            title: Book title
            authors: List of author names
            file_hash: SHA256 hash of EPUB content
            content_bytes: Raw EPUB bytes (for ID generation)
            isbn: ISBN if available
            default_language: Default language for code blocks
            structure_source: How structure was determined

        Returns:
            Fully initialized Book instance
        """
        primary_author = authors[0] if authors else None
        book_id = cls.generate_id(content_bytes, title, primary_author)

        return cls(
            id=book_id,
            title=title,
            authors=authors,
            isbn=isbn,
            file_hash=file_hash,
            default_language=default_language,
            structure_source=structure_source,
        )


class Chunk(BaseModel):
    """A unit of content from a book.

    Chunks are the fundamental unit for embedding and retrieval. Each chunk
    belongs to exactly one book and maintains links to adjacent chunks for
    context reconstruction (especially important for code-prose relationships).

    Design decisions:
    - Code blocks are never split, regardless of size
    - Section path is full hierarchy (Part > Chapter > Section > Subsection)
    - Chunks spanning section boundaries list all sections
    - Adjacent chunks are linked via prev/next IDs

    Attributes:
        id: UUID for unique identification
        book_id: Reference to parent Book.id
        content: Full text content (for FTS and embedding)
        content_type: Classification of content
        token_count: Token count for chunking decisions
        section_path: Full hierarchy path as list
        sections: All sections this chunk spans (usually 1)
        language: Programming language for code chunks
        sequence: Ordering within book (0-indexed)
        prev_chunk_id: ID of preceding chunk (for context)
        next_chunk_id: ID of following chunk (for context)
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    book_id: str = Field(min_length=6, max_length=6)
    content: str
    content_type: ContentType = ContentType.TEXT
    token_count: int = Field(ge=0)
    section_path: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    language: str | None = None
    sequence: int = Field(ge=0)
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None

    @computed_field
    @property
    def is_code(self) -> bool:
        """Check if this chunk contains code content.

        Convenience property for filtering and handling code-specific logic.

        Returns:
            True if content_type is CODE, False otherwise
        """
        return self.content_type == ContentType.CODE
