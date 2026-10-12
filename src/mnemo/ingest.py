"""End-to-end book ingestion pipeline.

Wires together the parser, chunker, storage, and optionally embedding
components to provide a simple API for adding and removing books.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, TypeVar

from mnemo.chunking import Chunker, ChunkerConfig
from mnemo.models import Book, is_boilerplate_section
from mnemo.parsing import ContentBlock, parse_book
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db

logger = __import__("logging").getLogger(__name__)

T = TypeVar("T")


class ReindexResult(TypedDict):
    """Per-book outcome from reindex_all_books."""

    book_id: str
    title: str
    status: Literal["success", "partial", "skipped", "failed", "merged"]
    chunks: int
    error: str | None


class NothingToEmbed(ValueError):
    """The book has no chunks worth embedding (all front/back matter).

    Re-running the embedding step can never produce vectors for this book,
    so callers must not advise a retry.
    """


def _batch_items(items: list[T], batch_size: int = 50) -> Iterator[list[T]]:
    """Yield successive batches of items."""
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def embed_book(
    book_id: str,
    db_path: Path | None = None,
    chroma_path: Path | None = None,
    batch_size: int = 50,
) -> int:
    """Generate and store embeddings for an already-ingested book.

    Retrieves chunks from SQLite, generates embeddings via the configured provider,
    and stores vectors in ChromaDB.

    Args:
        book_id: 6-char hex book identifier
        db_path: SQLite database path (default: ~/.mnemo/mnemo.db)
        chroma_path: ChromaDB path (default: ~/.mnemo/chroma)
        batch_size: Chunks per embedding API call (default: 50)

    Returns:
        Number of chunks embedded

    Raises:
        ValueError: Book not found or embedding credentials not configured
    """
    # Lazy imports to avoid hard dependency on embedding modules
    from mnemo.embeddings import Embedder
    from mnemo.vectors import VectorConfig, VectorStore

    # Load chunks from SQLite
    init_db(db_path)
    conn = get_connection(db_path)
    chunk_repo = ChunkRepository(conn)
    chunks = chunk_repo.get_by_book(book_id)
    conn.close()

    if not chunks:
        raise ValueError(f"No chunks found for book: {book_id}")

    # Filter out boilerplate (front/backmatter) — keep in SQLite for FTS5
    # but don't waste embeddings on index pages, copyright notices, etc.
    total = len(chunks)
    chunks = [c for c in chunks if not is_boilerplate_section(c.section_path)]
    skipped = total - len(chunks)
    if skipped:
        logger.info("Skipped %d boilerplate chunks (of %d total) for embedding", skipped, total)

    if not chunks:
        raise NothingToEmbed(f"No embeddable chunks for book: {book_id} (all boilerplate)")

    # Initialize embedder (will raise if no credentials)
    embedder = Embedder()

    # Initialize vector store
    vector_config = VectorConfig(persist_path=chroma_path)
    store = VectorStore(vector_config)

    # Delete any existing vectors for this book (re-embedding case)
    store.delete_by_book(book_id)

    # Process in batches
    embedded_count = 0
    for batch in _batch_items(chunks, batch_size):
        texts = [chunk.content for chunk in batch]
        embeddings = embedder.embed_batch(texts)

        ids = [chunk.id for chunk in batch]
        metadatas = [
            {
                "book_id": chunk.book_id,
                "content_type": chunk.content_type.value,
                "section_path": " > ".join(chunk.section_path) if chunk.section_path else "",
                "sequence": chunk.sequence,
            }
            for chunk in batch
        ]

        store.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=texts,  # Store original text for debugging
        )
        embedded_count += len(batch)

    store.close()
    return embedded_count


# Fields a user may have corrected with update_book_metadata or enrich_book.
_EDITABLE_FIELDS = ("title", "authors", "isbn", "publisher", "year", "description")


def carry_over(parsed: Book, previous: Book, force_metadata: bool) -> Book:
    """The parsed book under the previous one's id, keeping its edited metadata."""
    updates: dict[str, object] = {"id": previous.id, "added_at": previous.added_at}
    for name in _EDITABLE_FIELDS:
        if not (force_metadata and getattr(parsed, name)):
            updates[name] = getattr(previous, name)
    if not parsed.collection:
        updates["collection"] = previous.collection
    return parsed.model_copy(update=updates)


