# Testing

**Analysis Date:** 2026-03-26

## Test Framework

- **Runner:** pytest >=8.0
- **Async:** pytest-asyncio >=0.23 with `asyncio_mode = "auto"`
- **Coverage:** pytest-cov >=4.0
- **Mocking:** `unittest.mock` (MagicMock, AsyncMock, patch)
- **CLI testing:** `typer.testing.CliRunner`
- **Assertions:** Plain `assert` statements (no assertion library)

## Test Organization

Tests are in `tests/` at project root, one test file per module:

| Test File | Covers |
|-----------|--------|
| `test_chunker.py` | Chunking logic, token boundaries |
| `test_cli.py` | CLI commands via CliRunner |
| `test_embedding_integration.py` | Databricks API (likely requires credentials) |
| `test_embeddings.py` | Embedder unit tests with mocked HTTP |
| `test_enrich.py` | Metadata enrichment from APIs |
| `test_epub_parser.py` | EPUB parsing and metadata extraction |
| `test_integration.py` | End-to-end ingestion pipeline |
| `test_mcp.py` | MCP tool implementations |
| `test_migration.py` | ChromaDB distance metric migration |
| `test_search.py` | Search service, RRF fusion, filters |
| `test_storage.py` | Repository CRUD, FTS5 search |
| `test_vectors.py` | VectorStore operations |

**No conftest.py** — test fixtures are defined locally or via `epub_factory.py`.

## Test Types

- **Unit tests** — Most tests mock dependencies (DB, APIs, ChromaDB)
- **Integration tests** — `test_integration.py` uses real SQLite (temp paths), real EPUB factory
- **CLI tests** — `test_cli.py` uses Typer's CliRunner for command-level testing
- **MCP tests** — `test_mcp.py` tests tool implementations directly (not via MCP protocol)
- **No e2e tests** — No tests that start the MCP server and communicate over STDIO

## Running Tests

```bash
# All tests
make test

# With coverage
make test-cov

# Specific test file
pytest tests/test_search.py

# Full quality gate (lint + typecheck + test)
make all
```

**pytest config** (from `pyproject.toml`):
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

## Test Coverage

- **Tool:** pytest-cov
- **No coverage enforcement** — no minimum threshold configured
- **Coverage gaps:** `epub/content.py` (764 lines, content classification) appears under-tested relative to complexity

## Fixtures & Helpers

### EPUB Factory (`tests/fixtures/epub_factory.py`)
`create_test_epub()` — Generates valid EPUB files with configurable:
- Title, authors, ISBN, language
- Chapter content (title + HTML body)
- Raw dc:creator strings for testing author parsing edge cases
- Output to temp file or specified path

### Common Test Patterns
- **Temp directories** — Tests create temp SQLite DBs and ChromaDB paths
- **Mock patches** — `@patch("mnemo.module.dependency")` for isolating units
- **Class-based grouping** — Tests organized in classes (`TestHelp`, `TestServerSetup`)
- **Descriptive docstrings** — Most test methods have one-line docstrings

---

*Testing analysis: 2026-03-26*
