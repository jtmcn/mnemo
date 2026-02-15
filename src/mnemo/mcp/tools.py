"""MCP tool implementations for mnemo.

Each tool is registered with FastMCP via decorator.
Docstrings become tool descriptions for Claude.
Type hints generate JSON schema for parameters.

Note: Implementation functions are prefixed with _ and exposed for testing.
The @mcp.tool decorated versions are the actual MCP tools.
"""

import logging
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


# Implementation functions (testable directly)


def _search_books_impl(
    query: str,
    book_id: str | None = None,
    content_type: Literal["text", "code", "table", "diagram", "math"] | None = None,
    top_k: int = 10,
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid",
) -> str:
    """Search implementation - see search_books for docs."""
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


def _list_available_books_impl() -> str:
    """List implementation - see list_available_books for docs."""
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


def _get_book_info_impl(book_id: str) -> str:
    """Get book info implementation - see get_book_info for docs."""
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


def _remove_book_impl(book_id: str) -> str:
    """Remove book implementation - see remove_book for docs."""
    logger.info(f"remove_book: book_id={book_id}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    try:
        # Fetch book info BEFORE deletion (for the response message)
        book_repo = _get_book_repo()
        book = book_repo.get(book_id)

        if not book:
            return f"Error: Book not found: {book_id}"

        # Get chunk count before deletion
        chunk_repo = ChunkRepository(_db_connection)
        chunk_count = chunk_repo.count_by_book(book_id)

        # Perform deletion via existing pipeline
        from mnemo.ingest import remove_book as pipeline_remove

        pipeline_remove(book_id)

        # Invalidate search cache
        global _search_service
        if _search_service is not None:
            _search_service._book_cache.clear()

        # Return success message with deleted book info
        authors_str = ", ".join(book.authors) if book.authors else "Unknown"
        return (
            f"Removed: {book.title} by {authors_str} "
            f"(ID: `{book.id}`) - {chunk_count} chunks deleted"
        )

    except Exception as e:
        logger.exception("remove_book failed")
        return f"Error: {e}"


def _update_book_metadata_impl(
    book_id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> str:
    """Update book metadata implementation - see update_book_metadata for docs."""
    logger.info(
        f"update_book_metadata: book_id={book_id}, title={title!r}, "
        f"authors={authors!r}, isbn={isbn!r}"
    )

    # Validate book_id
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    # Validate at least one field (before normalization so isbn="" counts)
    if title is None and authors is None and isbn is None:
        return "Error: At least one of title, authors, or isbn must be provided"

    # Validate title not empty
    if title is not None and not title.strip():
        return "Error: title cannot be empty"

    # Normalize empty isbn: treat "" as "clear ISBN" (store NULL in DB)
    if isbn is not None and isbn.strip() == "":
        isbn = ""  # Keep as empty string; repository will store as NULL

    try:
        book_repo = _get_book_repo()
        updated = book_repo.update(
            book_id=book_id, title=title, authors=authors, isbn=isbn
        )

        if updated is None:
            return f"Book not found: {book_id}"

        # Invalidate search cache so search_books reflects changes
        global _search_service
        if _search_service is not None:
            _search_service._book_cache.clear()

        return _get_book_info_impl(book_id)

    except Exception as e:
        logger.exception("update_book_metadata failed")
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


# MCP tool registrations (delegate to implementations)


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
    return _search_books_impl(query, book_id, content_type, top_k, mode)


@mcp.tool
def list_available_books() -> str:
    """List all books in your library.

    Shows all indexed books with their IDs, titles, authors, and chunk counts.
    Use the book_id to filter searches to a specific book.

    Returns:
        Markdown table of available books
    """
    return _list_available_books_impl()


@mcp.tool
def get_book_info(book_id: str) -> str:
    """Get detailed information about a specific book.

    Args:
        book_id: 6-character book identifier (from list_available_books)

    Returns:
        Book details including title, authors, ISBN, and chapter count
    """
    return _get_book_info_impl(book_id)


@mcp.tool
def remove_book(book_id: str) -> str:
    """Remove a book from your library.

    Permanently deletes the book, all its chunks, and search vectors.
    The original EPUB file on disk is not affected.

    Args:
        book_id: 6-character book identifier (from list_available_books)

    Returns:
        Confirmation with deleted book details, or error message
    """
    return _remove_book_impl(book_id)


@mcp.tool
def update_book_metadata(
    book_id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> str:
    """Update a book's metadata (title, authors, or ISBN).

    Changes are saved to the database and immediately reflected in
    search results and book info lookups.

    Args:
        book_id: 6-character book identifier (from list_available_books)
        title: New title for the book
        authors: New list of author names (replaces existing authors)
        isbn: New ISBN for the book (empty string clears ISBN)

    Returns:
        Updated book details, or error message
    """
    return _update_book_metadata_impl(book_id, title, authors, isbn)
