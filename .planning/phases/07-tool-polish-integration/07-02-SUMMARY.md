---
phase: 07-tool-polish-integration
plan: 02
subsystem: testing
tags: [mcp, tool-annotations, lifecycle-test, fts5, integration-test]

dependency-graph:
  requires:
    - phase: 07-01
      provides: ToolAnnotations on all 6 tools, normalized error strings, LLM docstrings
  provides:
    - Annotation regression tests (4 tests covering all 6 tools)
    - Full lifecycle integration test (add -> search -> update -> verify -> remove -> verify removal)
  affects: []

tech-stack:
  added: []
  patterns: [SearchService(db_path=temp, chroma_path=temp) for isolated keyword search tests, mock_remove with real BookRepository.delete for lifecycle verification]

key-files:
  created: []
  modified:
    - tests/test_mcp.py

key-decisions:
  - "Adapt annotation assertions to actual values (None for omitted hints, not False)"
  - "Use mock_remove with BookRepository.delete to enable verify-removal step"
  - "SearchService with temp db_path + chroma_path for real FTS5 keyword search (no embeddings)"

patterns-established:
  - "Lifecycle test pattern: mock ingest to insert real data, SearchService with temp paths for keyword search, mock remove with real delete"

duration: ~4min
completed: 2026-02-17
---

# Phase 7 Plan 2: Annotation Verification and Lifecycle Tests Summary

**TestToolAnnotations (4 tests) and TestLifecycle (1 test) verifying annotations regression guard and full add-search-update-verify-remove cycle**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-17T16:56:04Z
- **Completed:** 2026-02-17T16:59:46Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- 4 annotation verification tests confirming correct ToolAnnotations on all 6 MCP tools (regression guard for 07-01)
- Full lifecycle integration test exercising add_book -> search_books (keyword FTS5) -> update_metadata -> get_book_info -> remove_book -> verify removal
- Test count increased from 48 to 53 (all passing)
- No external API or embedding service required by any new test

## Task Commits

Each task was committed atomically:

1. **Task 1: Add annotation verification tests** - `9f5c830` (test)
2. **Task 2: Add full lifecycle integration test** - `435cdcf` (test)

## Files Created/Modified
- `tests/test_mcp.py` - Added TestToolAnnotations (4 tests) and TestLifecycle (1 test) classes

## Decisions Made

1. **Annotation assertions match actual values, not plan literals** -- Plan specified `readOnlyHint is False` for remove/update/add, but actual value is `None` (omitted per 07-01 decision TOOL-ANN-01). Tests assert only the hints that are explicitly set, avoiding false specificity on defaults.

2. **mock_remove uses BookRepository.delete** -- Unlike other tests that mock `ingest.remove_book` as a no-op, the lifecycle test needs actual deletion to verify step 6 (book not found after removal). The mock side_effect calls `BookRepository(conn).delete(book_id)` directly.

3. **SearchService with temp paths for keyword search** -- `SearchService(db_path=temp, chroma_path=temp)` allows real FTS5 keyword search against the temp database without needing embedding credentials. ChromaDB is initialized but unused in keyword mode.

4. **Book ID must be lowercase hex** -- Plan used `lif001` but Book model validates `^[0-9a-f]{6}$`. Changed to `aaa001`. File hash must be exactly 64 chars.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed invalid book ID and file_hash in lifecycle test data**
- **Found during:** Task 2 (lifecycle test implementation)
- **Issue:** Plan used `lif001` (contains non-hex chars "l", "i") and `"lifecycle" + "a" * 56` (65 chars, exceeds 64-char limit). Book model validates `^[0-9a-f]{6}$` for id and max 64 chars for file_hash.
- **Fix:** Changed id to `aaa001` (valid hex) and file_hash to `"a" * 64` (exactly 64 chars)
- **Files modified:** tests/test_mcp.py
- **Verification:** Pydantic validation passes, all tests green
- **Committed in:** 435cdcf (Task 2 commit)

**2. [Rule 2 - Missing Critical] mock_remove must actually delete for verify-removal step**
- **Found during:** Task 2 (lifecycle test implementation)
- **Issue:** Plan's `mock_remove.return_value = True` doesn't delete data, so step 6 (`get_book_info` expecting "not found") would fail since book still exists in temp DB
- **Fix:** Changed mock_remove to use `side_effect` calling `BookRepository(conn).delete(book_id)` for real deletion
- **Files modified:** tests/test_mcp.py
- **Verification:** Step 6 correctly returns "not found" after removal
- **Committed in:** 435cdcf (Task 2 commit)

**3. [Rule 1 - Bug] Adapted annotation assertions to actual None values**
- **Found during:** Task 1 (annotation verification tests)
- **Issue:** Plan asserted `readOnlyHint is False` and `destructiveHint is False` for tools where those hints were omitted (actual value is `None`). Asserting `False` would fail.
- **Fix:** Only assert hints that are explicitly set per 07-01 implementation. Omitted hints are not tested for specific values.
- **Files modified:** tests/test_mcp.py
- **Verification:** All 4 annotation tests pass
- **Committed in:** 9f5c830 (Task 1 commit)

---

**Total deviations:** 3 auto-fixed (2 bugs, 1 missing critical)
**Impact on plan:** All auto-fixes necessary for test correctness. No scope creep.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
Phase 7 (Tool Polish & Integration) is now complete. Both plans executed:
- 07-01: ToolAnnotations, error normalization, LLM docstrings
- 07-02: Annotation verification tests, lifecycle integration test

v1.1 milestone is complete. All success criteria met:
- Annotations on all 6 tools (verified by 4 regression tests)
- Error conventions normalized ("Error:" prefix)
- LLM-tuned docstrings
- Full lifecycle test passes (add -> search -> update -> verify -> remove -> verify removal)

---
*Phase: 07-tool-polish-integration*
*Completed: 2026-02-17*
