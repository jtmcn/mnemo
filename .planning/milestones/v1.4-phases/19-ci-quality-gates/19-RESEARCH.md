# Phase 19: CI & Quality Gates - Research

**Researched:** 2026-04-04
**Domain:** GitHub Actions, Python CI pipelines, uv, pytest-cov, ruff, mypy
**Confidence:** HIGH

## Summary

This is a purely additive infrastructure phase: create `.github/workflows/ci.yml` and add a badge to `README.md`. The project's toolchain (uv, ruff, mypy, pytest-cov) is already fully configured in `pyproject.toml` and `Makefile` — CI simply invokes those existing tools in a hosted runner. The only non-trivial code change is adding `@pytest.mark.integration` to `test_embedding_integration.py` and registering the marker in `pyproject.toml` so CI can run `pytest -m 'not integration'` without warnings.

Coverage without the integration test file is currently 83% (verified 2026-04-04), which is above the 80% floor (D-02). The matrix build targets Python 3.11 and 3.12 (D-01), matching `pyproject.toml` classifiers. The GitHub remote is `joel-eq/mnemo` — this is the exact slug needed for the badge URL.

**Primary recommendation:** Single workflow file using `astral-sh/setup-uv` with built-in caching (`enable-cache: true`), inline commands mirroring the Makefile, Python matrix via `UV_PYTHON`, and `--fail-under=80` on the pytest-cov invocation.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** CI runs tests against Python 3.11 and 3.12 in a matrix build. These match the classifiers in pyproject.toml.
- **D-02:** pytest-cov enforces a minimum 80% coverage threshold. Current coverage is 84% (verified: 83% without integration tests on 2026-04-04), giving headroom. Build fails if coverage drops below 80%.
- **D-03:** Workflow triggers on push to `main` and on all pull requests. No path filters — keep it simple.
- **D-04:** `test_embedding_integration.py` is skipped in CI. Mark it with a pytest marker (e.g., `@pytest.mark.integration`) and exclude that marker in the CI pytest invocation. No Databricks secrets needed in GitHub Actions.

### Claude's Discretion

- Workflow file structure (single file vs multiple jobs)
- Caching strategy for uv/pip dependencies
- Whether to use `make` targets or inline pytest/ruff/mypy commands in the workflow
- Badge style and placement in README.md

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CICD-01 | GitHub Actions workflow runs the full test suite on push and PR | D-03 (triggers), D-04 (integration exclusion), uv CI setup |
| CICD-02 | GitHub Actions workflow runs linting (ruff) and type checking (mypy) | Makefile `check` + `typecheck` targets; inline commands preferred for CI transparency |
| CICD-03 | pytest-cov enforces a minimum coverage threshold (fail the build if below) | D-02 (80% threshold), `--cov-fail-under=80` flag, current 83% verified |
| CICD-04 | CI status badge is added to README.md | Badge URL format: `https://github.com/joel-eq/mnemo/actions/workflows/ci.yml/badge.svg` |
</phase_requirements>

---

## Standard Stack

### Core

| Library / Action | Version | Purpose | Why Standard |
|------------------|---------|---------|--------------|
| `astral-sh/setup-uv` | v6 | Install uv and cache deps in CI | Official uv GitHub Action; built-in cache via `enable-cache: true` |
| `actions/checkout` | v4 | Checkout repository | GitHub standard |
| `pytest` | >=8.0 (already in dev deps) | Test runner | Already declared in pyproject.toml |
| `pytest-cov` | >=4.0 (already in dev deps) | Coverage measurement + fail-under | Already declared; `--cov-fail-under=80` flag |
| `ruff` | >=0.1 (already in dev deps) | Lint + format check | Already declared |
| `mypy` | >=1.8 (already in dev deps) | Static type checking | Already declared |

No new dependencies. All tools are already installed via the project's dev extras.

**Installation command in CI:**
```bash
uv sync --locked --all-extras --dev
```

### Supporting

| Feature | Approach | Notes |
|---------|----------|-------|
| Python matrix | `UV_PYTHON` env var per matrix entry | Cleaner than `setup-python`; uv handles Python install |
| Dependency cache | `astral-sh/setup-uv` with `enable-cache: true` | Keys on `uv.lock` automatically |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `astral-sh/setup-uv` built-in cache | `actions/cache` manual config | Manual cache requires writing the key/restore-keys — no benefit here |
| Inline commands | `make` targets | Inline is more readable in CI logs and avoids requiring make to be installed in the runner |
| Single workflow file | Separate lint/test workflows | Single file is simpler and sufficient for this project's scale |

---

## Architecture Patterns

### Recommended File Structure
```
.github/
└── workflows/
    └── ci.yml         # Single workflow file, two jobs: lint + test
```

### Pattern 1: Single Workflow, Two Jobs (lint + test)

**What:** One workflow file with two independent jobs: `lint` (ruff + mypy) and `test` (pytest matrix). Jobs run in parallel; test failure does not block lint result visibility.

