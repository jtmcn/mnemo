---
phase: 14
slug: dependencies-configuration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-28
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ with pytest-asyncio |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `python3 -m pytest tests/test_cli.py -x -q` |
| **Full suite command** | `python3 -m pytest tests/ -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python3 -m pytest tests/test_cli.py -x -q`
- **After every plan wave:** Run `python3 -m pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 1 | CONF-01 | unit | `python3 -m pytest tests/test_cli.py -x -q` | Yes | ⬜ pending |
| 14-01-02 | 01 | 1 | CONF-01 | smoke | `python3 -c "import typer, rich"` | N/A | ⬜ pending |
| 14-02-01 | 02 | 1 | CONF-02 | manual | `ls .env.example && grep DATABRICKS_TOKEN .env.example` | No — Wave 0 creates it | ⬜ pending |
| 14-03-01 | 03 | 1 | CONF-03 | unit | `python3 -m pytest tests/test_mcp.py -x -q` | Partial | ⬜ pending |
| 14-03-02 | 03 | 1 | CONF-03 | regression | `python3 -m pytest tests/ -q` | Yes | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `.env.example` — created by CONF-02 task (documentation file, not test infrastructure)
- [ ] Optional: `tests/test_logging_config.py` — stub for CONF-03 log level verification

*Existing infrastructure covers most phase requirements. No new test framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `uv pip install mnemo` in clean venv pulls typer and rich | CONF-01 | Requires clean venv setup | `uv venv /tmp/test-venv && uv pip install -e . && python3 -c "import typer, rich"` |
| `MNEMO_LOG_LEVEL=DEBUG` produces verbose output | CONF-03 | Requires running MCP server | `MNEMO_LOG_LEVEL=DEBUG python3 -m mnemo.mcp.server` and check stderr for DEBUG lines |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
