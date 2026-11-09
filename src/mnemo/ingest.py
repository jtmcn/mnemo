"""End-to-end book ingestion pipeline.

Wires together the parser, chunker, storage, and optionally embedding
components to provide a simple API for adding and removing books.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mnemo.chunking import Chunker, ChunkerConfig
from mnemo.models import Book, is_boilerplate_section
from mnemo.parsing import ContentBlock
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db

logger = __import__("logging").getLogger(__name__)


class NothingToEmbed(ValueError):
    """The book has no chunks worth embedding (all front/back matter).

    Re-running the embedding step can never produce vectors for this book,
    so callers must not advise a retry.
    """


def _batch_items[T](items: list[T], batch_size: int = 50) -> Iterator[list[T]]:
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
        batch_size: Chunks per embed_batch call and vector-store write (default: 50);
            the embedder splits each batch into requests by token budget

    Returns:
        Number of chunks embedded

    Raises:
        ValueError: Book not found or embedding credentials not configured
    """
    # Lazy imports to avoid hard dependency on embedding modules
    from mnemo.embeddings import Embedder
    from mnemo.vectors import VectorConfig
    from mnemo.vectors.backend import open_store

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
    store = open_store(vector_config)

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
        from mnemo.vectors import VectorConfig
        from mnemo.vectors.backend import open_store
    except ImportError:
        return  # Vectors module not available
    store = open_store(VectorConfig(persist_path=chroma_path))
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
        from mnemo.vectors import VectorConfig
        from mnemo.vectors.backend import open_store

        vector_config = VectorConfig(persist_path=chroma_path)
        store = open_store(vector_config)
        store.delete_by_book(book_id)
        store.close()
    except ImportError:
        pass  # Vectors module not available

    return result
