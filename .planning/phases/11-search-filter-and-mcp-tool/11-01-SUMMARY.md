---
phase: 11-search-filter-and-mcp-tool
plan: "01"
subsystem: search, mcp, storage
tags: [search-filter, mcp-tool, section-hierarchy, tdd]
dependency_graph:
  requires: []
  provides: [SRCH-01, TOOL-01]
  affects: [src/mnemo/search/service.py, src/mnemo/storage/repository.py, src/mnemo/mcp/tools.py]
tech_stack:
  added: []
  patterns: [join-based substring matching, GROUP BY MIN(sequence) for ordered unique rows]
key_files:
  created: []
  modified:
    - src/mnemo/search/service.py
    - src/mnemo/storage/repository.py
    - src/mnemo/mcp/tools.py
    - tests/test_search.py
    - tests/test_mcp.py
    - tests/test_storage.py
    - pyproject.toml
decisions:
  - "Join-based section filter (' > '.join) is a strict superset of any() — backward compatible and adds cross-level match capability"
  - "get_book_structure reads exclusively from SQLite via ChunkRepository — no EPUB re-parsing"
  - "Pre-existing test failures (test_server_imports_without_side_effects, TestAddBookAsync) are out of scope — not caused by this plan"
requirements-completed: [SRCH-01, TOOL-01]
metrics:
  duration_seconds: 190
  completed_date: "2026-03-14"
  tasks_completed: 2
  files_modified: 7
---

# Phase 11 Plan 01: Search Filter and MCP Tool Summary

**One-liner:** Join-based hierarchy section filter and `get_book_structure` MCP tool reading indented section hierarchy from SQLite.

## What Was Built

**SRCH-01:** Changed section post-filter in `SearchService.search()` from `any(term in s for s in path)` to `term in " > ".join(path).lower()`. This one-line change enables cross-level substring matches (e.g., filtering by "Chapter 5 > Section" now matches chunks in subsections), while being fully backward compatible with existing single-level matches.

**TOOL-01:** Added `get_book_structure` MCP tool that returns an indented markdown outline of a book's section hierarchy. Backed by new `ChunkRepository.get_section_structure()` method that uses `GROUP BY section_path + MIN(sequence) ORDER BY first_seq` to get unique section paths in reading order. The tool validates book_id format, handles missing books and empty structure gracefully, and carries `readOnlyHint=True` annotation.

**Version:** Bumped from 1.2.2 to 1.3.0 (MINOR: new feature).

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 (RED) | Failing test for hierarchy path section filter | 7f30515 | tests/test_search.py |
| 1 (GREEN) | SRCH-01 join-based section filter | 2466928 | src/mnemo/search/service.py |
| 2 (RED) | Failing tests for TOOL-01 | 8db91c2 | tests/test_mcp.py, tests/test_storage.py |
| 2 (GREEN) | TOOL-01 implementation + version bump | 079cbf1 | src/mnemo/storage/repository.py, src/mnemo/mcp/tools.py, pyproject.toml |

## Verification Results

All new tests pass:
- `tests/test_search.py::TestSectionFilter` — 10 passed (includes new hierarchy path test)
- `tests/test_mcp.py::TestGetBookStructure` — 7 passed
- `tests/test_mcp.py::TestToolAnnotations` — 5 passed (includes new annotation test)
- `tests/test_mcp.py::TestServerSetup::test_tools_registered` — 1 passed
- `tests/test_storage.py::TestChunkRepositoryGetSectionStructure` — 3 passed

Full suite: 362 passed, 2 skipped, 5 pre-existing failures (unrelated, see below).

## Deviations from Plan

None — plan executed exactly as written.

## Pre-existing Failures (Out of Scope)

The following 5 tests were already failing before this plan and were explicitly identified in 11-RESEARCH.md as not to fix:

1. `TestServerSetup::test_server_imports_without_side_effects` — asserts `mcp.name == "mnemo"` but server includes version (`"mnemo v1.2.1"`)
2. `TestAddBookAsync` (4 tests) — async test plugin (`pytest-asyncio`) not properly installed/configured

These are pre-existing issues logged here for visibility but are out of scope for this plan.

## Self-Check: PASSED

All 8 files confirmed present. All 4 task commits confirmed in git history.
