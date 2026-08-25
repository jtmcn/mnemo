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

from mnemo.mcp._deps import make_book_repo, make_chunk_repo, make_search_service
from mnemo.mcp.server import mcp
from mnemo.search import SearchService
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db

if TYPE_CHECKING:
    from mnemo.services.book_service import IntakeOutcome

logger = logging.getLogger(__name__)

# Implementation functions (testable directly via DI)


def _add_book_impl(
    file_path: str,
    force: bool = False,
    chunk_min_tokens: int | None = None,
    chunk_max_tokens: int | None = None,
    collection: str | None = None,
    skip_existing: bool = False,
) -> str:
    """Add book implementation - see add_book for docs.

    Every decision here (validation, duplicate handling, partial success,
    cleanup) belongs to intake(); this function only renders the outcome as
    markdown. intake opens its own DB connection, which keeps this safe to run
    under asyncio.to_thread.
    """
    logger.info(f"add_book: file_path={file_path!r}, force={force}, collection={collection!r}")

    from mnemo.chunking.chunker import ChunkerConfig
    from mnemo.services.book_service import DuplicatePolicy, intake

    validation_error = ChunkerConfig.validate_params(chunk_min_tokens, chunk_max_tokens)
    if validation_error:
        return f"Error: {validation_error}"

    if force and skip_existing:
        return "Error: force and skip_existing are mutually exclusive."

    chunker_config = None
    if chunk_min_tokens is not None or chunk_max_tokens is not None:
        chunker_config = ChunkerConfig(
            min_tokens=chunk_min_tokens or 400,
            max_tokens=chunk_max_tokens or 800,
        )

    policy: DuplicatePolicy = "replace" if force else "skip" if skip_existing else "reject"
    outcome = intake(
        Path(file_path),
        on_duplicate=policy,
        collection=collection,
        chunker_config=chunker_config,
    )

    if outcome.status in ("added", "replaced"):
        make_search_service().invalidate_cache()

    return _render_intake(outcome)


def _render_intake(outcome: "IntakeOutcome") -> str:
    """Turn an IntakeOutcome into the markdown the MCP client sees."""
    book = outcome.book

    if outcome.status == "rejected":
        if outcome.reason == "duplicate" and book is not None:
            authors = ", ".join(book.authors) if book.authors else "Unknown"
            return (
                f'Error: Book already exists - "{book.title}" '
                f"by {authors} (ID: `{book.id}`). "
                f"Use force=true to re-index."
            )
        return f"Error: {outcome.message}"

    assert book is not None, "a non-rejected outcome always carries its book"

    if outcome.status == "already_indexed":
        return f'Skipped (already indexed): "{book.title}" (ID: `{book.id}`)'

    authors = ", ".join(book.authors) if book.authors else "Unknown"
    lines = [f"Added: {book.title} by {authors} (ID: `{book.id}`) - {outcome.chunks} chunks"]
    for note in outcome.notes:
        if note.kind == "embeddings_skipped":
            lines.append(
                f"Note: embeddings were skipped ({note.message}). "
                f"Keyword search works; run reindex_all_books to add semantic search."
            )
        elif note.kind == "suspect_isbn":
            lines.append(f"Note: {note.message}. Use enrich_book to look up the correct ISBN.")
        else:
            lines.append(f"Note: {note.message}")
    return "\n".join(lines)


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

    assert book_repo is not None, "book_repo is required"
    assert chunk_repo is not None, "chunk_repo is required"

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
        partial = sum(1 for r in results if r["status"] == "partial")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "failed")

        headline = f"Reindex complete: {success} succeeded"
        if partial:
            headline += f", {partial} without embeddings"
        headline += f", {skipped} skipped, {failed} failed\n"
        lines = [headline]

        for r in results:
            if r["status"] == "success":
                lines.append(f"- **{r['title']}** (`{r['book_id']}`): {r['chunks']} chunks")
            elif r["status"] == "partial":
                lines.append(
                    f"- **{r['title']}** (`{r['book_id']}`): {r['chunks']} chunks, "
                    f"no embeddings — {r['error']}"
                )
            elif r["status"] == "skipped":
                lines.append(f"- **{r['title']}** (`{r['book_id']}`): skipped — {r['error']}")
            else:
                lines.append(f"- **{r['title']}** (`{r['book_id']}`): FAILED — {r['error']}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("reindex_all_books failed")
        return f"Error: {e}"


def _discard_timed_out_book(file_hash: str) -> None:
    """Best-effort removal of a book left behind by a timed-out ingest."""
    try:
        init_db()
        conn = get_connection()
        try:
            partial = BookRepository(conn).get_by_hash(file_hash)
        finally:
            conn.close()
        if partial:
            from mnemo.ingest import remove_book as pipeline_remove

            pipeline_remove(partial.id)
    except Exception:
        logger.exception("Cleanup after a timed-out add_book did not complete")


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
    skip_existing: bool = False,
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
        skip_existing: If true, an already-indexed book is reported as skipped
            instead of an error. For unattended batches. Cannot be combined
            with force.

    Returns:
        Book details (ID, title, authors, chunk count) on success,
        or an error message starting with "Error:"
    """
    await ctx.info(f"Adding book from {file_path}...")

    # Hash the file before the thread starts: a timeout leaves no return value
    # to clean up from, so the hash has to be captured up front. Validation
    # itself belongs to intake, which reports a bad path as a rejection.
    from mnemo.parsing import pre_parse_metadata

    try:
        file_hash: str | None = pre_parse_metadata(Path(file_path)).file_hash
    except Exception:
        file_hash = None

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _add_book_impl,
                file_path,
                force,
                chunk_min_tokens,
                chunk_max_tokens,
                collection,
                skip_existing,
            ),
            timeout=300,  # 5 minutes
        )
    except TimeoutError:
        # Same trap as intake's cleanup: with force=True the hash may still
        # resolve to the book that was already there, since the worker may not
        # have reached its own delete. Without force, intake would have
        # rejected a duplicate before ingesting, so anything at this hash is
        # ours to remove.
        if file_hash is not None and not force:
            _discard_timed_out_book(file_hash)
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
        make_book_repo(),
        make_chunk_repo(),
        make_search_service(),
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
                make_search_service(),
            ),
            timeout=900,  # 15 minutes
        )
    except TimeoutError:
        return (
            "Error: Reindex timed out after 15 minutes. "
            "Some books may have been partially reindexed."
        )
    return result
