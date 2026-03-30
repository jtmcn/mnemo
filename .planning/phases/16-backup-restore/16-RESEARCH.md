# Phase 16: Backup & Restore - Research

**Researched:** 2026-03-29
**Domain:** Data backup/restore (SQLite + ChromaDB), archive creation, CLI integration
**Confidence:** HIGH

## Summary

This phase adds `mnemo backup` and `mnemo restore` commands that create and restore a single archive containing both the SQLite database and ChromaDB vector data. The architecture is straightforward: use Python's `sqlite3.Connection.backup()` for a safe SQLite snapshot, use ChromaDB's `collection.get(include=['embeddings','metadatas','documents'])` API for vector export, bundle everything into a `.tar.gz` archive with a JSON manifest containing version metadata.

The key insight is that ChromaDB should be exported via its API (not file-level copy) to ensure portability across ChromaDB versions and avoid issues with internal storage format changes. SQLite should use the `backup()` API rather than file copy to handle WAL mode safely.

**Primary recommendation:** API-level export for both SQLite and ChromaDB, bundled into a tar.gz with a manifest. File-level copy is fragile; API-level export is portable and version-safe.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | `mnemo backup` can export the SQLite database file | Use `sqlite3.Connection.backup()` to create a clean snapshot regardless of WAL state |
| DATA-02 | `mnemo backup` can export ChromaDB vector data | Use `collection.get(include=['embeddings','metadatas','documents'], limit=N, offset=M)` for paginated API export to JSON |
| DATA-03 | Exported data can be restored to a working state with `mnemo restore` | Restore SQLite via `backup()` in reverse, restore ChromaDB via `collection.add()` with the exported data |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Version is defined in `pyproject.toml` (single source of truth). Current: 1.7.0 (note: CLAUDE.md says 1.4.4 but pyproject.toml says 1.7.0 -- use pyproject.toml).
- Update version following semver: this is a new feature, so bump MINOR.
- Tech stack: Python 3.11+, Typer, Rich, ChromaDB >= 1.0.0, SQLite/FTS5

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `tarfile` | 3.11+ | Archive creation/extraction | Built-in, handles tar.gz natively |
| Python stdlib `sqlite3` | 3.11+ | SQLite backup via `Connection.backup()` | Built-in, safe WAL-aware backup |
| Python stdlib `json` | 3.11+ | Manifest + ChromaDB data serialization | Built-in, human-readable |
| Python stdlib `shutil` | 3.11+ | File operations during restore | Built-in |
| chromadb | 1.5.5 | Vector data export via `collection.get()` API | Already a project dependency |
| typer | >= 0.12 | CLI commands | Already a project dependency |
| rich | >= 13.0 | Progress display | Already a project dependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python stdlib `tempfile` | 3.11+ | Staging directory during backup/restore | Always -- never write directly to final location |
| Python stdlib `hashlib` | 3.11+ | Checksum for archive integrity | Optional but recommended for verification |

**Installation:** No new dependencies required. Everything uses stdlib + existing deps.

## Architecture Patterns

### Recommended Project Structure
```
src/mnemo/
  backup.py              # Core backup/restore logic (new file)
  cli.py                 # Add backup + restore commands
  storage/
    database.py          # get_db_path() already exists
    migrations.py         # LATEST_VERSION for manifest
  vectors/
    config.py            # VectorConfig.get_persist_path() already exists
    store.py             # VectorStore already has .get() access
```

### Pattern 1: Archive Structure
**What:** A tar.gz containing a manifest, SQLite dump, and ChromaDB JSON export
**When to use:** Always -- this is the backup format

```
mnemo-backup-YYYYMMDD-HHMMSS.tar.gz
  manifest.json          # Version metadata
  mnemo.db               # SQLite backup (clean, no WAL)
  chroma_export.json     # ChromaDB vectors as JSON
```

