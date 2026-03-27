# Technology Stack

**Analysis Date:** 2026-03-26

## Languages

**Primary:**
- Python 3.11+ (target version in `pyproject.toml` `tool.ruff` and `tool.mypy`; classifiers list 3.11, 3.12)

**Runtime:**
- CPython 3.12 via direnv (`.direnv/python-3.12/` layout)

## Runtime

**Environment:**
- Python 3.12 (managed by direnv with `layout python python3` in `.envrc`)
- Virtual environment at `.direnv/python-3.12/` (direnv-managed, not `.venv/`)

**Package Manager:**
- uv (lockfile: `uv.lock` at 640KB, present and committed)
- Build backend: Hatchling (`pyproject.toml` `[build-system]`)

## Frameworks

**Core:**
- FastMCP >=2.14,<3 - MCP (Model Context Protocol) server framework for Claude integration (`src/mnemo/mcp/server.py`)
- Typer (imported in `src/mnemo/cli.py`) - CLI framework with subcommands
- Rich (imported in `src/mnemo/cli.py`) - Terminal output formatting (tables, spinners, colored text)
- Pydantic >=2.0 - Data validation (declared dependency)

**Testing:**
- pytest >=8.0 - Test runner (config in `pyproject.toml` `[tool.pytest.ini_options]`)
- pytest-asyncio >=0.23 - Async test support (`asyncio_mode = "auto"`)
- pytest-cov >=4.0 - Coverage reporting

**Build/Dev:**
- Hatchling - PEP 517 build backend (`pyproject.toml` `[build-system]`)
- Ruff >=0.1 - Linting and formatting (`pyproject.toml` `[tool.ruff]`)
- mypy >=1.8 - Static type checking, strict mode (`pyproject.toml` `[tool.mypy]`)
- prek - Pre-commit hook runner (`prek.toml`)

## Key Dependencies

**Critical:**
- `ebooklib >=0.18` - EPUB file parsing (`src/mnemo/epub/parser.py`)
- `beautifulsoup4 >=4.12` - HTML content extraction from EPUB chapters
- `lxml >=5.0` - XML/HTML parser backend for BeautifulSoup
- `chromadb >=1.0.0` - Vector database for semantic search (`src/mnemo/vectors/store.py`)
- `httpx >=0.27` - HTTP client for Databricks embedding API and book enrichment APIs (`src/mnemo/embeddings/client.py`, `src/mnemo/epub/enrich.py`)
- `tiktoken >=0.5` - Token counting for chunk sizing (`src/mnemo/chunking/tokenizer.py`)
- `numpy >=1.26` - L2 normalization of embedding vectors (`src/mnemo/vectors/store.py`)
- `tenacity >=8.3` - Retry logic with exponential backoff for API calls (`src/mnemo/embeddings/client.py`)
- `isbnlib >=3.10` - ISBN validation and format conversion (`src/mnemo/epub/enrich.py`)

**Infrastructure:**
- `fastmcp >=2.14,<3` - MCP server over STDIO transport (`src/mnemo/mcp/server.py`)
- `sqlite3` (stdlib) - Relational metadata and FTS5 full-text search (`src/mnemo/storage/database.py`)

## Configuration

**Environment:**
- direnv loads secrets from `$HOME/.config/helios/secrets` (`.envrc`)
- Key env vars: `DATABRICKS_HOST`, `DATABRICKS_TOKEN` (set via `.envrc` from `DATABRICKS_TOKEN_EQ`)
- `DATABRICKS_HTTP_PATH` also exported but used externally
- `.env` file gitignored; no `.env.example` present

**Build:**
- `pyproject.toml` - Single source of truth for project metadata, dependencies, tool config
- `Makefile` - Developer workflow commands (`make lint`, `make format`, `make check`, `make test`, `make test-cov`, `make typecheck`, `make all`)
- `prek.toml` - Pre-commit hooks: trailing whitespace, end-of-file-fixer, and `make all`

**Ruff Configuration:**
- Line length: 100
- Target: Python 3.11
- Lint rules: E (pycodestyle errors), F (pyflakes), I (isort), UP (pyupgrade), B (bugbear), SIM (simplify)

**Mypy Configuration:**
- Strict mode enabled
- `warn_return_any = true`
- `warn_unused_ignores = true`

## Data Storage Paths

- SQLite database: `~/.mnemo/mnemo.db` (default, created automatically)
- ChromaDB vectors: `~/.mnemo/chroma/` (default, created automatically)
- All data is local, no cloud storage

## Platform Requirements

**Development:**
- macOS (primary, based on `.envrc` direnv layout and project structure)
- Python 3.11+ (3.12 used in practice)
- direnv for environment management
- uv for package management
- Access to Databricks workspace for embedding generation

**Production:**
- Runs as a local CLI tool and MCP server (STDIO transport)
- No container, no deployment pipeline, no CI/CD detected
- Installed via `pip install -e .` or `uv pip install -e .`
- Entry point: `mnemo` CLI (`project.scripts` in `pyproject.toml` -> `mnemo.cli:main`)

## Version Management

- Version defined in `pyproject.toml` `[project]` section (currently `1.7.0`)
- `src/mnemo/__init__.py` reads version at runtime via `importlib.metadata.version("mnemo")`
- Semantic versioning: PATCH for fixes, MINOR for features, MAJOR for breaking changes

---

*Stack analysis: 2026-03-26*
