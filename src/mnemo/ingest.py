"""End-to-end EPUB ingestion pipeline.

Wires together the parser, chunker, and storage components to provide
a simple API for adding and removing books from the database.
"""

from __future__ import annotations

from pathlib import Path

from mnemo.chunking import Chunker, ChunkerConfig
from mnemo.epub import EPUBParser
from mnemo.models import Book
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db


def ingest_book(
    epub_path: Path,
    db_path: Path | None = None,
    chunker_config: ChunkerConfig | None = None,
    force: bool = False,
) -> tuple[Book, int]:
    """Ingest an EPUB file into the database.

    Parses the EPUB, chunks the content, and stores everything in SQLite.
    Detects duplicates by content hash and prevents re-indexing unless
    force=True is specified.

    Args:
        epub_path: Path to EPUB file
        db_path: Database path (default: ~/.mnemo/mnemo.db)
        chunker_config: Chunking configuration
        force: If True, re-ingest even if duplicate detected

    Returns:
        Tuple of (Book, chunk_count)

    Raises:
        FileNotFoundError: EPUB doesn't exist
        ValueError: Duplicate book (unless force=True)
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

    # 4. Check for duplicate
    existing = book_repo.get_by_hash(book.file_hash)
    if existing and not force:
        conn.close()
        raise ValueError(
            f"Book already indexed (id: {existing.id}). Use force=True to re-index."
        )

    # 5. If force and exists, delete old version
    if existing and force:
        book_repo.delete(existing.id)

    # 6. Chunk content
    chunker = Chunker(chunker_config)
    chunks = chunker.chunk(book.id, content_blocks)

    # 7. Store
    book_repo.add(book)
    chunk_repo.add_many(chunks)
    conn.commit()
    conn.close()

    return book, len(chunks)


def remove_book(book_id: str, db_path: Path | None = None) -> bool:
    """Remove a book and all its chunks.

    Uses cascade delete - removing the book automatically removes
    all associated chunks from both the main table and FTS index.

    Args:
        book_id: 6-char hex book identifier
        db_path: Database path (default: ~/.mnemo/mnemo.db)

    Returns:
        True if book was found and removed, False if not found
    """
    init_db(db_path)
    conn = get_connection(db_path)
    book_repo = BookRepository(conn)

    result = book_repo.delete(book_id)
    conn.commit()
    conn.close()
    return result
