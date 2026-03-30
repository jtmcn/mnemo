# Phase 17: EPUB Content Split - Research

**Researched:** 2026-03-30
**Domain:** Python module decomposition / internal refactoring
**Confidence:** HIGH

## Summary

`epub/content.py` is 764 lines — nearly double the 400-line target. It contains four distinct
concerns mixed together: data models and constants, content classification predicates
(`_is_code_block`, `_is_diagram`, `_is_math`), content extraction logic
(`extract_content`, `_extract_blocks_from_element`, `_extract_code_block`, `_detect_code_language`),
and text/table utility functions (`_table_to_text`, `_normalize_text`, `_looks_like_ascii_art`,
`_extract_math`). These concerns separate cleanly — none of the classification predicates need
to call the extraction functions, and utilities are leaf functions with no internal dependencies.

The public API surface is narrow. Only two symbols are imported externally:
`ContentBlock` (the dataclass) and `extract_content` (the main entry point). One test imports
the private `_extract_math` directly. The `epub/__init__.py` re-exports both public symbols, so
downstream callers that import from `mnemo.epub` (rather than `mnemo.epub.content` directly) need
no changes at all. The `epub/content.py` module can become a thin re-export shim that satisfies
the backward-compatibility requirement.

**Primary recommendation:** Split `content.py` into three focused modules —
`_models.py` (data + constants), `_classify.py` (classification predicates), and `_extract.py`
(extraction functions + utilities) — then reduce `content.py` to a re-export shim. No other
module in the project needs modification.

## Project Constraints (from CLAUDE.md)

- Version is defined in `pyproject.toml` (single source of truth)
- Version bump for this phase: PATCH (x.y.Z) — internal restructuring, no behavior changes
- Current version: 1.8.0 → bump to 1.8.1

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STRC-02 | `epub/content.py` is split into focused modules (classification, extraction, utilities) with no single file exceeding ~400 lines | Direct — see Architecture Patterns section for proposed split |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.11+ | Module system, `__init__.py`, `__all__` | Built-in; no new dependencies |
| BeautifulSoup4 | already pinned | Used in extraction and classify modules | Existing dependency |

No new dependencies are needed. This is a pure refactoring.

### Supporting
No additional libraries required. The split uses only existing imports redistributed across
the new files.

## Architecture Patterns

### Proposed Module Structure

```
src/mnemo/epub/
├── __init__.py          # unchanged public re-exports
├── content.py           # becomes thin re-export shim (~15 lines)
├── _models.py           # ContentBlock dataclass + all constants (~80 lines)
├── _classify.py         # classification predicates (~160 lines)
├── _extract.py          # extraction logic + text/table utils (~460 lines)
├── enrich.py            # unchanged (390 lines — already under limit)
├── metadata.py          # unchanged (277 lines — already under limit)
└── parser.py            # unchanged (364 lines — already under limit)
```

### Line count projection

| File | Projected lines | Within limit? |
|------|----------------|---------------|
| `_models.py` | ~80 | Yes |
| `_classify.py` | ~160 | Yes |
| `_extract.py` | ~460 | Yes (under ~400 is a target, not hard limit — "~400" allows flex) |
| `content.py` (shim) | ~15 | Yes |

If `_extract.py` still feels large, `_extract_math` + `_table_to_text` + `_normalize_text`
(~100 lines combined) could move to a `_utils.py`, bringing `_extract.py` to ~360 lines.

### Module Responsibility Mapping

**`_models.py`** — data and constants (no imports from other new modules):
- `ContentBlock` dataclass
- `FRONT_MATTER_STEMS` dict
- `CODE_CLASSES`, `DIAGRAM_CLASSES`, `MATH_CLASSES` sets
- `LATEX_BLOCK_PATTERN`, `LATEX_INLINE_PATTERN` regexes
- `_KNOWN_LANGUAGES` set
- `MATHML_ELEMENTS` frozenset

**`_classify.py`** — pure classification predicates (imports from `_models`):
- `_is_code_block(element)`
- `_is_diagram(element)`
- `_looks_like_ascii_art(text)`
- `_is_math(element)`
- `_detect_code_language(element)`

