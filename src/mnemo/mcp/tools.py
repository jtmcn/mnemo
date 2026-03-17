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
from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.dependencies import CurrentContext
from mcp.types import ToolAnnotations

from mnemo.mcp.server import mcp
from mnemo.search import SearchService
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db

if TYPE_CHECKING:
    from mnemo.models import Book

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


def _get_chunk_repo() -> ChunkRepository:
    """Get ChunkRepository (lazy init)."""
    global _db_connection
    if _db_connection is None:
        init_db()
        _db_connection = get_connection()
    return ChunkRepository(_db_connection)


# Implementation functions (testable directly)


def _search_books_impl(
    query: str,
    book_id: str | None = None,
    content_type: Literal["text", "code", "table", "diagram", "math"] | None = None,
    top_k: int = 10,
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid",
    section: str | None = None,
    context_window: int = 0,
    max_chars: int = 2000,
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
        service = _get_search_service()
        results = service.search(
            query=query,
            top_k=top_k,
            book_id=book_id,
            content_type=content_type,
            mode=mode,
            section=section,
            context_window=context_window,
        )

        if not results:
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


def _add_book_impl(
    file_path: str,
    force: bool = False,
    pre_parsed: "Book | None" = None,
    chunk_min_tokens: int | None = None,
    chunk_max_tokens: int | None = None,
) -> str:
    """Add book implementation - see add_book for docs.

    Args:
        file_path: Path to EPUB file
        force: If True, re-index even if duplicate exists
        pre_parsed: Pre-extracted Book metadata (from extract_metadata).
            When called from async wrapper, metadata is extracted before the thread.
        chunk_min_tokens: Minimum tokens per chunk (default 400, min 100)
        chunk_max_tokens: Maximum tokens per chunk (default 800, max 2000)
    """
    logger.info(f"add_book: file_path={file_path!r}, force={force}")

    # Validate chunk size parameters
    from mnemo.chunking.chunker import ChunkerConfig

    validation_error = ChunkerConfig.validate_params(chunk_min_tokens, chunk_max_tokens)
    if validation_error:
        return f"Error: {validation_error}"

    # Build chunker config if custom params provided
    chunker_config = None
    if chunk_min_tokens is not None or chunk_max_tokens is not None:
        chunker_config = ChunkerConfig(
            min_tokens=chunk_min_tokens or 400,
            max_tokens=chunk_max_tokens or 800,
        )

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
                    f'\nNote: Similar book exists - "{sim.title}" by {sim_authors} (ID: `{sim.id}`)'
                )

        # Ingest with embedding
        from mnemo.ingest import ingest_book as pipeline_ingest
        from mnemo.ingest import remove_book as pipeline_remove

        try:
            book, chunk_count = pipeline_ingest(
                path,
                embed=True,
                force=force,
                chunker_config=chunker_config,
            )
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
        result = f"Added: {book.title} by {authors_str} (ID: `{book.id}`) - {chunk_count} chunks"
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
        updated = book_repo.update(book_id=book_id, title=title, authors=authors, isbn=isbn)

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


