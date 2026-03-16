---
phase: 10-parser-quality-fixes
plan: 02
subsystem: epub
tags: [epub, parsing, front-matter, section-labels, tdd]

# Dependency graph
requires:
  - phase: 10-parser-quality-fixes
    provides: Plan 01 word-boundary and author-splitting fixes (PARSE-01, PARSE-02)
provides:
  - FRONT_MATTER_STEMS constant in content.py for filename-to-label mapping
  - _infer_front_matter_label helper with exact and prefix/suffix matching
  - Front-matter section label inference in extract_content spine loop
  - create_epub_with_front_matter factory for test EPUBs with spine-only items
  - 4 regression tests for PARSE-03 front-matter label inference
affects: [search-display, mcp-tools, phase-11, phase-12]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FRONT_MATTER_STEMS dict constant: module-level, easy to extend without code changes"
    - "_infer_front_matter_label: exact stem match first, then prefix/suffix fallback, returns None for no-match"
    - "TDD: RED commit (failing tests) then GREEN commit (implementation) per plan"

key-files:
  created:
    - tests/fixtures/epub_factory.py::create_epub_with_front_matter
  modified:
    - src/mnemo/epub/content.py
    - tests/test_epub_parser.py
    - tests/fixtures/epub_factory.py

key-decisions:
  - "FRONT_MATTER_STEMS uses exact dict lookup first then startswith/endswith — no fuzzy matching needed for known stems"
  - "Returns None (not empty list) when no stem matches — caller distinguishes no-inference from inferred-empty"
  - "Factory adds front-matter to spine before chapter but omits from book.toc — mirrors real EPUB publisher behavior"

patterns-established:
  - "Pattern: Spine-only items (absent from TOC) get label via filename heuristic before falling back to empty section_path"
  - "Pattern: FRONT_MATTER_STEMS dict is the single extension point — add new stems without touching inference logic"

requirements-completed: [PARSE-03]

# Metrics
duration: 8min
completed: 2026-03-13
---

# Phase 10 Plan 02: Front-Matter Section Labels Summary

**FRONT_MATTER_STEMS heuristic lookup assigns descriptive labels to cover, TOC, copyright, and preface spine items absent from EPUB NAV/NCX**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-13T06:02:36Z
- **Completed:** 2026-03-13T06:10:46Z
- **Tasks:** 1 (TDD: 2 commits — RED then GREEN)
- **Files modified:** 3

## Accomplishments
- Added `FRONT_MATTER_STEMS` dict constant with 19 common front-matter filename stems
- Added `_infer_front_matter_label` helper with exact + prefix/suffix matching
- Inserted PARSE-03 heuristic into `extract_content` spine loop after `toc_mapping.get`
- Added `create_epub_with_front_matter` factory producing EPUBs with spine-only items
- 4 new tests all pass: cover, toc, unknown (no false positive), prefix match (preface_01)
- Full suite: 285 passed, 2 skipped

## Task Commits

Each TDD step committed atomically:

1. **RED — Failing tests for PARSE-03** - `969b460` (test)
2. **GREEN — PARSE-03 implementation** - `7d4a190` (feat)

## Files Created/Modified
- `src/mnemo/epub/content.py` - Added `FRONT_MATTER_STEMS` constant, `_infer_front_matter_label` helper, PARSE-03 inference in `extract_content`; added `pathlib.Path` import
- `tests/test_epub_parser.py` - Added `TestFrontMatterLabels` class with 4 tests; updated import
- `tests/fixtures/epub_factory.py` - Added `create_epub_with_front_matter` factory function

## Decisions Made
- Exact stem match is attempted before prefix/suffix fallback — avoids false positives for stems that share prefixes (e.g., "intro" matching "introduction")
- Helper returns `None` not `[]` when no match — allows caller to distinguish "no inference possible" from "inferred empty"
- Factory sets `book.spine = ["nav"] + front_matter_epub_items + [normal_chapter]` but `book.toc = [normal_chapter]` only — accurately simulates real EPUB front-matter structure

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- PARSE-03 complete; Phase 10 has all three bug fixes (PARSE-01, PARSE-02, PARSE-03) implemented
- Full test suite green (285 passed) — ready for Phase 10 verification gate
- FRONT_MATTER_STEMS is easily extensible if real-world EPUBs require additional stems

---
*Phase: 10-parser-quality-fixes*
*Completed: 2026-03-13*
