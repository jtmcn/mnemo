"""Search domain MCP tools for mnemo.

Registers: search_books, get_book_structure, get_book_chunks
"""

import logging
from typing import TYPE_CHECKING, Literal

from mcp.types import ToolAnnotations

from mnemo.mcp.formatters import (
    _format_enriched_results,
    _format_mixed_results,
    _format_search_results,
)
from mnemo.mcp.server import mcp
from mnemo.search import SearchService
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Lazy-initialized services (avoid import-time DB connections)
_search_service: SearchService | None = None
_db_connection = None


def _make_search_service() -> SearchService:
    """Get or create SearchService (lazy init)."""
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service


def _make_book_repo() -> BookRepository:
    """Get BookRepository (lazy init)."""
    global _db_connection
    if _db_connection is None:
        init_db()
        _db_connection = get_connection()
    return BookRepository(_db_connection)


def _make_chunk_repo() -> ChunkRepository:
    """Get ChunkRepository (lazy init)."""
    global _db_connection
    if _db_connection is None:
        init_db()
        _db_connection = get_connection()
    return ChunkRepository(_db_connection)


# Implementation functions (testable directly via DI)


def _search_books_impl(
    query: str,
    book_id: str | None = None,
    content_type: Literal["text", "code", "table", "diagram", "math"] | None = None,
    top_k: int = 10,
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid",
    section: str | None = None,
    context_window: int = 0,
    max_chars: int = 2000,
    collection: str | None = None,
    *,
    search_service: SearchService | None = None,
) -> str:
    """Search implementation - see search_books for docs."""
    logger.info(f"search_books: query={query!r}, book_id={book_id}, top_k={top_k}")

    # Validate inputs
    if not query or not query.strip():
        return "Error: Query cannot be empty"

    top_k = min(max(1, top_k), 50)  # Clamp to 1-50
    context_window = min(max(0, context_window), 3)  # Clamp to 0-3
    max_chars = min(max(100, max_chars), 10000)  # Clamp to 100-10000

    try:
        service = search_service
        results = service.search(
            query=query,
            top_k=top_k,
            book_id=book_id,
            content_type=content_type,
            mode=mode,
            section=section,
            context_window=context_window,
            collection=collection,
        )

        if not results:
            if section:
                suggestions = service.suggest_sections(section, book_id)
                if suggestions:
                    quoted = ", ".join(f'"{s}"' for s in suggestions)
                    return (
                        f'No results found for: {query} in section "{section}". '
                        f"Did you mean: {quoted}?"
                    )
            return f"No results found for: {query}"

        if context_window >= 1:
            return _format_enriched_results(results, max_chars)

        # Auto-expand small atomic chunks (code/diagram/math) that are too
        # terse to be useful on their own.  Threshold: ~50 tokens ≈ 200 chars.
        _SMALL_CHUNK_CHARS = 200
        _ATOMIC_TYPES = {"code", "diagram", "math"}
        small_indices = [
            i
            for i, r in enumerate(results)
            if r.content_type in _ATOMIC_TYPES and len(r.content) <= _SMALL_CHUNK_CHARS
        ]

        if small_indices:
            expanded_map: dict[int, dict] = {}
            for i in small_indices:
                expanded_map[i] = service._expand_result_context(results[i], window=1)
            return _format_mixed_results(results, expanded_map, max_chars)

        return _format_search_results(results, max_chars)

    except Exception as e:
        logger.exception("search_books failed")
        return f"Error: Search failed: {e}"


