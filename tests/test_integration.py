"""Integration tests for the end-to-end EPUB ingestion pipeline.

Tests the full flow: EPUB parsing -> chunking -> storage -> search.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mnemo.ingest import ingest_book, remove_book
from mnemo.models import ContentType
from mnemo.storage import ChunkRepository, get_connection, init_db


@pytest.fixture
def sample_epub() -> Path:
    """Path to the sample EPUB fixture."""
    return Path("tests/fixtures/sample.epub")


@pytest.fixture
def temp_db():
    """Provide a temporary database path."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "test.db"


class TestIngestion:
    """Tests for the book ingestion process."""

    def test_ingest_creates_book_and_chunks(self, sample_epub: Path, temp_db: Path):
        """Ingesting an EPUB creates a book with chunks."""
        book, count = ingest_book(sample_epub, temp_db)

        assert book.id is not None
        assert book.title == "Python Testing Guide"
        assert "Test Author" in book.authors
        assert count > 0

    def test_ingest_duplicate_raises_error(self, sample_epub: Path, temp_db: Path):
        """Attempting to ingest the same book twice raises ValueError."""
        ingest_book(sample_epub, temp_db)

        with pytest.raises(ValueError, match="already indexed"):
            ingest_book(sample_epub, temp_db)

    def test_ingest_force_replaces_book(self, sample_epub: Path, temp_db: Path):
        """Force flag allows re-indexing existing book."""
        book1, count1 = ingest_book(sample_epub, temp_db)
        book2, count2 = ingest_book(sample_epub, temp_db, force=True)

        # Same content, same ID
        assert book1.id == book2.id
        # Same chunk count
        assert count1 == count2

    def test_chunks_have_correct_types(self, sample_epub: Path, temp_db: Path):
        """Chunks are assigned correct content types."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)
        conn.close()

        types = {c.content_type for c in chunks}
        assert ContentType.TEXT in types
        assert ContentType.CODE in types
        assert ContentType.TABLE in types

    def test_code_blocks_preserved(self, sample_epub: Path, temp_db: Path):
        """Code blocks maintain their formatting."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)
        conn.close()

        code_chunks = [c for c in chunks if c.content_type == ContentType.CODE]
        assert len(code_chunks) >= 1

        # Verify indentation preserved
        for chunk in code_chunks:
            # Code should have 4-space indentation
            assert "    " in chunk.content

    def test_long_text_is_chunked(self, sample_epub: Path, temp_db: Path):
        """Long prose text is split into multiple chunks."""
        book, count = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)
        conn.close()

        # Chapter 3 has 100 repetitions of prose, should trigger chunking
        # We should have more chunks than just 3 (one per chapter)
        text_chunks = [c for c in chunks if c.content_type == ContentType.TEXT]
        assert len(text_chunks) > 3

    def test_section_paths_populated(self, sample_epub: Path, temp_db: Path):
        """Chunks have non-empty section paths."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)
        conn.close()

        # At least some chunks should have section paths
        chunks_with_paths = [c for c in chunks if c.section_path]
        assert len(chunks_with_paths) > 0


class TestFTS:
    """Tests for full-text search functionality."""

    def test_search_finds_content(self, sample_epub: Path, temp_db: Path):
        """FTS search returns matching chunks."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        results = chunk_repo.search_fts("testing")
        conn.close()

        assert len(results) > 0

    def test_search_filter_by_type(self, sample_epub: Path, temp_db: Path):
        """FTS search can filter by content type."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        # Search for 'test' which appears in code blocks
        results = chunk_repo.search_fts("test", content_type=ContentType.CODE)
        conn.close()

        assert all(r.content_type == ContentType.CODE for r in results)

    def test_search_filter_by_book(self, sample_epub: Path, temp_db: Path):
        """FTS search can filter by book ID."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        # Search within specific book
        results = chunk_repo.search_fts("testing", book_id=book.id)
        conn.close()

        assert all(r.book_id == book.id for r in results)

    def test_search_no_results(self, sample_epub: Path, temp_db: Path):
        """FTS search returns empty list when no matches."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        results = chunk_repo.search_fts("xyznonexistentquery123")
        conn.close()

        assert len(results) == 0


class TestRemoval:
    """Tests for book removal functionality."""

    def test_remove_book_cascades_chunks(self, sample_epub: Path, temp_db: Path):
        """Removing a book also removes all its chunks."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        # Chunks exist
        assert chunk_repo.count_by_book(book.id) > 0

        # Remove book
        result = remove_book(book.id, temp_db)
        assert result is True

        # Reconnect after remove_book closed connection
        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        # Chunks gone
        assert chunk_repo.count_by_book(book.id) == 0
        conn.close()

    def test_remove_nonexistent_book(self, temp_db: Path):
        """Removing a nonexistent book returns False."""
        init_db(temp_db)
        result = remove_book("aaaaaa", temp_db)
        assert result is False

    def test_fts_index_cleared_on_remove(self, sample_epub: Path, temp_db: Path):
        """FTS index is cleared when book is removed."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        # Can find content
        results_before = chunk_repo.search_fts("testing")
        assert len(results_before) > 0
        conn.close()

        # Remove book
        remove_book(book.id, temp_db)

        # Reconnect and search again
        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        # Content no longer searchable
        results_after = chunk_repo.search_fts("testing")
        assert len(results_after) == 0
        conn.close()


class TestChunkIntegrity:
    """Tests for chunk data integrity."""

    def test_chunks_are_linked(self, sample_epub: Path, temp_db: Path):
        """Chunks have prev/next links for context navigation."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)
        conn.close()

        # First chunk has no prev
        assert chunks[0].prev_chunk_id is None
        # Last chunk has no next
        assert chunks[-1].next_chunk_id is None

        # Middle chunks have both links
        if len(chunks) > 2:
            middle = chunks[1]
            assert middle.prev_chunk_id is not None
            assert middle.next_chunk_id is not None

    def test_chunks_in_sequence_order(self, sample_epub: Path, temp_db: Path):
        """Chunks are retrieved in proper sequence order."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)
        conn.close()

        # Check sequences are monotonically increasing
        for i in range(len(chunks) - 1):
            assert chunks[i].sequence < chunks[i + 1].sequence

    def test_chunk_links_are_valid(self, sample_epub: Path, temp_db: Path):
        """Chunk prev/next links reference actual chunks."""
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)

        chunk_ids = {c.id for c in chunks}

        for chunk in chunks:
            if chunk.prev_chunk_id:
                assert chunk.prev_chunk_id in chunk_ids
            if chunk.next_chunk_id:
                assert chunk.next_chunk_id in chunk_ids

        conn.close()