**When to use:** When lint failures and test failures are independent signals (this project).

**Example:**
```yaml
# Source: https://docs.astral.sh/uv/guides/integration/github/
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --locked --all-extras --dev
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/
      - run: uv run mypy src/

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - name: Set up Python
        run: uv python install ${{ matrix.python-version }}
      - run: uv sync --locked --all-extras --dev
      - run: uv run pytest -m 'not integration' --cov=mnemo --cov-report=term-missing --cov-fail-under=80
```

### Pattern 2: pytest Marker for Integration Exclusion

**What:** Register an `integration` marker in `pyproject.toml`, apply `@pytest.mark.integration` to the entire `test_embedding_integration.py` test classes, and use `-m 'not integration'` in CI.

**When to use:** Required here per D-04. Tests that need Databricks credentials must not run in CI.

**Example:**
```toml
# In pyproject.toml [tool.pytest.ini_options]
markers = [
    "integration: marks tests requiring external credentials (deselect with '-m not integration')",
]
```

```python
# In test_embedding_integration.py — add to each class:
import pytest

@pytest.mark.integration
class TestEmbedBook:
    ...
```

**Alternative:** Apply the marker at module level using `pytestmark` (cleaner for a file where all tests should be marked):
```python
import pytest

pytestmark = pytest.mark.integration
```

### Pattern 3: Badge Placement

**What:** Add a badge to the top of `README.md` immediately after the `# Mnemo` heading.

```markdown
# Mnemo

![CI](https://github.com/joel-eq/mnemo/actions/workflows/ci.yml/badge.svg)
```

Source: https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/monitoring-workflows/adding-a-workflow-status-badge

### Anti-Patterns to Avoid

- **`actions/setup-python` + pip:** Redundant when using uv — uv manages Python versions itself via `uv python install`.
- **`make check` / `make test` in workflow:** Works, but inline commands are preferable — they show exact commands in CI logs without requiring make to be installed.
- **`--cov-fail-under` on each matrix job:** Fine to have on both; each Python version is independently validated.
- **Unregistered pytest markers:** Always register custom markers in `pyproject.toml`; unregistered markers emit `PytestUnknownMarkWarning` and can be silently ignored.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| uv caching | Custom `actions/cache` config with manual keys | `astral-sh/setup-uv` with `enable-cache: true` | Official action handles key generation from `uv.lock` automatically |
| Coverage threshold enforcement | Script that parses pytest output | `--cov-fail-under=80` flag | Built into pytest-cov; non-zero exit code on failure |
| Marker-based test exclusion | Separate test directories, conftest skips | `pytestmark = pytest.mark.integration` + `-m 'not integration'` | Standard pytest mechanism, zero overhead |

---

## Common Pitfalls

### Pitfall 1: Coverage Fails Below Threshold Due to Missing Marker
**What goes wrong:** CI runs all 525 tests including the 8 in `test_embedding_integration.py` without the integration marker — then those tests either fail (no Databricks creds) or artificially inflate coverage numbers.
**Why it happens:** The marker is not applied before the workflow file is created.
**How to avoid:** Apply `pytestmark = pytest.mark.integration` to `test_embedding_integration.py` in the same plan step as adding the marker registration to `pyproject.toml`. Verify with `pytest --co -q -m 'not integration'` locally first — should collect 517 tests.
**Warning signs:** CI shows 525 collected tests; Databricks connection errors in CI output.

### Pitfall 2: `uv sync` Fails Due to Missing Lock File
**What goes wrong:** `uv sync --locked` requires a committed `uv.lock` — fails if lock is not present or stale.
**Why it happens:** `uv.lock` is in `git status` as modified (it is modified per the initial git status snapshot). If it's committed as-is, fine. If it's the wrong state, CI fails.
**How to avoid:** Verify `uv.lock` is clean and committed before this phase. Current git status shows `M uv.lock` (modified, not staged) — this must be resolved before the workflow is merged.
**Warning signs:** `error: Lockfile is out of date` in CI.

### Pitfall 3: Unregistered Marker Warning Silently Masking Exclusion
**What goes wrong:** `pytest -m 'not integration'` works even without registration, but emits warnings. More critically, `strict_markers = true` (if ever added) would cause an error.
**Why it happens:** pytest allows unregistered markers by default but warns.
**How to avoid:** Always register the marker in `[tool.pytest.ini_options]` `markers` list. No strict_markers required here.

### Pitfall 4: Matrix Python Install Without `uv python install`
**What goes wrong:** The `UV_PYTHON` env var tells uv which Python to use, but if the runner doesn't have that version and `uv python install` isn't called, uv will attempt to download it (which works but adds latency).
**Why it happens:** Skipping the explicit `uv python install ${{ matrix.python-version }}` step.
**How to avoid:** Add `run: uv python install ${{ matrix.python-version }}` before `uv sync`. Alternatively, `astral-sh/setup-uv` with `python-version: ${{ matrix.python-version }}` handles this automatically.

---

