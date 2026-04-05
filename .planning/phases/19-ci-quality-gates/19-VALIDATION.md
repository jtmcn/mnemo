---
phase: 19
slug: ci-quality-gates
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-04
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest -m 'not integration' -x -q` |
| **Full suite command** | `uv run pytest -m 'not integration' --cov=mnemo --cov-report=term-missing --cov-fail-under=80` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -m 'not integration' -x -q`
- **After every plan wave:** Run `uv run pytest -m 'not integration' --cov=mnemo --cov-report=term-missing --cov-fail-under=80`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 19-01-01 | 01 | 1 | CICD-04 | manual | `grep 'badge.svg' README.md` | ❌ W0 | ⬜ pending |
| 19-01-02 | 01 | 1 | CICD-01 | smoke | Push branch, check Actions tab | ❌ W0 | ⬜ pending |
| 19-01-03 | 01 | 1 | CICD-02 | smoke | Push branch, check Actions tab | ❌ W0 | ⬜ pending |
| 19-01-04 | 01 | 1 | CICD-03 | unit | `uv run pytest -m 'not integration' --cov=mnemo --cov-fail-under=80` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `.github/workflows/ci.yml` — covers CICD-01, CICD-02, CICD-03
- [ ] `README.md` badge line — covers CICD-04
- [ ] `pytestmark = pytest.mark.integration` applied in `tests/test_embedding_integration.py`
- [ ] `markers` registered in `pyproject.toml` `[tool.pytest.ini_options]`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CI triggers on push/PR | CICD-01 | Requires actual GitHub Actions execution | Push branch, verify Actions tab shows running workflow |
| Ruff/mypy run in CI | CICD-02 | Requires actual CI execution | Check lint job output in Actions tab |
| Badge visible on GitHub | CICD-04 | Badge renders only on GitHub, not locally | Open README.md on GitHub after first CI run |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
