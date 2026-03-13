---
phase: 10-parser-quality-fixes
plan: 01
subsystem: epub-parsing
tags: [beautifulsoup, ebooklib, epub, text-extraction, metadata]

# Dependency graph
requires: []
provides:
  - Word boundary preservation across adjacent inline HTML elements (PARSE-01)
  - Semicolon-delimited author string splitting in dc:creator metadata (PARSE-02)
affects: [10-02, 10-03, indexing, search]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Use get_text(separator=' ') on inline elements to preserve word boundaries"
    - "Split dc:creator on semicolons to handle multi-author strings"

key-files:
  created: []
  modified:
    - src/mnemo/epub/content.py
    - src/mnemo/epub/metadata.py
    - tests/test_epub_parser.py
    - tests/fixtures/epub_factory.py
    - pyproject.toml

key-decisions:
  - "Only the catch-all else branch in _extract_blocks_from_element gets separator=' '; code/table/diagram/math branches are untouched to preserve indentation"
  - "Semicolon splitting happens in _extract_authors after retrieving raw dc:creator strings, filtering empty parts after strip"

patterns-established:
  - "epub_factory raw_creators param: pass raw dc:creator strings bypassing add_author() for testing semicolon-delimited metadata"

requirements-completed: [PARSE-01, PARSE-02]

# Metrics
duration: 2min
completed: 2026-03-13
---

# Phase 10 Plan 01: Parser Quality Fixes (PARSE-01, PARSE-02) Summary

**Patched BeautifulSoup get_text separator and dc:creator semicolon splitting to fix word-joining and multi-author metadata bugs**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-13T06:02:32Z
- **Completed:** 2026-03-13T06:03:59Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 5

## Accomplishments

- Fixed PARSE-01: adjacent inline elements (`<span>a</span><span>strategy</span>`) now produce "a strategy" not "astrategy" by using `get_text(separator=" ")` on the catch-all branch
- Fixed PARSE-02: dc:creator strings like "Smith, Alice; Jones, Bob;" now split into `["Smith, Alice", "Jones, Bob"]` with trailing semicolons stripped
- Added `raw_creators` parameter to `create_test_epub` so tests can inject semicolon-delimited creator strings as a single dc:creator element
- 22 tests pass in test_epub_parser.py; 281 pass in full suite (2 skipped, 0 regressions)
- Bumped version 1.2.1 -> 1.2.2 (patch: bug fixes)

## Task Commits

1. **RED — Failing tests for PARSE-01 and PARSE-02** - `1de1580` (test)
2. **GREEN — Fix content.py + metadata.py, bump version** - `aa1bed3` (feat)

_TDD task: RED commit then GREEN commit_

## Files Created/Modified

- `src/mnemo/epub/content.py` - catch-all branch: `get_text(strip=True)` -> `get_text(separator=" ", strip=True)`
- `src/mnemo/epub/metadata.py` - `_extract_authors`: split each raw creator on ";" and filter empty parts
- `tests/test_epub_parser.py` - added `TestWordBoundaryFix` and `TestSemicolonAuthorSplit` test classes (4 new tests)
- `tests/fixtures/epub_factory.py` - added `raw_creators` optional parameter to `create_test_epub`
- `pyproject.toml` - version bumped 1.2.1 -> 1.2.2

## Decisions Made

- Only the catch-all branch gets `separator=" "` — code, table, diagram, and math branches call their own extraction functions that preserve raw whitespace; changing those would break indentation.
- Semicolon splitting always applied to every dc:creator string; normal single-author books have no semicolons so splitting is a no-op.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- PARSE-01 and PARSE-02 complete; content.py and metadata.py ready for PARSE-03 (front-matter label inference) in plan 10-02
- No blockers

---
*Phase: 10-parser-quality-fixes*
*Completed: 2026-03-13*