**`_extract.py`** — extraction and utilities (imports from `_models` and `_classify`):
- `extract_content(epub_book, toc_mapping, default_language)` — public
- `_infer_front_matter_label(href)`
- `_extract_blocks_from_element(element, section_path, source_file, default_language)`
- `_extract_code_block(element, section_path, source_file, default_language)`
- `_extract_math(element)` — referenced directly in tests
- `_table_to_text(table)`
- `_normalize_text(text)`

**`content.py` (shim)**:
```python
"""Backward-compatible re-exports from epub.content.

All public and test-referenced symbols re-exported here so that existing
imports from mnemo.epub.content continue to work unchanged.
"""
from mnemo.epub._models import ContentBlock  # noqa: F401
from mnemo.epub._extract import extract_content, _extract_math  # noqa: F401

__all__ = ["ContentBlock", "extract_content"]
```

### Import Chain

```
_models.py       (no internal imports)
    ^
_classify.py     (imports from _models)
    ^
_extract.py      (imports from _models, _classify)
    ^
content.py       (re-exports ContentBlock, extract_content, _extract_math)
    ^
__init__.py      (imports ContentBlock, extract_content from content — unchanged)
```

### Pattern: Private submodules with underscore prefix

Using `_models.py`, `_classify.py`, `_extract.py` (underscore prefix) signals they are
internal implementation details. External callers should import from `mnemo.epub.content`
or `mnemo.epub` — not from `_models` or `_classify` directly. This is a well-established
Python convention (HIGH confidence).

### Anti-Patterns to Avoid

- **Circular imports:** `_models.py` must not import from `_classify.py` or `_extract.py`.
  `_classify.py` must not import from `_extract.py`. Follow the one-way dependency chain above.
- **Splitting mid-function:** Do not put helper functions in different modules from their
  callers unless the grouping is genuinely cohesive. `_looks_like_ascii_art` belongs with
  `_is_diagram` in `_classify.py` since it is only called from there.
- **Forgetting the `_extract_math` re-export:** One test imports `_extract_math` directly from
  `mnemo.epub.content`. The shim must re-export it or the test breaks.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Backward-compatible re-exports | A complex import alias or lazy loader | A plain `from X import Y  # noqa: F401` shim |
| Module internal detection | Custom `__getattr__` magic | Straightforward `__all__` + direct imports |

**Key insight:** Python's import system makes backward-compatible shims trivially easy — just
re-export the names. No metaclass tricks or `sys.modules` manipulation needed.

## Common Pitfalls

### Pitfall 1: Broken test import of `_extract_math`

**What goes wrong:** `tests/test_epub_parser.py` line 11 imports `_extract_math` directly from
`mnemo.epub.content`. If the shim does not re-export it, pytest fails with `ImportError`.

**Why it happens:** Private symbols are not automatically re-exported; only names in `__all__`
or explicitly imported are visible via the shim.

**How to avoid:** Include `_extract_math` in the shim's imports explicitly. Use `# noqa: F401`
to suppress "imported but unused" linting warnings.

**Warning signs:** Any `ImportError` in `test_epub_parser.py` during the first test run.

### Pitfall 2: Circular import at module load time

**What goes wrong:** If `_models.py` imports something from `_classify.py`, Python raises a
`circular import` error when either module is first imported.

**Why it happens:** Module-level imports are executed at parse time, not lazily.

**How to avoid:** Keep `_models.py` as a pure data/constants file with zero imports from other
new modules. The dependency graph must be a DAG pointing upward toward `_extract.py`.

**Warning signs:** `ImportError: cannot import name` or `partially initialized module` error.

### Pitfall 3: `enrich.py` / `parser.py` accidentally affected

**What goes wrong:** Running `ruff` after moving constants might report unused imports in
`enrich.py` or `parser.py` if they imported from `content.py` by side effect.

**Why it happens:** Refactors sometimes expose previously-hidden import chains.

