"""MCP tool implementations for mnemo.

Each tool is registered with FastMCP via decorator.
Docstrings become tool descriptions for Claude.
Type hints generate JSON schema for parameters.

Note: Implementation functions are prefixed with _ and exposed for testing.
The @mcp.tool decorated versions are the actual MCP tools.
"""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastmcp import Context
from fastmcp.dependencies import CurrentContext
from mcp.types import ToolAnnotations

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
        return f"Error: Search failed: {e}"


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
        return f"Error: Failed to list books: {e}"


def _get_book_info_impl(book_id: str) -> str:
    """Get book info implementation - see get_book_info for docs."""
    logger.info(f"get_book_info: book_id={book_id}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    try:
        book_repo = _get_book_repo()
        book = book_repo.get(book_id)

        if not book:
            return f"Error: Book not found: {book_id}"

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
            f"**EPUB Path:** {book.epub_path or 'Not available'}",
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
            _search_service.invalidate_cache()

        # Return success message with deleted book info
        authors_str = ", ".join(book.authors) if book.authors else "Unknown"
        return (
            f"Removed: {book.title} by {authors_str} "
            f"(ID: `{book.id}`) - {chunk_count} chunks deleted"
        )

    except Exception as e:
        logger.exception("remove_book failed")
        return f"Error: {e}"


def _add_book_impl(file_path: str, force: bool = False, pre_parsed: "Book | None" = None) -> str:
    """Add book implementation - see add_book for docs.

    Args:
        file_path: Path to EPUB file
        force: If True, re-index even if duplicate exists
        pre_parsed: Pre-extracted Book metadata (from extract_metadata).
            When called from async wrapper, metadata is extracted before the thread.
    """
    logger.info(f"add_book: file_path={file_path!r}, force={force}")

    # Validate path exists
    path = Path(file_path)
    if not path.exists():
        return f"Error: File not found: {file_path}"

    # Validate .epub extension
    if path.suffix.lower() != ".epub":
        return f"Error: Not an EPUB file: {file_path} (expected .epub extension)"

    # Extract metadata if not provided (direct call without async wrapper)
    if pre_parsed is None:
        from mnemo.epub.metadata import extract_metadata

        try:
            pre_parsed = extract_metadata(path)
        except Exception as e:
            return f"Error: Failed to read EPUB: {e}"

    # Get own DB connection (thread safe — not shared with async caller)
    init_db()
    conn = get_connection()
    try:
        book_repo = BookRepository(conn)

        # Check for hard duplicate (file hash match)
        existing = book_repo.get_by_hash(pre_parsed.file_hash)

        if existing and not force:
            authors_str = ", ".join(existing.authors) if existing.authors else "Unknown"
            return (
                f'Error: Book already exists - "{existing.title}" '
                f"by {authors_str} (ID: `{existing.id}`). "
                f"Use force=true to re-index."
            )

        # Check for soft duplicate (similar title)
        soft_warning = ""
        if not existing:  # Only check soft dups if not a hash match
            similar = book_repo.find_similar_title(pre_parsed.title)
            if similar:
                sim = similar[0]
                sim_authors = ", ".join(sim.authors) if sim.authors else "Unknown"
                soft_warning = (
                    f'\nNote: Similar book exists - "{sim.title}" '
                    f"by {sim_authors} (ID: `{sim.id}`)"
                )

        # Ingest with embedding
        from mnemo.ingest import ingest_book as pipeline_ingest
        from mnemo.ingest import remove_book as pipeline_remove

        try:
            book, chunk_count = pipeline_ingest(path, embed=True, force=force)
        except Exception as e:
            # Clean up partial data: if book was stored before embedding failed,
            # look it up by hash and remove it
            try:
                cleanup_conn = get_connection()
                cleanup_repo = BookRepository(cleanup_conn)
                partial = cleanup_repo.get_by_hash(pre_parsed.file_hash)
                cleanup_conn.close()
                if partial:
                    pipeline_remove(partial.id)
            except Exception:
                pass  # Best effort cleanup
            return f"Error: Failed to add book: {e}"

        # Invalidate search cache
        global _search_service
        if _search_service is not None:
            _search_service.invalidate_cache()

        # Return success message
        authors_str = ", ".join(book.authors) if book.authors else "Unknown"
        result = (
            f"Added: {book.title} by {authors_str} (ID: `{book.id}`) - {chunk_count} chunks"
        )
        if soft_warning:
            result += soft_warning
        return result
    finally:
        conn.close()


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
    elif isbn is not None:
        from mnemo.epub.metadata import normalize_isbn

        normalized = normalize_isbn(isbn)
        if normalized is None:
            return f"Error: Invalid ISBN format: {isbn!r}. Expected ISBN-10 or ISBN-13."
        isbn = normalized

    try:
        book_repo = _get_book_repo()
        updated = book_repo.update(
            book_id=book_id, title=title, authors=authors, isbn=isbn
        )

        if updated is None:
            return f"Error: Book not found: {book_id}"

        # Invalidate search cache so search_books reflects changes
        global _search_service
        if _search_service is not None:
            _search_service.invalidate_cache()

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

    Returns:
        Markdown-formatted search results with source attribution,
        or an error message starting with "Error:"
    """
    return _search_books_impl(query, book_id, content_type, top_k, mode)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def list_available_books() -> str:
    """List all books in your library.

    Shows all indexed books with their IDs, titles, authors, and date added.
    Call this first to discover book IDs for filtering searches or looking up
    details with get_book_info.

    Returns:
        Markdown table of available books, or a message if the library is empty
    """
    return _list_available_books_impl()


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def get_book_info(book_id: str) -> str:
    """Get detailed information about a specific book.

    Returns title, authors, ISBN, chunk count, structure info, and language
    for one book. Use this to inspect a book's metadata before updating it
    or to check how many chunks a book was split into.

    Args:
        book_id: 6-character book identifier (from list_available_books)

    Returns:
        Markdown-formatted book details, or an error message starting with "Error:"
    """
    return _get_book_info_impl(book_id)


@mcp.tool(
    annotations=ToolAnnotations(
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    )
)
def remove_book(book_id: str) -> str:
    """Remove a book from your library.

    Permanently deletes the book, all its chunks, and search vectors.
    This action cannot be undone. The original EPUB file on disk is not affected.

    Args:
        book_id: 6-character book identifier (from list_available_books)

    Returns:
        Confirmation with deleted book details, or an error message starting with "Error:"
    """
    return _remove_book_impl(book_id)


@mcp.tool(
    annotations=ToolAnnotations(
        idempotentHint=True,
        openWorldHint=False,
    )
)
def update_book_metadata(
    book_id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> str:
    """Update a book's metadata (title, authors, or ISBN).

    Changes are saved immediately and reflected in search results and book info
    lookups. Pass isbn as an empty string to clear it. At least one field must
    be provided.

    Args:
        book_id: 6-character book identifier (from list_available_books)
        title: New title for the book
        authors: New list of author names (replaces all existing authors)
        isbn: New ISBN for the book (empty string clears ISBN)

    Returns:
        Updated book details, or an error message starting with "Error:"
    """
    return _update_book_metadata_impl(book_id, title, authors, isbn)


@mcp.tool(
    annotations=ToolAnnotations(
        openWorldHint=False,
    )
)
async def add_book(
    file_path: str,
    force: bool = False,
    ctx: Context = CurrentContext(),
) -> str:
    """Add an EPUB book to your library.

    Parses the EPUB, chunks the content, generates embeddings, and makes the
    book searchable. May take 1-5 minutes for large books due to embedding
    generation. Detects duplicates by file hash; use force=true to re-index.

    Args:
        file_path: Absolute path to the EPUB file
        force: If true, re-indexes even if the book already exists

    Returns:
        Book details (ID, title, authors, chunk count) on success,
        or an error message starting with "Error:"
    """
    await ctx.info(f"Adding book from {file_path}...")

    # Validate + extract metadata BEFORE thread (available for timeout cleanup)
    path = Path(file_path)
    if not path.exists():
        return f"Error: File not found: {file_path}"
    if path.suffix.lower() != ".epub":
        return f"Error: Not an EPUB file: {file_path} (expected .epub extension)"

    from mnemo.epub.metadata import extract_metadata

    try:
        pre_parsed = extract_metadata(path)
    except Exception as e:
        return f"Error: Failed to read EPUB: {e}"

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_add_book_impl, file_path, force, pre_parsed),
            timeout=300,  # 5 minutes
        )
    except asyncio.TimeoutError:
        # Best effort cleanup using pre_parsed.file_hash (no re-parsing needed)
        try:
            init_db()
            conn = get_connection()
            repo = BookRepository(conn)
            partial = repo.get_by_hash(pre_parsed.file_hash)
            conn.close()
            if partial:
                from mnemo.ingest import remove_book as pipeline_remove

                pipeline_remove(partial.id)
        except Exception:
            pass
        return (
            "Error: Book ingestion timed out after 5 minutes. "
            "The book may be too large or the embedding service may be slow. "
            "Please try again."
        )
    return result
