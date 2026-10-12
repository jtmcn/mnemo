"""Integration tests for the end-to-end EPUB ingestion pipeline.

Tests the full flow: EPUB parsing -> chunking -> storage -> search.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from mnemo import ingest as mnemo_ingest
from mnemo.ingest import reindex_all_books, remove_book
from mnemo.models import Book, ContentType
from mnemo.services.book_service import intake
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db
from tests.fixtures.epub_factory import create_test_epub
from tests.fixtures.pdf_factory import create_test_pdf


def add(path: Path, db: Path, *, force: bool = False, embed: bool = False, **kwargs):
    """Take a book in through intake and return what was stored."""
    policy = "replace" if force else "reject"
    outcome = intake(path, db_path=db, embed=embed, on_duplicate=policy, **kwargs)
    assert outcome.book is not None and outcome.status in ("added", "replaced"), outcome.message
    return outcome.book, outcome.chunks


def _stored(db: Path) -> list[Book]:
    conn = get_connection(db)
    try:
        return BookRepository(conn).list_all()
    finally:
        conn.close()


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
        book, count = add(sample_epub, temp_db)

        assert book.id is not None
        assert book.title == "Python Testing Guide"
        assert "Test Author" in book.authors
        assert count > 0

    def test_ingest_duplicate_is_rejected(self, sample_epub: Path, temp_db: Path):
        """Taking the same file in twice is rejected without a replace."""
        add(sample_epub, temp_db)

        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.status == "rejected"
        assert outcome.reason == "duplicate"

    def test_ingest_force_replaces_book(self, sample_epub: Path, temp_db: Path):
        """Force flag allows re-indexing existing book."""
        book1, count1 = add(sample_epub, temp_db)
        book2, count2 = add(sample_epub, temp_db, force=True)

        # Same content, same ID
        assert book1.id == book2.id
        # Same chunk count
        assert count1 == count2

    def test_chunks_have_correct_types(self, sample_epub: Path, temp_db: Path):
        """Chunks are assigned correct content types."""
        book, _ = add(sample_epub, temp_db)

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
        book, _ = add(sample_epub, temp_db)

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
        book, count = add(sample_epub, temp_db)

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
        book, _ = add(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)
        conn.close()

        # At least some chunks should have section paths
        chunks_with_paths = [c for c in chunks if c.section_path]
        assert len(chunks_with_paths) > 0


class TestIngestionCollection:
    """Tests for collection support at intake."""

    def test_ingest_persists_collection(self, sample_epub: Path, temp_db: Path):
        """add(collection="X") persists collection on the new book."""
        book, _ = add(sample_epub, temp_db, collection="ERCOT Nodal Protocols")

        # Reload from DB to confirm persistence
        from mnemo.storage import BookRepository

        conn = get_connection(temp_db)
        retrieved = BookRepository(conn).get(book.id)
        conn.close()

        assert retrieved.collection == "ERCOT Nodal Protocols"

    def test_ingest_without_collection_stores_none(self, sample_epub: Path, temp_db: Path):
        """No collection results in a NULL collection."""
        book, _ = add(sample_epub, temp_db)

        from mnemo.storage import BookRepository

        conn = get_connection(temp_db)
        retrieved = BookRepository(conn).get(book.id)
        conn.close()

        assert retrieved.collection is None

    def test_ingest_empty_collection_treated_as_none(self, sample_epub: Path, temp_db: Path):
        """collection='' stores NULL (empty == no collection)."""
        book, _ = add(sample_epub, temp_db, collection="")

        from mnemo.storage import BookRepository

        conn = get_connection(temp_db)
        retrieved = BookRepository(conn).get(book.id)
        conn.close()

        assert retrieved.collection is None

    def test_ingest_duplicate_does_not_retag(self, sample_epub: Path, temp_db: Path):
        """A rejected duplicate leaves the existing collection alone.

        Locks in Approach A: duplicate detection short-circuits before any
        collection mutation, so attempting to re-ingest with a different
        collection does NOT change the existing book's collection.
        """
        add(sample_epub, temp_db, collection="Original")

        outcome = intake(sample_epub, db_path=temp_db, embed=False, collection="Different")
        assert outcome.status == "rejected"

        # Verify the existing book still has its original collection
        from mnemo.storage import BookRepository

        conn = get_connection(temp_db)
        books = BookRepository(conn).list_all()
        conn.close()

        assert len(books) == 1
        assert books[0].collection == "Original"

    def test_ingest_force_with_collection_replaces(self, sample_epub: Path, temp_db: Path):
        """force=True with collection produces a fresh book carrying the new collection."""
        add(sample_epub, temp_db, collection="Original")
        book2, _ = add(sample_epub, temp_db, force=True, collection="Replaced")

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
        book, original_count = add(sample_epub, temp_db)
        results = reindex_all_books(db_path=temp_db, embed=False)

        assert len(results) == 1
        assert results[0]["status"] == "success"
        assert results[0]["book_id"] == book.id
        assert results[0]["chunks"] == original_count
        assert results[0]["error"] is None

    @staticmethod
    def _epub(tmp_path: Path, name: str, title: str, body: str) -> Path:
        return create_test_epub(
            title=title,
            chapters=[{"title": "One", "content": f"<p>{body}</p>"}],
            output_path=tmp_path / f"{name}.epub",
        )

    def test_reindex_keeps_same_content_entries_apart(self, tmp_path: Path, temp_db: Path):
        """Reindex never folds a different entry by content, so edits survive."""
        body = "Body text shared by both copies of the book. " * 6
        older_file = self._epub(tmp_path, "older", "Older", body)
        older, _ = add(older_file, temp_db)
        conn = get_connection(temp_db)
        # A pre-2.7.0 row has no content hash, so the same text could be added twice.
        conn.execute("UPDATE books SET content_hash = NULL WHERE id = ?", (older.id,))
        BookRepository(conn).update(older.id, title="Hand-Fixed Title")
        conn.commit()
        conn.close()
        newer, _ = add(self._epub(tmp_path, "newer", "Newer", body), temp_db)
        reindex_all_books(db_path=temp_db, embed=False)  # the upgrade: both now share a hash
        self._epub(tmp_path, "newer", "Newer, Retitled", body)

        results = reindex_all_books(db_path=temp_db, embed=False)

        conn = get_connection(temp_db)
        books = {b.id: b.title for b in BookRepository(conn).list_all()}
        conn.close()
        assert books == {older.id: "Hand-Fixed Title", newer.id: "Newer"}
        assert sorted((r["book_id"], r["status"]) for r in results) == sorted(
            [(older.id, "success"), (newer.id, "success")]
        )

    def test_reindex_folds_a_byte_identical_newer_entry_into_the_older(
        self, tmp_path: Path, temp_db: Path
    ):
        import shutil

        older_file = self._epub(tmp_path, "older", "Older", "Older body text.")
        newer_file = self._epub(tmp_path, "newer", "Newer", "Newer body text.")
        older, _ = add(older_file, temp_db)
        newer, _ = add(newer_file, temp_db)
        shutil.copy(newer_file, older_file)

        results = reindex_all_books(db_path=temp_db, embed=False)

        conn = get_connection(temp_db)
        remaining = [b.id for b in BookRepository(conn).list_all()]
        conn.close()
        assert remaining == [older.id]
        by_id = {r["book_id"]: r for r in results}
        assert by_id[older.id]["status"] == "success"
        assert by_id[newer.id]["status"] == "merged"
        assert by_id[newer.id]["error"] == f"same file as {older.id}"

    def test_embedding_failure_while_folding_stops_the_run(
        self, tmp_path: Path, temp_db: Path, monkeypatch
    ):
        """The fold re-embeds the survivor, so a failure there strips it and must stop."""
        import shutil
        from unittest.mock import patch

        # Reindex walks newest first: newer (absorbs older), then older (folds), then earliest.
        earliest, _ = add(self._epub(tmp_path, "earliest", "Earliest", "Earliest text."), temp_db)
        older_file = self._epub(tmp_path, "older", "Older", "Older body text.")
        newer_file = self._epub(tmp_path, "newer", "Newer", "Newer body text.")
        older, _ = add(older_file, temp_db)
        newer, _ = add(newer_file, temp_db)
        shutil.copy(older_file, newer_file)
        monkeypatch.setenv("MNEMO_EMBED_BASE_URL", "https://example.invalid/v1")

        with (
            patch("mnemo.embeddings.Embedder"),
            patch("mnemo.ingest.embed_book", side_effect=[3, RuntimeError("token expired")]),
        ):
            results = reindex_all_books(db_path=temp_db, embed=True)

        statuses = [(r["book_id"], r["status"]) for r in results]
        assert (newer.id, "partial") in statuses
        assert (earliest.id, "skipped") in statuses

    def test_reindex_folds_a_byte_identical_older_entry_into_the_newer(
        self, tmp_path: Path, temp_db: Path
    ):
        import shutil

        older_file = self._epub(tmp_path, "older", "Older", "Older body text.")
        newer_file = self._epub(tmp_path, "newer", "Newer", "Newer body text.")
        older, _ = add(older_file, temp_db)
        newer, _ = add(newer_file, temp_db)
        shutil.copy(older_file, newer_file)

        results = reindex_all_books(db_path=temp_db, embed=False)

        conn = get_connection(temp_db)
        remaining = [b.id for b in BookRepository(conn).list_all()]
        conn.close()
        assert remaining == [newer.id]
        by_id = {r["book_id"]: r for r in results}
        assert by_id[newer.id]["status"] == "success"
        assert by_id[older.id]["status"] == "merged"
        assert by_id[older.id]["error"] == f"same file as {newer.id}"

    def test_reindex_skips_missing_epub(self, sample_epub: Path, temp_db: Path):
        """Reindex skips books whose EPUB no longer exists on disk."""
        import shutil

        # Ingest from a copy so we can delete it
        copy_dir = temp_db.parent / "epubs"
        copy_dir.mkdir()
        copy_path = copy_dir / "sample.epub"
        shutil.copy(sample_epub, copy_path)

        add(copy_path, temp_db)

        # Delete the EPUB
        copy_path.unlink()

        results = reindex_all_books(db_path=temp_db, embed=False)
        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert "not found" in results[0]["error"].lower()

    def test_reindex_preserves_chunk_integrity(self, sample_epub: Path, temp_db: Path):
        """Reindex produces valid chunks with proper linking."""
        add(sample_epub, temp_db)
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

        add(sample_epub, temp_db, collection="ERCOT Nodal Protocols")
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
        old_book, _ = add(copy_path, temp_db)
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
        book, _ = add(sample_epub, temp_db)
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
        first, _ = add(original, temp_db)

        outcome = intake(edited, db_path=temp_db, embed=False)

        assert outcome.reason == "duplicate_content"
        assert outcome.book is not None and outcome.book.id == first.id

    def test_force_replace_keeps_id_and_metadata(self, pdfs, temp_db: Path):
        original, edited = pdfs
        first, _ = add(original, temp_db)

        second, _ = add(edited, temp_db, force=True)

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
        first, _ = add(original, temp_db)

        second, _ = add(edited, temp_db, force=True, force_metadata=True)

        assert second.id == first.id
        assert second.title == "Ontology-Pipeline"
        assert second.authors == ["Karima Makrof"]

    def test_force_readd_keeps_edited_metadata(self, sample_epub: Path, temp_db: Path):
        first, _ = add(sample_epub, temp_db)
        conn = get_connection(temp_db)
        BookRepository(conn).update(first.id, title="Hand-Fixed Title", year="2021")
        conn.commit()
        conn.close()

        second, _ = add(sample_epub, temp_db, force=True)

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
        book, _ = add(sample_epub, temp_db)
        self._retitle(temp_db, book.id, "Hand-Fixed Title")
        before = self._snapshot(temp_db)
        monkeypatch.setattr(mnemo_ingest.Chunker, "chunk", self._explode)

        outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.reason == "pipeline_error" and "chunker broke" in outcome.message

        assert before[0][:2] == (book.id, "Hand-Fixed Title") and before[0][2]
        assert self._snapshot(temp_db) == before

    def test_chunker_failure_keeps_the_content_matched_book(
        self, tmp_path: Path, temp_db: Path, monkeypatch
    ):
        original = create_test_pdf(tmp_path / "a.pdf", title="The Ontology Pipeline")
        edited = create_test_pdf(tmp_path / "b.pdf", title="Ontology-Pipeline")
        book, _ = add(original, temp_db)
        self._retitle(temp_db, book.id, "Hand-Fixed Title")
        before = self._snapshot(temp_db)
        monkeypatch.setattr(mnemo_ingest.Chunker, "chunk", self._explode)

        outcome = intake(edited, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.reason == "pipeline_error"

        assert self._snapshot(temp_db) == before

    def test_vector_store_open_failure_is_partial_success(
        self, sample_epub: Path, temp_db: Path, monkeypatch
    ):
        book, _ = add(sample_epub, temp_db)
        self._retitle(temp_db, book.id, "Hand-Fixed Title")

        class Unopenable:
            def __init__(self, _config):
                raise RuntimeError("chroma will not open")

        monkeypatch.setattr("mnemo.vectors.VectorStore", Unopenable)

        outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.status == "replaced" and not outcome.embedded
        assert "chroma will not open" in outcome.notes[-1].message

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
        book, _ = add(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        results = chunk_repo.search_fts("testing")
        conn.close()

        assert len(results) > 0

    def test_search_filter_by_type(self, sample_epub: Path, temp_db: Path):
        """FTS search can filter by content type."""
        book, _ = add(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        # Search for 'test' which appears in code blocks
        results = chunk_repo.search_fts("test", content_type=ContentType.CODE)
        conn.close()

        assert all(r.content_type == ContentType.CODE for r in results)

    def test_search_filter_by_book(self, sample_epub: Path, temp_db: Path):
        """FTS search can filter by book ID."""
        book, _ = add(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        # Search within specific book
        results = chunk_repo.search_fts("testing", book_id=book.id)
        conn.close()

        assert all(r.book_id == book.id for r in results)

    def test_search_no_results(self, sample_epub: Path, temp_db: Path):
        """FTS search returns empty list when no matches."""
        book, _ = add(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        results = chunk_repo.search_fts("xyznonexistentquery123")
        conn.close()

        assert len(results) == 0


class TestRemoval:
    """Tests for book removal functionality."""

    def test_remove_book_cascades_chunks(self, sample_epub: Path, temp_db: Path):
        """Removing a book also removes all its chunks."""
        book, _ = add(sample_epub, temp_db)

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
        book, _ = add(sample_epub, temp_db)

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
        book, _ = add(sample_epub, temp_db)

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
        book, _ = add(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)
        conn.close()

        # Check sequences are monotonically increasing
        for i in range(len(chunks) - 1):
            assert chunks[i].sequence < chunks[i + 1].sequence

    def test_chunk_links_are_valid(self, sample_epub: Path, temp_db: Path):
        """Chunk prev/next links reference actual chunks."""
        book, _ = add(sample_epub, temp_db)

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

    store_book commits the book and chunks before embedding, so an embedding
    error must read as partial success — the caller has to know a book was written.
    """

    def test_embedding_failure_keeps_the_committed_book(self, sample_epub, temp_db):
        from unittest.mock import patch

        from mnemo.storage import BookRepository

        with patch(
            "mnemo.ingest.embed_book",
            side_effect=ValueError("MNEMO_EMBED_BASE_URL must be set"),
        ):
            outcome = intake(sample_epub, db_path=temp_db, embed=True)

        assert outcome.status == "added" and not outcome.embedded
        assert "MNEMO_EMBED_BASE_URL" in outcome.notes[-1].message
        assert outcome.chunks > 0
        assert outcome.book is not None and outcome.book.title == "Python Testing Guide"

        # The book really is committed and keyword-searchable
        conn = get_connection(temp_db)
        book_repo = BookRepository(conn)
        chunk_repo = ChunkRepository(conn)
        assert book_repo.get(outcome.book.id) is not None
        assert chunk_repo.count_by_book(outcome.book.id) == outcome.chunks
        conn.close()

    def test_embed_false_stores_without_vectors(self, sample_epub, temp_db):
        book, count = add(sample_epub, temp_db, embed=False)
        assert count > 0
        assert book.id is not None

    def test_reindex_marks_unembedded_books_partial(self, sample_epub, temp_db, monkeypatch):
        """A book re-indexed but not re-embedded is partial, not failed.

        It was re-parsed, re-chunked and committed — reporting "failed, 0
        chunks" would send the user chasing a book that is actually fine
        except for its vectors.
        """
        from unittest.mock import patch

        add(sample_epub, temp_db, embed=False)

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

        store_book deletes a book's existing vectors before re-embedding, so
        proceeding without credentials would strip the library book by book.
        """
        from unittest.mock import patch

        add(sample_epub, temp_db, embed=False)

        monkeypatch.delenv("MNEMO_EMBED_BASE_URL", raising=False)
        monkeypatch.delenv("MNEMO_EMBED_API_KEY", raising=False)

        with (
            patch("mnemo.ingest.store_book") as mock_store,
            pytest.raises(ValueError, match="MNEMO_EMBED_BASE_URL"),
        ):
            reindex_all_books(db_path=temp_db, embed=True)

        mock_store.assert_not_called()

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

        add(sample_epub, temp_db, embed=False)

        monkeypatch.setenv("MNEMO_EMBED_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("MNEMO_EMBED_API_KEY", "your-api-key")

        unauthorized = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
        )
        with (
            patch("mnemo.embeddings.Embedder") as mock_embedder,
            patch("mnemo.ingest.store_book") as mock_store,
            pytest.raises(httpx.HTTPStatusError),
        ):
            mock_embedder.return_value.embed_one.side_effect = unauthorized
            reindex_all_books(db_path=temp_db, embed=True)

        mock_store.assert_not_called()

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

        add(sample_epub, temp_db, embed=False)
        add(second, temp_db, embed=False)

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
        be reported as a failed embedding and send the user chasing a retry.
        """
        from unittest.mock import patch

        from mnemo.ingest import NothingToEmbed

        assert issubclass(NothingToEmbed, ValueError)

        with patch("mnemo.ingest.embed_book", side_effect=NothingToEmbed("all boilerplate")):
            book, count = add(sample_epub, temp_db, embed=True)

        assert count > 0
        assert book.id is not None


