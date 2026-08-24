"""Tests for backup and restore functionality.

Covers DATA-01 (SQLite backup), DATA-02 (ChromaDB export),
DATA-03 (restore and round-trip), and safety checks.
"""

from __future__ import annotations

import json
import sqlite3
import tarfile
from pathlib import Path

import chromadb
import numpy as np
import pytest

from mnemo.backup import create_backup, restore_backup
from mnemo.storage.database import init_db
from mnemo.storage.migrations import LATEST_VERSION

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ephemeral_client():
    """Create a clean ephemeral ChromaDB client."""
    client = chromadb.EphemeralClient()
    client.clear_system_cache()
    for col in client.list_collections():
        client.delete_collection(col.name)
    return client


@pytest.fixture()
def populated_library(tmp_path):
    """Set up a test library with SQLite + ChromaDB data.

    Returns (db_path, chroma_client, collection) tuple.
    """
    db_path = tmp_path / "mnemo.db"
    init_db(db_path)

    # Insert a test book and a few chunks
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO books (id, title, authors, file_hash, structure_source, added_at) "
        "VALUES ('abc123', 'Test Book', '[\"Author A\"]', 'hash001', 'toc', '2026-01-01T00:00:00Z')"
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO chunks (id, book_id, content, content_type, token_count, "
            "section_path, sections, sequence) "
            "VALUES (?, 'abc123', ?, 'text', 100, '[]', '[]', ?)",
            (f"chunk-{i}", f"Content {i}", i),
        )
    conn.commit()
    conn.close()

    # Create a ChromaDB collection with 5 test vectors
    chroma_client = chromadb.EphemeralClient()
    chroma_client.clear_system_cache()
    collection = chroma_client.create_collection(
        name="mnemo",
        metadata={"hnsw:space": "cosine"},
    )
    rng = np.random.default_rng(42)
    embeddings = rng.random((5, 1024)).tolist()
    collection.add(
        ids=[f"vec-{i}" for i in range(5)],
        embeddings=embeddings,
        metadatas=[{"book_id": "abc123", "content_type": "text"} for _ in range(5)],
        documents=[f"Doc {i}" for i in range(5)],
    )

    return db_path, chroma_client, collection


# ---------------------------------------------------------------------------
# DATA-01: SQLite backup
# ---------------------------------------------------------------------------


class TestBackup:
    """Tests for create_backup() covering DATA-01 and DATA-02."""

    def test_backup_creates_archive_with_sqlite(self, populated_library, tmp_path):
        """create_backup() produces a .tar.gz that contains mnemo.db."""
        db_path, chroma_client, _col = populated_library
        output = tmp_path / "backup.tar.gz"

        create_backup(db_path, chroma_client, output)

        assert output.exists()
        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()
        assert "mnemo.db" in names

    def test_backup_sqlite_consolidates_wal(self, populated_library, tmp_path):
        """Backed-up SQLite DB is readable standalone (no WAL dependency)."""
        db_path, chroma_client, _col = populated_library
        output = tmp_path / "backup.tar.gz"

        create_backup(db_path, chroma_client, output)

        # Extract the db and verify it's readable
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with tarfile.open(output, "r:gz") as tar:
            tar.extract("mnemo.db", path=extract_dir)

        restored_db = extract_dir / "mnemo.db"
        conn = sqlite3.connect(restored_db)
        rows = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        conn.close()
        assert rows == 1

    # -----------------------------------------------------------------------
    # DATA-02: ChromaDB export
    # -----------------------------------------------------------------------

    def test_backup_creates_archive_with_chroma(self, populated_library, tmp_path):
        """Archive contains chroma_export.json with ids, embeddings, metadatas."""
        db_path, chroma_client, _col = populated_library
        output = tmp_path / "backup.tar.gz"

        create_backup(db_path, chroma_client, output)

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()
            assert "chroma_export.json" in names
            f = tar.extractfile("chroma_export.json")
            data = json.loads(f.read())

        assert "ids" in data
        assert "embeddings" in data
        assert "metadatas" in data
        assert len(data["ids"]) == 5

    def test_backup_chroma_pagination(self, tmp_path):
        """export_chromadb works correctly with small batch_size (pagination)."""
        from mnemo.backup import export_chromadb

        db_path = tmp_path / "mnemo.db"
        init_db(db_path)

        chroma_client = chromadb.EphemeralClient()
        chroma_client.clear_system_cache()
        collection = chroma_client.create_collection(
            name="mnemo",
            metadata={"hnsw:space": "cosine"},
        )
        rng = np.random.default_rng(99)
        embeddings = rng.random((5, 1024)).tolist()
        collection.add(
            ids=[f"v-{i}" for i in range(5)],
            embeddings=embeddings,
            metadatas=[{"book_id": "x"} for _ in range(5)],
        )

        dest = tmp_path / "chroma_export.json"
        count = export_chromadb(chroma_client, dest, collection_name="mnemo", batch_size=2)

        assert count == 5
        data = json.loads(dest.read_text())
        assert len(data["ids"]) == 5

    def test_backup_manifest_contains_metadata(self, populated_library, tmp_path):
        """manifest.json has expected fields."""
        db_path, chroma_client, _col = populated_library
        output = tmp_path / "backup.tar.gz"

        manifest = create_backup(db_path, chroma_client, output)

        assert "mnemo_version" in manifest
        assert "schema_version" in manifest
        assert "chromadb_version" in manifest
        assert "created_at" in manifest
        assert manifest["book_count"] == 1
        assert manifest["chunk_count"] == 3
        assert manifest["vector_count"] == 5


