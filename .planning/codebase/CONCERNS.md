# Concerns & Technical Debt

**Analysis Date:** 2026-03-26

## Known Issues

- **No TODO/FIXME/HACK comments** — Codebase is clean of tracked debt markers
- **`noqa` suppressions** — 12 instances, all justified (import side effects `F401`, default argument `B008`, import ordering `E402`)

## Technical Debt

### Large Files
- `mcp/tools.py` (1233 lines) — All MCP tool implementations in a single file. Could benefit from splitting by domain (search tools, book management tools, etc.)
- `epub/content.py` (764 lines) — Content classification and extraction logic is dense

### Global Mutable State
- MCP module uses global singletons (`_search_service`, `_db_connection`) with lazy init. Works for single-process STDIO but would complicate testing or multi-instance scenarios

### Manual Schema Migrations
- `storage/database.py` uses `ALTER TABLE ADD COLUMN` with `try/except` for idempotent migrations. No migration framework, no version tracking — works at current scale but fragile for complex schema changes

### CLI/MCP Code Duplication
- CLI commands and MCP tools implement similar logic (add book, search, list). The MCP tools call implementation functions directly, but there's overlap in validation and formatting logic

## Performance Concerns

### Fuzzy Title Search
- `SearchService` uses `difflib.SequenceMatcher` for fuzzy title matching, which scans all books linearly. Fine for personal library size (<1000 books) but O(n) per search

### Sequential Open Library Requests
- Author resolution in `enrich.py` makes separate HTTP requests per author. Could be parallelized with `asyncio.gather` or batched

### Embedding Batch Size
- Default batch of 50 chunks per API call is conservative. Could be tuned for throughput

### ChromaDB Startup
- `PersistentClient` initialization can be slow on first access with large collections

## Security Considerations

### Credential Management
- Databricks token loaded from `~/.config/helios/secrets` via direnv — not in repo
- No `.env.example` file documenting required variables
- Token passed as HTTP Basic auth, not a header bearer token

### Input Validation
- EPUB file paths validated for existence
- ISBN checksums validated before API calls
- FTS5 queries use parameterized SQL (no injection risk)
- Book IDs are 6-char hex (UUID prefix) — collision possible but unlikely at personal scale

### File Path Exposure
- `books.epub_path` stores absolute filesystem paths — exposed via MCP tools and `--json` CLI output

## Missing Capabilities

### No CI/CD
- No GitHub Actions, no automated testing pipeline
- Quality gate relies on `prek.toml` pre-commit hook running `make all`

### No Coverage Enforcement
- `pytest-cov` is a dependency but no minimum threshold is configured

### No Log Configuration
- Logging level hardcoded; no way to adjust verbosity without code changes (except MCP stderr config)

### No Backup/Export Strategy
- `mnemo export` exports EPUB paths but not the SQLite database or ChromaDB vectors
- Full restore requires re-ingestion from EPUB files

## Dependency Risks

### ChromaDB Version Bound
- `chromadb >=1.0.0` — major version range, may break on future chromadb releases with API changes

### ebooklib Maintenance
- `ebooklib >=0.18` — library has infrequent updates; EPUB3 support may lag

### FastMCP Maturity
- `fastmcp >=2.14,<3` — MCP ecosystem is young; breaking changes possible in v3

### Missing Declared Dependencies
- `typer` and `rich` are imported but not listed in `[project.dependencies]` in pyproject.toml (may be transitive via fastmcp or another dep)

---

*Concerns analysis: 2026-03-26*
