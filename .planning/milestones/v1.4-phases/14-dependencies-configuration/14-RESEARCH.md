# Phase 14: Dependencies & Configuration - Research

**Researched:** 2026-03-28
**Domain:** Python packaging (pyproject.toml), environment variable configuration, Python logging
**Confidence:** HIGH

## Summary

Phase 14 is a low-risk, purely additive set of changes: declare two missing direct dependencies, create a `.env.example` documentation file, and make the log level configurable via an environment variable. No behavior changes, no schema changes, no new external dependencies.

The codebase already uses `typer` and `rich` extensively (cli.py imports both at the top level) but neither is declared in `[project.dependencies]` in pyproject.toml. They arrive today as transitive dependencies of `fastmcp`, `chromadb`, and other packages. This works in practice but is fragile — if any transitive path drops them, the CLI breaks silently.

Logging is currently hard-coded to `INFO` level in `mcp/server.py` via `logging.basicConfig()`. The standard Python pattern to make this env-configurable is a one-liner: read `MNEMO_LOG_LEVEL` at startup and pass it to `basicConfig`. All 505 tests pass today; after these changes they must still pass unchanged.

**Primary recommendation:** Three targeted edits — pyproject.toml (add 2 deps), new .env.example file, mcp/server.py (read MNEMO_LOG_LEVEL). No new libraries needed for any of these.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CONF-01 | `typer` and `rich` declared in `[project.dependencies]` in pyproject.toml | Direct edit to pyproject.toml; both already installed, just undeclared |
| CONF-02 | `.env.example` documents all required and optional environment variables | New file listing DATABRICKS_TOKEN, DATABRICKS_HOST, data dir defaults, log level |
| CONF-03 | Log level configurable via `MNEMO_LOG_LEVEL` env var without code changes | Read env var in mcp/server.py before basicConfig call |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Version is defined in `pyproject.toml` (single source of truth). `__init__.py` reads it via `importlib.metadata`.
- Semantic versioning: PATCH for bug fixes/minor changes, MINOR for new features, MAJOR for breaking changes.
- Current version per pyproject.toml: **1.7.0** (CLAUDE.md states 1.4.4, which is stale — pyproject.toml wins).

## Standard Stack

### Core
| Library | Version (installed) | Purpose | Status |
|---------|---------------------|---------|--------|
| typer | 0.24.1 | CLI framework — `app = typer.Typer(...)` in cli.py | Used but UNDECLARED in deps |
| rich | 14.3.3 | Terminal UI — `Console`, `Table`, `Progress` in cli.py | Used but UNDECLARED in deps |

Both libraries are currently pulled in transitively:
- `typer` via: `chromadb` → `huggingface_hub` → `typer` (and others)
- `rich` via: `fastmcp` → `rich`, `typer` → `rich`, `chromadb` → `rich`

Making them explicit direct dependencies (CONF-01) is the correct fix.

### No New Libraries Needed
All three requirements are met with the standard library + already-installed packages:

| Requirement | Mechanism | External Dep Needed? |
|-------------|-----------|----------------------|
| CONF-01 | Edit pyproject.toml `dependencies` list | No |
| CONF-02 | New `.env.example` text file | No |
| CONF-03 | `os.environ.get("MNEMO_LOG_LEVEL", "INFO")` | No |

**Installation (after pyproject.toml edit):**
```bash
uv pip install -e ".[dev]"
```
No new packages will be downloaded — typer and rich are already present in the lock file.

## Architecture Patterns

### CONF-01: Declaring Direct Dependencies

**Current pyproject.toml dependencies block:**
```toml
dependencies = [
    "ebooklib>=0.18",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "tiktoken>=0.5",
    "pydantic>=2.0",
    "httpx>=0.27",
    "tenacity>=8.3",
    "numpy>=1.26",
    "chromadb>=1.0.0",
    "fastmcp>=2.14,<3",
    "isbnlib>=3.10",
]
```

