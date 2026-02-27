# Stack Research: Mnemo Book Management MCP Tools

**Milestone:** Add book management MCP tools (add_book, remove_book, update_book_metadata)
**Researched:** 2026-02-11
**Overall Confidence:** HIGH

## Executive Summary

Adding three management MCP tools to mnemo requires **zero new dependencies**. The existing stack (FastMCP 2.14.4, mcp SDK 1.25.0, SQLite, ChromaDB) already provides everything needed. The key technical findings are:

1. **FastMCP 2.14.4 fully supports MCP tool annotations** via `ToolAnnotations` from `mcp.types` -- verified working on the installed version.
2. **`MNEMO_BOOKS_DIR` configuration** follows the same `os.environ.get()` pattern already used by `EmbeddingConfig.from_env()`.
3. **No schema changes needed** -- the existing SQLite `books` table already has `title`, `authors`, and `isbn` columns.
4. **`BookRepository.update()` is the only new code** at the storage layer -- a straightforward dynamic UPDATE builder.
5. **All three tools wire to existing functions** (`ingest_book()`, `remove_book()`, and the new `BookRepository.update()`).

This is a wiring milestone, not a technology milestone. The research focus is on using existing capabilities correctly.

---

## Stack Additions Required

### New Dependencies: NONE

No new packages are needed. Every capability required for this milestone is already in `pyproject.toml`:

| Capability | Provided By | Already Installed |
|---|---|---|
| MCP tool registration | `fastmcp>=2.14,<3` | Yes (2.14.4) |
| Tool annotations | `mcp` SDK (transitive dep of fastmcp) | Yes (1.25.0) |
| EPUB ingestion | `ebooklib`, `beautifulsoup4`, `lxml` | Yes |
| Embeddings | `httpx`, `tenacity`, `numpy` | Yes |
| Vector storage | `chromadb>=1.0.0` | Yes |
| SQLite metadata | stdlib `sqlite3` | Yes |
| Data models | `pydantic>=2.0` | Yes |
| Environment config | stdlib `os` | Yes |

**Rationale for no additions:** The PRD explicitly states the new tools delegate to existing pipeline functions (`ingest_book()`, `remove_book()`). The only net-new logic is `BookRepository.update()`, which uses plain `sqlite3`. Tool annotations are provided by the `mcp` SDK that FastMCP already depends on.

---

## FastMCP Tool Annotations (Key Finding)

### Verified Working on Installed Version

**FastMCP 2.14.4** with **mcp SDK 1.25.0** fully supports `ToolAnnotations`. This was verified by direct execution on the project's Python environment.

### Import and Usage

```python
from mcp.types import ToolAnnotations
from mnemo.mcp.server import mcp

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_available_books() -> str:
    """List all books in your library."""
    ...
```

### Available Annotation Fields

| Field | Type | Purpose | Default |
|---|---|---|---|
| `title` | `str \| None` | Human-readable title for the tool | `None` |
| `readOnlyHint` | `bool \| None` | Tool does not modify state | `None` |
| `destructiveHint` | `bool \| None` | Tool performs irreversible actions | `None` |
| `idempotentHint` | `bool \| None` | Repeated calls with same args = same effect | `None` |
| `openWorldHint` | `bool \| None` | Tool interacts with external entities | `None` |

**Important:** `destructiveHint` and `idempotentHint` are only meaningful when `readOnlyHint` is false. A read-only tool is by definition neither destructive nor idempotent-sensitive.

### Recommended Annotations per Tool

| Tool | readOnlyHint | destructiveHint | idempotentHint | openWorldHint | Rationale |
|---|---|---|---|---|---|
| `search_books` | `True` | -- | -- | `False` | Read-only search, no external calls |
| `list_available_books` | `True` | -- | -- | `False` | Read-only listing |
| `get_book_info` | `True` | -- | -- | `False` | Read-only lookup |
| **`add_book`** | `False` | `False` | `False` | `False` | Creates state, not destructive (refuses duplicates), NOT idempotent (returns error on repeat without force) |
| **`remove_book`** | `False` | **`True`** | `True` | `False` | Permanently deletes book data. Idempotent: removing already-removed book returns "not found" |
| **`update_book_metadata`** | `False` | `False` | `True` | `False` | Modifies but doesn't destroy. Idempotent: same update = same result |

**Note on existing tools:** The current three search tools (`search_books`, `list_available_books`, `get_book_info`) have no annotations. Consider adding `readOnlyHint=True` to them as part of this milestone for consistency. This is additive and non-breaking.

