"""Tests for vector store."""

from pathlib import Path

import chromadb
import numpy as np
import pytest

from mnemo.vectors import QueryResult, VectorConfig, VectorStore


@pytest.fixture
def ephemeral_store():
    """Create a vector store backed by EphemeralClient (no file descriptors)."""
    client = chromadb.EphemeralClient()
    config = VectorConfig(collection_name="test")
    store = VectorStore(config, client=client)
    yield store
    store.close()


class TestVectorConfig:
    """Tests for VectorConfig."""

    def test_default_values(self):
        """Config has sensible defaults."""
        config = VectorConfig()
        assert config.collection_name == "mnemo"
        assert config.persist_path is None

    def test_get_persist_path_default(self):
        """Default path is ~/.mnemo/chroma."""
        config = VectorConfig()
        path = config.get_persist_path()
        assert path == Path.home() / ".mnemo" / "chroma"

    def test_get_persist_path_custom(self, tmp_path):
        """Custom path is used when provided."""
        config = VectorConfig(persist_path=tmp_path / "custom")
        path = config.get_persist_path()
        assert path == tmp_path / "custom"


class TestVectorStore:
    """Tests for VectorStore."""

    @pytest.fixture
    def store(self, ephemeral_store):
        return ephemeral_store

    @pytest.fixture
    def sample_embedding(self):
        """Sample 1024-dim embedding."""
        return [0.1] * 1024

    @pytest.fixture
    def sample_embeddings(self):
        """Multiple sample embeddings."""
        return [
            [0.1] * 1024,
            [0.2] * 1024,
            [0.3] * 1024,
        ]

    def test_init_creates_collection(self, store):
        """Store initializes with collection."""
        assert store.collection is not None
        assert store.collection.name == "test"

    def test_embedding_dim_constant(self):
        """Embedding dimension is documented."""
        assert VectorStore.EMBEDDING_DIM == 1024

    def test_add_empty_list(self, store):
        """Adding empty list is a no-op."""
        store.add([], [], [])
        assert store.count() == 0

    def test_add_single_vector(self, store, sample_embedding):
        """Can add a single vector."""
        store.add(
            ids=["chunk-1"],
            embeddings=[sample_embedding],
            metadatas=[{"book_id": "abc123", "content_type": "text"}],
        )
        assert store.count() == 1

    def test_add_multiple_vectors(self, store, sample_embeddings):
        """Can add multiple vectors."""
        store.add(
            ids=["chunk-1", "chunk-2", "chunk-3"],
            embeddings=sample_embeddings,
            metadatas=[
                {"book_id": "abc123", "content_type": "text"},
                {"book_id": "abc123", "content_type": "code"},
                {"book_id": "def456", "content_type": "text"},
            ],
        )
        assert store.count() == 3

    def test_add_with_documents(self, store, sample_embedding):
        """Can add vectors with original text."""
        store.add(
            ids=["chunk-1"],
            embeddings=[sample_embedding],
            metadatas=[{"book_id": "abc123"}],
            documents=["Original chunk text"],
        )
        assert store.count() == 1

    def test_add_validates_length_mismatch(self, store, sample_embedding):
        """Raises on mismatched input lengths."""
        with pytest.raises(ValueError, match="same length"):
            store.add(
                ids=["chunk-1", "chunk-2"],
                embeddings=[sample_embedding],  # Only one
                metadatas=[{"book_id": "abc123"}],
            )

    def test_add_validates_dimension(self, store):
        """Raises on wrong embedding dimension."""
        with pytest.raises(ValueError, match="1024-dimensional"):
            store.add(
                ids=["chunk-1"],
                embeddings=[[0.1] * 512],  # Wrong dim
                metadatas=[{"book_id": "abc123"}],
            )