**manifest.json example:**
```json
{
  "mnemo_version": "1.8.0",
  "schema_version": 4,
  "chromadb_version": "1.5.5",
  "created_at": "2026-03-29T14:30:00Z",
  "book_count": 12,
  "chunk_count": 4500,
  "vector_count": 4500
}
```

### Pattern 2: SQLite Backup via backup() API
**What:** Use `sqlite3.Connection.backup()` to create a consistent snapshot
**When to use:** Always for SQLite -- handles WAL mode correctly
**Example:**
```python
import sqlite3
from pathlib import Path

def backup_sqlite(source_path: Path, dest_path: Path) -> None:
    """Create a clean SQLite backup, consolidating WAL."""
    source = sqlite3.connect(source_path)
    dest = sqlite3.connect(dest_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
```

**Why not file copy:** The mnemo database uses WAL mode (`PRAGMA journal_mode = WAL`). A simple file copy of `mnemo.db` without also copying `mnemo.db-wal` and `mnemo.db-shm` would produce an inconsistent database. The `backup()` API consolidates WAL into a single clean file.

### Pattern 3: ChromaDB API-Level Export
**What:** Export all vectors via `collection.get()` with pagination
**When to use:** Always -- file-level copy of ChromaDB's internal format is fragile
**Example:**
```python
import json
from pathlib import Path

def export_chromadb(store: VectorStore, dest_path: Path, batch_size: int = 5000) -> int:
    """Export ChromaDB collection to JSON file."""
    total = store.collection.count()
    all_data = {"ids": [], "embeddings": [], "metadatas": [], "documents": []}

    offset = 0
    while offset < total:
        batch = store.collection.get(
            include=["embeddings", "metadatas", "documents"],
            limit=batch_size,
            offset=offset,
        )
        all_data["ids"].extend(batch["ids"])
        all_data["embeddings"].extend(
            batch["embeddings"].tolist()  # numpy -> list
        )
        all_data["metadatas"].extend(batch["metadatas"])
        all_data["documents"].extend(batch["documents"] or [])
        offset += len(batch["ids"])

    dest_path.write_text(json.dumps(all_data))
    return total
```

### Pattern 4: Safe Restore with Validation
**What:** Extract to temp dir, validate manifest, then atomically replace data
**When to use:** Always during restore
**Example:**
```python
def restore(archive_path: Path, data_dir: Path) -> dict:
    """Restore from backup archive."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Extract archive
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(tmp_path, filter="data")  # Python 3.12+ filter

        # Validate manifest
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        _validate_manifest(manifest)

        # Restore SQLite
        backup_sqlite(tmp_path / "mnemo.db", data_dir / "mnemo.db")

        # Restore ChromaDB
        _restore_chromadb(tmp_path / "chroma_export.json", data_dir / "chroma")

        return manifest
```

### Anti-Patterns to Avoid
- **File-level ChromaDB copy:** ChromaDB's internal storage format (HNSW index files, SQLite metadata) is version-specific. Copying the `chroma/` directory may fail on ChromaDB version upgrades. Use the API.
- **Restoring without stopping ChromaDB client:** If a PersistentClient has the chroma directory open, restoring files underneath it causes corruption. Must close/recreate the client.
- **Copying SQLite without WAL consolidation:** `mnemo.db` alone is incomplete when WAL mode is active. Always use `backup()`.
- **In-place restore without backup:** If restore fails midway, both old and new data are corrupted. Always restore to temp first, then atomic swap.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SQLite backup | File copy or raw SQL dump | `sqlite3.Connection.backup()` | Handles WAL, locking, consistency automatically |
| Archive format | Custom binary format | `tarfile` (tar.gz) | Standard, well-tested, streaming compression |
| Temp file management | Manual mkdir/cleanup | `tempfile.TemporaryDirectory()` | Auto-cleanup on error, no orphan files |
| Progress display | Print statements | Rich Progress/SpinnerColumn | Already used throughout CLI, consistent UX |

