---
phase: 12
slug: output-formatting
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-13
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/test_mcp.py::TestSearchBooksContextWindow -v` |
| **Full suite command** | `python -m pytest tests/test_mcp.py -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_mcp.py::TestSearchBooksContextWindow -v`
- **After every plan wave:** Run `python -m pytest tests/test_mcp.py -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | TOOL-02 | unit | `python -m pytest tests/test_mcp.py::TestSearchBooksContextWindow -v` | ✅ (assertions need update) | ⬜ pending |
| 12-01-02 | 01 | 1 | TOOL-02 | manual | n/a | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. The 3 tests in `TestSearchBooksContextWindow` exist and are the right tests; they just need assertion string updates to match the new format.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual scan in Claude Desktop renders `---` as horizontal rule and `**bold**` as styled label | TOOL-02 | Automated markdown rendering not feasible — output consumed by LLM chat UI | 1. Run `search_books` with `context_window=1` via MCP in Claude Desktop 2. Verify matched chunk has visible horizontal rule separator 3. Verify `[MATCH]` label is bold and on its own line 4. Verify context chunks are visually subordinate |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
