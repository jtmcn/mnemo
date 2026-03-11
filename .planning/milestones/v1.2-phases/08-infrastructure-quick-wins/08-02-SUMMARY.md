---
phase: 08-infrastructure-quick-wins
plan: 02
subsystem: database, api
tags: [sqlite, pydantic, mcp, chunking, migration]

# Dependency graph
requires:
  - phase: 01-04 (v1.0)
    provides: Book model, storage layer, chunking pipeline, MCP tools
provides:
  - epub_path column in books table with ALTER TABLE migration
  - ChunkerConfig.validate_params() for chunk size validation
  - chunk_min_tokens/chunk_max_tokens params on add_book MCP tool
affects: [09-section-filtering, future re-indexing features]

# Tech tracking
tech-stack:
  added: []
  patterns: [schema migration via ALTER TABLE with idempotent try/except]

key-files:
  created: []
  modified:
    - src/mnemo/models.py
    - src/mnemo/storage/database.py
    - src/mnemo/storage/repository.py
    - src/mnemo/ingest.py
    - src/mnemo/mcp/tools.py
    - src/mnemo/chunking/chunker.py
    - tests/test_storage.py
    - tests/test_mcp.py
    - tests/test_chunker.py

key-decisions:
  - "Schema migration via ALTER TABLE wrapped in try/except for idempotent duplicate-column handling"
  - "epub_path stored as resolved absolute path during ingest (not relative)"
  - "Chunk size validation returns error string rather than raising exception, matching MCP tool error pattern"

patterns-established:
  - "Schema migration pattern: _migrate_schema() called from init_db after executescript"

requirements-completed: [INFRA-04, CHUNK-01, CHUNK-02, CHUNK-03]

# Metrics
duration: 6min
completed: 2026-03-10
---

# Phase 8 Plan 02: EPUB Path Storage and Configurable Chunk Sizes Summary

**epub_path column with ALTER TABLE migration, chunk_min/max_tokens params on add_book MCP tool with bounds validation**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-10T16:48:01Z
- **Completed:** 2026-03-10T16:54:29Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- EPUB file path stored as absolute path during ingest, visible in get_book_info
- Existing databases auto-migrate via ALTER TABLE to add epub_path column
- add_book MCP tool accepts chunk_min_tokens and chunk_max_tokens with bounds validation (min>=100, max<=2000, min<max)
- Default chunk sizes (400/800) preserved when parameters omitted (backward compatible)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add epub_path to Book model, database schema, and repository**
   - `4cc7eaa` (test: add failing tests for epub_path)
   - `2c053b5` (feat: add epub_path to Book model, schema, and repository)

2. **Task 2: Add configurable chunk sizes to add_book MCP tool with validation**
   - `b2d90be` (test: add failing tests for chunk size validation and MCP params)
   - `a138903` (feat: add configurable chunk sizes to add_book with validation)

## Files Created/Modified
- `src/mnemo/models.py` - Added epub_path field to Book model
- `src/mnemo/storage/database.py` - Added epub_path column to schema, _migrate_schema() for existing DBs
- `src/mnemo/storage/repository.py` - Updated BookRepository add/get for epub_path
- `src/mnemo/ingest.py` - Store resolved absolute epub_path during ingest
- `src/mnemo/mcp/tools.py` - Added chunk_min/max_tokens params, epub_path display in get_book_info
- `src/mnemo/chunking/chunker.py` - Added ChunkerConfig.validate_params()
- `tests/test_storage.py` - 7 new epub_path tests
- `tests/test_mcp.py` - 3 new chunk param tests, fixed lifecycle mock signature
- `tests/test_chunker.py` - 7 new validation tests

## Decisions Made
- Schema migration via ALTER TABLE with try/except for idempotent duplicate-column handling
- epub_path stored as resolved absolute path (via Path.resolve()) during ingest
- Chunk size validation returns error string matching existing MCP tool error pattern

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mock_ingest signature in lifecycle test**
- **Found during:** Task 2 (chunk size params implementation)
- **Issue:** TestLifecycle.test_full_lifecycle mock_ingest function did not accept chunker_config kwarg, causing test failure when pipeline_ingest now passes chunker_config=None
- **Fix:** Added chunker_config=None parameter to mock_ingest function
- **Files modified:** tests/test_mcp.py
- **Verification:** TestLifecycle.test_full_lifecycle passes
- **Committed in:** a138903 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Mock signature fix necessary for test compatibility. No scope creep.

## Issues Encountered
- 4 pre-existing test failures in TestAddBookAsync (missing pytest-asyncio plugin) -- not caused by this plan's changes

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- epub_path infrastructure ready for future re-indexing feature
- Configurable chunk sizes ready for per-book tuning
- All existing tests pass (except pre-existing async test issues)

## Self-Check: PASSED

All 9 files verified present. All 4 task commits verified in git log.

---
*Phase: 08-infrastructure-quick-wins*
*Completed: 2026-03-10*
