"""Metadata domain MCP tools for mnemo.

Registers: list_available_books, get_book_info, update_book_metadata, enrich_book
"""

import asyncio
import logging

from fastmcp import Context
from fastmcp.dependencies import CurrentContext
from mcp.types import ToolAnnotations

from mnemo.mcp._deps import make_book_repo, make_chunk_repo, make_search_service
from mnemo.mcp.server import mcp
from mnemo.search import SearchService
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db

logger = logging.getLogger(__name__)

# Implementation functions (testable directly via DI)


def _list_available_books_impl(book_repo: BookRepository | None = None) -> str:
    """List implementation - see list_available_books for docs."""
    logger.info("list_available_books called")

    assert book_repo is not None, "book_repo is required"

    try:
        books = book_repo.list_all()

        if not books:
            return "No books indexed yet. Use `mnemo add <path>` to add books."

        lines = [
            "| ID | Title | Authors | Collection | Description |",
            "|---|---|---|---|---|",
        ]
        for book in books:
            authors = ", ".join(book.authors) if book.authors else "Unknown"
            coll = book.collection or ""
            desc = ""
            if book.description:
                desc = (
                    book.description[:80] + "..."
                    if len(book.description) > 80
                    else book.description
                )
            lines.append(f"| `{book.id}` | {book.title} | {authors} | {coll} | {desc} |")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("list_available_books failed")
        return f"Error: Failed to list books: {e}"


