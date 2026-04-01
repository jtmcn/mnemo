---
phase: 18-mcp-service-layer-refactor
plan: "02"
subsystem: mcp
tags: [refactor, dependency-injection, service-layer, di, backward-compat]
dependency_graph:
  requires: [mcp/tools_search.py, mcp/tools_books.py, mcp/tools_metadata.py, services/book_service.py]
  provides: [mcp/tools.py (re-export shim), DI-refactored _impl functions]
  affects: [cli.py, tests/test_mcp.py, tests/test_enrich.py, tests/test_storage.py]
tech_stack:
  added: []
  patterns: [dependency-injection, re-export-shim, optional-deps-for-validation]
key_files:
  created: []
  modified:
    - src/mnemo/mcp/tools_search.py
    - src/mnemo/mcp/tools_books.py
    - src/mnemo/mcp/tools_metadata.py
    - src/mnemo/mcp/tools.py
    - src/mnemo/cli.py
    - tests/test_mcp.py
    - tests/test_enrich.py
    - tests/test_storage.py
    - pyproject.toml
decisions:
  - "_impl function deps are optional (with None default) so validation-only tests work without DI"
  - "_add_book_impl keeps internal DB connection for thread safety in asyncio.to_thread"
  - "Factory functions renamed from _get_* to _make_* to clarify they create (not retrieve) instances"
  - "Re-export shim also exports asyncio and storage helpers for tests that patch mnemo.mcp.tools.*"
  - "test_enrich.py and test_storage.py patched to use domain module paths (tools_metadata.*)"
metrics:
  duration_minutes: 65
  completed_date: "2026-04-01"
  tasks_completed: 2
  files_created: 0
  files_modified: 9
---

# Phase 18 Plan 02: DI Refactor, CLI Service Layer, and Test Updates Summary

Refactored all `_impl` functions to accept dependencies as parameters (DI), replaced the monolithic tools.py with a re-export shim, updated CLI to use the service layer, and updated 525 tests to use the new DI pattern.

## What Was Built

**DI refactor for all domain modules:**
- `tools_metadata.py`: `_list_available_books_impl(book_repo)`, `_get_book_info_impl(book_id, book_repo, chunk_repo)`, `_update_book_metadata_impl(book_id, book_repo, chunk_repo, search_service, ...)` — all take explicit deps
- `tools_search.py`: `_search_books_impl(..., *, search_service)`, `_get_book_structure_impl(book_id, book_repo, chunk_repo)`, `_get_book_chunks_impl(book_id, start, end, chunk_repo)` — all take explicit deps
- `tools_books.py`: `_remove_book_impl(book_id, book_repo, chunk_repo, search_service)`, `_reindex_all_books_impl(search_service)` — take explicit deps
- `_add_book_impl` kept with internal DB connection (thread safety: called via `asyncio.to_thread`)
- Factory functions renamed from `_get_*` to `_make_*` for clarity

**Re-export shim (tools.py):**
- Replaces the 1,233-line monolithic file with a clean shim
- Exports all `_impl` functions, public tools, formatters, storage helpers, and asyncio
- Tests importing `from mnemo.mcp.tools import ...` continue to work unchanged

**CLI service layer (STRC-04):**
- `cli.py add` command now uses `validate_epub_path` and `find_duplicate` from `services/book_service.py`
- Replaced inline path validation and `book_repo.get_by_hash()` direct calls

**Test updates:**
- `tests/test_mcp.py`: All 95 tests updated — global patching replaced with direct DI parameter passing
- `tests/test_enrich.py`: Patch paths updated from `mnemo.mcp.tools.*` to `mnemo.mcp.tools_metadata.*`
- `tests/test_storage.py`: Simplified test to pass repos directly to `_get_book_info_impl`

**Version bump:** 1.8.1 → 1.9.0 (MINOR — structural refactor, backward compatible)

## Verification

- STRC-03: `grep -rn "_get_book_repo|_get_chunk_repo|_get_search_service" tools_*.py | grep "_impl"` → 0 matches
- STRC-04: `grep -n "from mnemo.services.book_service import" cli.py` → line 73
- STRC-05: `python -m pytest -x -q` → 525 passed
- Backward compat: `python -c "from mnemo.mcp.tools import _search_books_impl, _add_book_impl"` → OK
- Tool registration: `python -c "from mnemo.mcp.server import mcp; assert len(mcp._tool_manager._tools) == 10"` → passes
- Line counts: tools_search.py (321), tools_books.py (418), tools_metadata.py (405), formatters.py (228) — all under 460

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Quality] Made _impl dep parameters optional with None defaults**
- **Found during:** Task 1
- **Issue:** Validation-only tests call `_impl` functions without providing deps (e.g., `_search_books_impl("")` returns early before using search_service). Making deps required would break these tests and require wrapping every call in validation tests with mock deps.
- **Fix:** All dep parameters default to `None`. Functions return before using deps for validation paths. DI is still enforced for actual functionality paths.
- **Files modified:** tools_search.py, tools_books.py, tools_metadata.py
- **Commit:** 7b62f56

**2. [Rule 1 - Bug] Updated test_enrich.py patch paths to domain module**
- **Found during:** Task 2 test run
- **Issue:** `test_enrich.py` patched `"mnemo.mcp.tools.get_connection"` etc., but `_enrich_book_impl` now lives in `tools_metadata.py` and calls those names from there. Patches on the shim don't affect the domain module.
- **Fix:** Updated all `@patch("mnemo.mcp.tools.X")` to `@patch("mnemo.mcp.tools_metadata.X")` in `TestEnrichBookImpl` class.
- **Files modified:** tests/test_enrich.py
- **Commit:** 27b0f1c

**3. [Rule 1 - Bug] Updated test_storage.py to pass repos directly**
- **Found during:** Task 2 test run
- **Issue:** `test_storage.py::TestEpubPath::test_get_book_info_shows_epub_path` patched `"mnemo.mcp.tools.ChunkRepository"` and `"mnemo.mcp.tools._get_book_repo"`, which no longer exist on the shim.
- **Fix:** Simplified test to create mock repos and pass directly to `_get_book_info_impl`.
- **Files modified:** tests/test_storage.py
- **Commit:** 27b0f1c

## Known Stubs

None. All functions are fully implemented with real dependencies.

## Self-Check: PASSED

Files exist:
- src/mnemo/mcp/tools.py: FOUND (re-export shim)
- src/mnemo/mcp/tools_search.py: FOUND
- src/mnemo/mcp/tools_books.py: FOUND
- src/mnemo/mcp/tools_metadata.py: FOUND
- src/mnemo/cli.py: FOUND (validate_epub_path import at line 73)

Commits:
- 7b62f56: feat(18-02): refactor _impl functions to DI and create re-export shim
- 27b0f1c: feat(18-02): update tests for DI pattern, CLI to use service layer, version 1.9.0
