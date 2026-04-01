---
phase: 18-mcp-service-layer-refactor
plan: "01"
subsystem: mcp
tags: [refactor, service-layer, module-split, structural]
dependency_graph:
  requires: []
  provides: [services/book_service.py, mcp/formatters.py, mcp/tools_search.py, mcp/tools_books.py, mcp/tools_metadata.py]
  affects: [mcp/server.py, cli.py]
tech_stack:
  added: []
  patterns: [domain-module-split, service-layer, formatter-extraction]
key_files:
  created:
    - src/mnemo/services/__init__.py
    - src/mnemo/services/book_service.py
    - src/mnemo/mcp/formatters.py
    - src/mnemo/mcp/tools_search.py
    - src/mnemo/mcp/tools_books.py
    - src/mnemo/mcp/tools_metadata.py
  modified:
    - src/mnemo/mcp/server.py
    - src/mnemo/cli.py
decisions:
  - "Services package uses TYPE_CHECKING for Book import to avoid runtime cost"
  - "cli.py serve command updated to remove redundant tools.py import — server.py handles registration"
  - "Ruff import-sort applied to all new files"
metrics:
  duration_minutes: 6
  completed_date: "2026-04-01"
  tasks_completed: 2
  files_created: 6
  files_modified: 2
---

# Phase 18 Plan 01: MCP Service Layer and Domain Split Summary

Split monolithic `mcp/tools.py` (1,233 lines) into domain modules and extracted a service layer with shared validation functions.

## What Was Built

**Service layer** — `src/mnemo/services/book_service.py` with three functions: `validate_epub_path`, `find_duplicate`, `list_all_books`. Shared business logic for CLI and MCP layers. Plan 02 (DI refactor) will wire these into both layers.

**Formatter extraction** — `src/mnemo/mcp/formatters.py` with pure string-formatting functions (`_format_search_results`, `_format_enriched_results`, `_format_mixed_results`, `_truncate_at_boundary`). No imports from server.py or globals.

**Domain module split:**
- `tools_search.py` (317 lines) — search_books, get_book_structure, get_book_chunks
- `tools_books.py` (406 lines) — add_book, remove_book, reindex_all_books
- `tools_metadata.py` (395 lines) — list_available_books, get_book_info, update_book_metadata, enrich_book

**Server update** — `server.py` now imports the three domain modules (triggering `@mcp.tool` registration via side effect). `cli.py serve` updated to remove the now-redundant `import mnemo.mcp.tools`.

## Verification

- All 10 MCP tools register correctly: `python -c "from mnemo.mcp.server import mcp; print(len(mcp._tool_manager._tools))"` → `10`
- 525 tests pass
- `ruff check` clean on all new/modified files
- No file exceeds 406 lines (well under 460 limit)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed double tool registration in cli.py serve command**
- **Found during:** Task 2
- **Issue:** `cli.py serve` imported `mnemo.mcp.tools` (old monolithic file) AND `mnemo.mcp.server` (which now imports the 3 domain modules). This caused 10 "Tool already exists" warnings.
- **Fix:** Removed `import mnemo.mcp.tools` from cli.py serve command — server.py import is sufficient.
- **Files modified:** src/mnemo/cli.py
- **Commit:** 047be01

**2. [Rule 1 - Bug] Fixed wrong type annotation in tools_books.py**
- **Found during:** Post-task review
- **Issue:** `pre_parsed` parameter typed as `"BookRepository | None"` instead of `"Book | None"`
- **Fix:** Corrected type annotation, added `TYPE_CHECKING` import for Book
- **Files modified:** src/mnemo/mcp/tools_books.py
- **Commit:** 8589c7f

**3. [Rule 2 - Quality] Removed unused _truncate_at_boundary import from tools_search.py**
- **Found during:** ruff check
- **Issue:** `_truncate_at_boundary` is used internally within formatters.py, not needed in tools_search.py
- **Fix:** Removed from import in tools_search.py (ruff auto-fix)
- **Commit:** 9ba8b2a

## Known Stubs

None. All functions are fully implemented — this was a pure file reorganization with no behavioral changes.

## Self-Check: PASSED

Files exist:
- src/mnemo/services/__init__.py: FOUND
- src/mnemo/services/book_service.py: FOUND
- src/mnemo/mcp/formatters.py: FOUND
- src/mnemo/mcp/tools_search.py: FOUND
- src/mnemo/mcp/tools_books.py: FOUND
- src/mnemo/mcp/tools_metadata.py: FOUND

Commits:
- a658792: feat(18-01): create service layer and split tools.py into domain modules
- 047be01: feat(18-01): update server.py and cli.py to import domain modules
- 9ba8b2a: fix(18-01): apply ruff import sort fixes to new modules
- 8589c7f: fix(18-01): correct pre_parsed type annotation in tools_books.py
