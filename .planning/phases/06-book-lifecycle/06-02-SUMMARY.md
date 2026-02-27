---
phase: 06-book-lifecycle
plan: 02
subsystem: mcp
tags: [fastmcp, mcp-tools, add-book, epub, ingest, embeddings, asyncio, timeout]

# Dependency graph
requires:
  - phase: 06-book-lifecycle
    provides: "remove_book pattern: _impl + @mcp.tool + cache invalidation + pre-operation checks"
  - phase: 05-metadata-updates
    provides: "_impl + @mcp.tool pattern, _get_book_repo(), cache invalidation"
  - phase: 02-vector-pipeline
    provides: "ingest_book() pipeline, embed_book(), extract_metadata()"
provides:
  - "add_book MCP tool for ingesting EPUBs via Claude"
  - "_add_book_impl testable implementation with validation, duplicate detection, failure cleanup"
affects: [07-tool-polish]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Async timeout wrapper: asyncio.wait_for(asyncio.to_thread(sync_fn), timeout=300) for long-running sync operations"
    - "Pre-parse duplicate detection: extract_metadata() for hash check before full ingest"
    - "Soft vs hard duplicate: hash match = blocking error, title match = appended warning"
    - "Failure cleanup: look up partial record by hash and pipeline_remove() on ingest failure"

key-files:
  created: []
  modified:
    - "src/mnemo/mcp/tools.py"
    - "tests/test_mcp.py"

key-decisions:
  - "Used _get_book_repo() for duplicate checking instead of creating separate connection (testability with tools._db_connection swap)"
  - "Patching at source module level (mnemo.epub.metadata.extract_metadata, mnemo.ingest.ingest_book) since imports are local inside function body"
  - "Cleanup test uses ingest_book side_effect that inserts partial record then raises, simulating mid-pipeline failure"

patterns-established:
  - "Add tool pattern: validate path -> validate extension -> pre-parse metadata -> check duplicates -> delegate to pipeline -> invalidate cache -> return result"
  - "Async MCP wrapper pattern: ctx.info() progress + asyncio.wait_for(to_thread(sync_impl), timeout)"

# Metrics
duration: 4min
completed: 2026-02-14
---

# Phase 6 Plan 2: Add Book MCP Tool Summary

**add_book MCP tool with EPUB validation, hash-based duplicate detection, 5-minute async timeout, failure cleanup, and 8 new tests**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-15T02:24:27Z
- **Completed:** 2026-02-15T02:28:35Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `add_book` MCP tool registered and callable by Claude with async timeout wrapper (5 min)
- `_add_book_impl` validates path existence and .epub extension, detects hard duplicates by file hash, warns on soft duplicates by title similarity, delegates to `ingest_book(embed=True)`, cleans up partial data on failure, invalidates search cache on success
- 8 new tests: 3 validation (file not found, non-EPUB, case-insensitive) + 5 integration (success, duplicate detected, force reindex, cache clear, cleanup on failure)
- All 267 existing tests continue to pass (2 skipped)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _add_book_impl and add_book MCP tool** - `1ee3e70` (feat)
2. **Task 2: Add add_book tests** - `05ccffd` (test)

## Files Created/Modified
- `src/mnemo/mcp/tools.py` - Added `_add_book_impl` (sync implementation with validation, duplicate detection, failure cleanup) and `@mcp.tool async def add_book` (async wrapper with 5-min timeout, progress logging)
- `tests/test_mcp.py` - Added `TestAddBookValidation` (3 tests) and `TestAddBookIntegration` (5 tests), updated tool count assertion to 6

## Decisions Made
- Used `_get_book_repo()` for duplicate checking instead of raw `init_db()`/`get_connection()` calls, maintaining consistency with the established testability pattern (swap `tools._db_connection` in tests)
- Patched ingest functions at source module level (`mnemo.epub.metadata.extract_metadata`, `mnemo.ingest.ingest_book`) since imports are local inside `_add_book_impl`'s function body
- Cleanup test uses `ingest_book` side_effect that inserts a partial book record then raises, accurately simulating a mid-pipeline failure (book stored, embedding fails)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used _get_book_repo() instead of raw init_db()/get_connection()**
- **Found during:** Task 1 (implementation) / Task 2 (testing)
- **Issue:** Plan specified `init_db()` + `get_connection()` + `BookRepository(conn)` for duplicate checking, but this bypasses the `_get_book_repo()` / `tools._db_connection` pattern used by all other tools, making the function untestable with the established temp DB swap pattern
- **Fix:** Used `_get_book_repo()` for both the duplicate check and the cleanup path, consistent with all other tool implementations
- **Files modified:** `src/mnemo/mcp/tools.py`
- **Verification:** All 8 new tests pass with the `tools._db_connection` swap pattern
- **Committed in:** `1ee3e70` (Task 1) and `05ccffd` (Task 2)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary for testability. No scope creep. Behavior is identical; only the connection management differs.

## Issues Encountered
- Book model validates IDs against `^[0-9a-f]{6}$` pattern; initial test IDs like "exist1", "new123", "part01" failed validation. Fixed by using valid hex IDs ("eee111", "aaa123", "bbb001").

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Both `add_book` and `remove_book` MCP tools complete
- Phase 6 (Book Lifecycle Tools) fully done
- Ready for Phase 7 (Tool Polish) when planned

---
*Phase: 06-book-lifecycle*
*Completed: 2026-02-14*