def _get_book_chunks_impl(
    book_id: str,
    start_sequence: int,
    end_sequence: int,
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
        chunk_repo = _get_chunk_repo()
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


def _format_search_results(results: list, max_chars: int = 2000) -> str:
    """Format search results as markdown with attribution.

    Example output per result:
    ---
    **Source:** Python Cookbook > Chapter 3 > Generators
    **Book ID:** a7f3b2 | **Seq:** 42 | **Type:** code | **Match:** semantic | **Score:** 0.85

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
            f"**Seq:** {result.sequence} | "
            f"**Type:** {result.content_type} | "
            f"**Match:** {result.source} | "
            f"**Score:** {result.score:.2f}"
        )
        lines.append("")

        # Format content based on type
        content = result.content
        if len(content) > max_chars:
            content = (
                content[:max_chars]
                + f"\n\n[truncated at {max_chars} chars"
                + f' — use get_book_chunks(book_id="{result.book_id}",'
                + f" start_sequence={result.sequence},"
                + f" end_sequence={result.sequence}) to read full text]"
            )

        if result.content_type == "code":
            lines.append(f"```\n{content}\n```")
        else:
            lines.append(content)

        lines.append("")

    return "\n".join(lines)


def _format_enriched_results(expanded_results: list[dict], max_chars: int = 2000) -> str:
    """Format enriched search results with context chunk markers.

    Shows each expanded result with matched chunks clearly delineated
    from surrounding context chunks.
    """
    lines = [f"Found {len(expanded_results)} results (with context):\n"]

    for exp in expanded_results:
        result = exp["result"]
        matched_ids = exp["matched_chunk_ids"]

        section = " > ".join(result.section_path) if result.section_path else "Unknown section"

        lines.append("---")
        lines.append(f"**Source:** {result.book_title} > {section}")
        lines.append(
            f"**Book ID:** `{result.book_id}` | "
            f"**Type:** {result.content_type} | "
            f"**Match:** {result.source} | "
            f"**Score:** {result.score:.2f}"
        )

        for chunk in exp["chunks"]:
            lines.append("")
            lines.append("---")
            if chunk.id in matched_ids:
                lines.append(f"**[MATCH \u2014 seq {chunk.sequence}]**")
            else:
                lines.append(f"*[Context \u2014 seq {chunk.sequence}]*")
            lines.append("")

            content = chunk.content
            if len(content) > max_chars:
                content = (
                    content[:max_chars]
                    + f"\n\n[truncated at {max_chars} chars"
                    + f' — use get_book_chunks(book_id="{result.book_id}",'
                    + f" start_sequence={chunk.sequence},"
                    + f" end_sequence={chunk.sequence}) to read full text]"
                )

            if chunk.content_type.value == "code":
                lines.append(f"```\n{content}\n```")
            else:
                lines.append(content)

        lines.append("")

    return "\n".join(lines)


def _format_mixed_results(
    results: list, expanded_map: dict[int, dict], max_chars: int = 2000
) -> str:
    """Format results where some have been auto-expanded with context.

    Regular results render normally. Small atomic chunks that were auto-expanded
    render with their surrounding context chunks for readability.
    """
    lines = [f"Found {len(results)} results:\n"]

    for i, result in enumerate(results):
        if i in expanded_map:
            # Render as enriched result with context
            exp = expanded_map[i]
            matched_ids = exp["matched_chunk_ids"]
            section = " > ".join(result.section_path) if result.section_path else "Unknown section"

            lines.append("---")
            lines.append(f"**Source:** {result.book_title} > {section}")
            lines.append(
                f"**Book ID:** `{result.book_id}` | "
                f"**Seq:** {result.sequence} | "
                f"**Type:** {result.content_type} | "
                f"**Match:** {result.source} | "
                f"**Score:** {result.score:.2f}"
            )

            for chunk in exp["chunks"]:
                lines.append("")
                if chunk.id in matched_ids:
                    lines.append(f"**[MATCH \u2014 seq {chunk.sequence}]**")
                else:
                    lines.append(f"*[Context \u2014 seq {chunk.sequence}]*")
                lines.append("")

                content = chunk.content
                if len(content) > max_chars:
                    content = (
                        content[:max_chars]
                        + f"\n\n[truncated at {max_chars} chars"
                        + f' \u2014 use get_book_chunks(book_id="{result.book_id}",'
                        + f" start_sequence={chunk.sequence},"
                        + f" end_sequence={chunk.sequence}) to read full text]"
                    )

                if chunk.content_type.value == "code":
                    lines.append(f"```\n{content}\n```")
                else:
                    lines.append(content)

            lines.append("")
        else:
            # Render as normal result
            section = " > ".join(result.section_path) if result.section_path else "Unknown section"

            lines.append("---")
            lines.append(f"**Source:** {result.book_title} > {section}")
            lines.append(
                f"**Book ID:** `{result.book_id}` | "
                f"**Seq:** {result.sequence} | "
                f"**Type:** {result.content_type} | "
                f"**Match:** {result.source} | "
                f"**Score:** {result.score:.2f}"
            )
            lines.append("")

            content = result.content
            if len(content) > max_chars:
                content = (
                    content[:max_chars]
                    + f"\n\n[truncated at {max_chars} chars"
                    + f' \u2014 use get_book_chunks(book_id="{result.book_id}",'
                    + f" start_sequence={result.sequence},"
                    + f" end_sequence={result.sequence}) to read full text]"
                )

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
    section: str | None = None,
    context_window: int = 0,
    max_chars: int = 2000,
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
    )


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
    chunk_min_tokens: int | None = None,
    chunk_max_tokens: int | None = None,
    ctx: Context = CurrentContext(),  # noqa: B008
) -> str:
    """Add an EPUB book to your library.

    Parses the EPUB, chunks the content, generates embeddings, and makes the
    book searchable. May take 1-5 minutes for large books due to embedding
    generation. Detects duplicates by file hash; use force=true to re-index.

    Args:
        file_path: Absolute path to the EPUB file
        force: If true, re-indexes even if the book already exists
        chunk_min_tokens: Minimum tokens per chunk (default 400, min 100)
        chunk_max_tokens: Maximum tokens per chunk (default 800, max 2000)

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
            asyncio.to_thread(
                _add_book_impl,
                file_path,
                force,
                pre_parsed,
                chunk_min_tokens,
                chunk_max_tokens,
            ),
            timeout=300,  # 5 minutes
        )
    except TimeoutError:
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


def _get_book_structure_impl(book_id: str) -> str:
    """Get book structure implementation - see get_book_structure for docs."""
    logger.info(f"get_book_structure: book_id={book_id}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    try:
        book_repo = _get_book_repo()
        book = book_repo.get(book_id)
        if not book:
            return f"Error: Book not found: {book_id}"

        chunk_repo = _get_chunk_repo()
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
    return _get_book_structure_impl(book_id)


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
    return _get_book_chunks_impl(book_id, start_sequence, end_sequence)
