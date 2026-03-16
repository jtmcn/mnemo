"""Search data models for Mnemo.

Defines structured representations of search results and filters:
- SearchResult: Unified result with attribution
- SearchFilter: Optional filters for search queries
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class SearchResult:
    """Unified search result with full attribution.

    Represents a single search hit from keyword, semantic, or hybrid search.
    Includes all information needed for display and follow-up queries.

    Attributes:
        chunk_id: UUID of the matched chunk
        book_id: 6-char hex identifier of the source book
        book_title: Human-readable book title for attribution
        content: Full text content of the chunk
        content_type: Type of content (text, code, table, diagram, math)
        section_path: Full hierarchy path (Part > Chapter > Section)
        score: RRF score (higher = more relevant)
        source: Which search method(s) found this result
    """

    chunk_id: str
    book_id: str
    book_title: str
    content: str
    content_type: str
    section_path: list[str]
    score: float
    source: Literal["semantic", "keyword", "both"]
    sequence: int = 0


@dataclass
class SearchFilter:
    """Optional filters for search queries.

    All fields are optional - None means no filter applied.

    Attributes:
        book_id: Filter to specific book (6-char hex)
        content_type: Filter to content type (text, code, table, diagram, math)
    """

    book_id: str | None = None
    content_type: str | None = None
