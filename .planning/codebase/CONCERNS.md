# Concerns & Technical Debt

**Analysis Date:** 2026-08-23

## Known Issues

- **No TODO/FIXME/HACK comments** — Codebase is clean of tracked debt markers
- **`noqa` suppressions** — 12 instances, all justified (import side effects `F401`, default argument `B008`, import ordering `E402`)

## Technical Debt

### Large Files
- `epub/content.py` (764 lines) — Content classification and extraction logic is dense

### Global Mutable State
- MCP lazy singletons (`_search_service`, `_db_connection`) now live in one place, `mcp/_deps.py`, with a `reset()` for tests. Still process-global — fine for single-process STDIO, would complicate multi-instance scenarios

### mypy Not Enforced
- `[tool.mypy] strict = true` in `pyproject.toml`, but CI runs mypy with `continue-on-error: true`. 71 errors remain, dominated by bare `dict`/`list` annotations (`type-arg`) and missing third-party stubs (`import-untyped`)

### CLI/MCP Code Duplication
- CLI commands and MCP tools implement similar logic (add book, search, list). `services/book_service.py` holds the one genuinely shared piece (`validate_book_path`); validation and formatting overlap remains

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
- `books.file_path` stores absolute filesystem paths — exposed via MCP tools and `--json` CLI output

## Missing Capabilities

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

---

*Concerns analysis: 2026-08-23*
