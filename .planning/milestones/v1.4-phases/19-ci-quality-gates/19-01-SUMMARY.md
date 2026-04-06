---
phase: 19-ci-quality-gates
plan: "01"
subsystem: ci
tags: [ci, github-actions, pytest, ruff, mypy, coverage]
dependency_graph:
  requires: []
  provides: [ci-pipeline, integration-marker, ci-badge]
  affects: [pyproject.toml, tests/test_embedding_integration.py, .github/workflows/ci.yml, README.md]
tech_stack:
  added: [github-actions, astral-sh/setup-uv@v6, pytest-cov]
  patterns: [parallel-ci-jobs, python-version-matrix, marker-based-test-exclusion]
key_files:
  created:
    - .github/workflows/ci.yml
  modified:
    - pyproject.toml
    - tests/test_embedding_integration.py
    - README.md
    - uv.lock
key_decisions:
  - Two parallel CI jobs (lint + test) for independent failure signals
  - astral-sh/setup-uv@v6 with enable-cache for fast installs
  - Inline commands in CI (not make targets) for transparent logs
  - 80% coverage threshold enforced via --cov-fail-under=80
metrics:
  duration_seconds: 102
  completed_date: "2026-04-06"
  tasks_completed: 2
  files_modified: 5
---

# Phase 19 Plan 01: CI Quality Gates Summary

**One-liner:** GitHub Actions CI pipeline with ruff+mypy lint and pytest matrix (3.11/3.12) with 83% coverage enforced, integration tests excluded via pytest marker.

## What Was Built

A complete GitHub Actions CI pipeline that triggers on push to main and all PRs. Two parallel jobs:

1. **lint** — ruff check, ruff format --check, mypy (all run against src/ and tests/)
2. **test** — pytest matrix across Python 3.11 and 3.12 with coverage gate (80% minimum)

Integration tests (8 tests in test_embedding_integration.py) are excluded from CI via `pytestmark = pytest.mark.integration` and the `-m 'not integration'` pytest flag. The marker is registered in pyproject.toml to avoid unknown marker warnings.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Register integration marker, apply pytestmark, create CI workflow | d4b523d | pyproject.toml, tests/test_embedding_integration.py, .github/workflows/ci.yml |
| 2 | Add CI badge to README and commit uv.lock | 03e39fe | README.md, uv.lock |

## Verification Results

- `pytest --co -q -m 'not integration'`: 517/525 tests collected (8 deselected)
- `pytest -m 'not integration' --cov=mnemo --cov-fail-under=80`: 517 passed, 83.24% coverage — threshold met
- `ruff check src/ tests/`: All checks passed
- `ruff format --check src/ tests/`: 57 files already formatted
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`: YAML valid
- `grep 'badge.svg' README.md`: Match found

## Deviations from Plan

### Known Issue (Not a Deviation)

**Pre-existing mypy errors:** `uv run mypy src/` reports 78 errors across 18 files. These are pre-existing type annotation issues from before this phase (Phase 18 refactor left some union-attr and missing-return-type errors). The CI `lint` job as configured will fail on first push until these are resolved. This is intentional — CI is correctly configured to enforce mypy, and these errors are tracked as tech debt to address in a follow-up.

These errors were verified to be pre-existing by checking that they exist on the main branch before any changes from this plan.

**Logged to deferred-items:** Pre-existing mypy errors (78 errors in 18 files) need cleanup before CI lint job can pass.

## Known Stubs

None — all CI configuration is fully wired.

## Self-Check: PASSED

- .github/workflows/ci.yml: FOUND
- pyproject.toml (markers): FOUND (contains "integration: marks tests requiring external credentials")
- tests/test_embedding_integration.py (pytestmark): FOUND
- README.md (badge): FOUND
- Commits d4b523d and 03e39fe: FOUND
