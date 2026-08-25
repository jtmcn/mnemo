"""End-to-end book ingestion pipeline.

Wires together the parser, chunker, storage, and optionally embedding
components to provide a simple API for adding and removing books.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Literal, TypedDict, TypeVar

from mnemo.chunking import Chunker, ChunkerConfig
from mnemo.models import Book, is_boilerplate_section
from mnemo.parsing import parse_book
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db

logger = __import__("logging").getLogger(__name__)

T = TypeVar("T")


class ReindexResult(TypedDict):
    """Per-book outcome from reindex_all_books."""

    book_id: str
    title: str
    status: Literal["success", "partial", "skipped", "failed"]
    chunks: int
    error: str | None


class NothingToEmbed(ValueError):
    """The book has no chunks worth embedding (all front/back matter).

    Distinct from EmbeddingFailed: re-running the embedding step can never
    produce vectors for this book, so callers must not advise a retry.
    """


class DuplicateBook(ValueError):
    """The file hash is already indexed and force was not set.

    Raised instead of a bare ValueError so callers can tell "already have it"
    from "the pipeline broke" — pydantic's ValidationError is a ValueError
    too, and a malformed book was being reported as a duplicate.

    Subclasses ValueError because ingest_book has always documented this as
    one; existing `except ValueError` callers keep working.
    """

    def __init__(self, book: Book, message: str) -> None:
        super().__init__(message)
        self.book = book


class EmbeddingFailed(ValueError):
    """Book was stored and is keyword-searchable, but embedding did not run.

    ingest_book commits the book and its chunks before embedding, so an
    embedding error leaves a durable, usable book. Raised instead of the
    underlying error so callers can tell "nothing was written" from
    "written, vectors missing" and report the latter as partial success.

    Subclasses ValueError because ingest_book has always documented embedding
    failure as a ValueError; existing `except ValueError` callers keep working.
    """

    def __init__(self, book: Book, chunk_count: int, cause: Exception) -> None:
        super().__init__(str(cause))
        self.book = book
        self.chunk_count = chunk_count


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


def ingest_book(
    book_path: Path,
    db_path: Path | None = None,
    chunker_config: ChunkerConfig | None = None,
    force: bool = False,
    embed: bool = False,
    chroma_path: Path | None = None,
    collection: str | None = None,
) -> tuple[Book, int]:
    """Ingest a book file into the database.

    Parses the book, chunks the content, stores in SQLite, and optionally
    generates embeddings for vector search.

    Args:
        book_path: Path to book file (.epub, .docx)
        db_path: Database path (default: ~/.mnemo/mnemo.db)
        chunker_config: Chunking configuration
        force: If True, re-ingest even if duplicate detected
        embed: If True, generate embeddings after storing chunks
        chroma_path: ChromaDB path for vectors (default: ~/.mnemo/chroma)
        collection: Optional collection name to tag this book at ingest. Empty
            string is treated the same as None (no collection). Only applied to
            fresh ingests; for duplicates without force=True, the existing book's
            collection is unchanged.

    Returns:
        Tuple of (Book, chunk_count)

    Raises:
        FileNotFoundError: File doesn't exist
        DuplicateBook: Duplicate book (unless force=True). A ValueError subclass.
        EmbeddingFailed: Book was stored successfully but embedding failed. A
            ValueError subclass. The book is committed and keyword-searchable;
            only vectors are missing.
    """
    # 1. Validate input
    book_path = Path(book_path)
    if not book_path.exists():
        raise FileNotFoundError(f"File not found: {book_path}")

    # 2. Initialize database
    init_db(db_path)
    conn = get_connection(db_path)
    book_repo = BookRepository(conn)
    chunk_repo = ChunkRepository(conn)

    # 3. Parse book (dispatches to format-specific parser)
    book, content_blocks = parse_book(book_path)

    # 3b. Store resolved absolute file_path and optional collection
    updates: dict[str, str] = {"file_path": str(book_path.resolve())}
    # Empty string is treated as no collection at ingest (no existing value to clear).
    # This differs from BookRepository.update where collection="" clears to NULL.
    if collection:
        updates["collection"] = collection
    book = book.model_copy(update=updates)

    # 4. Check for duplicate
    existing = book_repo.get_by_hash(book.file_hash)
    if existing and not force:
        conn.close()
        raise DuplicateBook(
            existing, f"Book already indexed (id: {existing.id}). Use force=True to re-index."
        )

    # 5. If force and exists, delete old version (including vectors)
    if existing and force:
        book_repo.delete(existing.id)
        # Also delete vectors if they exist
        try:
            from mnemo.vectors import VectorConfig, VectorStore

            vector_config = VectorConfig(persist_path=chroma_path)
            store = VectorStore(vector_config)
            store.delete_by_book(existing.id)
            store.close()
        except ImportError:
            pass  # Vectors module not available

    # 6. Chunk content
    chunker = Chunker(chunker_config)
    chunks = chunker.chunk(book.id, content_blocks)

    # 7. Store
    book_repo.add(book)
    chunk_repo.add_many(chunks)
    conn.commit()
    conn.close()

    # 8. Optionally embed. The book is already committed at this point, so an
    # embedding failure is partial success, not an ingest failure.
    if embed:
        try:
            embed_book(book.id, db_path=db_path, chroma_path=chroma_path)
        except NothingToEmbed:
            # Structural, not a failure: there is nothing here to embed and a
            # retry would not change that.
            logger.info("Nothing to embed for %s (%s)", book.id, book.title)
        except Exception as e:
            # info, not warning: every caller reports this to the user itself, and a
            # warning would double-print over the CLI spinner.
            logger.info("Embedding failed for %s (%s): %s", book.id, book.title, e)
            raise EmbeddingFailed(book, len(chunks), e) from e

    return book, len(chunks)


def reindex_all_books(
    db_path: Path | None = None,
    chroma_path: Path | None = None,
    chunker_config: ChunkerConfig | None = None,
    embed: bool = True,
) -> list[ReindexResult]:
    """Re-ingest all books in the library.

    Iterates over all indexed books, validates their file paths still exist,
    and re-ingests each with force=True. Useful when the chunking or embedding
    pipeline has been updated.

    Args:
        db_path: Database path (default: ~/.mnemo/mnemo.db)
        chroma_path: ChromaDB path (default: ~/.mnemo/chroma)
        chunker_config: Chunking configuration override
        embed: If True, regenerate embeddings (default: True)

    Returns:
        List of result dicts with keys: book_id, title, status, chunks, error.
        status is "partial" for a book that was re-indexed but not re-embedded.
        The first embedding failure stops the run: reindexing deletes a book's
        vectors before rewriting them, so the remaining books are left alone
        and reported as "skipped".

    Raises:
        ValueError: embed=True with no embedding endpoint configured.
        httpx.HTTPError: embed=True with an endpoint that rejects a probe
            request (bad key, unknown model, unreachable host). Both are
            raised before any book is touched, since reindexing is destructive.
    """
    # ingest_book deletes a book's existing vectors before re-embedding it
    # (step 5), so a provider that fails mid-run strips the library one book at
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
            _, chunk_count = ingest_book(
                Path(book_file),
                db_path=db_path,
                chroma_path=chroma_path,
                chunker_config=chunker_config,
                force=True,
                embed=embed,
                collection=book.collection,
            )
            results.append(
                {
                    "book_id": book.id,
                    "title": book.title,
                    "status": "success",
                    "chunks": chunk_count,
                    "error": None,
                }
            )
        except EmbeddingFailed as e:
            # Re-parsed, re-chunked and committed; only the vectors are missing.
            results.append(
                {
                    "book_id": book.id,
                    "title": book.title,
                    "status": "partial",
                    "chunks": e.chunk_count,
                    "error": str(e),
                }
            )
            # Every book is re-embedded the same way, so a failure here is a
            # failure for the rest too — and each iteration deletes that book's
            # vectors first (step 5). Carrying on would strip the whole library
            # for an expired token or a provider outage, neither of which the
            # credential preflight can see. Stop and leave the rest untouched.
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

    return results


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
