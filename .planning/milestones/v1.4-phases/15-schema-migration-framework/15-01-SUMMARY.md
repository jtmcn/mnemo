---
phase: 15-schema-migration-framework
plan: "01"
subsystem: storage
tags: [migrations, sqlite, schema-versioning, tdd]
dependency_graph:
  requires: []
  provides: [schema_version_table, numbered_migration_functions]
  affects: [src/mnemo/storage/database.py, tests/test_storage.py]
tech_stack:
  added: []
  patterns: [versioned-migration-registry, tdd-red-green]
key_files:
  created:
    - src/mnemo/storage/migrations.py
  modified:
    - src/mnemo/storage/database.py
    - tests/test_storage.py
decisions:
  - "Use schema_version table with single row (UPDATE vs INSERT) rather than append-only log — simpler for personal-scale single-writer DB"
  - "Fresh DB detection: count == 0 AND description column present — stamps at LATEST_VERSION without running incremental migrations"
  - "Legacy DB version inference by column presence (description->4, year->3, publisher->2, epub_path->1, else->0)"
  - "Each migration commits individually so partial-failure recovery is safe"
metrics:
  duration: "5 minutes"
  completed: "2026-03-29"
  tasks_completed: 2
  files_changed: 3
requirements_satisfied: [DATA-04, DATA-05]
---

# Phase 15 Plan 01: Schema Migration Framework Summary

Replaced the fragile try/except ALTER TABLE migration pattern in database.py with a versioned migration system backed by a schema_version table. Created migrations.py with 4 numbered migration functions and complete version tracking logic, then rewired init_db to use the new system.

## What Was Built

**src/mnemo/storage/migrations.py** (new file, 129 lines):
- 4 numbered migration functions: `_migration_001_add_epub_path` through `_migration_004_add_description`
- `MIGRATIONS` list of `(version, fn)` tuples — ordered registry
- `LATEST_VERSION = 4` derived from registry tail
- `ensure_schema_version(conn)` — creates schema_version table if absent
- `apply_pending_migrations(conn)` — main entry point handling all 3 DB states
- `_is_fresh_database(conn)` — detects brand-new DB (no rows, has description column)
- `_infer_legacy_version(conn)` — infers version from column presence for pre-versioning DBs
- `_get_schema_version` / `_set_schema_version` — low-level version row accessors

**src/mnemo/storage/database.py** (modified):
- Added import: `from mnemo.storage.migrations import apply_pending_migrations, ensure_schema_version`
- Deleted entire `_migrate_schema` function (24 lines of try/except ALTER TABLE)
- `init_db` now calls `ensure_schema_version(conn)` then `apply_pending_migrations(conn)` after executescript

**tests/test_storage.py** (modified):
- Added `TestSchemaVersion` class with 5 test methods covering all DB states
- `test_fresh_db_has_schema_version` — schema_version table exists after init_db
- `test_fresh_db_at_latest_version` — version row = 4 after fresh init
- `test_versioned_db_idempotent` — second init_db call leaves version=4, count=1
- `test_legacy_db_gets_stamped` — full-column legacy DB stamped at 4 without errors
- `test_partial_legacy_db_migrated` — partial legacy DB gets all 4 columns applied

## Test Results

- 510 total tests pass (505 pre-existing + 5 new)
- TestSchemaVersion: 5/5 pass
- TestEpubPath::test_existing_db_without_epub_path_gets_migrated: passes (regression)
- TestDatabaseInitialization: 4/4 pass (regression)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

Files created/modified:
- FOUND: src/mnemo/storage/migrations.py
- FOUND: src/mnemo/storage/database.py
- FOUND: tests/test_storage.py

Commits:
- FOUND: fc05b39 (test RED phase)
- FOUND: 21a6210 (feat GREEN phase)
