---
phase: 17-epub-content-split
plan: "01"
subsystem: epub
tags: [refactor, structure, modules, epub]
dependency_graph:
  requires: []
  provides: [epub/_models.py, epub/_classify.py, epub/_extract.py, epub/content.py-shim]
  affects: [epub/parser.py, epub/__init__.py, chunking/chunker.py]
tech_stack:
  added: []
  patterns: [private-module-prefix, re-export-shim, one-way-dependency-chain]
key_files:
  created:
    - src/mnemo/epub/_models.py
    - src/mnemo/epub/_classify.py
    - src/mnemo/epub/_extract.py
  modified:
    - src/mnemo/epub/content.py
    - pyproject.toml
decisions:
  - "Private module prefix (_models, _classify, _extract) signals internal API boundaries"
  - "Re-export shim in content.py preserves all existing imports without changes to callers"
  - "STRC-02 satisfied: no file in epub/ exceeds 463 lines (ceiling was ~460)"
metrics:
  duration: 3m
  completed: "2026-03-31"
  tasks_completed: 2
  files_changed: 5
---

# Phase 17 Plan 01: Epub Content Split Summary

Split 764-line epub/content.py into three focused private modules plus a 10-line backward-compatible re-export shim, satisfying STRC-02 and preparing the epub package for Phase 18 maintenance.

## What Was Built

Three private submodules extracted from `epub/content.py`:

- **`_models.py`** (143 lines): `ContentBlock` dataclass, all constants (`FRONT_MATTER_STEMS`, `CODE_CLASSES`, `DIAGRAM_CLASSES`, `MATH_CLASSES`, `LATEX_*_PATTERN`, `_KNOWN_LANGUAGES`, `MATHML_ELEMENTS`). No internal imports.
- **`_classify.py`** (189 lines): Classification predicates (`_is_code_block`, `_is_diagram`, `_looks_like_ascii_art`, `_is_math`, `_detect_code_language`). Imports only from `_models`.
- **`_extract.py`** (463 lines): Extraction logic (`extract_content`, `_extract_blocks_from_element`, `_extract_code_block`, `_extract_math`, `_table_to_text`, `_normalize_text`, `_infer_front_matter_label`). Imports from `_models` and `_classify`.
- **`content.py`** (10 lines): Re-export shim preserving `ContentBlock`, `extract_content`, `_extract_math` for existing callers.

Version bumped from 1.8.0 to 1.8.1 (PATCH).

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1    | 6a6f12a | feat(17-01): extract epub content.py into three private submodules |
| 2    | 11ca31f | feat(17-01): convert content.py to re-export shim, bump version to 1.8.1 |

## Verification Results

- Import compatibility: `from mnemo.epub.content import ContentBlock, extract_content, _extract_math` — OK
- Package-level imports: `from mnemo.epub import EPUBParser, ContentBlock, extract_content` — OK
- Full test suite: 525 passed, 0 failures
- Line counts: _models=143, _classify=189, _extract=463, content=10 (all under ceiling)
- Lint: `uv run ruff check src/mnemo/epub/` — clean

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused imports from _classify.py and _extract.py**
- **Found during:** Task 2 (ruff check)
- **Issue:** `MATHML_ELEMENTS` imported in `_classify.py` but unused; `LATEX_BLOCK_PATTERN`, `LATEX_INLINE_PATTERN`, and `_looks_like_ascii_art` imported in `_extract.py` but unused
- **Fix:** `uv run ruff check --fix` auto-removed unused imports and reordered import blocks to isort order
- **Files modified:** `_classify.py`, `_extract.py`
- **Commit:** 11ca31f (included in task 2 commit)

## Known Stubs

None. All symbols wire to real implementations.

## Self-Check: PASSED

Files exist:
- FOUND: src/mnemo/epub/_models.py
- FOUND: src/mnemo/epub/_classify.py
- FOUND: src/mnemo/epub/_extract.py
- FOUND: src/mnemo/epub/content.py

Commits exist:
- FOUND: 6a6f12a
- FOUND: 11ca31f
