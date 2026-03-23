"""End-to-end EPUB ingestion pipeline.

Wires together the parser, chunker, storage, and optionally embedding
components to provide a simple API for adding and removing books.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from mnemo.chunking import Chunker, ChunkerConfig
from mnemo.epub import EPUBParser
from mnemo.models import Book, is_boilerplate_section
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db

logger = __import__("logging").getLogger(__name__)


def _batch_items(items: list, batch_size: int = 50) -> Iterator[list]:
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

    Retrieves chunks from SQLite, generates embeddings via Databricks,
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
    from mnemo.embeddings import DatabricksEmbedder
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
        raise ValueError(f"No embeddable chunks for book: {book_id} (all boilerplate)")

    # Initialize embedder (will raise if no credentials)
    embedder = DatabricksEmbedder()

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
    epub_path: Path,
    db_path: Path | None = None,
    chunker_config: ChunkerConfig | None = None,
    force: bool = False,
    embed: bool = False,
    chroma_path: Path | None = None,
) -> tuple[Book, int]:
    """Ingest an EPUB file into the database.

    Parses the EPUB, chunks the content, stores in SQLite, and optionally
    generates embeddings for vector search.

    Args:
        epub_path: Path to EPUB file
        db_path: Database path (default: ~/.mnemo/mnemo.db)
        chunker_config: Chunking configuration
        force: If True, re-ingest even if duplicate detected
        embed: If True, generate embeddings after storing chunks
        chroma_path: ChromaDB path for vectors (default: ~/.mnemo/chroma)

    Returns:
        Tuple of (Book, chunk_count)

    Raises:
        FileNotFoundError: EPUB doesn't exist
        ValueError: Duplicate book (unless force=True) or embedding fails
    """
    # 1. Validate input
    epub_path = Path(epub_path)
    if not epub_path.exists():
        raise FileNotFoundError(f"EPUB not found: {epub_path}")

    # 2. Initialize database
    init_db(db_path)
    conn = get_connection(db_path)
    book_repo = BookRepository(conn)
    chunk_repo = ChunkRepository(conn)

    # 3. Parse EPUB
    parser = EPUBParser()
    book, content_blocks = parser.parse(epub_path)

    # 3b. Store resolved absolute epub_path
    book = book.model_copy(update={"epub_path": str(epub_path.resolve())})

    # 4. Check for duplicate
    existing = book_repo.get_by_hash(book.file_hash)
    if existing and not force:
        conn.close()
        raise ValueError(f"Book already indexed (id: {existing.id}). Use force=True to re-index.")

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

    # 8. Optionally embed
    if embed:
        embed_book(book.id, db_path=db_path, chroma_path=chroma_path)

    return book, len(chunks)


def reindex_all_books(
    db_path: Path | None = None,
    chroma_path: Path | None = None,
    chunker_config: ChunkerConfig | None = None,
    embed: bool = True,
) -> list[dict]:
    """Re-ingest all books in the library.

    Iterates over all indexed books, validates their EPUB paths still exist,
    and re-ingests each with force=True. Useful when the chunking or embedding
    pipeline has been updated.

    Args:
        db_path: Database path (default: ~/.mnemo/mnemo.db)
        chroma_path: ChromaDB path (default: ~/.mnemo/chroma)
        chunker_config: Chunking configuration override
        embed: If True, regenerate embeddings (default: True)

    Returns:
        List of result dicts with keys: book_id, title, status, chunks, error
    """
    init_db(db_path)
    conn = get_connection(db_path)
    book_repo = BookRepository(conn)
    books = book_repo.list_all()
    conn.close()

    results: list[dict] = []

    for book in books:
        epub_path = book.epub_path
        if not epub_path or not Path(epub_path).exists():
            results.append(
                {
                    "book_id": book.id,
                    "title": book.title,
                    "status": "skipped",
                    "chunks": 0,
                    "error": "EPUB file not found" if epub_path else "No EPUB path stored",
                }
            )
            continue

        try:
            _, chunk_count = ingest_book(
                Path(epub_path),
                db_path=db_path,
                chroma_path=chroma_path,
                chunker_config=chunker_config,
                force=True,
                embed=embed,
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