## Common Pitfalls

### Pitfall 1: WAL Mode SQLite Copy
**What goes wrong:** Copying `mnemo.db` without `mnemo.db-wal` produces a stale or corrupt database
**Why it happens:** WAL mode stores recent writes in a separate WAL file; the main db file may be pages behind
**How to avoid:** Always use `sqlite3.Connection.backup()` which consolidates WAL into the output
**Warning signs:** Restored database is missing recent books or has wrong schema_version

### Pitfall 2: ChromaDB Embedding Numpy Serialization
**What goes wrong:** `collection.get(include=['embeddings'])` returns numpy arrays, which are not JSON-serializable
**Why it happens:** ChromaDB returns embeddings as `numpy.ndarray`
**How to avoid:** Call `.tolist()` on embeddings before JSON serialization
**Warning signs:** `TypeError: Object of type ndarray is not JSON serializable`

### Pitfall 3: ChromaDB Collection Recreation on Restore
**What goes wrong:** Restored vectors don't return search results because collection metadata is wrong
**Why it happens:** ChromaDB collection must be created with `metadata={"hnsw:space": "cosine"}` -- if you just call `get_or_create_collection` without metadata, it defaults to L2
**How to avoid:** Always pass `metadata={"hnsw:space": "cosine"}` when creating the collection during restore. Store distance metric in manifest.
**Warning signs:** Search returns results but scores are wrong (L2 vs cosine)

### Pitfall 4: tarfile Security (Path Traversal)
**What goes wrong:** Malicious archives can write files outside the target directory
**Why it happens:** Tar members can contain `../` paths
**How to avoid:** Use `tar.extractall(filter="data")` on Python 3.12+, or validate member paths on 3.11. Since project requires Python 3.11+, implement a `_safe_extract()` helper that checks paths.
**Warning signs:** Files appearing outside the expected extraction directory

### Pitfall 5: Large Collection Memory Pressure
**What goes wrong:** `collection.get()` with all embeddings loaded at once exhausts memory for very large libraries
**Why it happens:** 1024-dim float32 embeddings * N vectors = 4KB per vector; 10K vectors = 40MB (manageable), 100K = 400MB
**How to avoid:** Paginated export with `limit`/`offset` (batch_size=5000 is ~20MB per batch)
**Warning signs:** MemoryError during export

### Pitfall 6: Existing Data on Restore
**What goes wrong:** User runs restore on a library with existing data and loses both old and new
**Why it happens:** Restore overwrites existing files but may fail partway through
**How to avoid:** Check for existing data and require `--force` flag. Default behavior: error if data exists. Consider creating an automatic backup of existing data before overwriting.
**Warning signs:** User reports data loss after failed restore

## Code Examples

### CLI Command Registration (Typer pattern from existing code)
```python
@app.command()
def backup(
    output: Annotated[
        Path,
        typer.Argument(help="Output archive path"),
    ] = Path(f"mnemo-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Back up the entire library (database + vectors) to an archive."""
    ...

@app.command()
def restore(
    archive: Annotated[
        Path,
        typer.Argument(help="Backup archive to restore"),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing data"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Restore library from a backup archive."""
    ...
```

### Safe tarfile Extraction for Python 3.11
```python
import tarfile
from pathlib import Path

def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract tar safely, preventing path traversal."""
    dest = dest.resolve()
    for member in tar.getmembers():
        member_path = (dest / member.name).resolve()
        if not str(member_path).startswith(str(dest)):
            raise ValueError(f"Path traversal detected: {member.name}")
    tar.extractall(dest)
```

