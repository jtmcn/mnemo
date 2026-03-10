---
phase: 8
slug: infrastructure-quick-wins
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
---

# Phase 8 — Validation Strategy

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
| 8-01-01 | 01 | 1 | INFRA-01 | unit | `python -m pytest tests/test_vectors.py -x -k cosine` | ❌ W0 | ⬜ pending |
| 8-01-02 | 01 | 1 | INFRA-02 | unit | `python -m pytest tests/test_migration.py -x -k copy` | ❌ W0 | ⬜ pending |
| 8-01-03 | 01 | 1 | INFRA-03 | unit | `python -m pytest tests/test_migration.py -x -k verify` | ❌ W0 | ⬜ pending |
| 8-01-04 | 01 | 1 | INFRA-05 | unit | `python -m pytest tests/test_cli.py -x -k migrate` | ❌ W0 | ⬜ pending |
| 8-02-01 | 02 | 1 | SRCH-01 | unit | `python -m pytest tests/test_search.py -x -k score` | ❌ W0 | ⬜ pending |
| 8-02-02 | 02 | 1 | CHUNK-01 | unit | `python -m pytest tests/test_mcp.py -x -k chunk_size` | ❌ W0 | ⬜ pending |
| 8-02-03 | 02 | 1 | CHUNK-02 | unit | `python -m pytest tests/test_mcp.py -x -k chunk_valid` | ❌ W0 | ⬜ pending |
| 8-02-04 | 02 | 1 | CHUNK-03 | unit | `python -m pytest tests/test_chunker.py -x -k default` | ✅ partial | ⬜ pending |
| 8-02-05 | 02 | 1 | INFRA-04 | unit | `python -m pytest tests/test_storage.py -x -k epub_path` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_migration.py` — stubs for INFRA-02, INFRA-03 (new file)
- [ ] New tests in `tests/test_vectors.py` — stubs for INFRA-01
- [ ] New tests in `tests/test_storage.py` — stubs for INFRA-04
- [ ] New tests in `tests/test_search.py` — stubs for SRCH-01
- [ ] New tests in `tests/test_mcp.py` — stubs for CHUNK-01, CHUNK-02
- [ ] New tests in `tests/test_cli.py` — stubs for INFRA-05

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CLI migrate-cosine end-to-end with real ChromaDB data | INFRA-05 | Requires actual persisted collection | Run `mnemo migrate-cosine` against test collection, verify output |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
