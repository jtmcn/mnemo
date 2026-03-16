---
phase: 13
slug: audit-gap-closure
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-14
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/test_mcp.py::TestServerSetup tests/test_mcp.py::TestAddBookAsync -v` |
| **Full suite command** | `python -m pytest tests/test_mcp.py -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_mcp.py --tb=short -q`
- **After every plan wave:** Run `python -m pytest tests/test_mcp.py -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 1 | TOOL-02 | documentation | `test -f .planning/phases/12-output-formatting/12-VERIFICATION.md` | ❌ W0 | ⬜ pending |
| 13-01-02 | 01 | 1 | SRCH-01, TOOL-01 | frontmatter | `grep -c 'SRCH-01' .planning/phases/11-search-filter-and-mcp-tool/11-01-SUMMARY.md` | ✅ | ⬜ pending |
| 13-01-03 | 01 | 1 | — | documentation | `grep '\[x\].*12-01-PLAN' .planning/ROADMAP.md` | ✅ | ⬜ pending |
| 13-01-04 | 01 | 1 | — | unit | `python -m pytest tests/test_mcp.py::TestServerSetup::test_tools_registered -v` | ✅ | ⬜ pending |
| 13-01-05 | 01 | 1 | — | unit | `python -m pytest tests/test_mcp.py -v -k TestToolAnnotations` | ✅ | ⬜ pending |
| 13-01-06 | 01 | 1 | — | unit | `python -m pytest tests/test_mcp.py::TestServerSetup::test_server_imports_without_side_effects tests/test_mcp.py::TestAddBookAsync -v` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. The only action is installing the already-declared `pytest-asyncio` dependency.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| VERIFICATION.md content quality | TOOL-02 | Document must cite specific evidence | Review 12-VERIFICATION.md has line-number citations and passing test references |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