### Dict Shorthand (Alternative Syntax)

Annotations can also be passed as a plain dict:

```python
@mcp.tool(annotations={"destructiveHint": True, "readOnlyHint": False})
def remove_book(book_id: str) -> str:
    ...
```

Both approaches are verified working. The `ToolAnnotations` import is more explicit and type-safe; the dict is terser. **Recommend `ToolAnnotations` for readability** since this project already uses typed patterns throughout.

### Tags (Bonus Feature)

FastMCP also supports `tags` for tool categorization:

```python
@mcp.tool(tags={"management"})
def add_book(...) -> str:
    ...
```

Tags are optional and useful for client-side filtering. Consider adding `tags={"search"}` to existing tools and `tags={"management"}` to new tools, but this is low-priority polish.

**Confidence:** HIGH -- all annotation behaviors verified by executing Python code against the installed `fastmcp==2.14.4` and `mcp==1.25.0`.

---

## MNEMO_BOOKS_DIR Environment Configuration

### Pattern

Follow the same `os.environ.get()` pattern already established in `src/mnemo/embeddings/config.py`:

```python
import os
from pathlib import Path

def get_books_dir() -> Path | None:
    """Get configured books directory from environment."""
    books_dir = os.environ.get("MNEMO_BOOKS_DIR")
    if books_dir:
        return Path(books_dir)
    return None
```

### Where to Use

1. **Server startup** (`server.py` or `tools.py`): Log the configured path on init (to stderr). Warn if directory does not exist but do NOT crash -- the user may add it later.
2. **`add_book` tool**: Optionally validate that `file_path` is within `MNEMO_BOOKS_DIR` if configured. This is a safety measure, not a hard requirement. The PRD says "optionally restrict paths to this dir."

### No New Dependencies

Standard library `os` and `pathlib` are sufficient. No need for `pydantic-settings` or `python-dotenv` -- the project doesn't use them today and the single env var doesn't justify adding them.

**Confidence:** HIGH -- pattern is already established in the codebase.

---

## BookRepository.update() Implementation

### No Schema Migration Needed

The existing SQLite `books` table already has all required columns:

```sql
CREATE TABLE IF NOT EXISTS books (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,  -- JSON array
    isbn TEXT,
    ...
);
```

### Implementation Approach

Dynamic UPDATE builder using parameterized queries:

```python
def update(
    self,
    book_id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> Book | None:
    """Update book metadata. Returns updated Book or None if not found."""
    fields: list[str] = []
    values: list[str] = []

    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if authors is not None:
        fields.append("authors = ?")
        values.append(json.dumps(authors))
    if isbn is not None:
        fields.append("isbn = ?")
        values.append(isbn)

    if not fields:
        raise ValueError("At least one field must be provided")

    values.append(book_id)
    sql = f"UPDATE books SET {', '.join(fields)} WHERE id = ?"
    cursor = self.conn.execute(sql, values)
    self.conn.commit()

    if cursor.rowcount == 0:
        return None
    return self.get(book_id)
```

**Why not an ORM:** The project uses raw `sqlite3` throughout. Adding SQLAlchemy or similar for one method would be inconsistent and unnecessary.

**Confidence:** HIGH -- follows existing repository patterns exactly.

---

## Sync vs Async Tool Functions

### Current Pattern: Sync Functions

All existing MCP tools in `tools.py` are synchronous:

```python
@mcp.tool
def search_books(query: str, ...) -> str:
    ...
```

FastMCP handles sync functions by running them in a thread pool, which is appropriate for SQLite operations (which use the GIL anyway).

### add_book Concern: Long-Running Ingestion

The `add_book` tool calls `ingest_book()` which:
1. Parses EPUB (fast, ~1s)
2. Chunks content (fast, ~1s)
3. Stores in SQLite (fast, <1s)
4. Optionally embeds via Databricks API (slow, 10-60s depending on book size)

**Recommendation:** Keep sync. FastMCP's thread pool handles this correctly. The MCP STDIO transport is inherently single-client, so there's no concurrency benefit from async. If embedding takes too long, the tool should still complete -- the MCP client (Claude Desktop) will wait.

### FastMCP Context for Progress Reporting (Optional)

FastMCP provides a `Context` object for progress reporting during long operations:

```python
from fastmcp import Context

@mcp.tool
def add_book(file_path: str, ctx: Context, ...) -> str:
    await ctx.report_progress(0.5, 1.0, "Embedding chunks...")
    await ctx.info("Ingestion started for: " + file_path)
```

