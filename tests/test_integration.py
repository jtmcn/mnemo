"""Integration tests for the end-to-end EPUB ingestion pipeline.

Tests the full flow: EPUB parsing -> chunking -> storage -> search.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from mnemo import ingest as mnemo_ingest
from mnemo.ingest import DuplicateBook, ingest_book, reindex_all_books, remove_book
from mnemo.models import ContentType
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db
from tests.fixtures.epub_factory import create_test_epub
from tests.fixtures.pdf_factory import create_test_pdf


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
        # Short intro blocks merge, but chapter 3's long prose still splits
        ch3 = [c for c in chunks if c.section_path == ["Chapter 3: Best Practices"]]
        assert len(ch3) > 1

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

    def test_reindex_reports_a_folded_entry_as_merged(self, tmp_path: Path, temp_db: Path):
        """An edited file that now matches another entry folds into it, visibly."""

        def make(name: str, body: str) -> Path:
            return create_test_epub(
                title=name,
                chapters=[{"title": "One", "content": f"<p>{body}</p>"}],
                output_path=tmp_path / f"{name}.epub",
            )

        older = make("Older", "Body text for the older book.")
        newer = make("Newer", "Body text for the newer book.")
        first, _ = ingest_book(older, temp_db)
        second, _ = ingest_book(newer, temp_db)
        # Rewrite the older file so its content now equals the newer book's.
        make("Older", "Body text for the newer book.")

        results = reindex_all_books(db_path=temp_db, embed=False)

        conn = get_connection(temp_db)
        remaining = {b.id for b in BookRepository(conn).list_all()}
        conn.close()
        assert len(remaining) == 1
        survivor = remaining.pop()
        assert survivor in (first.id, second.id)
        assert len(results) == 2
        merged = [r for r in results if r["status"] == "merged"]
        assert len(merged) == 1
        assert merged[0]["book_id"] != survivor
        assert merged[0]["error"] == f"same content as {survivor}"
        assert all(r["book_id"] == survivor for r in results if r["status"] == "success")

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

    def test_reindex_replaces_book_whose_file_changed(self, sample_epub: Path, temp_db: Path):
        """A source file edited since ingest is replaced in place, keeping its id."""
        import shutil
        import zipfile

        from mnemo.storage import BookRepository

        copy_path = temp_db.parent / "sample.epub"
        shutil.copy(sample_epub, copy_path)
        old_book, _ = ingest_book(copy_path, temp_db)
        with zipfile.ZipFile(copy_path, "a") as zf:
            zf.writestr("extra.txt", "edited after ingest")

        results = reindex_all_books(db_path=temp_db, embed=False)

        conn = get_connection(temp_db)
        books = BookRepository(conn).list_all()
        conn.close()
        assert len(books) == 1
        assert books[0].id == old_book.id
        assert results[0]["book_id"] == books[0].id

    def test_reindex_keeps_edited_metadata(self, sample_epub: Path, temp_db: Path):
        book, _ = ingest_book(sample_epub, temp_db)
        conn = get_connection(temp_db)
        BookRepository(conn).update(book.id, title="Hand-Fixed Title", authors=["A. Person"])
        conn.commit()
        conn.close()

        reindex_all_books(db_path=temp_db, embed=False)

        conn = get_connection(temp_db)
        books = BookRepository(conn).list_all()
        conn.close()
        assert [(b.id, b.title, b.authors) for b in books] == [
            (book.id, "Hand-Fixed Title", ["A. Person"])
        ]


class TestContentDedup:
    """A file whose only change is its metadata is the same book."""

    @pytest.fixture
    def pdfs(self, tmp_path: Path) -> tuple[Path, Path]:
        original = create_test_pdf(
            tmp_path / "The Ontology Pipeline.pdf",
            title="The Ontology Pipeline",
            author="Jessica Talisman",
        )
        edited = create_test_pdf(
            tmp_path / "Ontology-Pipeline.pdf", title="Ontology-Pipeline", author="Karima Makrof"
        )
        return original, edited

    def test_metadata_only_change_is_a_duplicate(self, pdfs, temp_db: Path):
        original, edited = pdfs
        first, _ = ingest_book(original, temp_db)

        with pytest.raises(DuplicateBook) as exc:
            ingest_book(edited, temp_db)

        assert exc.value.book.id == first.id

    def test_force_replace_keeps_id_and_metadata(self, pdfs, temp_db: Path):
        original, edited = pdfs
        first, _ = ingest_book(original, temp_db)

        second, _ = ingest_book(edited, temp_db, force=True)

        assert second.id == first.id
        assert second.title == "The Ontology Pipeline"
        assert second.authors == ["Jessica Talisman"]
        assert second.added_at == first.added_at
        assert second.file_path == str(edited.resolve())
        conn = get_connection(temp_db)
        books = BookRepository(conn).list_all()
        conn.close()
        assert [b.id for b in books] == [first.id]

    def test_force_metadata_takes_the_files_values(self, pdfs, temp_db: Path):
        original, edited = pdfs
        first, _ = ingest_book(original, temp_db)

        second, _ = ingest_book(edited, temp_db, force=True, force_metadata=True)

        assert second.id == first.id
        assert second.title == "Ontology-Pipeline"
        assert second.authors == ["Karima Makrof"]

    def test_force_readd_keeps_edited_metadata(self, sample_epub: Path, temp_db: Path):
        first, _ = ingest_book(sample_epub, temp_db)
        conn = get_connection(temp_db)
        BookRepository(conn).update(first.id, title="Hand-Fixed Title", year="2021")
        conn.commit()
        conn.close()

        second, _ = ingest_book(sample_epub, temp_db, force=True)

        assert second.title == "Hand-Fixed Title"
        assert second.year == "2021"


class TestReplaceIsAtomic:
    """A replace that fails part-way leaves the existing book, edits and all."""

    @staticmethod
    def _retitle(db: Path, book_id: str, title: str) -> None:
        conn = get_connection(db)
        BookRepository(conn).update(book_id, title=title)
        conn.commit()
        conn.close()

    @staticmethod
    def _snapshot(db: Path) -> list[tuple[str, str, list[str]]]:
        conn = get_connection(db)
        try:
            chunks = ChunkRepository(conn)
            return [
                (b.id, b.title, [c.id for c in chunks.get_by_book(b.id)])
                for b in BookRepository(conn).list_all()
            ]
        finally:
            conn.close()

    @staticmethod
    def _explode(*_args, **_kwargs):
        raise RuntimeError("chunker broke")

    def test_chunker_failure_keeps_the_hash_matched_book(
        self, sample_epub: Path, temp_db: Path, monkeypatch
    ):
        book, _ = ingest_book(sample_epub, temp_db)
        self._retitle(temp_db, book.id, "Hand-Fixed Title")
        before = self._snapshot(temp_db)
        monkeypatch.setattr(mnemo_ingest.Chunker, "chunk", self._explode)

        with pytest.raises(RuntimeError, match="chunker broke"):
            ingest_book(sample_epub, temp_db, force=True)

        assert before[0][:2] == (book.id, "Hand-Fixed Title") and before[0][2]
        assert self._snapshot(temp_db) == before

    def test_chunker_failure_keeps_the_content_matched_book(
        self, tmp_path: Path, temp_db: Path, monkeypatch
    ):
        original = create_test_pdf(tmp_path / "a.pdf", title="The Ontology Pipeline")
        edited = create_test_pdf(tmp_path / "b.pdf", title="Ontology-Pipeline")
        book, _ = ingest_book(original, temp_db)
        self._retitle(temp_db, book.id, "Hand-Fixed Title")
        before = self._snapshot(temp_db)
        monkeypatch.setattr(mnemo_ingest.Chunker, "chunk", self._explode)

        with pytest.raises(RuntimeError, match="chunker broke"):
            ingest_book(edited, temp_db, force=True)

        assert self._snapshot(temp_db) == before

    def test_vector_store_open_failure_leaves_sql_consistent(
        self, sample_epub: Path, temp_db: Path, monkeypatch
    ):
        book, _ = ingest_book(sample_epub, temp_db)
        self._retitle(temp_db, book.id, "Hand-Fixed Title")

        class Unopenable:
            def __init__(self, _config):
                raise RuntimeError("chroma will not open")

        monkeypatch.setattr("mnemo.vectors.VectorStore", Unopenable)

        with pytest.raises(RuntimeError, match="chroma will not open"):
            ingest_book(sample_epub, temp_db, force=True)

        after = self._snapshot(temp_db)
        assert [(b_id, title) for b_id, title, _ in after] == [(book.id, "Hand-Fixed Title")]
        assert after[0][2]
        conn = get_connection(temp_db)
        orphans = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE book_id NOT IN (SELECT id FROM books)"
        ).fetchone()[0]
        conn.close()
        assert orphans == 0


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
                side_effect=ValueError("MNEMO_EMBED_BASE_URL must be set"),
            ),
            pytest.raises(EmbeddingFailed) as exc_info,
        ):
            ingest_book(sample_epub, temp_db, embed=True)

        err = exc_info.value
        assert "MNEMO_EMBED_BASE_URL" in str(err)
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

        monkeypatch.setenv("MNEMO_EMBED_BASE_URL", "https://example.invalid/v1")
        monkeypatch.setenv("MNEMO_EMBED_API_KEY", "token")

        # Preflight passes, then the provider dies mid-run.
        with (
            patch("mnemo.embeddings.Embedder"),
            patch("mnemo.ingest.embed_book", side_effect=RuntimeError("service down")),
        ):
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

        monkeypatch.delenv("MNEMO_EMBED_BASE_URL", raising=False)
        monkeypatch.delenv("MNEMO_EMBED_API_KEY", raising=False)

        with (
            patch("mnemo.ingest.ingest_book") as mock_ingest,
            pytest.raises(ValueError, match="MNEMO_EMBED_BASE_URL"),
        ):
            reindex_all_books(db_path=temp_db, embed=True)

        mock_ingest.assert_not_called()

    def test_reindex_aborts_before_touching_anything_on_a_bad_key(
        self, sample_epub, temp_db, monkeypatch
    ):
        """A configured endpoint that rejects the probe aborts the run.

        A base URL alone proves nothing — the key can be a placeholder and the
        model can be wrong. Reindexing on that would delete book 1's vectors
        before the 401 arrived, so the probe has to be a real round-trip.
        """
        from unittest.mock import MagicMock, patch

        import httpx

        ingest_book(sample_epub, temp_db, embed=False)

        monkeypatch.setenv("MNEMO_EMBED_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("MNEMO_EMBED_API_KEY", "your-api-key")

        unauthorized = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
        )
        with (
            patch("mnemo.embeddings.Embedder") as mock_embedder,
            patch("mnemo.ingest.ingest_book") as mock_ingest,
            pytest.raises(httpx.HTTPStatusError),
        ):
            mock_embedder.return_value.embed_one.side_effect = unauthorized
            reindex_all_books(db_path=temp_db, embed=True)

        mock_ingest.assert_not_called()

    def test_reindex_stops_after_the_first_embedding_failure(
        self, sample_epub, temp_db, tmp_path, monkeypatch
    ):
        """A systemic embedding failure must not strip the whole library.

        Each iteration deletes that book's vectors before re-embedding, so
        carrying on past the first failure — a provider that dies after the
        preflight probe succeeded — would destroy every book's vectors and
        rewrite none of them.
        """
        from unittest.mock import patch

        # Distinct content, or content dedup would treat it as the same book.
        second = create_test_epub(
            title="Second Book",
            chapters=[
                {"title": "Other", "content": "<p>Entirely different prose about rivers.</p>"}
            ],
            output_path=tmp_path / "second.epub",
        )

        ingest_book(sample_epub, temp_db, embed=False)
        ingest_book(second, temp_db, embed=False)

        monkeypatch.setenv("MNEMO_EMBED_BASE_URL", "https://example.invalid/v1")
        monkeypatch.setenv("MNEMO_EMBED_API_KEY", "expired")

        with (
            patch("mnemo.embeddings.Embedder"),
            patch("mnemo.ingest.embed_book", side_effect=RuntimeError("401")) as mock_embed,
        ):
            results = reindex_all_books(db_path=temp_db, embed=True)

        # Only the first book was attempted; the second was left alone.
        assert mock_embed.call_count == 1
        statuses = [r["status"] for r in results]
        assert statuses.count("partial") == 1
        assert statuses.count("skipped") == 1
        skipped = next(r for r in results if r["status"] == "skipped")
        assert "Stopped after an embedding failure" in skipped["error"]

    def test_all_boilerplate_book_is_not_an_embedding_failure(self, sample_epub, temp_db):
        """A book with nothing embeddable is structural, not a retriable gap.

        Re-running the embedding step can never give it vectors, so it must not
        raise EmbeddingFailed and send the user chasing a retry.
        """
        from unittest.mock import patch

        from mnemo.ingest import NothingToEmbed

        assert issubclass(NothingToEmbed, ValueError)

        with patch("mnemo.ingest.embed_book", side_effect=NothingToEmbed("all boilerplate")):
            book, count = ingest_book(sample_epub, temp_db, embed=True)

        assert count > 0
        assert book.id is not None

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


class TestConnectionLifetime:
    """ingest_book must not leak its SQLite handle when a step raises."""

    @staticmethod
    def _capture(monkeypatch) -> list[sqlite3.Connection]:
        """Record every connection ingest_book opens."""
        opened: list[sqlite3.Connection] = []
        real = mnemo_ingest.get_connection

        def spy(*args, **kwargs):
            conn = real(*args, **kwargs)
            opened.append(conn)
            return conn

        monkeypatch.setattr(mnemo_ingest, "get_connection", spy)
        return opened

    @staticmethod
    def _is_closed(conn: sqlite3.Connection) -> bool:
        try:
            conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            return True
        return False

    def test_parse_failure_closes_the_connection(
        self, sample_epub: Path, temp_db: Path, monkeypatch
    ):
        """A book that fails to parse must not leave the handle open.

        The connection is opened before parsing, and the MCP server is
        long-lived, so leaked handles accumulate across add_book calls.
        """
        opened = self._capture(monkeypatch)
        monkeypatch.setattr(
            mnemo_ingest, "parse_book", lambda _: (_ for _ in ()).throw(ValueError("bad epub"))
        )

        with pytest.raises(ValueError, match="bad epub"):
            ingest_book(sample_epub, temp_db)

        assert opened, "ingest_book opened no connection"
        assert all(self._is_closed(c) for c in opened)

    def test_duplicate_closes_the_connection(self, sample_epub: Path, temp_db: Path, monkeypatch):
        """The DuplicateBook path closes too, now that finally owns the handle."""
        ingest_book(sample_epub, temp_db)

        opened = self._capture(monkeypatch)
        with pytest.raises(DuplicateBook):
            ingest_book(sample_epub, temp_db)

        assert opened, "ingest_book opened no connection"
        assert all(self._is_closed(c) for c in opened)

    def test_vector_delete_failure_closes_the_store(
        self, sample_epub: Path, temp_db: Path, monkeypatch
    ):
        """A Chroma delete that fails on the force path still releases its fds.

        Same exposure as the SQLite handle: reached from MCP add_book(force=True)
        in a long-lived process.
        """
        ingest_book(sample_epub, temp_db)

        closed: list[bool] = []

        class ExplodingStore:
            def __init__(self, _config): ...

            def delete_by_book(self, _book_id):
                raise RuntimeError("chroma is unhappy")

            def close(self):
                closed.append(True)

        monkeypatch.setattr("mnemo.vectors.VectorStore", ExplodingStore)

        with pytest.raises(RuntimeError, match="chroma is unhappy"):
            ingest_book(sample_epub, temp_db, force=True)

        assert closed == [True]