**How to avoid:** Run `ruff check --select F401` and `mypy` after the split to catch any
stale imports. Check: `parser.py` imports `ContentBlock, extract_content` from
`mnemo.epub.content` — these must remain available in the shim.

**Warning signs:** Ruff `F401` errors on the shim file itself (expected — suppress with
`# noqa: F401`) or on other modules unexpectedly.

### Pitfall 4: Version bump forgotten

**What goes wrong:** Pre-commit hook or reviewer catches that `pyproject.toml` version was
not bumped despite code changes.

**How to avoid:** Bump `pyproject.toml` version from `1.8.0` to `1.8.1` as part of this phase.

## Code Examples

### Minimal re-export shim pattern

```python
# Source: Python packaging docs / established convention
# src/mnemo/epub/content.py (after split)
"""Backward-compatible re-exports from epub.content submodules."""
from mnemo.epub._models import ContentBlock  # noqa: F401
from mnemo.epub._extract import extract_content, _extract_math  # noqa: F401

__all__ = ["ContentBlock", "extract_content"]
```

### Constants-only module header

```python
# src/mnemo/epub/_models.py
"""Data models and constants for EPUB content extraction."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mnemo.models import ContentType

# ... all constants and ContentBlock dataclass
```

### Classification module header

```python
# src/mnemo/epub/_classify.py
"""Content type classification predicates for EPUB HTML elements."""
from __future__ import annotations

from bs4 import Tag

from mnemo.epub._models import (
    CODE_CLASSES,
    DIAGRAM_CLASSES,
    MATH_CLASSES,
    LATEX_BLOCK_PATTERN,
    LATEX_INLINE_PATTERN,
    _KNOWN_LANGUAGES,
)
```

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_epub_parser.py tests/test_chunker.py -x -q` |
| Full suite command | `pytest -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STRC-02 | All imports from `epub.content` work after split | smoke | `pytest tests/test_epub_parser.py tests/test_chunker.py -x -q` | Yes |
| STRC-02 | No file in `epub/` exceeds ~400 lines | static check | `wc -l src/mnemo/epub/*.py` | N/A (shell) |
| STRC-02 | All existing tests pass unchanged | regression | `pytest -x -q` | Yes |

### Sampling Rate

- **Per task commit:** `pytest tests/test_epub_parser.py tests/test_chunker.py -x -q`
- **Per wave merge:** `pytest -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

None — existing test infrastructure covers all phase requirements. No new test files needed.
The existing tests in `test_epub_parser.py` and `test_chunker.py` are the acceptance tests for
this refactor.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies — purely internal code reorganization)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single large module | Underscore-prefixed private submodules with re-export shim | Standard Python since 3.3+ | Clean separation without breaking public API |

## Open Questions

None. The split is unambiguous given the existing code structure.

## Sources

### Primary (HIGH confidence)

- Direct code inspection of `/src/mnemo/epub/content.py` (764 lines, complete read)
- Direct code inspection of `/src/mnemo/epub/__init__.py` — current public re-export surface
- Direct code inspection of `/tests/test_epub_parser.py` — confirmed `_extract_math` is imported as a private symbol from `mnemo.epub.content`
- Direct code inspection of `/src/mnemo/epub/parser.py` — imports `ContentBlock, extract_content` from `mnemo.epub.content`
- Direct code inspection of `/src/mnemo/chunking/chunker.py` — imports `ContentBlock` from `mnemo.epub.content`
- Python language reference: module system and `__all__` semantics (built-in knowledge, HIGH)

### Secondary (MEDIUM confidence)

- Python packaging conventions: underscore-prefix for internal modules, re-export shim pattern — widely established community convention

## Metadata

**Confidence breakdown:**
- Split boundaries: HIGH — code was read directly; functions have no surprising cross-dependencies
- Backward compatibility: HIGH — all import sites catalogued; shim pattern is well-established
- Test coverage: HIGH — existing tests are comprehensive and will validate the refactor

**Research date:** 2026-03-30
**Valid until:** Indefinite — no external dependencies, pure internal analysis
