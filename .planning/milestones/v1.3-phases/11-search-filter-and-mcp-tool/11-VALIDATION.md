---
phase: 11
slug: search-filter-and-mcp-tool
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-13
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via pyproject.toml) |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/test_search.py tests/test_mcp.py -x -q --tb=short` |
| **Full suite command** | `python -m pytest -x -q --tb=short` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_search.py tests/test_mcp.py -x -q --tb=short`
- **After every plan wave:** Run `python -m pytest -x -q --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 0 | SRCH-01 | unit | `python -m pytest tests/test_search.py::TestSectionFilter::test_section_filter_matches_hierarchy_path -x` | ❌ W0 | ⬜ pending |
| 11-01-02 | 01 | 0 | TOOL-01 | unit | `python -m pytest tests/test_mcp.py::TestGetBookStructure -x -q` | ❌ W0 | ⬜ pending |
| 11-01-03 | 01 | 0 | TOOL-01 | unit | `python -m pytest tests/test_storage.py -x -q -k structure` | ❌ W0 | ⬜ pending |
| 11-01-04 | 01 | 1 | SRCH-01 | unit | `python -m pytest tests/test_search.py::TestSectionFilter -x -q` | ✅ | ⬜ pending |
| 11-01-05 | 01 | 1 | TOOL-01 | unit | `python -m pytest tests/test_mcp.py::TestGetBookStructure -x -q` | ❌ W0 | ⬜ pending |
| 11-01-06 | 01 | 1 | TOOL-01 | unit | `python -m pytest tests/test_mcp.py::TestToolAnnotations -x -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_search.py::TestSectionFilter::test_section_filter_matches_hierarchy_path` — stub for SRCH-01 hierarchy matching
- [ ] `tests/test_mcp.py::TestGetBookStructure` class — stubs for TOOL-01 structure output
- [ ] `tests/test_storage.py` — stub for `ChunkRepository.get_section_structure`
- [ ] Update `tests/test_mcp.py::TestServerSetup::test_tools_registered` to expect `get_book_structure`
- [ ] Update `tests/test_mcp.py::TestToolAnnotations` with `test_get_book_structure_has_read_only_annotations`

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
