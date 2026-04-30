"""Book management domain MCP tools for mnemo.

Registers: add_book, remove_book, reindex_all_books
"""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

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


def _add_book_impl(
    file_path: str,
    force: bool = False,
    pre_parsed: "Book | None" = None,
    chunk_min_tokens: int | None = None,
    chunk_max_tokens: int | None = None,
    collection: str | None = None,
) -> str:
    """Add book implementation - see add_book for docs.

    Args:
        file_path: Path to book file (.epub, .docx)
        force: If True, re-index even if duplicate exists
        pre_parsed: Pre-extracted Book metadata (from extract_metadata for EPUB,
            or None for other formats where metadata comes from the full parse).
        chunk_min_tokens: Minimum tokens per chunk (default 400, min 100)
        chunk_max_tokens: Maximum tokens per chunk (default 800, max 2000)
        collection: Optional collection name to tag the book with at ingest.

    Note: This function creates its own DB connection internally for thread safety.
    It does not accept a book_repo parameter because it runs in asyncio.to_thread
    and needs a thread-local connection.
    """
    logger.info(f"add_book: file_path={file_path!r}, force={force}, collection={collection!r}")

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

    # Validate file extension
    from mnemo.parsing import SUPPORTED_FORMATS

    if path.suffix.lower() not in SUPPORTED_FORMATS:
        return (
            f"Error: Unsupported format: {path.suffix} "
            f"(supported: {', '.join(sorted(SUPPORTED_FORMATS))})"
        )

    # Extract metadata if not provided (direct call without async wrapper)
    if pre_parsed is None:
        from mnemo.parsing import pre_parse_metadata

        try:
            pre_parsed = pre_parse_metadata(path)
        except Exception as e:
            return f"Error: Failed to read file: {e}"

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
                collection=collection,
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

        # Check ISBN checksum validity (local only, no network calls)
        if book.isbn:
            from mnemo.epub.enrich import validate_isbn

            is_valid, _ = validate_isbn(book.isbn)
            if not is_valid:
                result += (
                    f"\nNote: ISBN {book.isbn} may be invalid (bad checksum). "
                    f"Use enrich_book to look up the correct ISBN."
                )

        return result
    finally:
        conn.close()


def _remove_book_impl(
    book_id: str,
    book_repo: BookRepository | None = None,
    chunk_repo: ChunkRepository | None = None,
    search_service: SearchService | None = None,
) -> str:
    """Remove book implementation - see remove_book for docs."""
    logger.info(f"remove_book: book_id={book_id}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    try:
        # Fetch book info BEFORE deletion (for the response message)
        book = book_repo.get(book_id)

        if not book:
            return f"Error: Book not found: {book_id}"

        # Get chunk count before deletion
        chunk_count = chunk_repo.count_by_book(book_id)

        # Perform deletion via existing pipeline
        from mnemo.ingest import remove_book as pipeline_remove

        pipeline_remove(book_id)

        # Invalidate search cache
        if search_service is not None:
            search_service.invalidate_cache()

        # Return success message with deleted book info
        authors_str = ", ".join(book.authors) if book.authors else "Unknown"
        return (
            f"Removed: {book.title} by {authors_str} "
            f"(ID: `{book.id}`) - {chunk_count} chunks deleted"
        )

    except Exception as e:
        logger.exception("remove_book failed")
        return f"Error: {e}"


def _reindex_all_books_impl(search_service: SearchService | None = None) -> str:
    """Reindex implementation - see reindex_all_books for docs."""
    logger.info("reindex_all_books called")

    try:
        from mnemo.ingest import reindex_all_books

        results = reindex_all_books(embed=True)

        if not results:
            return "No books in library to reindex."

        # Invalidate search cache
        if search_service is not None:
            search_service.invalidate_cache()

        success = sum(1 for r in results if r["status"] == "success")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "failed")

        lines = [f"Reindex complete: {success} succeeded, {skipped} skipped, {failed} failed\n"]

        for r in results:
            if r["status"] == "success":
                lines.append(f"- **{r['title']}** (`{r['book_id']}`): {r['chunks']} chunks")
            elif r["status"] == "skipped":
                lines.append(f"- **{r['title']}** (`{r['book_id']}`): skipped — {r['error']}")
            else:
                lines.append(f"- **{r['title']}** (`{r['book_id']}`): FAILED — {r['error']}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("reindex_all_books failed")
        return f"Error: {e}"


# MCP tool registrations (delegate to implementations)


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
    collection: str | None = None,
    ctx: Context = CurrentContext(),  # noqa: B008
) -> str:
    """Add a book to your library.

    Parses the book, chunks the content, generates embeddings, and makes it
    searchable. Supports EPUB and DOCX formats. May take 1-5 minutes for
    large books due to embedding generation. Detects duplicates by file hash;
    use force=true to re-index.

    Args:
        file_path: Absolute path to the book file (.epub, .docx)
        force: If true, re-indexes even if the book already exists
        chunk_min_tokens: Minimum tokens per chunk (default 400, min 100)
        chunk_max_tokens: Maximum tokens per chunk (default 800, max 2000)
        collection: Optional collection name to group this book with related
            ones (e.g., "ERCOT Nodal Protocols"). Only applied to fresh ingests;
            for duplicates without force=True, the existing book's collection is
            unchanged. Use update_book_metadata to retag an existing book.

    Returns:
        Book details (ID, title, authors, chunk count) on success,
        or an error message starting with "Error:"
    """
    await ctx.info(f"Adding book from {file_path}...")

    # Validate + extract metadata BEFORE thread (available for timeout cleanup)
    path = Path(file_path)
    if not path.exists():
        return f"Error: File not found: {file_path}"

    from mnemo.parsing import SUPPORTED_FORMATS

    if path.suffix.lower() not in SUPPORTED_FORMATS:
        return (
            f"Error: Unsupported format: {path.suffix} "
            f"(supported: {', '.join(sorted(SUPPORTED_FORMATS))})"
        )

    # Pre-parse metadata for duplicate detection and timeout cleanup
    from mnemo.parsing import pre_parse_metadata

    try:
        pre_parsed = pre_parse_metadata(path)
    except Exception as e:
        return f"Error: Failed to read file: {e}"

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _add_book_impl,
                file_path,
                force,
                pre_parsed,
                chunk_min_tokens,
                chunk_max_tokens,
                collection,
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
    return _remove_book_impl(
        book_id,
        _make_book_repo(),
        _make_chunk_repo(),
        _make_search_service() if _search_service is not None else None,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def reindex_all_books(
    ctx: Context = CurrentContext(),  # noqa: B008
) -> str:
    """Re-index all books in the library.

    Re-parses every book, re-chunks content, and regenerates embeddings.
    Use this after upgrading mnemo to pick up improved chunking or embedding
    changes. Books whose source files are missing on disk are skipped.
    This is a long-running operation (may take several minutes).

    Returns:
        Summary of results per book (success/skipped/failed counts and details),
        or an error message starting with "Error:"
    """
    await ctx.info("Reindexing all books...")

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _reindex_all_books_impl,
                _make_search_service() if _search_service is not None else None,
            ),
            timeout=900,  # 15 minutes
        )
    except TimeoutError:
        return (
            "Error: Reindex timed out after 15 minutes. "
            "Some books may have been partially reindexed."
        )
    return result
