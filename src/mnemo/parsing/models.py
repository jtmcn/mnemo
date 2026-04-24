"""Shared data models for document parsing across all formats."""

from __future__ import annotations

from dataclasses import dataclass, field

from mnemo.models import ContentType


@dataclass
class ContentBlock:
    """Intermediate representation of parsed document content.

    Represents a single block of content extracted from a document,
    with metadata about its type, location, and source. Format-agnostic.

    Attributes:
        content: The text content of the block
        content_type: Classification of the content (TEXT, CODE, etc.)
        section_path: Hierarchical path to this content (e.g., ["Chapter 1", "Section 1.1"])
        language: Programming language for code blocks (e.g., "python")
        source_file: Source identifier (EPUB item href, page number, etc.)
    """

    content: str
    content_type: ContentType = ContentType.TEXT
    section_path: list[str] = field(default_factory=list)
    language: str | None = None
    source_file: str = ""
