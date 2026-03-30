---
phase: 16-backup-restore
plan: 01
subsystem: backup
tags: [backup, restore, sqlite, chromadb, cli, tdd]
dependency_graph:
  requires:
    - "src/mnemo/storage/database.py (init_db, get_db_path)"
    - "src/mnemo/storage/migrations.py (LATEST_VERSION)"
    - "src/mnemo/vectors/config.py (VectorConfig)"
    - "chromadb.ClientAPI"
  provides:
    - "create_backup(db_path, chroma_client, output_path) -> dict"
    - "restore_backup(archive_path, db_path, chroma_client, force) -> dict"
    - "CLI: mnemo backup [output]"
    - "CLI: mnemo restore <archive> [--force]"
  affects:
    - "src/mnemo/cli.py (two new commands)"
tech_stack:
  added:
    - "tarfile (stdlib) — archive creation and extraction"
    - "sqlite3.Connection.backup() — WAL-consolidated DB snapshot"
  patterns:
    - "TDD Red-Green-Refactor cycle across 3 tasks"
    - "tempfile.TemporaryDirectory() for atomic staging"
    - "Paginated ChromaDB export (batch_size param)"
    - "Flat archive member names (no directory prefix)"
key_files:
  created:
    - src/mnemo/backup.py
    - tests/test_backup.py
  modified:
    - src/mnemo/cli.py
    - tests/test_cli.py
    - pyproject.toml
decisions:
  - "Used sqlite3.Connection.backup() (online backup API) for WAL-consolidated copy"
  - "Flat tar member names (manifest.json, mnemo.db, chroma_export.json) — no subdirectory"
  - "force=True deletes existing db_path before restore (sqlite3 backup requires fresh file)"
  - "filter='data' on extractall() to comply with Python 3.14 tarfile security defaults"
  - "numpy array `or []` anti-pattern avoided — use explicit None check for chromadb embeddings"
metrics:
  duration_seconds: 262
  completed_date: "2026-03-30"
  tasks_completed: 3
  files_created: 2
  files_modified: 3
  tests_added: 15
  tests_total: 525
---

# Phase 16 Plan 01: Backup & Restore Summary

**One-liner:** `.tar.gz` backup/restore covering WAL-consolidated SQLite + paginated ChromaDB export via `create_backup`/`restore_backup` with CLI commands.

## What Was Built

Implemented full backup and restore functionality for Mnemo libraries:

- `src/mnemo/backup.py` — Core logic module with six functions:
  - `_safe_extract()` — path traversal prevention
  - `backup_sqlite()` — WAL-consolidated SQLite copy via online backup API
  - `export_chromadb()` — paginated vector export to JSON
  - `create_backup()` — orchestrates staging, packing into .tar.gz with manifest
  - `_restore_chromadb()` — recreates collection with cosine metric, batched insert
  - `restore_backup()` — validates manifest, schema version gate, restores both stores

- `src/mnemo/cli.py` — Two new CLI commands:
  - `mnemo backup [OUTPUT]` — archive with spinner, auto-timestamped filename
  - `mnemo restore ARCHIVE [--force]` — restore with helpful error on FileExistsError

- `tests/test_backup.py` — 13 tests across TestBackup, TestRestore, TestRoundTrip, TestSafety

- Version bumped 1.7.0 → 1.8.0 (new feature, MINOR bump per CLAUDE.md)

## Requirements Verified

| Req ID | Test(s) | Status |
|--------|---------|--------|
| DATA-01 | test_backup_creates_archive_with_sqlite, test_backup_sqlite_consolidates_wal | PASS |
| DATA-02 | test_backup_creates_archive_with_chroma, test_backup_chroma_pagination | PASS |
| DATA-03 | test_restore_recreates_sqlite, test_restore_recreates_chromadb, test_backup_restore_roundtrip | PASS |
| DATA-03 validation | test_restore_validates_manifest, test_restore_rejects_future_schema | PASS |
| DATA-03 safety | test_restore_refuses_existing_data, test_restore_force_overwrites | PASS |
| SAFETY | test_safe_extract_rejects_path_traversal | PASS |
| CLI | test_backup_help, test_restore_help | PASS |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] numpy array truth-value comparison in export_chromadb**
- **Found during:** Task 2 (TDD GREEN)
- **Issue:** `raw_embeddings = batch.get("embeddings") or []` raises `ValueError: The truth value of an array is ambiguous` because ChromaDB returns numpy arrays
- **Fix:** Replaced `or []` with explicit `if raw_embeddings is None:` check
- **Files modified:** src/mnemo/backup.py
- **Commit:** 20a9fd6

**2. [Rule 1 - Bug] force=True restore failed on pre-existing file**
- **Found during:** Task 2 (TDD GREEN) — test_restore_force_overwrites
- **Issue:** `sqlite3.Connection.backup()` raised "file is not a database" when dest_path already existed with non-SQLite content, even in force mode
- **Fix:** Added `db_path.unlink()` before restore when force=True
- **Files modified:** src/mnemo/backup.py
- **Commit:** 20a9fd6

**3. [Rule 2 - Security] Added filter='data' to tarfile.extractall()**
- **Found during:** Task 3 (REFACTOR)
- **Issue:** Python 3.14 will reject unfiltered tar extraction by default; deprecation warning during test run
- **Fix:** Added `filter="data"` to the extractall() call in `_safe_extract()`
- **Files modified:** src/mnemo/backup.py
- **Commit:** 5e90cbb

## Commits

| Hash | Message |
|------|---------|
| b119efb | test(16-01): add failing tests for backup and restore (TDD RED) |
| 20a9fd6 | feat(16-01): implement backup.py and CLI commands (TDD GREEN) |
| 5e90cbb | refactor(16-01): polish backup module, bump version to 1.8.0 |

## Known Stubs

None. All data paths are fully wired.

## Self-Check: PASSED