class TestVectorStoreQuery:
    """Tests for query functionality."""

    @pytest.fixture
    def populated_store(self):
        """Store with sample vectors."""
        client = chromadb.EphemeralClient()
        config = VectorConfig(collection_name="test")
        store = VectorStore(config, client=client)

        # Add vectors with different metadata
        store.add(
            ids=["chunk-1", "chunk-2", "chunk-3"],
            embeddings=[
                [1.0] + [0.0] * 1023,  # Point along first axis
                [0.0] + [1.0] + [0.0] * 1022,  # Point along second axis
                [0.5] + [0.5] + [0.0] * 1022,  # Between first two
            ],
            metadatas=[
                {"book_id": "book1", "content_type": "text", "section": "ch1"},
                {"book_id": "book1", "content_type": "code", "section": "ch2"},
                {"book_id": "book2", "content_type": "text", "section": "ch1"},
            ],
            documents=["First chunk", "Second chunk", "Third chunk"],
        )
        yield store
        store.close()

    def test_query_returns_results(self, populated_store):
        """Query returns QueryResult objects."""
        results = populated_store.query(
            query_embedding=[1.0] + [0.0] * 1023,
            n_results=3,
        )
        assert len(results) == 3
        assert all(isinstance(r, dict) for r in results)
        assert all("id" in r and "distance" in r for r in results)

    def test_query_orders_by_distance(self, populated_store):
        """Results are ordered by distance."""
        # Query close to chunk-1
        results = populated_store.query(
            query_embedding=[1.0] + [0.0] * 1023,
            n_results=3,
        )
        # chunk-1 should be closest (same direction)
        assert results[0]["id"] == "chunk-1"

    def test_query_includes_metadata(self, populated_store):
        """Results include metadata."""
        results = populated_store.query(
            query_embedding=[1.0] + [0.0] * 1023,
            n_results=1,
        )
        assert results[0]["metadata"]["book_id"] == "book1"
        assert results[0]["metadata"]["content_type"] == "text"

    def test_query_includes_documents(self, populated_store):
        """Results include original documents."""
        results = populated_store.query(
            query_embedding=[1.0] + [0.0] * 1023,
            n_results=1,
        )
        assert results[0]["document"] == "First chunk"

    def test_query_filter_by_book(self, populated_store):
        """Can filter results by book_id."""
        results = populated_store.query(
            query_embedding=[0.5] + [0.5] + [0.0] * 1022,
            n_results=3,
            book_id="book2",
        )
        assert len(results) == 1
        assert results[0]["metadata"]["book_id"] == "book2"

    def test_query_filter_by_content_type(self, populated_store):
        """Can filter results by content_type."""
        results = populated_store.query(
            query_embedding=[0.5] + [0.5] + [0.0] * 1022,
            n_results=3,
            content_type="code",
        )
        assert len(results) == 1
        assert results[0]["metadata"]["content_type"] == "code"

    def test_query_filter_combined(self, populated_store):
        """Can combine book_id and content_type filters."""
        results = populated_store.query(
            query_embedding=[0.5] + [0.5] + [0.0] * 1022,
            n_results=3,
            book_id="book1",
            content_type="text",
        )
        assert len(results) == 1
        assert results[0]["metadata"]["book_id"] == "book1"
        assert results[0]["metadata"]["content_type"] == "text"

    def test_query_validates_dimension(self, populated_store):
        """Raises on wrong query dimension."""
        with pytest.raises(ValueError, match="1024-dimensional"):
            populated_store.query(
                query_embedding=[0.1] * 512,  # Wrong dim
                n_results=10,
            )


class TestVectorStoreDelete:
    """Tests for delete functionality."""

    @pytest.fixture
    def populated_store(self):
        """Store with vectors from multiple books."""
        client = chromadb.EphemeralClient()
        config = VectorConfig(collection_name="test")
        store = VectorStore(config, client=client)

        store.add(
            ids=["book1-1", "book1-2", "book2-1"],
            embeddings=[
                [0.1] * 1024,
                [0.2] * 1024,
                [0.3] * 1024,
            ],
            metadatas=[
                {"book_id": "book1"},
                {"book_id": "book1"},
                {"book_id": "book2"},
            ],
        )
        yield store
        store.close()

    def test_delete_by_book(self, populated_store):
        """Can delete all vectors for a book."""
        count = populated_store.delete_by_book("book1")
        assert count == 2
        assert populated_store.count() == 1

    def test_delete_nonexistent_book(self, populated_store):
        """Deleting nonexistent book returns 0."""
        count = populated_store.delete_by_book("nonexistent")
        assert count == 0
        assert populated_store.count() == 3

    def test_count_by_book(self, populated_store):
        """Can count vectors for a specific book."""
        assert populated_store.count(book_id="book1") == 2
        assert populated_store.count(book_id="book2") == 1
        assert populated_store.count() == 3


class TestNormalization:
    """Tests for L2 normalization."""

    @pytest.fixture
    def store(self, ephemeral_store):
        return ephemeral_store

    def test_normalize_unit_vector(self, store):
        """Unit vectors remain unit vectors."""
        embedding = [1.0] + [0.0] * 1023
        normalized = store._normalize([embedding])
        norm = np.linalg.norm(normalized[0])
        assert abs(norm - 1.0) < 1e-6

    def test_normalize_scaled_vector(self, store):
        """Scaled vectors become unit vectors."""
        embedding = [100.0] + [0.0] * 1023
        normalized = store._normalize([embedding])
        norm = np.linalg.norm(normalized[0])
        assert abs(norm - 1.0) < 1e-6

    def test_normalize_preserves_direction(self, store):
        """Normalization preserves direction."""
        embedding = [3.0, 4.0] + [0.0] * 1022
        normalized = store._normalize([embedding])[0]
        # Should be [0.6, 0.8, 0, 0, ...]
        assert abs(normalized[0] - 0.6) < 1e-6
        assert abs(normalized[1] - 0.8) < 1e-6

    def test_normalize_handles_zero_vector(self, store):
        """Zero vectors don't cause division by zero."""
        embedding = [0.0] * 1024
        # Should not raise
        normalized = store._normalize([embedding])
        # Result will be near-zero (divided by epsilon)
        assert len(normalized[0]) == 1024


class TestPersistence:
    """Tests for persistence across restarts."""

    def test_data_persists(self, tmp_path):
        """Data survives store recreation."""
        config = VectorConfig(
            persist_path=tmp_path / "test_chroma",
            collection_name="test",
        )

        # Create store and add data
        store1 = VectorStore(config)
        store1.add(
            ids=["chunk-1"],
            embeddings=[[0.1] * 1024],
            metadatas=[{"book_id": "abc123"}],
        )
        store1.close()

        # Recreate store and verify
        store2 = VectorStore(config)
        assert store2.count() == 1
        store2.close()
