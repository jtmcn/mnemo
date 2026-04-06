---
phase: 18
slug: mcp-service-layer-refactor
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-31
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pyproject.toml) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/test_mcp.py tests/test_cli.py -x -q` |
| **Full suite command** | `python -m pytest -x -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_mcp.py tests/test_cli.py -x -q`
- **After every plan wave:** Run `python -m pytest -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 18-01-01 | 01 | 1 | STRC-01 | structural | `wc -l src/mnemo/mcp/*.py` | N/A | ⬜ pending |
| 18-01-02 | 01 | 1 | STRC-03 | structural + unit | `grep -n "_get_book_repo\|_get_chunk_repo\|_get_search_service" src/mnemo/mcp/tools_*.py` | N/A | ⬜ pending |
| 18-02-01 | 02 | 2 | STRC-04 | unit | `python -m pytest tests/test_mcp.py tests/test_cli.py -x -q` | ✅ | ⬜ pending |
| 18-02-02 | 02 | 2 | STRC-05 | regression | `python -m pytest -x -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
