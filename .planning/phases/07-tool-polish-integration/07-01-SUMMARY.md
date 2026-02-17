---
phase: 07-tool-polish-integration
plan: 01
subsystem: mcp-tools
tags: [mcp, tool-annotations, error-conventions, docstrings, llm-discovery]

dependency-graph:
  requires: [06-02]
  provides: [tool-annotations, error-normalization, llm-docstrings]
  affects: [07-02]

tech-stack:
  added: []
  patterns: [ToolAnnotations decorator pattern, "Error:" prefix convention]

file-tracking:
  key-files:
    modified:
      - src/mnemo/mcp/tools.py
      - tests/test_mcp.py

decisions:
  - id: TOOL-ANN-01
    choice: "Omit idempotentHint for read-only tools (use None/default) rather than setting True"
    why: "MCP spec says idempotentHint defaults to unspecified; read-only tools don't need it since readOnlyHint already covers safe re-invocation"

metrics:
  duration: ~2.5min
  completed: 2026-02-17
---

# Phase 7 Plan 1: Tool Annotations, Error Normalization, and Docstrings Summary

**One-liner:** ToolAnnotations on all 6 MCP tools, "Error:" prefix on all error returns, LLM-tuned docstrings with when-to-use guidance

## What Was Done

### Task 1: Add ToolAnnotations and normalize error strings (c20904c)

Added `from mcp.types import ToolAnnotations` import and annotated all six `@mcp.tool` decorators:

| Tool | readOnlyHint | destructiveHint | idempotentHint | openWorldHint |
|------|-------------|-----------------|----------------|---------------|
| search_books | True | False | (omit) | False |
| list_available_books | True | False | (omit) | False |
| get_book_info | True | False | (omit) | False |
| remove_book | (omit) | True | False | False |
| update_book_metadata | (omit) | (omit) | True | False |
| add_book | (omit) | (omit) | (omit) | False |

Normalized four inconsistent error returns to "Error:" prefix:
- `"Search error: {e}"` -> `"Error: Search failed: {e}"`
- `"Error listing books: {e}"` -> `"Error: Failed to list books: {e}"`
- `"Book not found: {book_id}"` (in get_book_info) -> `"Error: Book not found: {book_id}"`
- `"Book not found: {book_id}"` (in update_book_metadata) -> `"Error: Book not found: {book_id}"`

Updated one test assertion: `"Search error"` -> `"Search failed"` in `test_search_books_handles_exception`.

### Task 2: Enhance tool docstrings for LLM discovery (fb7b18e)

Updated all six MCP tool docstrings with:
- First sentence: what it does
- Second sentence: when to use it (LLM guidance)
- Accurate Args with concrete examples/constraints
- Returns section mentioning `"Error:"` convention

Non-error returns (`"No results found for: {query}"`, `"No books indexed yet..."`) were left unchanged.

## Requirements Satisfied

- **TOOL-01:** Mutation annotations -- `remove_book` has `destructiveHint=True`, `update_book_metadata` has `idempotentHint=True`
- **TOOL-02:** Read-only annotations -- `search_books`, `list_available_books`, `get_book_info` all have `readOnlyHint=True`
- **TOOL-03:** Error conventions -- every error return in tools.py starts with `"Error: "`
- **TOOL-04:** LLM-tuned docstrings -- every tool docstring includes when-to-use guidance and mentions `"Error:"` return format

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- All 48 tests pass (`uv run pytest tests/test_mcp.py -v`)
- All 6 tools have correct ToolAnnotations (verified programmatically)
- All error returns match `"Error: "` prefix (verified via grep)
- Non-error returns unchanged (verified via grep)
- Docstrings picked up by FastMCP (verified via `mcp._tool_manager._tools`)

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | c20904c | feat(07-01): add ToolAnnotations and normalize error strings |
| 2 | fb7b18e | docs(07-01): enhance tool docstrings for LLM discovery |

## Next Phase Readiness

Plan 07-02 (response-format-helpers) can proceed. No blockers.
