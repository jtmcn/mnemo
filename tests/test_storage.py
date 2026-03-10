"""Tests for SQLite storage layer.

Tests cover:
- Database initialization
- Book CRUD operations
- Chunk bulk insert and retrieval
- Cascade delete behavior
- FTS5 full-text search
- Duplicate detection
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from mnemo.models import Book, Chunk, ContentType
from mnemo.storage.database import get_connection, init_db
from mnemo.storage.repository import BookRepository, ChunkRepository


@pytest.fixture
def db_path() -> Path:
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "test.db"


@pytest.fixture
def conn(db_path: Path):
    """Create and initialize a test database connection."""
    init_db(db_path)
    connection = get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def book_repo(conn) -> BookRepository:
    """Create a BookRepository instance."""
    return BookRepository(conn)


@pytest.fixture
def chunk_repo(conn) -> ChunkRepository:
    """Create a ChunkRepository instance."""
    return ChunkRepository(conn)


@pytest.fixture
def sample_book() -> Book:
    """Create a sample book for testing."""
    return Book(
        id="abc123",
        title="Test Book",
        authors=["Author One", "Author Two"],
        isbn="978-1234567890",
        file_hash="a" * 64,
        default_language="python",
        structure_source="toc",
        added_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_chunks(sample_book: Book) -> list[Chunk]:
    """Create sample chunks for testing."""
    chunks = []
    for i in range(5):
        chunk = Chunk(
            id=str(uuid.uuid4()),
            book_id=sample_book.id,
            content=f"This is test content for chunk {i}. Python async programming.",
            content_type=ContentType.TEXT if i % 2 == 0 else ContentType.CODE,
            token_count=10 + i,
            section_path=["Part 1", f"Chapter {i + 1}"],
            sections=[f"Chapter {i + 1}"],
            language="python" if i % 2 == 1 else None,
            sequence=i,
        )
        chunks.append(chunk)

    # Set prev/next links
    for i, chunk in enumerate(chunks):
        if i > 0:
            chunk.prev_chunk_id = chunks[i - 1].id
        if i < len(chunks) - 1:
            chunk.next_chunk_id = chunks[i + 1].id

    return chunks


class TestDatabaseInitialization:
    """Tests for database schema initialization."""

    def test_init_db_creates_tables(self, db_path: Path):
        """init_db should create all required tables."""
        init_db(db_path)
        conn = get_connection(db_path)

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t["name"] for t in tables]

        assert "books" in table_names
        assert "chunks" in table_names
        assert "chunks_fts" in table_names

        conn.close()

    def test_init_db_creates_triggers(self, db_path: Path):
        """init_db should create FTS sync triggers."""
        init_db(db_path)
        conn = get_connection(db_path)

        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        trigger_names = [t["name"] for t in triggers]

        assert "chunks_ai" in trigger_names
        assert "chunks_ad" in trigger_names
        assert "chunks_au" in trigger_names

        conn.close()

    def test_init_db_creates_indexes(self, db_path: Path):
        """init_db should create performance indexes."""
        init_db(db_path)
        conn = get_connection(db_path)

        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = [i["name"] for i in indexes]

        assert "idx_chunks_book_id" in index_names
        assert "idx_chunks_content_type" in index_names
        assert "idx_chunks_sequence" in index_names

        conn.close()

    def test_init_db_idempotent(self, db_path: Path):
        """init_db should be safe to call multiple times."""
        init_db(db_path)
        init_db(db_path)  # Should not raise

        conn = get_connection(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert len([t for t in tables if t["name"] == "books"]) == 1
        conn.close()


class TestBookRepository:
    """Tests for BookRepository CRUD operations."""

    def test_add_book(self, book_repo: BookRepository, sample_book: Book):
        """add() should insert book into database."""
        result = book_repo.add(sample_book)

        assert result.id == sample_book.id
        assert book_repo.get(sample_book.id) is not None

    def test_get_book(self, book_repo: BookRepository, sample_book: Book):
        """get() should retrieve book by ID."""
        book_repo.add(sample_book)

        retrieved = book_repo.get(sample_book.id)

        assert retrieved is not None
        assert retrieved.id == sample_book.id
        assert retrieved.title == sample_book.title
        assert retrieved.authors == sample_book.authors
        assert retrieved.isbn == sample_book.isbn

    def test_get_nonexistent_book(self, book_repo: BookRepository):
        """get() should return None for nonexistent book."""
        assert book_repo.get("notfnd") is None

    def test_get_by_hash(self, book_repo: BookRepository, sample_book: Book):
        """get_by_hash() should find book by file_hash."""
        book_repo.add(sample_book)

        duplicate = book_repo.get_by_hash(sample_book.file_hash)

        assert duplicate is not None
        assert duplicate.id == sample_book.id

    def test_get_by_hash_not_found(self, book_repo: BookRepository):
        """get_by_hash() should return None when hash not found."""
        assert book_repo.get_by_hash("b" * 64) is None

    def test_list_all(self, book_repo: BookRepository, sample_book: Book):
        """list_all() should return all books."""
        book_repo.add(sample_book)

        # Add another book
        book2 = Book(
            id="def456",
            title="Second Book",
            authors=["Another Author"],
            file_hash="b" * 64,
            structure_source="inferred",
            added_at=datetime.now(timezone.utc),
        )
        book_repo.add(book2)

        books = book_repo.list_all()

        assert len(books) == 2
        book_ids = [b.id for b in books]
        assert sample_book.id in book_ids
        assert book2.id in book_ids

    def test_delete_book(self, book_repo: BookRepository, sample_book: Book):
        """delete() should remove book from database."""
        book_repo.add(sample_book)
        assert book_repo.get(sample_book.id) is not None

        result = book_repo.delete(sample_book.id)

        assert result is True
        assert book_repo.get(sample_book.id) is None

    def test_delete_nonexistent_book(self, book_repo: BookRepository):
        """delete() should return False for nonexistent book."""
        result = book_repo.delete("notfnd")
        assert result is False

    def test_find_similar_title(self, book_repo: BookRepository):
        """find_similar_title() should find books with similar titles."""
        book1 = Book(
            id="abc123",
            title="Python Programming Guide",
            authors=["Author"],
            file_hash="a" * 64,
            structure_source="toc",
        )
        book2 = Book(
            id="def456",
            title="Python Programming Handbook",
            authors=["Author"],
            file_hash="b" * 64,
            structure_source="toc",
        )
        book3 = Book(
            id="cde789",
            title="JavaScript Basics",
            authors=["Author"],
            file_hash="c" * 64,
            structure_source="toc",
        )
        book_repo.add(book1)
        book_repo.add(book2)
        book_repo.add(book3)

        similar = book_repo.find_similar_title("Python Programming", threshold=0.6)

        assert len(similar) >= 2
        similar_ids = [b.id for b in similar]
        assert book1.id in similar_ids
        assert book2.id in similar_ids

    def test_duplicate_file_hash_rejected(
        self, book_repo: BookRepository, sample_book: Book
    ):
        """Adding book with duplicate file_hash should raise IntegrityError."""
        import sqlite3

        book_repo.add(sample_book)

        duplicate = Book(
            id="ddd123",
            title="Duplicate Book",
            authors=["Author"],
            file_hash=sample_book.file_hash,  # Same hash
            structure_source="toc",
        )

        with pytest.raises(sqlite3.IntegrityError):
            book_repo.add(duplicate)


class TestBookRepositoryUpdate:
    """Tests for BookRepository.update() method."""

    def test_update_title(
        self, book_repo: BookRepository, sample_book: Book
    ):
        """update() with title should change title and leave authors unchanged."""
        book_repo.add(sample_book)

        updated = book_repo.update(sample_book.id, title="New Title")

        assert updated is not None
        assert updated.title == "New Title"
        assert updated.authors == sample_book.authors

    def test_update_authors(
        self, book_repo: BookRepository, sample_book: Book
    ):
        """update() with authors should change authors and leave title unchanged."""
        book_repo.add(sample_book)

        updated = book_repo.update(sample_book.id, authors=["New Author"])

        assert updated is not None
        assert updated.authors == ["New Author"]
        assert updated.title == sample_book.title

    def test_update_isbn(
        self, book_repo: BookRepository, sample_book: Book
    ):
        """update() with isbn should change isbn."""
        book_repo.add(sample_book)

        updated = book_repo.update(sample_book.id, isbn="978-0000000000")

        assert updated is not None
        assert updated.isbn == "978-0000000000"

    def test_update_multiple_fields(
        self, book_repo: BookRepository, sample_book: Book
    ):
        """update() with title + authors should change both."""
        book_repo.add(sample_book)

        updated = book_repo.update(
            sample_book.id, title="Updated Title", authors=["Alice", "Bob"]
        )

        assert updated is not None
        assert updated.title == "Updated Title"
        assert updated.authors == ["Alice", "Bob"]

    def test_update_no_fields_raises(
        self, book_repo: BookRepository, sample_book: Book
    ):
        """update() with no fields should raise ValueError."""
        book_repo.add(sample_book)

        with pytest.raises(ValueError, match="At least one field"):
            book_repo.update(sample_book.id)

    def test_update_nonexistent_returns_none(
        self, book_repo: BookRepository
    ):
        """update() for nonexistent book_id should return None."""
        result = book_repo.update("notfnd", title="New Title")
        assert result is None

    def test_update_persists(
        self, book_repo: BookRepository, sample_book: Book
    ):
        """update() changes should persist (verified by separate get)."""
        book_repo.add(sample_book)

        book_repo.update(sample_book.id, title="Persisted Title")

        refetched = book_repo.get(sample_book.id)
        assert refetched is not None
        assert refetched.title == "Persisted Title"


class TestChunkRepository:
    """Tests for ChunkRepository operations."""

    def test_add_many_chunks(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
        sample_chunks: list[Chunk],
    ):
        """add_many() should bulk insert chunks."""
        book_repo.add(sample_book)

        result = chunk_repo.add_many(sample_chunks)

        assert len(result) == len(sample_chunks)
        assert chunk_repo.count_by_book(sample_book.id) == len(sample_chunks)

    def test_add_many_empty_list(self, chunk_repo: ChunkRepository):
        """add_many() should handle empty list."""
        result = chunk_repo.add_many([])
        assert result == []

    def test_get_chunk(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
        sample_chunks: list[Chunk],
    ):
        """get() should retrieve chunk by ID."""
        book_repo.add(sample_book)
        chunk_repo.add_many(sample_chunks)

        retrieved = chunk_repo.get(sample_chunks[0].id)

        assert retrieved is not None
        assert retrieved.id == sample_chunks[0].id
        assert retrieved.content == sample_chunks[0].content
        assert retrieved.content_type == sample_chunks[0].content_type

    def test_get_nonexistent_chunk(self, chunk_repo: ChunkRepository):
        """get() should return None for nonexistent chunk."""
        assert chunk_repo.get(str(uuid.uuid4())) is None

    def test_get_by_book(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
        sample_chunks: list[Chunk],
    ):
        """get_by_book() should return chunks ordered by sequence."""
        book_repo.add(sample_book)
        chunk_repo.add_many(sample_chunks)

        chunks = chunk_repo.get_by_book(sample_book.id)

        assert len(chunks) == len(sample_chunks)
        # Verify ordering
        for i, chunk in enumerate(chunks):
            assert chunk.sequence == i

    def test_count_by_book(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
        sample_chunks: list[Chunk],
    ):
        """count_by_book() should return correct count."""
        book_repo.add(sample_book)
        chunk_repo.add_many(sample_chunks)

        count = chunk_repo.count_by_book(sample_book.id)

        assert count == len(sample_chunks)

    def test_count_nonexistent_book(self, chunk_repo: ChunkRepository):
        """count_by_book() should return 0 for nonexistent book."""
        assert chunk_repo.count_by_book("notfnd") == 0


class TestCascadeDelete:
    """Tests for cascade delete behavior."""

    def test_delete_book_cascades_to_chunks(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
        sample_chunks: list[Chunk],
    ):
        """Deleting a book should automatically delete all its chunks."""
        book_repo.add(sample_book)
        chunk_repo.add_many(sample_chunks)

        # Verify chunks exist
        assert chunk_repo.count_by_book(sample_book.id) == len(sample_chunks)

        # Delete book
        book_repo.delete(sample_book.id)

        # Verify chunks are gone
        assert chunk_repo.count_by_book(sample_book.id) == 0

        # Verify individual chunks are gone
        for chunk in sample_chunks:
            assert chunk_repo.get(chunk.id) is None


class TestFTSSearch:
    """Tests for FTS5 full-text search."""

    def test_search_fts_basic(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """search_fts() should find chunks matching query."""
        book_repo.add(sample_book)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content="Python is a great programming language for beginners.",
                content_type=ContentType.TEXT,
                token_count=10,
                section_path=["Ch1"],
                sections=["Ch1"],
                sequence=0,
            ),
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content="JavaScript is used for web development.",
                content_type=ContentType.TEXT,
                token_count=8,
                section_path=["Ch2"],
                sections=["Ch2"],
                sequence=1,
            ),
        ]
        chunk_repo.add_many(chunks)

        results = chunk_repo.search_fts("Python")

        assert len(results) == 1
        assert "Python" in results[0].content

    def test_search_fts_multiple_results(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """search_fts() should return multiple matching chunks."""
        book_repo.add(sample_book)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content="Programming is fun. I love programming.",
                content_type=ContentType.TEXT,
                token_count=8,
                section_path=["Ch1"],
                sections=["Ch1"],
                sequence=0,
            ),
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content="Programming languages are tools for developers.",
                content_type=ContentType.TEXT,
                token_count=7,
                section_path=["Ch2"],
                sections=["Ch2"],
                sequence=1,
            ),
        ]
        chunk_repo.add_many(chunks)

        results = chunk_repo.search_fts("programming")

        assert len(results) == 2

    def test_search_fts_filter_by_book(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
    ):
        """search_fts() should filter by book_id."""
        book1 = Book(
            id="abc123",
            title="Book 1",
            authors=["Author"],
            file_hash="a" * 64,
            structure_source="toc",
        )
        book2 = Book(
            id="def456",
            title="Book 2",
            authors=["Author"],
            file_hash="b" * 64,
            structure_source="toc",
        )
        book_repo.add(book1)
        book_repo.add(book2)

        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                book_id=book1.id,
                content="Python programming tutorial.",
                content_type=ContentType.TEXT,
                token_count=3,
                section_path=[],
                sections=[],
                sequence=0,
            ),
            Chunk(
                id=str(uuid.uuid4()),
                book_id=book2.id,
                content="Python data analysis guide.",
                content_type=ContentType.TEXT,
                token_count=4,
                section_path=[],
                sections=[],
                sequence=0,
            ),
        ]
        chunk_repo.add_many(chunks)

        # Search all
        all_results = chunk_repo.search_fts("Python")
        assert len(all_results) == 2

        # Search filtered
        book1_results = chunk_repo.search_fts("Python", book_id=book1.id)
        assert len(book1_results) == 1
        assert book1_results[0].book_id == book1.id

    def test_search_fts_filter_by_content_type(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """search_fts() should filter by content_type."""
        book_repo.add(sample_book)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content="def hello_world(): print('Hello')",
                content_type=ContentType.CODE,
                token_count=5,
                section_path=[],
                sections=[],
                sequence=0,
            ),
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content="The hello_world function prints a greeting.",
                content_type=ContentType.TEXT,
                token_count=7,
                section_path=[],
                sections=[],
                sequence=1,
            ),
        ]
        chunk_repo.add_many(chunks)

        # Search only CODE
        code_results = chunk_repo.search_fts("hello", content_type=ContentType.CODE)
        assert len(code_results) == 1
        assert code_results[0].content_type == ContentType.CODE

        # Search only TEXT
        text_results = chunk_repo.search_fts("hello", content_type=ContentType.TEXT)
        assert len(text_results) == 1
        assert text_results[0].content_type == ContentType.TEXT

    def test_search_fts_limit(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """search_fts() should respect limit parameter."""
        book_repo.add(sample_book)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content=f"Python chapter {i}",
                content_type=ContentType.TEXT,
                token_count=3,
                section_path=[],
                sections=[],
                sequence=i,
            )
            for i in range(10)
        ]
        chunk_repo.add_many(chunks)

        results = chunk_repo.search_fts("Python", limit=5)

        assert len(results) == 5

    def test_search_fts_empty_query(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """search_fts() should return empty for empty query."""
        book_repo.add(sample_book)
        chunk_repo.add_many(
            [
                Chunk(
                    id=str(uuid.uuid4()),
                    book_id=sample_book.id,
                    content="Some content",
                    content_type=ContentType.TEXT,
                    token_count=2,
                    section_path=[],
                    sections=[],
                    sequence=0,
                )
            ]
        )

        results = chunk_repo.search_fts("")
        assert results == []

        results = chunk_repo.search_fts("   ")
        assert results == []

    def test_search_fts_special_characters(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """search_fts() should handle special characters safely."""
        book_repo.add(sample_book)
        chunk_repo.add_many(
            [
                Chunk(
                    id=str(uuid.uuid4()),
                    book_id=sample_book.id,
                    content="C++ is a powerful language",
                    content_type=ContentType.TEXT,
                    token_count=5,
                    section_path=[],
                    sections=[],
                    sequence=0,
                )
            ]
        )

        # These should not raise errors
        chunk_repo.search_fts("C++")
        chunk_repo.search_fts("test@example.com")
        chunk_repo.search_fts("foo(bar)")


class TestEpubPath:
    """Tests for epub_path storage and retrieval."""

    def test_book_model_accepts_epub_path(self):
        """Book model should accept optional epub_path field."""
        book = Book(
            id="abc123",
            title="Test Book",
            authors=["Author"],
            file_hash="a" * 64,
            structure_source="toc",
            epub_path="/path/to/book.epub",
        )
        assert book.epub_path == "/path/to/book.epub"

    def test_book_model_epub_path_defaults_none(self):
        """Book model epub_path should default to None."""
        book = Book(
            id="abc123",
            title="Test Book",
            authors=["Author"],
            file_hash="a" * 64,
            structure_source="toc",
        )
        assert book.epub_path is None

    def test_init_db_creates_epub_path_column(self, db_path: Path):
        """init_db should create books table with epub_path column."""
        init_db(db_path)
        conn = get_connection(db_path)
        # Check column exists
        columns = conn.execute("PRAGMA table_info(books)").fetchall()
        column_names = [c["name"] for c in columns]
        assert "epub_path" in column_names
        conn.close()

    def test_existing_db_without_epub_path_gets_migrated(self, db_path: Path):
        """Existing database without epub_path column should get it after init_db."""
        # Create old-style DB without epub_path
        import sqlite3
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE books (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT NOT NULL,
                isbn TEXT,
                file_hash TEXT UNIQUE NOT NULL,
                default_language TEXT,
                structure_source TEXT NOT NULL,
                added_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        # Now run init_db -- should add epub_path via migration
        init_db(db_path)
        conn = get_connection(db_path)
        columns = conn.execute("PRAGMA table_info(books)").fetchall()
        column_names = [c["name"] for c in columns]
        assert "epub_path" in column_names
        conn.close()

    def test_book_repo_stores_epub_path(self, book_repo: BookRepository):
        """BookRepository.add should store epub_path when provided."""
        book = Book(
            id="abc123",
            title="Test Book",
            authors=["Author"],
            file_hash="a" * 64,
            structure_source="toc",
            epub_path="/absolute/path/to/book.epub",
        )
        book_repo.add(book)
        retrieved = book_repo.get("abc123")
        assert retrieved is not None
        assert retrieved.epub_path == "/absolute/path/to/book.epub"

    def test_book_repo_stores_none_epub_path(self, book_repo: BookRepository):
        """BookRepository.add should store None epub_path."""
        book = Book(
            id="abc123",
            title="Test Book",
            authors=["Author"],
            file_hash="a" * 64,
            structure_source="toc",
        )
        book_repo.add(book)
        retrieved = book_repo.get("abc123")
        assert retrieved is not None
        assert retrieved.epub_path is None

    def test_get_book_info_shows_epub_path(self):
        """get_book_info should show epub_path when present."""
        from mnemo.mcp.tools import _get_book_info_impl

        book = Book(
            id="abc123",
            title="Test Book",
            authors=["Author"],
            file_hash="a" * 64,
            structure_source="toc",
            epub_path="/path/to/test.epub",
        )

        with patch("mnemo.mcp.tools._get_book_repo") as mock_repo, \
             patch("mnemo.mcp.tools.ChunkRepository") as mock_chunk_cls:
            mock_repo.return_value.get.return_value = book
            mock_chunk_cls.return_value.count_by_book.return_value = 10
            # Need to set _db_connection to avoid issues
            import mnemo.mcp.tools as tools_mod
            old_conn = tools_mod._db_connection
            tools_mod._db_connection = MagicMock()
            try:
                result = _get_book_info_impl("abc123")
            finally:
                tools_mod._db_connection = old_conn

        assert "EPUB Path" in result
        assert "/path/to/test.epub" in result


class TestGetChunkRange:
    """Tests for ChunkRepository.get_chunk_range method."""

    def test_get_chunk_range_returns_ordered_chunks(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """get_chunk_range should return chunks in sequence order within range."""
        book_repo.add(sample_book)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content=f"Chunk content {i}",
                content_type=ContentType.TEXT,
                token_count=10,
                section_path=["Part 1", f"Chapter {i + 1}"],
                sections=[f"Chapter {i + 1}"],
                sequence=i,
            )
            for i in range(5)
        ]
        chunk_repo.add_many(chunks)

        result = chunk_repo.get_chunk_range(sample_book.id, 1, 3)

        assert len(result) == 3
        assert result[0].sequence == 1
        assert result[1].sequence == 2
        assert result[2].sequence == 3

    def test_get_chunk_range_clamps_negative_start(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """get_chunk_range should clamp negative start_seq to 0."""
        book_repo.add(sample_book)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content=f"Chunk content {i}",
                content_type=ContentType.TEXT,
                token_count=10,
                section_path=["Part 1"],
                sections=["Part 1"],
                sequence=i,
            )
            for i in range(3)
        ]
        chunk_repo.add_many(chunks)

        result = chunk_repo.get_chunk_range(sample_book.id, -2, 1)

        assert len(result) == 2
        assert result[0].sequence == 0
        assert result[1].sequence == 1

    def test_get_chunk_range_empty_for_unknown_book(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """get_chunk_range should return empty list for nonexistent book_id."""
        book_repo.add(sample_book)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content="Some content",
                content_type=ContentType.TEXT,
                token_count=10,
                section_path=[],
                sections=[],
                sequence=0,
            )
        ]
        chunk_repo.add_many(chunks)

        result = chunk_repo.get_chunk_range("notfnd", 0, 5)

        assert result == []

    def test_get_chunk_range_respects_limit(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """get_chunk_range should respect default limit of 20."""
        book_repo.add(sample_book)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                book_id=sample_book.id,
                content=f"Chunk {i}",
                content_type=ContentType.TEXT,
                token_count=5,
                section_path=[],
                sections=[],
                sequence=i,
            )
            for i in range(25)
        ]
        chunk_repo.add_many(chunks)

        result = chunk_repo.get_chunk_range(sample_book.id, 0, 24)

        assert len(result) == 20


class TestFTSSyncTriggers:
    """Tests that FTS triggers keep index in sync."""

    def test_fts_sync_on_insert(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """FTS index should be updated when chunks are inserted."""
        book_repo.add(sample_book)
        chunk = Chunk(
            id=str(uuid.uuid4()),
            book_id=sample_book.id,
            content="Unique searchable content here",
            content_type=ContentType.TEXT,
            token_count=4,
            section_path=[],
            sections=[],
            sequence=0,
        )
        chunk_repo.add_many([chunk])

        # Should find via FTS
        results = chunk_repo.search_fts("searchable")
        assert len(results) == 1

    def test_fts_sync_on_delete(
        self,
        book_repo: BookRepository,
        chunk_repo: ChunkRepository,
        sample_book: Book,
    ):
        """FTS index should be updated when book (and chunks) are deleted."""
        book_repo.add(sample_book)
        chunk = Chunk(
            id=str(uuid.uuid4()),
            book_id=sample_book.id,
            content="Deletable searchable content",
            content_type=ContentType.TEXT,
            token_count=3,
            section_path=[],
            sections=[],
            sequence=0,
        )
        chunk_repo.add_many([chunk])

        # Verify searchable
        assert len(chunk_repo.search_fts("Deletable")) == 1

        # Delete book (cascades to chunks)
        book_repo.delete(sample_book.id)

        # Should no longer be in FTS
        results = chunk_repo.search_fts("Deletable")
        assert len(results) == 0
