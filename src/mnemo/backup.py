"""Backup and restore functionality for Mnemo libraries.

Archive format (.tar.gz) contains:
  - manifest.json  — metadata: versions, counts, creation timestamp
  - mnemo.db       — SQLite database (WAL-consolidated snapshot)
  - chroma_export.json — ChromaDB vectors, embeddings, and metadata

Usage:
    from mnemo.backup import create_backup, restore_backup

    # Create a backup
    manifest = create_backup(db_path, chroma_client, Path("backup.tar.gz"))

    # Restore from a backup
    restore_backup(Path("backup.tar.gz"), new_db_path, chroma_client)
"""

from __future__ import annotations

import json
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import chromadb

from mnemo.storage.migrations import LATEST_VERSION


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract all members of a tar archive, rejecting path traversal attempts.

    Args:
        tar: Open tarfile to extract from.
        dest: Destination directory (must exist).

    Raises:
        ValueError: If any member would extract outside ``dest``.
    """
    resolved_dest = dest.resolve()
    for member in tar.getmembers():
        member_path = (resolved_dest / member.name).resolve()
        if not str(member_path).startswith(str(resolved_dest)):
            raise ValueError(
                f"Path traversal attempt detected in archive: {member.name!r}"
            )
    tar.extractall(dest, filter="data")  # noqa: S202 — paths validated above


def backup_sqlite(source_path: Path, dest_path: Path) -> None:
    """Create a WAL-consolidated copy of a SQLite database.

    Uses the sqlite3 online backup API to produce a consistent snapshot
    that can be read without the source WAL file.

    Args:
        source_path: Path to the source SQLite database.
        dest_path: Path to write the backup copy.
    """
    source = sqlite3.connect(source_path)
    dest = sqlite3.connect(dest_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()


def export_chromadb(
    client: chromadb.ClientAPI,
    dest_path: Path,
    collection_name: str = "mnemo",
    batch_size: int = 5000,
) -> int:
    """Export all vectors from a ChromaDB collection to a JSON file.

    Paginates through the collection in batches to handle large libraries.

    Args:
        client: ChromaDB client.
        dest_path: Path to write the JSON export file.
        collection_name: Name of the ChromaDB collection.
        batch_size: Number of vectors to fetch per page.

    Returns:
        Total number of vectors exported.
    """
    collection = client.get_collection(collection_name)

    all_ids: list[str] = []
    all_embeddings: list[list[float]] = []
    all_metadatas: list[dict] = []
    all_documents: list[str | None] = []

    offset = 0
    while True:
        batch = collection.get(
            include=["embeddings", "metadatas", "documents"],
            limit=batch_size,
            offset=offset,
        )
        batch_ids = batch.get("ids", [])
        if not batch_ids:
            break

        all_ids.extend(batch_ids)

        # Convert numpy arrays to plain Python lists
        raw_embeddings = batch.get("embeddings")
        if raw_embeddings is None:
            raw_embeddings = []
        for emb in raw_embeddings:
            if hasattr(emb, "tolist"):
                all_embeddings.append(emb.tolist())
            else:
                all_embeddings.append(list(emb))

        raw_metadatas = batch.get("metadatas")
        if raw_metadatas is not None:
            all_metadatas.extend(raw_metadatas)

        raw_docs = batch.get("documents")
        if raw_docs is not None:
            all_documents.extend(raw_docs)

        offset += len(batch_ids)
        if len(batch_ids) < batch_size:
            break

    data = {
        "ids": all_ids,
        "embeddings": all_embeddings,
        "metadatas": all_metadatas,
        "documents": all_documents,
    }
    dest_path.write_text(json.dumps(data), encoding="utf-8")
    return len(all_ids)


def create_backup(
    db_path: Path,
    chroma_client: chromadb.ClientAPI,
    output_path: Path,
    collection_name: str = "mnemo",
) -> dict:
    """Create a full backup archive of a Mnemo library.

    The resulting .tar.gz archive contains manifest.json, mnemo.db,
    and chroma_export.json.

    Args:
        db_path: Path to the SQLite database file.
        chroma_client: Connected ChromaDB client.
        output_path: Destination path for the .tar.gz archive.
        collection_name: Name of the ChromaDB collection to export.

    Returns:
        Manifest dict with version info, counts, and creation timestamp.
    """
    import mnemo

    with tempfile.TemporaryDirectory() as staging_dir:
        staging = Path(staging_dir)

        # 1. Backup SQLite (WAL-consolidated)
        staged_db = staging / "mnemo.db"
        backup_sqlite(db_path, staged_db)

        # 2. Export ChromaDB vectors
        staged_chroma = staging / "chroma_export.json"
        vector_count = export_chromadb(
            chroma_client, staged_chroma, collection_name=collection_name
        )

        # 3. Gather counts from the DB snapshot
        conn = sqlite3.connect(staged_db)
        try:
            schema_version = conn.execute(
                "SELECT version FROM schema_version"
            ).fetchone()
            schema_ver = schema_version[0] if schema_version else 0
            book_count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        finally:
            conn.close()

        # 4. Build manifest
        manifest = {
            "mnemo_version": mnemo.__version__,
            "schema_version": schema_ver,
            "chromadb_version": chromadb.__version__,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "book_count": book_count,
            "chunk_count": chunk_count,
            "vector_count": vector_count,
        }

        staged_manifest = staging / "manifest.json"
        staged_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # 5. Pack archive (flat member names — no directory prefix)
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(staged_manifest, arcname="manifest.json")
            tar.add(staged_db, arcname="mnemo.db")
            tar.add(staged_chroma, arcname="chroma_export.json")

    return manifest


def _restore_chromadb(
    client: chromadb.ClientAPI,
    export_path: Path,
    collection_name: str = "mnemo",
    batch_size: int = 5000,
) -> int:
    """Restore ChromaDB vectors from a JSON export file.

    Deletes any existing collection and recreates it with cosine distance
    before restoring vectors in batches.

    Args:
        client: ChromaDB client to restore into.
        export_path: Path to the chroma_export.json file.
        collection_name: Name of the collection to create.
        batch_size: Number of vectors to insert per batch.

    Returns:
        Total number of vectors restored.
    """
    data = json.loads(export_path.read_text(encoding="utf-8"))

    ids: list[str] = data.get("ids", [])
    embeddings: list[list[float]] = data.get("embeddings", [])
    metadatas: list[dict] = data.get("metadatas", [])
    documents: list[str | None] = data.get("documents", [])

    # Remove existing collection if present, then recreate with cosine metric
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass  # Collection did not exist — that's fine

    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # Insert in batches
    total = len(ids)
    for start in range(0, total, batch_size):
        end = start + batch_size
        batch_ids = ids[start:end]
        batch_embs = embeddings[start:end]
        batch_metas = metadatas[start:end]
        batch_docs = documents[start:end] if documents else None

        kwargs: dict = {
            "ids": batch_ids,
            "embeddings": batch_embs,
            "metadatas": batch_metas,
        }
        if batch_docs:
            kwargs["documents"] = batch_docs

        collection.add(**kwargs)

    return total


def restore_backup(
    archive_path: Path,
    db_path: Path,
    chroma_client: chromadb.ClientAPI,
    force: bool = False,
    collection_name: str = "mnemo",
) -> dict:
    """Restore a Mnemo library from a backup archive.

    Args:
        archive_path: Path to the .tar.gz backup archive.
        db_path: Destination path for the restored SQLite database.
        chroma_client: ChromaDB client to restore vectors into.
        force: If True, overwrite existing database. Defaults to False.
        collection_name: Name of the ChromaDB collection to restore.

    Returns:
        Manifest dict from the archive.

    Raises:
        FileExistsError: If ``db_path`` exists and ``force`` is False.
        ValueError: If the archive is missing manifest.json.
        ValueError: If the manifest schema_version exceeds LATEST_VERSION.
    """
    if db_path.exists():
        if not force:
            raise FileExistsError(
                f"Database already exists at {db_path}. Use force=True to overwrite."
            )
        # Remove the existing file so sqlite3 backup can write a fresh DB
        db_path.unlink()

    with tempfile.TemporaryDirectory() as staging_dir:
        staging = Path(staging_dir)

        with tarfile.open(archive_path, "r:gz") as tar:
            _safe_extract(tar, staging)

        manifest_path = staging / "manifest.json"
        if not manifest_path.exists():
            raise ValueError(
                "Archive is missing manifest.json — this may not be a valid Mnemo backup."
            )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        schema_ver = manifest.get("schema_version", 0)
        if schema_ver > LATEST_VERSION:
            raise ValueError(
                f"Archive schema_version {schema_ver} is newer than this installation "
                f"supports (LATEST_VERSION={LATEST_VERSION}). "
                "Upgrade Mnemo before restoring."
            )

        # Restore SQLite
        staged_db = staging / "mnemo.db"
        backup_sqlite(staged_db, db_path)

        # Restore ChromaDB
        staged_chroma = staging / "chroma_export.json"
        _restore_chromadb(chroma_client, staged_chroma, collection_name=collection_name)

    return manifest
