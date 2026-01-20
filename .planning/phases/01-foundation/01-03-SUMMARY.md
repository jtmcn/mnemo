---
phase: 01-foundation
plan: 03
subsystem: storage
tags: [sqlite, fts5, repository, crud]

# Dependency graph
requires: [01-01]
provides:
  - SQLite database schema with FTS5 full-text search
  - BookRepository for book CRUD operations
  - ChunkRepository for bulk insert and search
  - Cascade delete (book deletion removes all chunks)
affects: [01-04, 01-05, 02-vector-pipeline, 03-search-mcp]

# Tech tracking
tech-stack:
  added: []
  patterns: [repository-pattern, fts5-triggers, wal-mode]

key-files:
  created:
    - src/mnemo/storage/__init__.py
    - src/mnemo/storage/database.py
    - src/mnemo/storage/repository.py
    - tests/test_storage.py
  modified: []

key-decisions:
  - "FTS5 with triggers for automatic index sync on insert/update/delete"
  - "WAL journal mode for better concurrency"
  - "Quote-wrapping all FTS queries for safe special character handling"
  - "SequenceMatcher for similar title detection (edition detection)"

patterns-established:
  - "Repository pattern: BookRepository and ChunkRepository encapsulate DB operations"
  - "JSON serialization for list fields (authors, section_path, sections)"
  - "Row factory set to sqlite3.Row for named column access"

# Metrics
duration: 4min
completed: 2026-01-20
---

# Phase 1 Plan 03: SQLite Storage Summary

**SQLite persistence with FTS5 full-text search, cascade deletes, and repository pattern for books and chunks**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-20T06:24:25Z
- **Completed:** 2026-01-20T06:28:22Z
- **Tasks:** 2
- **Tests:** 31 passing
- **Files created:** 4

## Accomplishments

- SQLite database schema with books and chunks tables
- FTS5 virtual table with automatic sync triggers
- BookRepository with CRUD, duplicate detection, and similar title search
- ChunkRepository with bulk insert and filtered FTS search
- Foreign key cascade delete (deleting book removes all chunks)
- Comprehensive test coverage for all operations

## Task Commits

Each task was committed atomically:

1. **Task 1: Create database schema with FTS5** - `712c989` (feat)
2. **Task 2: Implement repository classes with FTS search** - `08a093b` (feat)

## Files Created

- `src/mnemo/storage/__init__.py` - Package exports
- `src/mnemo/storage/database.py` - Schema definition and connection management
- `src/mnemo/storage/repository.py` - BookRepository and ChunkRepository classes
- `tests/test_storage.py` - 31 tests covering all functionality

## Schema Details

**Books table:**
- 6-char hex ID (primary key)
- title, authors (JSON), isbn, file_hash (unique)
- default_language, structure_source, added_at

**Chunks table:**
- UUID ID (primary key)
- book_id with FK cascade to books
- content, content_type, token_count
- section_path (JSON), sections (JSON)
- language, sequence, prev/next chunk links

**FTS5 index:**
- chunks_fts virtual table on content
- Automatic sync via triggers (insert, update, delete)

## Decisions Made

1. **FTS5 triggers over manual sync** - Ensures index consistency without explicit management
2. **WAL mode** - Better concurrent read/write performance for future CLI usage
3. **Quote-wrapped FTS queries** - Simple approach that handles all special characters (C++, foo(bar), etc.)
4. **SequenceMatcher for title similarity** - Built-in Python, good enough for edition detection

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed FTS5 special character handling**
- **Found during:** Task 2 (test_search_fts_special_characters)
- **Issue:** Queries like "foo(bar)" caused FTS5 syntax errors due to unescaped parentheses
- **Fix:** Simplified _sanitize_fts_query to always quote-wrap search terms
- **Files modified:** src/mnemo/storage/repository.py
- **Committed in:** 08a093b (Task 2 commit)

**2. [Rule 1 - Bug] Fixed test book IDs**
- **Found during:** Task 2 (test_find_similar_title, test_duplicate_file_hash_rejected)
- **Issue:** Test book IDs used non-hex characters (ghi789, dup123) violating Book.id pattern
- **Fix:** Changed to valid hex IDs (cde789, ddd123)
- **Files modified:** tests/test_storage.py
- **Committed in:** 08a093b (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (bugs)
**Impact on plan:** None - both were test/implementation fixes within normal development

## Issues Encountered

None - all functionality implemented as specified.

## User Setup Required

None - SQLite is bundled with Python, no external dependencies.

## Next Phase Readiness

- Storage layer ready for chunking pipeline (01-04)
- Repository interfaces ready for ingestion workflow (01-05)
- FTS search ready for hybrid search integration (Phase 3)

---
*Phase: 01-foundation*
*Completed: 2026-01-20*
