---
phase: 14-dependencies-configuration
plan: 01
subsystem: dependencies-configuration
tags: [dependencies, configuration, logging, env-vars]
dependency_graph:
  requires: []
  provides: [CONF-01, CONF-02, CONF-03]
  affects: [pyproject.toml, uv.lock, .env.example, src/mnemo/mcp/server.py]
tech_stack:
  added: []
  patterns: [env-configurable-log-level, explicit-direct-deps]
key_files:
  created:
    - .env.example
  modified:
    - pyproject.toml
    - uv.lock
    - src/mnemo/mcp/server.py
decisions:
  - "typer>=0.12 and rich>=13.0 declared as direct deps (version floors cover installed versions 0.24.1 and 14.x)"
  - "MNEMO_LOG_LEVEL uses getattr(logging, name, logging.INFO) fallback pattern — safe for invalid level names"
  - ".env.example excludes DATABRICKS_HTTP_PATH (confirmed absent from all Python source)"
metrics:
  duration_minutes: 8
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
  completed_date: "2026-03-29"
requirements_satisfied: [CONF-01, CONF-02, CONF-03]
---

# Phase 14 Plan 01: Dependencies and Configuration Summary

**One-liner:** Declared typer>=0.12 and rich>=13.0 as explicit direct dependencies, created .env.example documenting all env vars with placeholder values, and added MNEMO_LOG_LEVEL env-var control over MCP server log level using getattr fallback pattern.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Declare typer and rich as direct dependencies | fe43e55 | pyproject.toml, uv.lock |
| 2 | Create .env.example | 4931744 | .env.example |
| 3 | Make MCP server log level configurable | a7bf7b4 | src/mnemo/mcp/server.py |

## What Was Built

### Task 1 — Direct Dependency Declarations (CONF-01)

Added `typer>=0.12` and `rich>=13.0` to `[project.dependencies]` in `pyproject.toml`. These packages were previously arriving via transitive dependencies (chromadb pulls in typer, for example), which is fragile — any dependency that transitively provides them could drop the transitive dep and break mnemo. Making them explicit ensures they're always installed and their minimum versions are enforced.

Ran `uv lock` to regenerate the lock file. All 34 CLI tests pass.

### Task 2 — Environment Variable Documentation (CONF-02)

Created `.env.example` at project root with:
- `DATABRICKS_HOST` and `DATABRICKS_TOKEN` (required for add/search)
- `MNEMO_LOG_LEVEL` (optional, MCP server only, commented-out defaulting to INFO)
- Notes on hard-coded data directories (`~/.mnemo/mnemo.db`, `~/.mnemo/chroma`)
- Explicit note that mnemo does not auto-load `.env` (use direnv/dotenv/source)

Does not include `DATABRICKS_HTTP_PATH` — confirmed absent from all Python source files in `src/mnemo/`.

### Task 3 — Configurable Log Level (CONF-03)

Updated `src/mnemo/mcp/server.py` to:
1. Add `import os`
2. Read `MNEMO_LOG_LEVEL` from environment (default `"INFO"`)
3. Use `getattr(logging, _level_name, logging.INFO)` to convert string to int constant — falls back to INFO for invalid names
4. Pass `_log_level` to `logging.basicConfig(level=_log_level, ...)`

All module-level `getLogger(__name__)` calls throughout mnemo inherit from the root logger configured here, so this single change affects all logging output.

All 505 tests pass unchanged.

## Verification Results

```
grep '"typer>=0.12"' pyproject.toml       -> PASS
grep '"rich>=13.0"' pyproject.toml        -> PASS
test -f .env.example                      -> PASS
grep DATABRICKS_TOKEN .env.example        -> PASS
grep MNEMO_LOG_LEVEL src/mnemo/mcp/server.py -> PASS
python3 -m pytest tests/ -q              -> 505 passed
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all changes are fully wired.

## Self-Check: PASSED

Files verified:
- FOUND: pyproject.toml (contains typer>=0.12 and rich>=13.0)
- FOUND: .env.example (contains DATABRICKS_HOST, DATABRICKS_TOKEN, MNEMO_LOG_LEVEL)
- FOUND: src/mnemo/mcp/server.py (contains import os, MNEMO_LOG_LEVEL, getattr pattern)
- FOUND: uv.lock (regenerated)

Commits verified:
- FOUND: fe43e55 (feat: declare typer and rich as direct dependencies)
- FOUND: 4931744 (chore: add .env.example documenting all environment variables)
- FOUND: a7bf7b4 (feat: make MCP server log level configurable via MNEMO_LOG_LEVEL)
