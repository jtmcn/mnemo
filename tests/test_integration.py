"""Integration tests for the end-to-end EPUB ingestion pipeline.

Tests the full flow: EPUB parsing -> chunking -> storage -> search.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mnemo.ingest import ingest_book, reindex_all_books, remove_book
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


class TestIngestionCollection:
    """Tests for ingest_book collection support."""

    def test_ingest_persists_collection(self, sample_epub: Path, temp_db: Path):
        """ingest_book(collection="X") persists collection on the new book."""
        book, _ = ingest_book(sample_epub, temp_db, collection="ERCOT Nodal Protocols")

        # Reload from DB to confirm persistence
        from mnemo.storage import BookRepository

        conn = get_connection(temp_db)
        retrieved = BookRepository(conn).get(book.id)
        conn.close()

        assert retrieved.collection == "ERCOT Nodal Protocols"

    def test_ingest_without_collection_stores_none(self, sample_epub: Path, temp_db: Path):
        """ingest_book without collection results in NULL collection."""
        book, _ = ingest_book(sample_epub, temp_db)

        from mnemo.storage import BookRepository

        conn = get_connection(temp_db)
        retrieved = BookRepository(conn).get(book.id)
        conn.close()

        assert retrieved.collection is None

    def test_ingest_empty_collection_treated_as_none(self, sample_epub: Path, temp_db: Path):
        """ingest_book with collection='' stores NULL (empty == no collection)."""
        book, _ = ingest_book(sample_epub, temp_db, collection="")

        from mnemo.storage import BookRepository

        conn = get_connection(temp_db)
        retrieved = BookRepository(conn).get(book.id)
        conn.close()

        assert retrieved.collection is None

    def test_ingest_duplicate_does_not_retag(self, sample_epub: Path, temp_db: Path):
        """Duplicate ingest without force raises ValueError; existing collection preserved.

        Locks in Approach A: duplicate detection short-circuits before any
        collection mutation, so attempting to re-ingest with a different
        collection does NOT change the existing book's collection.
        """
        ingest_book(sample_epub, temp_db, collection="Original")

        with pytest.raises(ValueError, match="already indexed"):
            ingest_book(sample_epub, temp_db, collection="Different")

        # Verify the existing book still has its original collection
        from mnemo.storage import BookRepository

        conn = get_connection(temp_db)
        books = BookRepository(conn).list_all()
        conn.close()

        assert len(books) == 1
        assert books[0].collection == "Original"

    def test_ingest_force_with_collection_replaces(self, sample_epub: Path, temp_db: Path):
        """force=True with collection produces a fresh book carrying the new collection."""
        ingest_book(sample_epub, temp_db, collection="Original")
        book2, _ = ingest_book(sample_epub, temp_db, force=True, collection="Replaced")

        from mnemo.storage import BookRepository

        conn = get_connection(temp_db)
        retrieved = BookRepository(conn).get(book2.id)
        conn.close()

        assert retrieved.collection == "Replaced"


class TestReindexAllBooks:
    """Tests for reindex_all_books."""

    def test_reindex_empty_library(self, temp_db: Path):
        """Reindex with no books returns empty list."""
        init_db(temp_db)
        results = reindex_all_books(db_path=temp_db, embed=False)
        assert results == []

    def test_reindex_single_book(self, sample_epub: Path, temp_db: Path):
        """Reindex re-ingests an existing book."""
        book, original_count = ingest_book(sample_epub, temp_db)
        results = reindex_all_books(db_path=temp_db, embed=False)

        assert len(results) == 1
        assert results[0]["status"] == "success"
        assert results[0]["book_id"] == book.id
        assert results[0]["chunks"] == original_count
        assert results[0]["error"] is None

    def test_reindex_skips_missing_epub(self, sample_epub: Path, temp_db: Path):
        """Reindex skips books whose EPUB no longer exists on disk."""
        import shutil

        # Ingest from a copy so we can delete it
        copy_dir = temp_db.parent / "epubs"
        copy_dir.mkdir()
        copy_path = copy_dir / "sample.epub"
        shutil.copy(sample_epub, copy_path)

        ingest_book(copy_path, temp_db)

        # Delete the EPUB
        copy_path.unlink()

        results = reindex_all_books(db_path=temp_db, embed=False)
        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert "not found" in results[0]["error"].lower()

    def test_reindex_preserves_chunk_integrity(self, sample_epub: Path, temp_db: Path):
        """Reindex produces valid chunks with proper linking."""
        ingest_book(sample_epub, temp_db)
        results = reindex_all_books(db_path=temp_db, embed=False)

        book_id = results[0]["book_id"]
        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book_id)
        conn.close()

        assert len(chunks) > 0
        # Sequences are monotonically increasing
        for i in range(len(chunks) - 1):
            assert chunks[i].sequence < chunks[i + 1].sequence

    def test_reindex_preserves_collection(self, sample_epub: Path, temp_db: Path):
        """Reindex preserves an existing book's collection through force re-ingest."""
        from mnemo.storage import BookRepository

        ingest_book(sample_epub, temp_db, collection="ERCOT Nodal Protocols")
        reindex_all_books(db_path=temp_db, embed=False)

        conn = get_connection(temp_db)
        books = BookRepository(conn).list_all()
        conn.close()

        assert len(books) == 1
        assert books[0].collection == "ERCOT Nodal Protocols"


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