**After fix — add two lines:**
```toml
dependencies = [
    "ebooklib>=0.18",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "tiktoken>=0.5",
    "pydantic>=2.0",
    "httpx>=0.27",
    "tenacity>=8.3",
    "numpy>=1.26",
    "chromadb>=1.0.0",
    "fastmcp>=2.14,<3",
    "isbnlib>=3.10",
    "typer>=0.12",
    "rich>=13.0",
]
```

Version floors: `typer>=0.12` is conservative (0.24.1 is installed; 0.12 introduced the current stable API surface). `rich>=13.0` is conservative (14.x is installed; 13.x introduced `Table` and `Progress` as stable).

**Verification after edit:**
```bash
uv pip install -e . --dry-run  # confirms no new downloads needed
```

### CONF-02: .env.example Pattern

Standard pattern for Python projects. The file is documentation only — it is never loaded by the application directly (Python does not auto-load .env files; the user's shell/direnv handles that).

The file must be checked into git. It must NOT contain real secrets. Add `.env` (not `.env.example`) to `.gitignore` if not already there.

**Complete inventory of env vars used by mnemo:**

| Variable | File | Required | Default | Notes |
|----------|------|----------|---------|-------|
| `DATABRICKS_HOST` | `src/mnemo/embeddings/config.py:21` | Yes (for embeddings) | `""` | e.g. `https://dbc-xxx.cloud.databricks.com` |
| `DATABRICKS_TOKEN` | `src/mnemo/embeddings/config.py:26` | Yes (for embeddings) | `""` | Personal access token |
| `MNEMO_LOG_LEVEL` | `mcp/server.py` (post-CONF-03) | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Note: `DATABRICKS_HTTP_PATH` is referenced in `.envrc` but does NOT appear anywhere in the Python source code — it is not used by mnemo itself. Do not document it in `.env.example` unless investigation reveals otherwise.

Data directory paths (`~/.mnemo/mnemo.db`, `~/.mnemo/chroma`) are hard-coded defaults in `storage/database.py` and `vectors/config.py` — they are not currently env-configurable. Do not list them as env vars (would be misleading). They can be mentioned as commentary.

**Recommended .env.example:**
```bash
# Mnemo Environment Variables
# Copy this file to .env and fill in your values.
# Mnemo does not load .env automatically — use direnv, dotenv, or source it manually.

# ── Databricks Embeddings (required for add/search) ─────────────────────────
# Get token: Databricks workspace → User Settings → Developer → Access tokens
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=your-databricks-personal-access-token

# ── Logging ─────────────────────────────────────────────────────────────────
# Log level for the MCP server. Valid values: DEBUG, INFO, WARNING, ERROR
# Default: INFO
# MNEMO_LOG_LEVEL=INFO

# ── Data Directories (currently hard-coded, not configurable via env) ────────
# SQLite database:  ~/.mnemo/mnemo.db
# ChromaDB vectors: ~/.mnemo/chroma
# These directories are created automatically on first run.
```

### CONF-03: Configurable Log Level Pattern

**Current hard-coded logging in `mcp/server.py`:**
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
```

**After fix — read from env:**
```python
import os

_log_level = getattr(logging, os.environ.get("MNEMO_LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
```

`getattr(logging, "DEBUG", logging.INFO)` is the standard safe pattern — it returns the integer constant (e.g., `logging.DEBUG = 10`) or falls back to INFO if an invalid value is provided. No third-party library needed.

**Why only mcp/server.py needs this change:**
- `mcp/server.py` calls `logging.basicConfig()` — this is the single root configuration point for the entire logging subsystem. All module-level `getLogger(__name__)` calls in ingest.py, tools.py, search/service.py, etc. inherit from the root logger.
- The CLI (`cli.py`) does not call `basicConfig` — it delegates output to `rich.Console`, not the logging system.
- `ingest.py` uses `logging.getLogger(__name__)` but does not call `basicConfig`, so it inherits whatever the root is set to.

### Recommended Project Structure (no changes)
```
src/mnemo/
├── __init__.py
├── cli.py            # Uses typer + rich (will be explicitly declared after CONF-01)
├── ingest.py
├── mcp/
│   ├── server.py     # CONF-03: add MNEMO_LOG_LEVEL read here
│   └── tools.py
├── embeddings/
│   └── config.py     # DATABRICKS_HOST/TOKEN (documented in CONF-02)
└── ...
.env.example          # CONF-02: new file
pyproject.toml        # CONF-01: add typer + rich to dependencies
```

### Anti-Patterns to Avoid

- **Don't auto-load .env files in application code:** The `.env.example` is documentation; do not add `python-dotenv` or similar. The `.envrc` already handles env loading via direnv for the developer. Adding auto-loading in the app would change behavior for all users.
- **Don't change the logging format:** The MCP server has a comment "IMPORTANT: Never use print() - corrupts STDIO transport." The logging format and `sys.stderr` handler are intentional — do not alter them.
- **Don't set minimum typer version too high:** The current install is 0.24.1 but the lock file has 0.23.0 — set floor to `>=0.12` to give flexibility while requiring the modern stable API.
- **Don't use `logging.getLevelName()`:** Deprecated in Python 3.4+; `getattr(logging, name)` is the current pattern.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Safe env→log level conversion | Custom string→int mapper | `getattr(logging, name.upper(), logging.INFO)` | Built-in, handles invalid values gracefully |
| Dependency declaration | Nothing — just edit pyproject.toml | Standard pyproject.toml `[project.dependencies]` | PEP 621 standard; uv handles resolution |
| Env var documentation | Custom config parsing system | `.env.example` text file | Convention; no code needed |

## Common Pitfalls

### Pitfall 1: Version Floor Too Conservative
**What goes wrong:** Setting `typer>=0.24.1` (exact installed version) makes the package impossible to install on a machine with a slightly older typer.
**Why it happens:** Developer pins to what they see installed.
**How to avoid:** Set floor to the oldest version that has the required API surface. For typer, `>=0.12` covers all modern usage. For rich, `>=13.0` covers Table/Progress.
**Warning signs:** `uv pip install mnemo` fails with version conflict in CI.

### Pitfall 2: Forgetting `uv.lock` Update
**What goes wrong:** pyproject.toml is edited but uv.lock is not regenerated, causing divergence.
**Why it happens:** Manual edit without running `uv lock`.
**How to avoid:** Run `uv lock` (or `uv pip install -e .`) after editing pyproject.toml.
**Warning signs:** `uv lock --check` exits non-zero.

### Pitfall 3: MNEMO_LOG_LEVEL Silently Ignored for CLI
**What goes wrong:** User sets `MNEMO_LOG_LEVEL=DEBUG` but CLI output doesn't change because the CLI uses `rich.Console`, not the logging system.
**Why it happens:** The logging system and rich Console are separate output paths.
**How to avoid:** Document clearly in .env.example that `MNEMO_LOG_LEVEL` affects the MCP server only, not the CLI's rich output.
**Warning signs:** User confusion; can be addressed with a code comment.

### Pitfall 4: .env.example Committed with Real Secrets
**What goes wrong:** Developer copies their actual token values into .env.example.
**Why it happens:** Working fast, copy-paste from .envrc.
**How to avoid:** Use placeholder values (`your-databricks-personal-access-token`), never real values.
**Warning signs:** Secrets scanner alert in CI.

## Code Examples

### Pattern: Safe log level from env (standard Python)
```python
# Source: Python stdlib logging docs
import logging
import os

_level_name = os.environ.get("MNEMO_LOG_LEVEL", "INFO").upper()
_log_level = getattr(logging, _level_name, logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
```

### Pattern: PEP 621 direct dependencies
```toml
# Source: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
[project]
dependencies = [
    "typer>=0.12",
    "rich>=13.0",
]
```

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | All code | Yes | 3.12 | — |
| uv | Dependency management | Yes | 0.10.12 | pip |
| typer | cli.py (already installed) | Yes | 0.24.1 | — |
| rich | cli.py (already installed) | Yes | 14.3.3 | — |

No missing dependencies. All three CONF requirements are satisfiable with zero new package installs.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python3 -m pytest tests/test_cli.py -x -q` |
| Full suite command | `python3 -m pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CONF-01 | `typer` and `rich` importable after clean install | smoke | `python3 -c "import typer, rich"` (manual) | N/A |
| CONF-01 | CLI commands still work (typer wiring intact) | unit | `python3 -m pytest tests/test_cli.py -x -q` | Yes |
| CONF-02 | `.env.example` file exists and contains required vars | manual | `ls .env.example && grep DATABRICKS_TOKEN .env.example` | No — Wave 0 creates it |
| CONF-03 | `MNEMO_LOG_LEVEL=DEBUG` changes log level in MCP server | unit | `python3 -m pytest tests/test_mcp.py -x -q` | Partial — check if test exists |
| CONF-03 | All 505 existing tests pass unchanged | regression | `python3 -m pytest tests/ -q` | Yes |

**Note on CONF-03 testing:** The MCP server's logging behavior is not currently tested in `tests/test_mcp.py` (tests mock at the tool level). A minimal test that patches `os.environ` and inspects the root logger level would be the correct approach, but given the phase goal ("all existing tests pass unchanged"), it is acceptable to verify manually that `MNEMO_LOG_LEVEL=DEBUG python3 -m mnemo.mcp.server` produces debug output.

### Sampling Rate
- **Per task commit:** `python3 -m pytest tests/test_cli.py -x -q`
- **Per wave merge:** `python3 -m pytest tests/ -q`
- **Phase gate:** All 505 tests green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] No test for CONF-03 log level behavior — acceptable to verify manually given phase scope; optionally add `tests/test_logging_config.py` covering the `getattr(logging, name, INFO)` pattern.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `setup.py` + `requirements.txt` | `pyproject.toml` `[project.dependencies]` | PEP 621 (2021) | Single source of truth; uv native |
| `pip-tools` for locking | `uv lock` | 2024 | Faster, handles workspaces |
| Hard-coded log levels | Env-configurable via `logging.basicConfig` | Always available | Enables debug without deploys |

## Open Questions

1. **Should MNEMO_LOG_LEVEL also control CLI verbosity?**
   - What we know: The CLI uses `rich.Console` for output, not the logging system. The `--verbose` flag on `mnemo add` is separate.
   - What's unclear: Whether users expect `MNEMO_LOG_LEVEL=DEBUG` to affect CLI output.
   - Recommendation: Out of scope for Phase 14 (CONF-03 only specifies "verbose output" in the MCP server context). Document the limitation in `.env.example`.

2. **Should `DATABRICKS_HTTP_PATH` be documented in .env.example?**
   - What we know: It appears in `.envrc` but NOT in any Python source file in `src/mnemo/`. It's not used by the app.
   - What's unclear: Whether it was used historically or is needed by the Databricks client.
   - Recommendation: Do not include it in `.env.example` — it would imply the app reads it, which it doesn't. Confirm with a final `grep -r HTTP_PATH src/` before writing the file.

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/mnemo/cli.py`, `src/mnemo/mcp/server.py`, `src/mnemo/embeddings/config.py`, `pyproject.toml`
- `uv.lock` — confirmed transitive dependency paths for typer and rich
- Python stdlib logging docs (standard pattern for `getattr(logging, name)`)
- PEP 621 — `[project.dependencies]` specification

### Secondary (MEDIUM confidence)
- `python3 -m pip show typer/rich` — confirmed `Required-by` chains
- Live test run: 505 tests pass, confirming baseline

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — direct code inspection, no ambiguity
- Architecture: HIGH — three well-understood patterns (pyproject.toml edit, text file, one-liner env read)
- Pitfalls: HIGH — all verified against actual codebase state

**Research date:** 2026-03-28
**Valid until:** 2026-06-28 (stable domain — Python packaging and logging patterns change slowly)