### Reading Schema Version for Manifest
```python
from mnemo.storage.database import get_db_path, get_connection
from mnemo.storage.migrations import LATEST_VERSION

def _get_current_schema_version() -> int:
    """Read schema version from the live database."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row[0] if row else LATEST_VERSION
    finally:
        conn.close()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ChromaDB file-level copy | API-level export via `get()` | ChromaDB 1.0+ (2025) | Portable across versions |
| `sqlite3` `.dump()` text export | `Connection.backup()` binary | Python 3.7+ | Faster, handles WAL, binary-identical |
| `tarfile.extractall()` unsafe | `extractall(filter="data")` | Python 3.12 | Prevents path traversal |

## Open Questions

1. **Default output filename**
   - What we know: Timestamp-based names (`mnemo-backup-20260329-143000.tar.gz`) prevent accidental overwrite
   - What's unclear: Should we use CWD or a specific directory?
   - Recommendation: Default to CWD with timestamp, allow explicit path argument

2. **Restore schema version mismatch**
   - What we know: Backup includes schema_version in manifest, restore target may have different migrations available
   - What's unclear: Should restore refuse if backup schema_version > current mnemo's LATEST_VERSION?
   - Recommendation: Error if backup schema_version > LATEST_VERSION (backup from newer mnemo). Allow older versions and apply migrations after restore.

3. **ChromaDB version compatibility on restore**
   - What we know: API-level export (ids, embeddings, metadatas, documents) is version-agnostic JSON
   - What's unclear: Embedding dimensions could theoretically change between model versions
   - Recommendation: Store embedding dimension in manifest, validate on restore

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `uv run pytest tests/test_backup.py -x` |
| Full suite command | `uv run pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01 | backup exports SQLite database | unit | `uv run pytest tests/test_backup.py::TestBackup::test_backup_creates_archive_with_sqlite -x` | Wave 0 |
| DATA-02 | backup exports ChromaDB vectors | unit | `uv run pytest tests/test_backup.py::TestBackup::test_backup_creates_archive_with_chroma -x` | Wave 0 |
| DATA-03 | restore recreates working library | integration | `uv run pytest tests/test_backup.py::TestRoundTrip::test_backup_restore_roundtrip -x` | Wave 0 |
| DATA-03 | restore validates archive manifest | unit | `uv run pytest tests/test_backup.py::TestRestore::test_restore_validates_manifest -x` | Wave 0 |
| DATA-03 | restore errors on existing data without --force | unit | `uv run pytest tests/test_backup.py::TestRestore::test_restore_refuses_existing_data -x` | Wave 0 |
| CLI | backup command registered | unit | `uv run pytest tests/test_cli.py::TestBackup -x` | Wave 0 |
| CLI | restore command registered | unit | `uv run pytest tests/test_cli.py::TestRestore -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_backup.py -x`
- **Per wave merge:** `uv run pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_backup.py` -- covers DATA-01, DATA-02, DATA-03 (new file)
- [ ] CLI test classes in `tests/test_cli.py` -- TestBackup, TestRestore (additions to existing file)

## Sources

### Primary (HIGH confidence)
- **Codebase inspection** -- `cli.py`, `storage/database.py`, `storage/migrations.py`, `vectors/config.py`, `vectors/store.py`
- **Python 3.11 stdlib docs** -- `sqlite3.Connection.backup()`, `tarfile`, `json`, `tempfile`
- **ChromaDB 1.5.5 API** -- Verified `collection.get(include=['embeddings','metadatas','documents'], limit=N, offset=M)` returns numpy arrays with pagination support
- **Live system inspection** -- `~/.mnemo/` directory structure, ChromaDB internal file layout (chroma.sqlite3 + HNSW index files)

### Secondary (MEDIUM confidence)
- **ChromaDB storage format** -- UUID-named directories contain HNSW binary files (data_level0.bin, header.bin, etc.) which are version-specific internal format

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all stdlib + existing deps, verified on this system
- Architecture: HIGH -- based on direct API testing and codebase patterns
- Pitfalls: HIGH -- WAL mode and numpy serialization verified empirically

**Research date:** 2026-03-29
**Valid until:** 2026-04-28 (stable domain, no fast-moving dependencies)