def _delete_vectors(book_ids: set[str], chroma_path: Path | None) -> None:
    try:
        from mnemo.vectors import VectorConfig, VectorStore
    except ImportError:
        return  # Vectors module not available
    store = VectorStore(VectorConfig(persist_path=chroma_path))
    # close() releases Chroma's file descriptors, so it runs even when a delete fails.
    try:
        for book_id in book_ids:
            store.delete_by_book(book_id)
    finally:
        store.close()


EmbedStatus = Literal["embedded", "nothing_to_embed", "failed", "not_requested"]


@dataclass(frozen=True)
class Stored:
    """What the pipeline did with a book it was told to store."""

    book: Book
    chunks: int
    embedding: EmbedStatus
    embed_error: str | None = None


def store_book(
    book: Book,
    blocks: list[ContentBlock],
    *,
    replaces: frozenset[str] = frozenset(),
    chunker_config: ChunkerConfig | None = None,
    embed: bool = False,
    db_path: Path | None = None,
    chroma_path: Path | None = None,
) -> Stored:
    """Chunk, store and optionally embed `book`, removing the books in `replaces`.

    Executes a decision intake already made: no duplicate lookups, no policy.
    Raises only before the commit, when nothing has changed.
    """
    chunks = Chunker(chunker_config).chunk(book.id, blocks)

    init_db(db_path)
    conn = get_connection(db_path)
    try:
        book_repo = BookRepository(conn)
        chunk_repo = ChunkRepository(conn)
        for stale_id in replaces:
            book_repo.delete(stale_id, commit=False)
        book_repo.add(book, commit=False)
        chunk_repo.add_many(chunks, commit=False)
        conn.commit()
    finally:
        conn.close()

    # Past the commit the book is durable, so vector trouble is partial success.
    if replaces:
        try:
            _delete_vectors(set(replaces), chroma_path)
        except Exception as e:
            logger.info("Removing old vectors failed for %s: %s", book.id, e)
            return Stored(book, len(chunks), "failed", f"Old vectors could not be removed: {e}")

    if not embed:
        return Stored(book, len(chunks), "not_requested")
    try:
        embed_book(book.id, db_path=db_path, chroma_path=chroma_path)
    except NothingToEmbed:
        return Stored(book, len(chunks), "nothing_to_embed")
    except Exception as e:
        logger.info("Embedding failed for %s (%s): %s", book.id, book.title, e)
        return Stored(book, len(chunks), "failed", str(e))
    return Stored(book, len(chunks), "embedded")