def _get_book_structure_impl(
    book_id: str,
    book_repo: BookRepository | None = None,
    chunk_repo: ChunkRepository | None = None,
) -> str:
    """Get book structure implementation - see get_book_structure for docs."""
    logger.info(f"get_book_structure: book_id={book_id}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    try:
        book = book_repo.get(book_id)
        if not book:
            return f"Error: Book not found: {book_id}"

        rows = chunk_repo.get_section_structure(book_id)

        if not rows:
            return f"## {book.title}\n\nNo sections found."

        lines = [f"## {book.title}", ""]
        for sp in rows:
            if not sp:
                continue
            depth = len(sp) - 1
            indent = "  " * depth
            label = sp[-1]
            lines.append(f"{indent}- {label}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("get_book_structure failed")
        return f"Error: {e}"


def _get_book_chunks_impl(
    book_id: str,
    start_sequence: int,
    end_sequence: int,
    chunk_repo: ChunkRepository | None = None,
) -> str:
    """Get book chunks implementation - see get_book_chunks for docs."""
    logger.info(f"get_book_chunks: book_id={book_id}, start={start_sequence}, end={end_sequence}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    range_size = end_sequence - start_sequence + 1
    if range_size > 20:
        return "Error: Range too large (max 20 chunks)"

    if start_sequence < 0:
        return "Error: start_sequence must be >= 0"

    if end_sequence < start_sequence:
        return "Error: end_sequence must be >= start_sequence"

    try:
        chunks = chunk_repo.get_chunk_range(book_id, start_sequence, end_sequence)

        if not chunks:
            return "Error: No chunks found in range"

        lines = []
        for chunk in chunks:
            section = " > ".join(chunk.section_path) if chunk.section_path else "Unknown"
            lines.append(f"**[Seq {chunk.sequence}] {chunk.content_type.value} | {section}**")
            lines.append("")
            lines.append(chunk.content)
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("get_book_chunks failed")
        return f"Error: {e}"


# MCP tool registrations (delegate to implementations)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def search_books(
    query: str,
    book_id: str | None = None,
    content_type: Literal["text", "code", "table", "diagram", "math"] | None = None,
    top_k: int = 10,
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid",
    section: str | None = None,
    context_window: int = 0,
    max_chars: int = 2000,
    collection: str | None = None,
) -> str:
    """Search your book library for relevant content.

    Finds passages, code examples, and explanations from your indexed books
    using hybrid search (combines keyword matching with semantic understanding).
    Use this when the user asks about a topic, concept, API, or code pattern
    that might be covered in their books.

    Args:
        query: Search query - can be natural language questions, specific terms,
               or code patterns
        book_id: Optional 6-char book ID to search within one book only
        content_type: Optional filter - "text", "code", "table", "diagram", or "math"
        top_k: Maximum results to return (default 10, max 50)
        mode: Search mode - hybrid (default, recommended), semantic, or keyword
        section: Optional section name to filter results (e.g., 'Chapter 3',
            'Generators'). Case-insensitive substring match against section
            hierarchy.
        context_window: Number of neighboring chunks to include around each
            match (default 0 = current behavior). Use 1-2 for reading in
            context. Larger windows produce more verbose output. Max 3.
        max_chars: Maximum characters per chunk in output (default 2000, max 10000).
            Truncated results include a hint to use get_book_chunks for full text.
        collection: Optional collection name to search within (e.g.,
            'ERCOT Nodal Protocols'). Restricts results to books in that
            collection. Use list_available_books to see collection names.

    Returns:
        Markdown-formatted search results with source attribution,
        or an error message starting with "Error:"
    """
    return _search_books_impl(
        query,
        book_id,
        content_type,
        top_k,
        mode,
        section,
        context_window,
        max_chars,
        collection,
        search_service=_make_search_service(),
    )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def get_book_structure(book_id: str) -> str:
    """Get the section hierarchy for a book.

    Returns an indented markdown outline of all sections in a book,
    ordered by reading sequence. Use this before searching to understand
    what chapters or sections exist, then pass a section name to
    search_books to filter results.

    Args:
        book_id: 6-character book identifier (from list_available_books)

    Returns:
        Indented markdown section outline, or an error message starting with "Error:"
    """
    return _get_book_structure_impl(book_id, _make_book_repo(), _make_chunk_repo())


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def get_book_chunks(
    book_id: str,
    start_sequence: int,
    end_sequence: int,
) -> str:
    """Fetch contiguous chunks from a book for deep reading.

    Returns up to 20 consecutive chunks ordered by sequence number.
    Use after search_books to read surrounding context.

    Args:
        book_id: 6-character book identifier (from list_available_books)
        start_sequence: First chunk sequence number to fetch (0-indexed)
        end_sequence: Last chunk sequence number to fetch (inclusive)

    Returns:
        Markdown-formatted chunks with content, section path, content type,
        and sequence number, or an error message starting with "Error:"
    """
    return _get_book_chunks_impl(book_id, start_sequence, end_sequence, _make_chunk_repo())