## Code Examples

### Complete ci.yml

```yaml
# Source: https://docs.astral.sh/uv/guides/integration/github/
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --locked --all-extras --dev
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/
      - run: uv run mypy src/

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          python-version: ${{ matrix.python-version }}
      - run: uv sync --locked --all-extras --dev
      - run: uv run pytest -m 'not integration' --cov=mnemo --cov-report=term-missing --cov-fail-under=80
```

### pytestmark module-level pattern

```python
# tests/test_embedding_integration.py (top of file, after imports)
import pytest

pytestmark = pytest.mark.integration
```

### Marker registration in pyproject.toml

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"
filterwarnings = [
    "ignore::bs4.XMLParsedAsHTMLWarning",
]
markers = [
    "integration: marks tests requiring external credentials (deselect with '-m not integration')",
]
```

### README badge line

```markdown
![CI](https://github.com/joel-eq/mnemo/actions/workflows/ci.yml/badge.svg)
```

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | Dependency install in CI | N/A (CI runner) | Installed via `astral-sh/setup-uv` | — |
| Python 3.11 | Matrix build | N/A (CI runner) | Installed by uv in CI | — |
| Python 3.12 | Matrix build | N/A (CI runner) | Installed by uv in CI | — |
| GitHub Actions | Workflow execution | ✓ | Remote `joel-eq/mnemo` confirmed | — |

No missing dependencies with no fallback — this phase only adds workflow files.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest -m 'not integration' -x -q` |
| Full suite command | `uv run pytest -m 'not integration' --cov=mnemo --cov-report=term-missing --cov-fail-under=80` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CICD-01 | Workflow triggers on push/PR and runs tests | smoke | Push a branch, check Actions tab | ❌ Wave 0 (workflow file) |
| CICD-02 | Workflow runs ruff + mypy | smoke | Push a branch, check Actions tab | ❌ Wave 0 (workflow file) |
| CICD-03 | Build fails if coverage < 80% | unit | `uv run pytest -m 'not integration' --cov=mnemo --cov-fail-under=80` | ✅ (existing tests) |
| CICD-04 | Badge visible in README | manual | Open README.md on GitHub after push | ❌ Wave 0 (README change) |

### Sampling Rate

- **Per task commit:** `uv run pytest -m 'not integration' -x -q`
- **Per wave merge:** `uv run pytest -m 'not integration' --cov=mnemo --cov-report=term-missing --cov-fail-under=80`
- **Phase gate:** Full suite green + CI badge green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `.github/workflows/ci.yml` — covers CICD-01, CICD-02, CICD-03
- [ ] `README.md` badge line — covers CICD-04
- [ ] `@pytest.mark.integration` (pytestmark) applied in `tests/test_embedding_integration.py`
- [ ] `markers` registered in `pyproject.toml` `[tool.pytest.ini_options]`

---

## Key Facts for the Planner

| Fact | Value |
|------|-------|
| GitHub remote | `joel-eq/mnemo` |
| Workflow filename | `ci.yml` (used in badge URL) |
| Badge URL | `https://github.com/joel-eq/mnemo/actions/workflows/ci.yml/badge.svg` |
| Integration test file | `tests/test_embedding_integration.py` (8 tests) |
| Tests without integration | 517 collected |
| Current coverage (no integration) | 83% (2026-04-04) |
| Coverage threshold | 80% (`--cov-fail-under=80`) |
| Python targets | 3.11 and 3.12 |
| uv.lock status | Modified (M) in git — must be committed/cleaned before CI runs |
| New files needed | `.github/workflows/ci.yml`, badge line in README.md |
| Files modified | `pyproject.toml` (add markers), `tests/test_embedding_integration.py` (add pytestmark) |

---

## Sources

### Primary (HIGH confidence)

- `astral-sh/setup-uv` GitHub Actions docs — https://docs.astral.sh/uv/guides/integration/github/ — setup-uv action, caching, matrix strategy
- GitHub Actions badge docs — https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/monitoring-workflows/adding-a-workflow-status-badge — badge URL format
- pytest markers docs — https://docs.pytest.org/en/stable/how-to/mark.html — marker registration and `-m` flag
- `/Users/joel/Code/mnemo/pyproject.toml` — dev deps, ruff/mypy/pytest config, Python classifiers
- `/Users/joel/Code/mnemo/Makefile` — existing quality gate commands
- Live pytest run — 83% coverage on 517 tests without integration file (2026-04-04)

### Secondary (MEDIUM confidence)

- GitHub Actions caching docs — https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/caching-dependencies-to-speed-up-workflows — general cache key patterns

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all tools already declared in pyproject.toml; uv GitHub Actions docs consulted directly
- Architecture: HIGH — single workflow pattern is standard; verified via official uv docs
- Pitfalls: HIGH — coverage numbers and test counts verified by running pytest locally

**Research date:** 2026-04-04
**Valid until:** 2026-05-04 (stable tooling — GitHub Actions syntax rarely breaks)
