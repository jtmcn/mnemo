"""Tests for ChromaDB cosine distance migration."""

from __future__ import annotations

import chromadb
import numpy as np
import pytest

from mnemo.vectors.config import VectorConfig
from mnemo.vectors.store import VectorStore


@pytest.fixture
def ephemeral_client():
    """Create an ephemeral ChromaDB client for testing."""
    return chromadb.EphemeralClient()


@pytest.fixture
def sample_vectors():
    """Generate sample 1024-dim vectors for testing."""
    rng = np.random.default_rng(42)
    return {
        "ids": [f"chunk-{i}" for i in range(5)],
        "embeddings": rng.random((5, 1024)).tolist(),
        "metadatas": [
            {"book_id": "abc123", "content_type": "text"},
            {"book_id": "abc123", "content_type": "code"},
            {"book_id": "def456", "content_type": "text"},
            {"book_id": "def456", "content_type": "text"},
            {"book_id": "ghi789", "content_type": "code"},
        ],
        "documents": [f"Document {i}" for i in range(5)],
    }


class TestMigrateToCosinEmpty:
    """Tests for migrating empty collections."""

    def test_empty_collection_recreated_with_cosine(self, ephemeral_client):
        """migrate_to_cosine on empty collection recreates with cosine metric."""
        from mnemo.vectors.migrate import migrate_to_cosine

        # Create an empty L2 collection
        ephemeral_client.get_or_create_collection(
            name="mnemo",
            metadata={"hnsw:space": "l2"},
        )

        result = migrate_to_cosine(ephemeral_client, "mnemo")

        assert result["migrated"] == 0

        # Verify collection now uses cosine
        collection = ephemeral_client.get_collection("mnemo")
        assert collection.metadata.get("hnsw:space") == "cosine"


class TestMigrateToCosineNormal:
    """Tests for migrating populated collections."""

    def test_copies_all_vectors(self, ephemeral_client, sample_vectors):
        """migrate_to_cosine copies all vectors to new cosine collection."""
        from mnemo.vectors.migrate import migrate_to_cosine

        # Create L2 collection with data
        collection = ephemeral_client.get_or_create_collection(
            name="mnemo",
            metadata={"hnsw:space": "l2"},
        )
        collection.add(**sample_vectors)
        assert collection.count() == 5

        result = migrate_to_cosine(ephemeral_client, "mnemo")

        assert result["migrated"] == 5
        assert result["verified"] is True

        # Verify data preserved
        new_collection = ephemeral_client.get_collection("mnemo")
        assert new_collection.count() == 5

        # Verify all IDs preserved
        data = new_collection.get(include=["metadatas", "documents"])
        assert set(data["ids"]) == set(sample_vectors["ids"])

    def test_verifies_counts_before_delete(self, ephemeral_client, sample_vectors):
        """migrate_to_cosine verifies vector counts match before deleting old collection."""
        from mnemo.vectors.migrate import migrate_to_cosine

        collection = ephemeral_client.get_or_create_collection(
            name="mnemo",
            metadata={"hnsw:space": "l2"},
        )
        collection.add(**sample_vectors)

        # This should succeed (counts match)
        result = migrate_to_cosine(ephemeral_client, "mnemo")
        assert result["verified"] is True

    def test_raises_on_count_mismatch(self, ephemeral_client, sample_vectors, monkeypatch):
        """migrate_to_cosine raises RuntimeError on count mismatch."""
        from mnemo.vectors import migrate as migrate_mod
        from mnemo.vectors.migrate import migrate_to_cosine

        collection = ephemeral_client.get_or_create_collection(
            name="mnemo",
            metadata={"hnsw:space": "l2"},
        )
        collection.add(**sample_vectors)

        # Patch to simulate count mismatch: make a temp collection's count return wrong value
        original_get = ephemeral_client.get_collection

        call_count = 0

        def mock_get_collection(name, **kwargs):
            nonlocal call_count
            coll = original_get(name, **kwargs)
            # After migration copy, the temp collection count check
            if "_cosine_migration" in name:
                call_count += 1
                if call_count == 1:
                    # First count check after copying - return wrong count
                    original_count = coll.count
                    coll.count = lambda: 0  # Simulate mismatch
            return coll

        monkeypatch.setattr(ephemeral_client, "get_collection", mock_get_collection)

        with pytest.raises(RuntimeError, match="count mismatch"):
            migrate_to_cosine(ephemeral_client, "mnemo")

    def test_preserves_collection_name(self, ephemeral_client, sample_vectors):
        """migrate_to_cosine preserves collection name 'mnemo' after migration."""
        from mnemo.vectors.migrate import migrate_to_cosine

        collection = ephemeral_client.get_or_create_collection(
            name="mnemo",
            metadata={"hnsw:space": "l2"},
        )
        collection.add(**sample_vectors)

        migrate_to_cosine(ephemeral_client, "mnemo")

        # Collection should still be named "mnemo"
        collection = ephemeral_client.get_collection("mnemo")
        assert collection.name == "mnemo"
        assert collection.metadata.get("hnsw:space") == "cosine"

        # Temp collection should not exist
        collection_names = [c.name for c in ephemeral_client.list_collections()]
        assert not any("_cosine_migration" in name for name in collection_names)


class TestMigrateToCosineIdempotent:
    """Tests for idempotency of migration."""

    def test_already_cosine_is_noop(self, ephemeral_client, sample_vectors):
        """Running on already-cosine collection is safe and returns early."""
        from mnemo.vectors.migrate import migrate_to_cosine

        # Create cosine collection directly
        collection = ephemeral_client.get_or_create_collection(
            name="mnemo",
            metadata={"hnsw:space": "cosine"},
        )
        collection.add(**sample_vectors)

        result = migrate_to_cosine(ephemeral_client, "mnemo")

        assert result["migrated"] == 0
        assert result["already_cosine"] is True

        # Data should be untouched
        assert ephemeral_client.get_collection("mnemo").count() == 5


class TestVectorStoreCosineMetric:
    """Tests that VectorStore creates collections with cosine distance."""

    def test_creates_collection_with_cosine(self):
        """VectorStore creates collection with hnsw:space=cosine."""
        client = chromadb.EphemeralClient()
        config = VectorConfig(collection_name="test_cosine")
        store = VectorStore(config, client=client)

        assert store.collection.metadata.get("hnsw:space") == "cosine"
        store.close()