class TestEmbeddingFailureIsPartialSuccess:
    """A failed embedding leaves a durable, keyword-searchable book (#6).

    ingest_book commits the book and chunks (step 7) before embedding (step 8),
    so the embed error must be distinguishable from an ingest failure — the
    caller has to know a book was written.
    """

    def test_raises_embedding_failed_with_the_committed_book(self, sample_epub, temp_db):
        from unittest.mock import patch

        from mnemo.ingest import EmbeddingFailed
        from mnemo.storage import BookRepository

        with (
            patch(
                "mnemo.ingest.embed_book",
                side_effect=ValueError("DATABRICKS_HOST and DATABRICKS_TOKEN must be set"),
            ),
            pytest.raises(EmbeddingFailed) as exc_info,
        ):
            ingest_book(sample_epub, temp_db, embed=True)

        err = exc_info.value
        assert "DATABRICKS_HOST" in str(err)
        assert err.chunk_count > 0
        assert err.book.title == "Python Testing Guide"

        # The book really is committed and keyword-searchable
        conn = get_connection(temp_db)
        book_repo = BookRepository(conn)
        chunk_repo = ChunkRepository(conn)
        assert book_repo.get(err.book.id) is not None
        assert chunk_repo.count_by_book(err.book.id) == err.chunk_count
        conn.close()

    def test_embed_false_does_not_raise(self, sample_epub, temp_db):
        """Only the embed=True path can raise EmbeddingFailed."""
        book, count = ingest_book(sample_epub, temp_db, embed=False)
        assert count > 0
        assert book.id is not None

    def test_reindex_marks_unembedded_books_partial(self, sample_epub, temp_db, monkeypatch):
        """A book re-indexed but not re-embedded is partial, not failed.

        It was re-parsed, re-chunked and committed — reporting "failed, 0
        chunks" would send the user chasing a book that is actually fine
        except for its vectors.
        """
        from unittest.mock import patch

        ingest_book(sample_epub, temp_db, embed=False)

        monkeypatch.setenv("DATABRICKS_HOST", "https://example.invalid")
        monkeypatch.setenv("DATABRICKS_TOKEN", "token")

        with patch("mnemo.ingest.embed_book", side_effect=RuntimeError("service down")):
            results = reindex_all_books(db_path=temp_db, embed=True)

        assert len(results) == 1
        assert results[0]["status"] == "partial"
        assert results[0]["chunks"] > 0
        assert "service down" in results[0]["error"]

    def test_reindex_aborts_before_touching_anything_without_credentials(
        self, sample_epub, temp_db, monkeypatch
    ):
        """The credential preflight runs before any book is re-ingested.

        ingest_book deletes a book's existing vectors before re-embedding, so
        proceeding without credentials would strip the library book by book.
        """
        from unittest.mock import patch

        ingest_book(sample_epub, temp_db, embed=False)

        monkeypatch.delenv("DATABRICKS_HOST", raising=False)
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)

        with (
            patch("mnemo.ingest.ingest_book") as mock_ingest,
            pytest.raises(ValueError, match="DATABRICKS_HOST"),
        ):
            reindex_all_books(db_path=temp_db, embed=True)

        mock_ingest.assert_not_called()

    def test_embedding_failed_is_a_value_error(self, sample_epub, temp_db):
        """ingest_book has always documented embedding failure as a ValueError.

        mnemo exports ingest_book as public API, so an out-of-repo caller
        wrapping it in `except ValueError` must keep working.
        """
        from unittest.mock import patch

        from mnemo.ingest import EmbeddingFailed

        assert issubclass(EmbeddingFailed, ValueError)

        with (
            patch("mnemo.ingest.embed_book", side_effect=RuntimeError("boom")),
            pytest.raises(ValueError),
        ):
            ingest_book(sample_epub, temp_db, embed=True)
