---
phase: 10
slug: parser-quality-fixes
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-12
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (current project standard) |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `python -m pytest tests/test_epub_parser.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -q --ignore=tests/test_mcp.py` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_epub_parser.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -q --ignore=tests/test_mcp.py`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 0 | PARSE-01 | unit | `python -m pytest tests/test_epub_parser.py::TestContentExtraction::test_word_boundaries_preserved_across_inline_elements -x` | ❌ W0 | ⬜ pending |
| 10-01-02 | 01 | 0 | PARSE-01 | unit | `python -m pytest tests/test_epub_parser.py::TestContentExtraction::test_inline_sibling_word_boundaries -x` | ❌ W0 | ⬜ pending |
| 10-01-03 | 01 | 0 | PARSE-02 | unit | `python -m pytest tests/test_epub_parser.py::TestExtractMetadata::test_semicolon_delimited_authors -x` | ❌ W0 | ⬜ pending |
| 10-01-04 | 01 | 0 | PARSE-02 | unit | `python -m pytest tests/test_epub_parser.py::TestExtractMetadata::test_author_trailing_semicolon -x` | ❌ W0 | ⬜ pending |
| 10-01-05 | 01 | 0 | PARSE-03 | unit | `python -m pytest tests/test_epub_parser.py::TestContentExtraction::test_front_matter_cover_label -x` | ❌ W0 | ⬜ pending |
| 10-01-06 | 01 | 0 | PARSE-03 | unit | `python -m pytest tests/test_epub_parser.py::TestContentExtraction::test_front_matter_toc_label -x` | ❌ W0 | ⬜ pending |
| 10-01-07 | 01 | 0 | PARSE-03 | unit | `python -m pytest tests/test_epub_parser.py::TestContentExtraction::test_unknown_href_no_label -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_epub_parser.py` — add `test_word_boundaries_preserved_across_inline_elements` to `TestContentExtraction`
- [ ] `tests/test_epub_parser.py` — add `test_inline_sibling_word_boundaries` to `TestContentExtraction`
- [ ] `tests/test_epub_parser.py` — add `test_semicolon_delimited_authors` to `TestExtractMetadata`
- [ ] `tests/test_epub_parser.py` — add `test_author_trailing_semicolon` to `TestExtractMetadata`
- [ ] `tests/test_epub_parser.py` — add `test_front_matter_cover_label` to `TestContentExtraction`
- [ ] `tests/test_epub_parser.py` — add `test_front_matter_toc_label` to `TestContentExtraction`
- [ ] `tests/test_epub_parser.py` — add `test_unknown_href_no_label` to `TestContentExtraction`
- [ ] `tests/fixtures/epub_factory.py` — add `create_epub_with_front_matter()` factory function for PARSE-03 tests

*Existing infrastructure covers framework and fixtures; only new test stubs needed.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