# ---------------------------------------------------------------------------
# DATA-03: Restore
# ---------------------------------------------------------------------------


class TestRestore:
    """Tests for restore_backup() covering DATA-03."""

    def test_restore_recreates_sqlite(self, populated_library, tmp_path):
        """restore_backup() recreates SQLite DB from archive."""
        db_path, chroma_client, _col = populated_library
        archive = tmp_path / "backup.tar.gz"
        create_backup(db_path, chroma_client, archive)

        restore_client = chromadb.EphemeralClient()
        restore_client.clear_system_cache()
        new_db = tmp_path / "restored.db"

        restore_backup(archive, new_db, restore_client)

        assert new_db.exists()
        conn = sqlite3.connect(new_db)
        count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        conn.close()
        assert count == 1

    def test_restore_recreates_chromadb(self, populated_library, tmp_path):
        """restore_backup() recreates ChromaDB collection with cosine metric."""
        db_path, chroma_client, _col = populated_library
        archive = tmp_path / "backup.tar.gz"
        create_backup(db_path, chroma_client, archive)

        restore_client = chromadb.EphemeralClient()
        restore_client.clear_system_cache()
        new_db = tmp_path / "restored.db"

        restore_backup(archive, new_db, restore_client)

        collection = restore_client.get_collection("mnemo")
        assert collection.count() == 5
        assert collection.metadata.get("hnsw:space") == "cosine"

    def test_restore_validates_manifest(self, tmp_path):
        """restore errors on archive missing manifest.json."""
        # Create a minimal tar.gz without manifest.json
        archive = tmp_path / "bad.tar.gz"
        dummy_db = tmp_path / "mnemo.db"
        dummy_db.write_bytes(b"dummy")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(dummy_db, arcname="mnemo.db")

        restore_client = chromadb.EphemeralClient()
        new_db = tmp_path / "restored.db"

        with pytest.raises(ValueError, match="manifest"):
            restore_backup(archive, new_db, restore_client)

    def test_restore_refuses_existing_data(self, populated_library, tmp_path):
        """restore errors if DB exists and force=False."""
        db_path, chroma_client, _col = populated_library
        archive = tmp_path / "backup.tar.gz"
        create_backup(db_path, chroma_client, archive)

        restore_client = chromadb.EphemeralClient()
        restore_client.clear_system_cache()

        # Create a pre-existing DB file at the target path
        existing_db = tmp_path / "existing.db"
        existing_db.write_bytes(b"existing data")

        with pytest.raises(FileExistsError):
            restore_backup(archive, existing_db, restore_client, force=False)

    def test_restore_force_overwrites(self, populated_library, tmp_path):
        """restore with force=True replaces existing data."""
        db_path, chroma_client, _col = populated_library
        archive = tmp_path / "backup.tar.gz"
        create_backup(db_path, chroma_client, archive)

        restore_client = chromadb.EphemeralClient()
        restore_client.clear_system_cache()

        existing_db = tmp_path / "existing.db"
        existing_db.write_bytes(b"existing data")

        # Should not raise
        restore_backup(archive, existing_db, restore_client, force=True)
        assert existing_db.exists()
        conn = sqlite3.connect(existing_db)
        count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        conn.close()
        assert count == 1

    def test_restore_rejects_future_schema(self, populated_library, tmp_path):
        """restore errors when manifest schema_version > LATEST_VERSION."""
        db_path, chroma_client, _col = populated_library
        archive = tmp_path / "backup.tar.gz"
        create_backup(db_path, chroma_client, archive)

        # Tamper with the manifest to set a future schema version
        import tempfile

        with tempfile.TemporaryDirectory() as staging:
            staging_path = Path(staging)
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(staging_path)  # noqa: S202 — test-only

            manifest_path = staging_path / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["schema_version"] = LATEST_VERSION + 999
            manifest_path.write_text(json.dumps(manifest))

            tampered = tmp_path / "tampered.tar.gz"
            with tarfile.open(tampered, "w:gz") as tar:
                for item in staging_path.iterdir():
                    tar.add(item, arcname=item.name)

        restore_client = chromadb.EphemeralClient()
        restore_client.clear_system_cache()
        new_db = tmp_path / "restored.db"

        with pytest.raises(ValueError, match="schema"):
            restore_backup(tampered, new_db, restore_client)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Round-trip backup then restore."""

    def test_backup_restore_roundtrip(self, populated_library, tmp_path):
        """Backup and restore produces identical vector count and cosine metric."""
        db_path, chroma_client, _col = populated_library
        archive = tmp_path / "roundtrip.tar.gz"
        create_backup(db_path, chroma_client, archive)

        restore_client = chromadb.EphemeralClient()
        restore_client.clear_system_cache()
        new_db = tmp_path / "restored.db"

        restore_backup(archive, new_db, restore_client)

        collection = restore_client.get_collection("mnemo")
        assert collection.count() == 5
        assert collection.metadata.get("hnsw:space") == "cosine"


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class TestSafety:
    """Security and safety tests."""

    def test_safe_extract_rejects_path_traversal(self, tmp_path):
        """_safe_extract raises ValueError on path traversal attempts."""
        from mnemo.backup import _safe_extract

        # Build a tar with a traversal member name
        archive = tmp_path / "evil.tar.gz"
        payload = tmp_path / "payload.txt"
        payload.write_text("evil content")

        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(name="../evil.txt")
            data = b"evil"
            import io

            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        dest = tmp_path / "safe_dest"
        dest.mkdir()

        with tarfile.open(archive, "r:gz") as tar, pytest.raises(ValueError, match="traversal"):
            _safe_extract(tar, dest)


class TestNoneMetadataExport:
    """Chroma returns None for vectors stored without metadata.

    Verified against the installed chromadb: get(include=["metadatas"]) yields
    a None entry, so exporting must not call dict() on it unguarded — that
    would abort the whole backup over one such vector.
    """

    def test_export_survives_a_vector_without_metadata(self, tmp_path):
        import chromadb

        from mnemo.backup import export_chromadb

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        col = client.get_or_create_collection("mnemo", metadata={"hnsw:space": "cosine"})
        col.add(ids=["a"], embeddings=[[0.1, 0.2]], metadatas=[{"book_id": "x"}])
        col.add(ids=["b"], embeddings=[[0.3, 0.4]])

        out = tmp_path / "export.json"
        count = export_chromadb(client, out, collection_name="mnemo")

        assert count == 2
        import json

        data = json.loads(out.read_text())
        assert len(data["metadatas"]) == 2
        assert {"book_id": "x"} in data["metadatas"]
        assert None in data["metadatas"]