def reindex_all_books(
    db_path: Path | None = None,
    chroma_path: Path | None = None,
    chunker_config: ChunkerConfig | None = None,
    embed: bool = True,
) -> list[ReindexResult]:
    """Re-ingest all books in the library.

    Iterates over all indexed books, validates their file paths still exist,
    and re-stores each in place under its own id. Useful when the chunking or
    embedding pipeline has been updated.

    Args:
        db_path: Database path (default: ~/.mnemo/mnemo.db)
        chroma_path: ChromaDB path (default: ~/.mnemo/chroma)
        chunker_config: Chunking configuration override
        embed: If True, regenerate embeddings (default: True)

    Returns:
        List of result dicts with keys: book_id, title, status, chunks, error.
        status is "partial" for a book that was re-indexed but not re-embedded,
        and "merged" for an entry whose file is now byte-identical to another
        entry's and was folded into it (error names the surviving id). Entries
        that merely share content are each kept in place.
        The first embedding failure stops the run: reindexing deletes a book's
        vectors before rewriting them, so the remaining books are left alone
        and reported as "skipped".

    Raises:
        ValueError: embed=True with no embedding endpoint configured.
        httpx.HTTPError: embed=True with an endpoint that rejects a probe
            request (bad key, unknown model, unreachable host). Both are
            raised before any book is touched, since reindexing is destructive.
    """
    # store_book deletes a book's existing vectors before re-embedding it,
    # so a provider that fails mid-run strips the library one book at
    # a time. A real round-trip is the only preflight that catches a bad key or
    # model, not just a missing base URL. Costs one embedding of one word.
    if embed:
        from mnemo.embeddings import Embedder

        Embedder().embed_one("preflight")

    init_db(db_path)
    conn = get_connection(db_path)
    book_repo = BookRepository(conn)
    books = book_repo.list_all()
    conn.close()

    results: list[ReindexResult] = []
    file_hashes: dict[str, str] = {}

    for index, book in enumerate(books):
        book_file = book.file_path
        if not book_file or not Path(book_file).exists():
            results.append(
                {
                    "book_id": book.id,
                    "title": book.title,
                    "status": "skipped",
                    "chunks": 0,
                    "error": "Source file not found" if book_file else "No file path stored",
                }
            )
            continue

        try:
            parsed, blocks = parse_book(Path(book_file))
            parsed = parsed.model_copy(
                update={"file_path": str(Path(book_file).resolve()), "collection": book.collection}
            )
            conn = get_connection(db_path)
            try:
                repo = BookRepository(conn)
                twin = repo.get_by_hash(parsed.file_hash)
                # An earlier iteration may have folded this entry into its byte-twin.
                previous = repo.get(book.id) or twin
            finally:
                conn.close()
            stored = store_book(
                carry_over(parsed, previous, False) if previous else parsed,
                blocks,
                replaces=frozenset({book.id} | ({twin.id} if twin else set())),
                chunker_config=chunker_config,
                embed=embed,
                db_path=db_path,
                chroma_path=chroma_path,
            )
            file_hashes[stored.book.id] = stored.book.file_hash
            if stored.embedding == "failed":
                # Re-parsed, re-chunked and committed; only the vectors are missing.
                results.append(
                    {
                        "book_id": stored.book.id,
                        "title": stored.book.title,
                        "status": "partial",
                        "chunks": stored.chunks,
                        "error": stored.embed_error,
                    }
                )
                # Every book is re-embedded the same way, so a failure here is a
                # failure for the rest too — and each one loses its vectors first.
                # Stop rather than strip the library on an expired token or outage.
                remaining = books[index + 1 :]
                results.extend(
                    {
                        "book_id": other.id,
                        "title": other.title,
                        "status": "skipped",
                        "chunks": 0,
                        "error": "Stopped after an embedding failure; not re-indexed",
                    }
                    for other in remaining
                )
                break
            if stored.book.id != book.id:
                results.append(
                    {
                        "book_id": book.id,
                        "title": book.title,
                        "status": "merged",
                        "chunks": 0,
                        "error": f"same file as {stored.book.id}",
                    }
                )
                continue
            results.append(
                {
                    "book_id": stored.book.id,
                    "title": stored.book.title,
                    "status": "success",
                    "chunks": stored.chunks,
                    "error": None,
                }
            )
        except Exception as e:
            results.append(
                {
                    "book_id": book.id,
                    "title": book.title,
                    "status": "failed",
                    "chunks": 0,
                    "error": str(e),
                }
            )

    _mark_merged(results, file_hashes, db_path)
    return results


def _mark_merged(
    results: list[ReindexResult], file_hashes: dict[str, str], db_path: Path | None
) -> None:
    """Relabel rows whose book a later entry with the same file deleted."""
    conn = get_connection(db_path)
    try:
        library = BookRepository(conn).list_all()
    finally:
        conn.close()
    live = {b.id for b in library}
    for row in results:
        if row["status"] not in ("success", "partial") or row["book_id"] in live:
            continue
        digest = file_hashes.get(row["book_id"])
        survivor = next((b.id for b in library if b.file_hash == digest), None)
        row["status"] = "merged"
        row["chunks"] = 0
        row["error"] = f"same file as {survivor}" if survivor else "same file as another entry"


def remove_book(
    book_id: str,
    db_path: Path | None = None,
    chroma_path: Path | None = None,
) -> bool:
    """Remove a book and all its chunks and vectors.

    Uses cascade delete in SQLite and deletes vectors from ChromaDB.

    Args:
        book_id: 6-char hex book identifier
        db_path: Database path (default: ~/.mnemo/mnemo.db)
        chroma_path: ChromaDB path (default: ~/.mnemo/chroma)

    Returns:
        True if book was found and removed, False if not found
    """
    # Delete from SQLite
    init_db(db_path)
    conn = get_connection(db_path)
    book_repo = BookRepository(conn)

    result = book_repo.delete(book_id)
    conn.commit()
    conn.close()

    # Delete vectors (if any)
    try:
        from mnemo.vectors import VectorConfig, VectorStore

        vector_config = VectorConfig(persist_path=chroma_path)
        store = VectorStore(vector_config)
        store.delete_by_book(book_id)
        store.close()
    except ImportError:
        pass  # Vectors module not available

    return result