def _get_book_info_impl(
    book_id: str,
    book_repo: BookRepository | None = None,
    chunk_repo: ChunkRepository | None = None,
) -> str:
    """Get book info implementation - see get_book_info for docs."""
    logger.info(f"get_book_info: book_id={book_id}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    assert book_repo is not None, "book_repo is required"
    assert chunk_repo is not None, "chunk_repo is required"

    try:
        book = book_repo.get(book_id)

        if not book:
            return f"Error: Book not found: {book_id}"

        chunk_count = chunk_repo.count_by_book(book_id)

        lines = [
            f"## {book.title}",
            "",
            f"**ID:** `{book.id}`",
            f"**Authors:** {', '.join(book.authors) if book.authors else 'Unknown'}",
            f"**ISBN:** {book.isbn or 'Not available'}",
        ]

        if book.publisher:
            lines.append(f"**Publisher:** {book.publisher}")
        if book.year:
            lines.append(f"**Year:** {book.year}")
        if book.collection:
            lines.append(f"**Collection:** {book.collection}")

        lines.extend(
            [
                f"**Chunks:** {chunk_count}",
                f"**Added:** {book.added_at.strftime('%Y-%m-%d %H:%M')}",
                f"**Structure:** {book.structure_source}",
                f"**File Path:** {book.file_path or 'Not available'}",
            ]
        )

        if book.default_language:
            lines.append(f"**Default language:** {book.default_language}")
        if book.description:
            lines.append(f"\n**Description:** {book.description}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("get_book_info failed")
        return f"Error: {e}"


def _update_book_metadata_impl(
    book_id: str,
    book_repo: BookRepository | None = None,
    chunk_repo: ChunkRepository | None = None,
    search_service: SearchService | None = None,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
    collection: str | None = None,
) -> str:
    """Update book metadata implementation - see update_book_metadata for docs."""
    logger.info(
        f"update_book_metadata: book_id={book_id}, title={title!r}, "
        f"authors={authors!r}, isbn={isbn!r}, collection={collection!r}"
    )

    # Validate book_id
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    # Validate at least one field (before normalization so isbn="" counts)
    if title is None and authors is None and isbn is None and collection is None:
        return "Error: At least one of title, authors, isbn, or collection must be provided"

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

    assert book_repo is not None, "book_repo is required"
    assert chunk_repo is not None, "chunk_repo is required"

    try:
        updated = book_repo.update(
            book_id=book_id,
            title=title,
            authors=authors,
            isbn=isbn,
            collection=collection,
        )

        if updated is None:
            return f"Error: Book not found: {book_id}"

        # Invalidate search cache so search_books reflects changes
        if search_service is not None:
            search_service.invalidate_cache()

        return _get_book_info_impl(book_id, book_repo, chunk_repo)

    except Exception as e:
        logger.exception("update_book_metadata failed")
        return f"Error: {e}"


def _enrich_book_impl(book_id: str, apply: bool = False) -> str:
    """Enrich a book's metadata via external lookup.

    Args:
        book_id: 6-char hex book identifier
        apply: If True, automatically apply found metadata
    """
    logger.info(f"enrich_book: book_id={book_id}, apply={apply}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    # Get own DB connection (thread safe — not shared with async caller)
    init_db()
    conn = get_connection()
    try:
        book_repo = BookRepository(conn)
        book = book_repo.get(book_id)
        if not book:
            return f"Error: Book not found: {book_id}"

        from mnemo.epub.enrich import enrich_book_metadata

        result = enrich_book_metadata(book.isbn, book.title, book.authors)

        # Format output
        lines = [f"## Enrichment: {book.title}", ""]

        # Current state
        if book.isbn:
            status = "valid" if result.isbn_valid else "invalid checksum"
            lines.append(f"**Current ISBN:** {book.isbn} ({status})")
        else:
            lines.append("**Current ISBN:** none")

        # Result
        if result.error:
            lines.append(f"**Lookup:** {result.error}")
            return "\n".join(lines)

        if result.validated_isbn:
            lines.append(f"**Found ISBN:** {result.validated_isbn} (via {result.source})")
        if result.title:
            lines.append(f"**Found title:** {result.title}")
        if result.authors:
            lines.append(f"**Found authors:** {', '.join(result.authors)}")
        if result.publisher:
            lines.append(f"**Publisher:** {result.publisher}")
        if result.year:
            lines.append(f"**Year:** {result.year}")
        if result.description:
            desc_preview = result.description[:200]
            if len(result.description) > 200:
                desc_preview += "..."
            lines.append(f"**Description:** {desc_preview}")

        # Apply if requested
        if apply:
            update_kwargs: dict[str, str] = {}
            if result.validated_isbn and result.validated_isbn != book.isbn:
                update_kwargs["isbn"] = result.validated_isbn
            if result.publisher and result.publisher != book.publisher:
                update_kwargs["publisher"] = result.publisher
            if result.year and result.year != book.year:
                update_kwargs["year"] = result.year
            if result.description and result.description != book.description:
                update_kwargs["description"] = result.description

            if update_kwargs:
                # Named rather than **kwargs: update() treats None as "leave
                # alone", so .get() on the absent keys is equivalent and typed.
                book_repo.update(
                    book_id=book_id,
                    isbn=update_kwargs.get("isbn"),
                    publisher=update_kwargs.get("publisher"),
                    year=update_kwargs.get("year"),
                    description=update_kwargs.get("description"),
                )

                make_search_service().invalidate_cache()

                fields = ", ".join(update_kwargs.keys())
                lines.append("")
                lines.append(f"Updated: {fields}.")
            else:
                lines.append("")
                lines.append("All metadata is up to date — no changes needed.")
        else:
            has_updates = (
                (result.validated_isbn and result.validated_isbn != book.isbn)
                or (result.publisher and result.publisher != book.publisher)
                or (result.year and result.year != book.year)
                or (result.description and result.description != book.description)
            )
            if has_updates:
                lines.append("")
                lines.append(
                    "Use `enrich_book` with `apply=true` to update, "
                    "or `update_book_metadata` to set manually."
                )

        return "\n".join(lines)

    except Exception as e:
        logger.exception("enrich_book failed")
        return f"Error: {e}"
    finally:
        conn.close()


# MCP tool registrations (delegate to implementations)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def list_available_books() -> str:
    """List all books in your library.

    Shows all indexed books with their IDs, titles, authors, collection,
    and a short description. Call this first to discover book IDs for
    filtering searches or looking up details with get_book_info.

    Returns:
        Markdown table of available books, or a message if the library is empty
    """
    return _list_available_books_impl(make_book_repo())


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
    return _get_book_info_impl(book_id, make_book_repo(), make_chunk_repo())


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
    collection: str | None = None,
) -> str:
    """Update a book's metadata (title, authors, ISBN, or collection).

    Changes are saved immediately and reflected in search results and book info
    lookups. Pass isbn as an empty string to clear it. Pass collection as an
    empty string to remove a book from its collection. At least one field must
    be provided.

    For new ingests, prefer passing `collection` directly to `add_book` instead
    of ingesting first and then updating here.

    Args:
        book_id: 6-character book identifier (from list_available_books)
        title: New title for the book
        authors: New list of author names (replaces all existing authors)
        isbn: New ISBN for the book (empty string clears ISBN)
        collection: Collection name to group related books (empty string removes from collection)

    Returns:
        Updated book details, or an error message starting with "Error:"
    """
    return _update_book_metadata_impl(
        book_id,
        make_book_repo(),
        make_chunk_repo(),
        make_search_service(),
        title,
        authors,
        isbn,
        collection,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        openWorldHint=True,
    )
)
async def enrich_book(
    book_id: str,
    apply: bool = False,
    ctx: Context = CurrentContext(),  # noqa: B008
) -> str:
    """Enrich a book's metadata via Google Books and Open Library.

    Validates the ISBN checksum, looks up or searches for the book in external
    services, and returns any metadata found (publisher, year, description, authors).
    Use apply=true to automatically update the book's metadata, or review first.

    Args:
        book_id: 6-character book identifier (from list_available_books)
        apply: If true, automatically update the book's metadata with found values

    Returns:
        Enrichment results showing current vs. found ISBN, or error message
    """
    await ctx.info(f"Enriching metadata for book {book_id}...")
    return await asyncio.to_thread(_enrich_book_impl, book_id, apply)
