"""Search data models for Mnemo.

Defines structured representations of search results and filters:
- SearchResult: Unified result with attribution
- SearchFilter: Optional filters for search queries
- ExpandedResult: A result plus its neighbouring context chunks
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from mnemo.models import Chunk


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


class ExpandedResult(TypedDict):
    """A search result together with the neighbouring chunks around it.

    Produced by SearchService._expand_result_context and rendered by the MCP
    formatters. Heterogeneous by design, hence a TypedDict rather than a
    dict[str, Any].

    Attributes:
        matched_chunk_id: Chunk that actually matched the query
        book_id: 6-char hex identifier of the source book
        start_seq: Sequence number of the first context chunk
        end_seq: Sequence number of the last context chunk
        chunks: The matched chunk plus its in-section neighbours, in order
        matched_chunk_ids: Chunk ids that matched (grows when results merge)
        result: The originating search result
    """

    matched_chunk_id: str
    book_id: str
    start_seq: int
    end_seq: int
    chunks: list[Chunk]
    matched_chunk_ids: set[str]
    result: SearchResult
