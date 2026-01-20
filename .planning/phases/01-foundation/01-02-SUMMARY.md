---
phase: 01-foundation
plan: 02
subsystem: epub-parsing
tags: [epub, ebooklib, beautifulsoup, content-detection, toc-parsing]

# Dependency graph
requires:
  - 01-01 (Python package + models)
provides:
  - EPUBParser class for EPUB file parsing
  - ContentBlock intermediate representation
  - Dublin Core metadata extraction
  - Content type detection (code, tables, diagrams, math, text)
  - TOC parsing with heading inference fallback
affects: [01-03-chunker, 02-vector-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns: [content-type-detection, toc-hierarchy-parsing, publisher-quirk-handling]

key-files:
  created:
    - src/mnemo/epub/__init__.py
    - src/mnemo/epub/parser.py
    - src/mnemo/epub/metadata.py
    - src/mnemo/epub/content.py
    - tests/test_epub_parser.py
    - tests/fixtures/__init__.py
    - tests/fixtures/epub_factory.py
  modified: []

key-decisions:
  - "Publisher-specific CSS classes for code detection (O'Reilly, Pragmatic, Manning)"
  - "ASCII art heuristic: >15% box characters and >5 total box chars"
  - "Warning suppression for XHTML parsing with lxml-html (intentional design)"

patterns-established:
  - "ContentBlock as intermediate representation between EPUB and Chunk"
  - "TOC fallback chain: EPUB3 nav -> EPUB2 NCX -> heading inference"
  - "Test fixture factory pattern for EPUB generation"

# Metrics
duration: 6min
completed: 2026-01-20
---

# Phase 1 Plan 02: EPUB Parser Summary

**Complete EPUB parser extracting structured content with 5 content types and hierarchical section paths**

## Performance

- **Duration:** 6 min
- **Started:** 2026-01-20T06:24:25Z
- **Completed:** 2026-01-20T06:30:49Z
- **Tasks:** 3
- **Files created:** 7
- **Tests:** 18 (all passing)

## Accomplishments

- **EPUBParser class** - Single entry point for EPUB parsing returning (Book, list[ContentBlock])
- **Dublin Core extraction** - Title, authors, ISBN (with normalization), file hash
- **Content type detection** - CODE, TABLE, DIAGRAM, MATH, TEXT with publisher-specific handling
- **TOC parsing** - EPUB3 nav, EPUB2 NCX, and heading inference fallback
- **Language detection** - From class="language-*", data-lang, and known language classes
- **Table conversion** - HTML tables to pipe-delimited searchable text

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement metadata extraction** - `bf2610f` (feat)
   - Created epub package structure
   - Dublin Core metadata extraction
   - ISBN normalization (ISBN-10, ISBN-13, URN)
   - Test fixture factory

2. **Task 2: Implement content extraction** - `82f6eb5` (feat)
   - ContentBlock dataclass
   - Content type detection (5 types)
   - Publisher-specific code class handling
   - ASCII diagram heuristics
   - Table to text conversion

3. **Task 3: TOC parsing and EPUBParser** - `53402c4` (feat)
   - EPUBParser main class
   - EPUB3 nav document parsing
   - EPUB2 NCX fallback
   - Heading inference fallback
   - Comprehensive test suite

## Files Created

- `src/mnemo/epub/__init__.py` - Package init with exports and warning suppression
- `src/mnemo/epub/parser.py` - EPUBParser class with TOC parsing
- `src/mnemo/epub/metadata.py` - Dublin Core extraction and ISBN normalization
- `src/mnemo/epub/content.py` - ContentBlock and type detection
- `tests/test_epub_parser.py` - 18 tests covering all functionality
- `tests/fixtures/__init__.py` - Test fixtures package
- `tests/fixtures/epub_factory.py` - EPUB generation factory for tests

## Content Type Detection

| Type | Detection Method |
|------|------------------|
| CODE | `<pre>`, `<code>`, programlisting/highlight/sourceCode classes |
| TABLE | `<table>` tags, converted to pipe-delimited format |
| DIAGRAM | `<pre>` with ascii/diagram class or ASCII art heuristics |
| MATH | `<math>`, equation class, LaTeX delimiters ($, \[) |
| TEXT | Everything else (paragraphs, lists, etc.) |

## Publisher Support

Code block detection includes patterns for:
- **Standard:** pre > code, highlight, sourceCode
- **O'Reilly:** programlisting, screen
- **Pragmatic:** code, livecodelozenge
- **Manning:** listingblock

## Decisions Made

1. **XHTML warning suppression** - Using lxml-html parser on XHTML is intentional; performance and compatibility are good
2. **ASCII art threshold** - 15% box characters and 5+ total provides good balance of detection vs false positives
3. **ContentBlock intermediate** - Separates parsing concerns from chunking concerns cleanly

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- **ebooklib constant location** - `ITEM_DOCUMENT` is in `ebooklib` not `ebooklib.epub`
- **EPUB content encoding** - Used `set_content()` with bytes in test factory for proper encoding

Both were minor and fixed inline.

## Next Phase Readiness

- EPUBParser ready for chunker integration (01-03)
- ContentBlock provides all data needed for intelligent chunking:
  - content_type for atomic code handling
  - section_path for hierarchy
  - language for code blocks
  - source_file for debugging

---
*Phase: 01-foundation*
*Completed: 2026-01-20*
