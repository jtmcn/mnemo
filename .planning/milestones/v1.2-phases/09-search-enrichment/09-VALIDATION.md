---
phase: 9
slug: search-enrichment
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | META-03 | unit | `python -m pytest tests/test_mcp.py -x -k get_book_chunks` | ❌ W0 | ⬜ pending |
| 09-01-02 | 01 | 1 | META-04 | unit | `python -m pytest tests/test_mcp.py -x -k book_chunks_fields` | ❌ W0 | ⬜ pending |
| 09-01-03 | 01 | 1 | META-05 | unit | `python -m pytest tests/test_mcp.py -x -k book_chunks_limit` | ❌ W0 | ⬜ pending |
| 09-02-01 | 02 | 1 | META-01 | unit | `python -m pytest tests/test_search.py -x -k section_filter` | ❌ W0 | ⬜ pending |
| 09-02-02 | 02 | 1 | META-02 | unit | `python -m pytest tests/test_search.py -x -k section_all_modes` | ❌ W0 | ⬜ pending |
| 09-03-01 | 03 | 2 | SRCH-02 | unit | `python -m pytest tests/test_search.py -x -k context_window` | ❌ W0 | ⬜ pending |
| 09-03-02 | 03 | 2 | SRCH-03 | unit | `python -m pytest tests/test_search.py -x -k section_boundary` | ❌ W0 | ⬜ pending |
| 09-03-03 | 03 | 2 | SRCH-04 | unit | `python -m pytest tests/test_search.py -x -k dedup` | ❌ W0 | ⬜ pending |
| 09-03-04 | 03 | 2 | SRCH-05 | unit | `python -m pytest tests/test_search.py -x -k context_window_zero` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_search.py` — stubs for SRCH-02, SRCH-03, SRCH-04, SRCH-05, META-01, META-02
- [ ] `tests/test_mcp.py` — stubs for META-03, META-04, META-05
- [ ] `tests/test_storage.py` — stubs for `get_chunk_range` repository method

*Existing test infrastructure covers framework installation.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
