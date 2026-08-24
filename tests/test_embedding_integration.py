"""Integration tests for embedding pipeline."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mnemo.ingest import embed_book, ingest_book, remove_book

pytestmark = pytest.mark.integration

# Path to test fixture
SAMPLE_EPUB = Path(__file__).parent / "fixtures" / "sample.epub"


def create_mock_embedder():
    """Create a mock embedder that returns correct number of embeddings."""
    mock_embedder = MagicMock()
    # Return embeddings matching input length
    mock_embedder.embed_batch.side_effect = lambda texts: [[0.1] * 1024] * len(texts)
    return mock_embedder


class TestEmbedBook:
    """Tests for embed_book function."""

    @pytest.fixture
    def db_with_book(self, tmp_path):
        """Ingest a book and return paths."""
        db_path = tmp_path / "test.db"
        chroma_path = tmp_path / "chroma"

        book, chunk_count = ingest_book(
            SAMPLE_EPUB,
            db_path=db_path,
            embed=False,  # Don't embed during ingest
        )

        return {
            "db_path": db_path,
            "chroma_path": chroma_path,
            "book_id": book.id,
            "chunk_count": chunk_count,
        }

    def test_embed_book_stores_vectors(self, db_with_book):
        """embed_book creates vectors in ChromaDB."""
        from mnemo.vectors import VectorConfig, VectorStore

        # Mock the embedder at the package level (where embed_book imports from)
        with patch("mnemo.embeddings.Embedder") as mock_embedder_class:
            mock_embedder_class.return_value = create_mock_embedder()

            count = embed_book(
                db_with_book["book_id"],
                db_path=db_with_book["db_path"],
                chroma_path=db_with_book["chroma_path"],
            )

        # Verify vectors stored
        config = VectorConfig(persist_path=db_with_book["chroma_path"])
        store = VectorStore(config)
        assert store.count(book_id=db_with_book["book_id"]) == count
        store.close()

    def test_embed_book_batches_requests(self, db_with_book):
        """embed_book calls API in batches."""
        with patch("mnemo.embeddings.Embedder") as mock_embedder_class:
            mock_embedder = create_mock_embedder()
            mock_embedder_class.return_value = mock_embedder

            embed_book(
                db_with_book["book_id"],
                db_path=db_with_book["db_path"],
                chroma_path=db_with_book["chroma_path"],
                batch_size=50,
            )

            # Should have called embed_batch at least once
            assert mock_embedder.embed_batch.call_count >= 1
            # Each call should have max 50 texts
            for call in mock_embedder.embed_batch.call_args_list:
                texts = call[0][0]
                assert len(texts) <= 50

    def test_embed_book_nonexistent_raises(self, tmp_path):
        """embed_book raises for nonexistent book."""
        from mnemo.storage import init_db

        db_path = tmp_path / "test.db"
        init_db(db_path)  # Initialize empty database

        with (
            patch("mnemo.embeddings.Embedder"),
            pytest.raises(ValueError, match="No chunks found"),
        ):
            embed_book(
                "nonexistent",
                db_path=db_path,
                chroma_path=tmp_path / "chroma",
            )

    def test_embed_book_reembeds_cleanly(self, db_with_book):
        """Re-embedding deletes old vectors first."""
        from mnemo.vectors import VectorConfig, VectorStore

        with patch("mnemo.embeddings.Embedder") as mock_embedder_class:
            mock_embedder_class.return_value = create_mock_embedder()

            # Embed twice
            embed_book(
                db_with_book["book_id"],
                db_path=db_with_book["db_path"],
                chroma_path=db_with_book["chroma_path"],
            )
            count = embed_book(
                db_with_book["book_id"],
                db_path=db_with_book["db_path"],
                chroma_path=db_with_book["chroma_path"],
            )

        # Should have same count (not doubled)
        config = VectorConfig(persist_path=db_with_book["chroma_path"])
        store = VectorStore(config)
        assert store.count(book_id=db_with_book["book_id"]) == count
        store.close()


class TestIngestWithEmbed:
    """Tests for ingest_book with embed=True."""

    def test_ingest_with_embed(self, tmp_path):
        """ingest_book with embed=True generates vectors."""
        from mnemo.vectors import VectorConfig, VectorStore

        db_path = tmp_path / "test.db"
        chroma_path = tmp_path / "chroma"

        with patch("mnemo.embeddings.Embedder") as mock_embedder_class:
            mock_embedder_class.return_value = create_mock_embedder()

            book, chunk_count = ingest_book(
                SAMPLE_EPUB,
                db_path=db_path,
                embed=True,
                chroma_path=chroma_path,
            )

        # Verify vectors stored
        config = VectorConfig(persist_path=chroma_path)
        store = VectorStore(config)
        assert store.count(book_id=book.id) == chunk_count
        store.close()

    def test_ingest_without_embed(self, tmp_path):
        """ingest_book with embed=False doesn't create vectors."""
        from mnemo.vectors import VectorConfig, VectorStore

        db_path = tmp_path / "test.db"
        chroma_path = tmp_path / "chroma"

        book, chunk_count = ingest_book(
            SAMPLE_EPUB,
            db_path=db_path,
            embed=False,
            chroma_path=chroma_path,
        )

        # No vectors should exist
        config = VectorConfig(persist_path=chroma_path)
        store = VectorStore(config)
        assert store.count(book_id=book.id) == 0
        store.close()


class TestRemoveBookWithVectors:
    """Tests for remove_book cleaning up vectors."""

    def test_remove_deletes_vectors(self, tmp_path):
        """remove_book deletes vectors from ChromaDB."""
        from mnemo.vectors import VectorConfig, VectorStore

        db_path = tmp_path / "test.db"
        chroma_path = tmp_path / "chroma"

        with patch("mnemo.embeddings.Embedder") as mock_embedder_class:
            mock_embedder_class.return_value = create_mock_embedder()

            book, _ = ingest_book(
                SAMPLE_EPUB,
                db_path=db_path,
                embed=True,
                chroma_path=chroma_path,
            )

        # Verify vectors exist
        config = VectorConfig(persist_path=chroma_path)
        store = VectorStore(config)
        assert store.count(book_id=book.id) > 0

        # Remove book
        remove_book(book.id, db_path=db_path, chroma_path=chroma_path)

        # Vectors should be gone
        assert store.count(book_id=book.id) == 0
        store.close()


class TestMetadataInVectors:
    """Tests for metadata stored with vectors."""

    def test_vectors_have_correct_metadata(self, tmp_path):
        """Vectors include book_id, content_type, section_path."""
        from mnemo.vectors import VectorConfig, VectorStore

        db_path = tmp_path / "test.db"
        chroma_path = tmp_path / "chroma"

        with patch("mnemo.embeddings.Embedder") as mock_embedder_class:
            mock_embedder_class.return_value = create_mock_embedder()

            book, _ = ingest_book(
                SAMPLE_EPUB,
                db_path=db_path,
                embed=True,
                chroma_path=chroma_path,
            )

        # Query vectors
        config = VectorConfig(persist_path=chroma_path)
        store = VectorStore(config)
        results = store.query(
            query_embedding=[0.1] * 1024,
            n_results=1,
            book_id=book.id,
        )

        assert len(results) == 1
        metadata = results[0]["metadata"]
        assert metadata["book_id"] == book.id
        assert "content_type" in metadata
        assert "section_path" in metadata
        assert "sequence" in metadata
        store.close()