**Caveat:** `ctx.report_progress()` and `ctx.info()` are async methods, so using them requires the tool function to be `async def`. This would be a pattern change from the existing sync tools.

**Recommendation:** Skip context/progress for this milestone. The tools will return a final result string. Progress reporting can be added later if embedding times are problematic. Keep the sync pattern consistent with existing tools.

**Confidence:** HIGH -- verified Context signatures and sync/async behavior.

---

## Integration Points with Existing Code

### Tool-to-Function Wiring

| New Tool | Delegates To | Module | Notes |
|---|---|---|---|
| `add_book` | `ingest_book()` | `mnemo.ingest` | Existing function, takes `Path`, returns `(Book, int)` |
| `remove_book` | `remove_book()` | `mnemo.ingest` | Existing function, takes `book_id: str`, returns `bool` |
| `update_book_metadata` | `BookRepository.update()` | `mnemo.storage.repository` | **New method** on existing class |

### Lazy Init Pattern

The existing `tools.py` uses lazy initialization for services:

```python
_search_service: SearchService | None = None
_db_connection = None

def _get_book_repo() -> BookRepository:
    global _db_connection
    if _db_connection is None:
        init_db()
        _db_connection = get_connection()
    return BookRepository(_db_connection)
```

The new tools should reuse `_get_book_repo()` for `update_book_metadata`. The `add_book` and `remove_book` tools can call `ingest_book()` and `remove_book()` directly from `mnemo.ingest`, which manage their own connections.

### Return Format

Existing tools return markdown strings. New tools should follow the same convention:
- `add_book`: Return markdown with book ID, title, authors, chunk count
- `remove_book`: Return confirmation message or "not found"
- `update_book_metadata`: Return updated book info (same format as `get_book_info`)

---

## What NOT to Add

| Suggestion | Why Not |
|---|---|
| `pydantic-settings` | Overkill for one env var. `os.environ.get()` is simpler and matches existing pattern. |
| `python-dotenv` | Not needed. MCP server receives env vars from Claude Desktop config. |
| SQLAlchemy / ORM | Project uses raw `sqlite3`. One UPDATE method doesn't justify an ORM. |
| `asyncio` / `aiosqlite` | Existing tools are sync. No concurrency benefit for single-client MCP STDIO. |
| `pytest-asyncio` | Not in current dev deps because tools are sync. Keep it that way. |
| New config file format | `MNEMO_BOOKS_DIR` is a single env var. No YAML/TOML config file needed. |
| Input validation library | Pydantic models already validate data. Tool parameter validation is straightforward string/path checking. |
| Retry logic for add_book | `ingest_book()` already uses `tenacity` for Databricks API retries internally. |

---

## pyproject.toml: No Changes Required

The current `pyproject.toml` dependencies section needs no modifications:

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
    "fastmcp>=2.14,<3",  # <-- provides ToolAnnotations via mcp dep
]
```

The `mcp` SDK (providing `mcp.types.ToolAnnotations`) is a transitive dependency of `fastmcp` and does not need to be listed explicitly.

---

## Sources

### Verified by Direct Execution (HIGH confidence)
- FastMCP 2.14.4 `@mcp.tool` decorator signature -- inspected via `help(mcp.tool)` on installed package
- `mcp.types.ToolAnnotations` class with all 5 fields -- instantiated and verified on `mcp==1.25.0`
- Annotation passing via both `ToolAnnotations` object and plain dict -- tested both patterns
- Sync tool functions work correctly in FastMCP -- confirmed existing pattern

### Official Documentation (HIGH confidence)
- [FastMCP Tools Documentation](https://gofastmcp.com/servers/tools) -- tool decorator API and annotations
- [MCP Protocol Tool Annotations](https://modelcontextprotocol.io/legacy/concepts/tools) -- annotation field definitions
- [FastMCP GitHub](https://github.com/jlowin/fastmcp) -- source of truth for FastMCP 2.x

### PyPI Versions (HIGH confidence)
- [fastmcp 2.14.4](https://pypi.org/project/fastmcp/) -- installed version
- [mcp 1.25.0](https://pypi.org/project/mcp/) -- installed transitive dependency

### Existing Codebase (HIGH confidence)
- `src/mnemo/mcp/tools.py` -- current tool registration pattern
- `src/mnemo/ingest.py` -- `ingest_book()` and `remove_book()` signatures
- `src/mnemo/storage/repository.py` -- `BookRepository` class to extend
- `src/mnemo/embeddings/config.py` -- `os.environ.get()` pattern for env config
- `src/mnemo/storage/database.py` -- SQLite schema (no migration needed)
