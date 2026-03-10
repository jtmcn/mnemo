"""ChromaDB collection migration from L2 to cosine distance.

Migrates existing collections by copying all data to a new collection
with cosine distance metric. Embeddings are preserved as-is (no re-embedding).
"""

from __future__ import annotations

import logging

import chromadb

logger = logging.getLogger(__name__)

# Batch size for copying vectors between collections
_BATCH_SIZE = 1000


def migrate_to_cosine(
    client: chromadb.ClientAPI,
    collection_name: str = "mnemo",
) -> dict:
    """Migrate a ChromaDB collection from L2 to cosine distance.

    Copies all vectors, metadata, and documents to a new collection with
    cosine distance metric. Verifies counts match before deleting the old
    collection.

    Args:
        client: ChromaDB client instance
        collection_name: Name of the collection to migrate

    Returns:
        Dict with migration results:
        - {"migrated": N, "verified": True} on success
        - {"migrated": 0, "already_cosine": True} if already cosine
        - {"migrated": 0} if collection was empty

    Raises:
        RuntimeError: If vector count mismatch after copy (data integrity check)
    """
    # Get existing collection
    try:
        old_collection = client.get_collection(collection_name)
    except Exception:
        # Collection doesn't exist - create with cosine and return
        client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        return {"migrated": 0}

    # Check if already using cosine distance
    if old_collection.metadata.get("hnsw:space") == "cosine":
        logger.info("Collection '%s' already uses cosine distance", collection_name)
        return {"migrated": 0, "already_cosine": True}

    old_count = old_collection.count()

    # Handle empty collection: delete and recreate with cosine
    if old_count == 0:
        logger.info("Empty collection, recreating with cosine metric")
        client.delete_collection(collection_name)
        client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        return {"migrated": 0}

    # Create temp collection with cosine metric
    temp_name = f"{collection_name}_cosine_migration"
    # Clean up any leftover temp collection from a previous failed migration
    try:
        client.delete_collection(temp_name)
    except Exception:
        pass

    temp_collection = client.create_collection(
        name=temp_name,
        metadata={"hnsw:space": "cosine"},
    )

    # Batch copy all data from old to temp
    _batch_copy(old_collection, temp_collection, old_count)

    # Verify counts match
    temp_count = temp_collection.count()
    if temp_count != old_count:
        # Clean up temp on failure
        client.delete_collection(temp_name)
        raise RuntimeError(
            f"Migration count mismatch: expected {old_count}, got {temp_count}"
        )

    logger.info("Verified %d vectors copied to temp collection", temp_count)

    # Delete old collection
    client.delete_collection(collection_name)

    # Create final collection with original name and cosine metric
    final_collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # Copy from temp to final
    _batch_copy(temp_collection, final_collection, temp_count)

    # Verify final counts
    final_count = final_collection.count()
    if final_count != old_count:
        raise RuntimeError(
            f"Final migration count mismatch: expected {old_count}, got {final_count}"
        )

    # Clean up temp collection
    client.delete_collection(temp_name)

    logger.info(
        "Successfully migrated %d vectors from L2 to cosine distance",
        final_count,
    )

    return {"migrated": final_count, "verified": True}


def _batch_copy(
    source: chromadb.Collection,
    target: chromadb.Collection,
    total: int,
) -> None:
    """Copy all data from source to target collection in batches."""
    offset = 0
    while offset < total:
        batch = source.get(
            include=["embeddings", "metadatas", "documents"],
            limit=_BATCH_SIZE,
            offset=offset,
        )

        if not batch["ids"]:
            break

        kwargs: dict = {
            "ids": batch["ids"],
            "embeddings": batch["embeddings"],
            "metadatas": batch["metadatas"],
        }
        if batch.get("documents"):
            kwargs["documents"] = batch["documents"]

        target.add(**kwargs)
        offset += len(batch["ids"])
