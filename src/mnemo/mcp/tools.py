"""MCP tool implementations for mnemo.

Each tool is registered with FastMCP via decorator.
Docstrings become tool descriptions for Claude.
Type hints generate JSON schema for parameters.
"""

import logging
import sys
from typing import Literal

from mnemo.mcp.server import mcp
from mnemo.search import SearchService
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db

logger = logging.getLogger(__name__)

# Lazy-initialized services (avoid import-time DB connections)
_search_service: SearchService | None = None
_db_connection = None


def _get_search_service() -> SearchService:
    """Get or create SearchService (lazy init)."""
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service


def _get_book_repo() -> BookRepository:
    """Get BookRepository (lazy init)."""
    global _db_connection
    if _db_connection is None:
        init_db()
        _db_connection = get_connection()
    return BookRepository(_db_connection)


@mcp.tool
def search_books(
    query: str,
    book_id: str | None = None,
    content_type: Literal["text", "code", "table", "diagram", "math"] | None = None,
    top_k: int = 10,
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid",
) -> str:
    """Search your book library for relevant content.

    Finds passages from your indexed technical books using hybrid search
    (combines keyword matching with semantic understanding).

    Args:
        query: Search query - can be natural language or specific terms
        book_id: Optional 6-char book ID to search within one book
        content_type: Optional filter for content type
        top_k: Maximum results to return (default 10, max 50)
        mode: Search mode - hybrid (default), semantic, or keyword

    Returns:
        Markdown-formatted search results with source attribution
    """
    logger.info(f"search_books: query={query!r}, book_id={book_id}, top_k={top_k}")

    # Validate inputs
    if not query or not query.strip():
        return "Error: Query cannot be empty"

    top_k = min(max(1, top_k), 50)  # Clamp to 1-50

    try:
        service = _get_search_service()
        results = service.search(
            query=query,
            top_k=top_k,
            book_id=book_id,
            content_type=content_type,
            mode=mode,
        )

        if not results:
            return f"No results found for: {query}"

        return _format_search_results(results)

    except Exception as e:
        logger.exception("search_books failed")
        return f"Search error: {e}"


@mcp.tool
def list_available_books() -> str:
    """List all books in your library.

    Shows all indexed books with their IDs, titles, authors, and chunk counts.
    Use the book_id to filter searches to a specific book.

    Returns:
        Markdown table of available books
    """
    logger.info("list_available_books called")

    try:
        book_repo = _get_book_repo()
        books = book_repo.list_all()

        if not books:
            return "No books indexed yet. Use `mnemo add <path>` to add books."

        lines = ["| ID | Title | Authors | Added |", "|---|---|---|---|"]
        for book in books:
            authors = ", ".join(book.authors) if book.authors else "Unknown"
            added = book.added_at.strftime("%Y-%m-%d")
            lines.append(f"| `{book.id}` | {book.title} | {authors} | {added} |")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("list_available_books failed")
        return f"Error listing books: {e}"


@mcp.tool
def get_book_info(book_id: str) -> str:
    """Get detailed information about a specific book.

    Args:
        book_id: 6-character book identifier (from list_available_books)

    Returns:
        Book details including title, authors, ISBN, and chapter count
    """
    logger.info(f"get_book_info: book_id={book_id}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    try:
        book_repo = _get_book_repo()
        book = book_repo.get(book_id)

        if not book:
            return f"Book not found: {book_id}"

        chunk_repo = ChunkRepository(_db_connection)
        chunk_count = chunk_repo.count_by_book(book_id)

        lines = [
            f"## {book.title}",
            "",
            f"**ID:** `{book.id}`",
            f"**Authors:** {', '.join(book.authors) if book.authors else 'Unknown'}",
            f"**ISBN:** {book.isbn or 'Not available'}",
            f"**Chunks:** {chunk_count}",
            f"**Added:** {book.added_at.strftime('%Y-%m-%d %H:%M')}",
            f"**Structure:** {book.structure_source}",
        ]

        if book.default_language:
            lines.append(f"**Default language:** {book.default_language}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("get_book_info failed")
        return f"Error: {e}"


def _format_search_results(results: list) -> str:
    """Format search results as markdown with attribution.

    Example output per result:
    ---
    **Source:** Python Cookbook > Chapter 3 > Generators
    **Book ID:** a7f3b2 | **Type:** code | **Score:** 0.032

    ```python
    def fibonacci():
        ...
    ```
    ---
    """
    lines = [f"Found {len(results)} results:\n"]

    for result in results:
        section = " > ".join(result.section_path) if result.section_path else "Unknown section"

        lines.append("---")
        lines.append(f"**Source:** {result.book_title} > {section}")
        lines.append(
            f"**Book ID:** `{result.book_id}` | "
            f"**Type:** {result.content_type} | "
            f"**Match:** {result.source}"
        )
        lines.append("")

        # Format content based on type
        content = result.content
        if len(content) > 2000:
            content = content[:2000] + "\n\n[truncated...]"

        if result.content_type == "code":
            lines.append(f"```\n{content}\n```")
        else:
            lines.append(content)

        lines.append("")

    return "\n".join(lines)
