# Phase 19: CI & Quality Gates - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-04
**Phase:** 19-ci-quality-gates
**Areas discussed:** Python version matrix, Coverage threshold, CI trigger rules, Credentials & embedding tests

---

## Python Version Matrix

| Option | Description | Selected |
|--------|-------------|----------|
| 3.11 + 3.12 (Recommended) | Matrix build covering both supported versions from pyproject.toml classifiers | ✓ |
| 3.12 only | Matches dev environment, faster CI | |
| 3.11 + 3.12 + 3.13 | Forward-looking, also tests latest Python | |

**User's choice:** 3.11 + 3.12
**Notes:** Matches pyproject.toml classifiers. Standard approach.

---

## Coverage Threshold

| Option | Description | Selected |
|--------|-------------|----------|
| 80% (Recommended) | 4% headroom below current 84%. Prevents regressions without blocking new work | ✓ |
| 85% | Tight to current level, forces maintaining/improving coverage | |
| 75% | Generous floor, only catches major drops | |

**User's choice:** 80%
**Notes:** Current measured coverage is 84% with 525 tests passing.

---

## CI Trigger Rules

| Option | Description | Selected |
|--------|-------------|----------|
| Push to main + all PRs (Recommended) | Standard setup, every PR validated, main stays green | ✓ |
| All pushes + all PRs | Also runs on feature branch pushes, more CI minutes | |
| PRs only | Only runs when PR opened/updated, direct pushes unvalidated | |

**User's choice:** Push to main + all PRs
**Notes:** No path filters — keeps it simple.

---

## Credentials & Embedding Tests

| Option | Description | Selected |
|--------|-------------|----------|
| Skip embedding tests in CI (Recommended) | Mark with pytest marker and exclude from CI, no secrets needed | ✓ |
| GitHub Actions secrets | Store Databricks creds as repo secrets | |
| Mock embeddings in CI | Replace real calls with mocks in CI | |

**User's choice:** Skip embedding tests in CI
**Notes:** Use pytest marker (e.g., @pytest.mark.integration) and exclude in CI invocation.

---

## Claude's Discretion

- Workflow file structure (single vs multiple jobs)
- Caching strategy for dependencies
- Whether to use Makefile targets or inline commands
- Badge style and placement

## Deferred Ideas

None — discussion stayed within phase scope.
