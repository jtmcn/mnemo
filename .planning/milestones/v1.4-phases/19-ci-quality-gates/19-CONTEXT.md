# Phase 19: CI & Quality Gates - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Automated CI pipeline via GitHub Actions. Every push to main and every PR is validated with linting, type checking, testing, and coverage enforcement. A status badge is added to README.md. No production code changes — this phase is purely additive infrastructure.

</domain>

<decisions>
## Implementation Decisions

### Python Version Matrix
- **D-01:** CI runs tests against Python 3.11 and 3.12 in a matrix build. These match the classifiers in pyproject.toml.

### Coverage Threshold
- **D-02:** pytest-cov enforces a minimum 80% coverage threshold. Current coverage is 84%, giving 4% headroom. Build fails if coverage drops below 80%.

### CI Trigger Rules
- **D-03:** Workflow triggers on push to `main` and on all pull requests. No path filters — keep it simple.

### Credential Handling
- **D-04:** `test_embedding_integration.py` is skipped in CI. Mark it with a pytest marker (e.g., `@pytest.mark.integration`) and exclude that marker in the CI pytest invocation. No Databricks secrets needed in GitHub Actions.

### Claude's Discretion
- Workflow file structure (single file vs multiple jobs)
- Caching strategy for uv/pip dependencies
- Whether to use `make` targets or inline pytest/ruff/mypy commands in the workflow
- Badge style and placement in README.md

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Build Configuration
- `pyproject.toml` — Python version targets, dependencies, dev dependencies, ruff/mypy/pytest config
- `Makefile` — Existing quality gate commands (check, typecheck, test, test-cov)
- `prek.toml` — Pre-commit hook configuration (shows existing local quality gates)

### Requirements
- `.planning/REQUIREMENTS.md` §CI & Quality Gates — CICD-01 through CICD-04 acceptance criteria

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Makefile` targets: `make check` (ruff lint + format check), `make typecheck` (mypy src/), `make test` (pytest), `make test-cov` (pytest --cov=mnemo --cov-report=term-missing)
- `pyproject.toml` already has dev dependencies declared: pytest>=8.0, pytest-asyncio>=0.23, pytest-cov>=4.0, ruff>=0.1, mypy>=1.8
- `prek.toml` pre-commit hooks already run `make all` locally

### Established Patterns
- uv for package management (lockfile committed at `uv.lock`)
- Hatchling build backend
- ruff rules: E, F, I, UP, B, SIM with line-length 100
- mypy strict mode enabled
- pytest with asyncio_mode = "auto"

### Integration Points
- `README.md` — CI badge will be added here (currently no badges)
- `.github/workflows/` — New directory, no existing workflows
- `tests/test_embedding_integration.py` — Needs pytest marker to skip in CI

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 19-ci-quality-gates*
*Context gathered: 2026-04-04*
