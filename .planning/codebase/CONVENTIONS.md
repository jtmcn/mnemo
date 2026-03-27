# Code Conventions

**Analysis Date:** 2026-03-26

## Naming Conventions

- **Files:** snake_case (`epub_factory.py`, `search_service.py`)
- **Classes:** PascalCase (`BookRepository`, `SearchService`, `DatabricksEmbedder`)
- **Functions/methods:** snake_case (`ingest_book`, `search_fts`, `embed_book`)
- **Constants:** UPPER_SNAKE (`BOILERPLATE_PENALTY`, `SEMANTIC_FLOOR`, `EMBEDDING_DIM`)
- **Private helpers:** Leading underscore (`_get_search_service`, `_batch_items`, `_google_books_by_isbn`)
- **Test classes:** `Test` prefix (`TestHelp`, `TestServerSetup`)
- **Modules:** snake_case, short names (`store.py`, `hybrid.py`, `client.py`)

## Code Style

- **Line length:** 100 (ruff config)
- **Target:** Python 3.11+
- **Formatter:** ruff format
- **Linter:** ruff (rules: E, F, I, UP, B, SIM)
- **Type checker:** mypy strict mode
- **Import ordering:** stdlib → third-party → local (isort via ruff)
- **Type annotations:** Used throughout, strict mypy compliance
- **`from __future__ import annotations`:** Used in all modules for PEP 604 unions

## Error Handling

- **Exceptions over return codes** — functions raise `ValueError`, `FileNotFoundError`, `sqlite3.IntegrityError`
- **CLI error display** — `console.print(f"[red]Error message[/red]")` for human output, JSON `{"error": ...}` for `--json`
- **Graceful degradation** — Embedding failures don't block ingestion; search falls back to keyword-only
- **Retry with tenacity** — Embedding API uses exponential backoff + jitter on transient HTTP errors (429, 5xx)
- **Validation at boundaries** — File existence, ISBN checksums, env var presence checked at entry points

## Logging

- **Module:** Python stdlib `logging`
- **Logger per module:** `logger = logging.getLogger(__name__)`
- **Levels used:** DEBUG (search scoring, chunk details), WARNING (missing data, API failures), INFO (ingestion progress)
- **MCP constraint:** All logging to stderr (stdout reserved for STDIO protocol)
- **No structured logging** — plain format strings

## Documentation

- **Docstring style:** Google-style with Args/Returns/Raises sections
- **Module docstrings:** Present in all modules, describe purpose and key behaviors
- **Class docstrings:** Describe responsibility and important implementation details
- **Inline comments:** Minimal, used for non-obvious logic (e.g., normalization, regex patterns)
- **Type annotations:** Serve as primary documentation for function signatures

## Common Patterns

### Lazy Imports
Heavy dependencies imported inside functions to avoid import-time costs:
```python
def embed_book(...):
    from mnemo.embeddings import DatabricksEmbedder  # lazy
```

### Repository Pattern
Database access through repository classes, not raw SQL:
```python
repo = BookRepository(conn)
book = repo.add(book)
```

### Dual Output (CLI)
All CLI commands support `--json` flag:
```python
if json_output:
    print(json.dumps(data))
else:
    console.print(rich_table)
```

### Pydantic Models
Core data structures use Pydantic with computed fields:
```python
class Book(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:6])
    @computed_field
    def short_title(self) -> str: ...
```

### Global Lazy Singletons (MCP)
MCP tools use module-level singletons initialized on first call:
```python
_search_service: SearchService | None = None
def _get_search_service() -> SearchService:
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service
```

---

*Conventions analysis: 2026-03-26*