class TestConnectionLifetime:
    """Intake and the pipeline must not leak SQLite handles when a step fails."""

    @staticmethod
    def _capture(monkeypatch) -> list[sqlite3.Connection]:
        """Record every connection intake and store_book open."""
        from mnemo.services import book_service

        opened: list[sqlite3.Connection] = []
        real = mnemo_ingest.get_connection

        def spy(*args, **kwargs):
            conn = real(*args, **kwargs)
            opened.append(conn)
            return conn

        monkeypatch.setattr(mnemo_ingest, "get_connection", spy)
        monkeypatch.setattr(book_service, "get_connection", spy)
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
        """Intake holds a connection while it parses; the MCP server is long-lived."""
        from mnemo.services import book_service

        opened = self._capture(monkeypatch)
        monkeypatch.setattr(
            book_service, "parse_book", lambda _: (_ for _ in ()).throw(ValueError("bad epub"))
        )

        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.reason == "parse_failed"
        assert opened, "intake opened no connection"
        assert all(self._is_closed(c) for c in opened)

    def test_duplicate_closes_the_connection(self, sample_epub: Path, temp_db: Path, monkeypatch):
        add(sample_epub, temp_db)

        opened = self._capture(monkeypatch)
        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.reason == "duplicate"
        assert opened, "intake opened no connection"
        assert all(self._is_closed(c) for c in opened)

    def test_store_failure_closes_the_connection(
        self, sample_epub: Path, temp_db: Path, monkeypatch
    ):
        opened = self._capture(monkeypatch)
        monkeypatch.setattr(
            mnemo_ingest.ChunkRepository,
            "add_many",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("disk full")),
        )

        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.reason == "pipeline_error"
        assert len(opened) == 2, "intake and store_book each open one"
        assert all(self._is_closed(c) for c in opened)
        assert _stored(temp_db) == []

    def test_vector_delete_failure_closes_the_store(
        self, sample_epub: Path, temp_db: Path, monkeypatch
    ):
        """A Chroma delete that fails on the force path still releases its fds.

        Same exposure as the SQLite handle: reached from MCP add_book(force=True)
        in a long-lived process.
        """
        add(sample_epub, temp_db)

        closed: list[bool] = []

        class ExplodingStore:
            def __init__(self, _config): ...

            def delete_by_book(self, _book_id):
                raise RuntimeError("chroma is unhappy")

            def close(self):
                closed.append(True)

        monkeypatch.setattr("mnemo.vectors.VectorStore", ExplodingStore)

        outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.status == "replaced" and not outcome.embedded
        assert closed == [True]
