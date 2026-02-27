# Architecture: MCP Book Management Tools Integration

**Project:** Mnemo v1.1 - Book Management MCP Tools
**Researched:** 2026-02-11
**Confidence:** HIGH (existing codebase examined, FastMCP APIs verified locally)

## Executive Summary

The new `add_book`, `remove_book`, and `update_book_metadata` MCP tools integrate cleanly with the existing architecture. The tools should call `ingest.py` functions directly (not through a new service layer) because the existing functions already orchestrate the full pipeline and the CLI uses them the same way. The one new component is `BookRepository.update()`. Configuration uses `MNEMO_BOOKS_DIR` as a pydantic-settings field or plain `os.environ` lookup, consistent with how `EmbeddingConfig` handles `DATABRICKS_HOST`. Long-running operations (embedding) are handled synchronously since MCP stdio transport is single-threaded per conversation and Claude waits for tool results anyway. Errors use FastMCP's `ToolError` for input validation failures and return error strings for operational failures, matching the existing tool pattern.

---

## Question 1: Direct Call vs. Service Layer

**Recommendation: Call `ingest.py` functions directly. Do NOT introduce a service layer.**

### Evidence from Existing Code

The existing architecture has two calling patterns:

1. **Search tools** use a service layer (`SearchService`) because search requires coordinating multiple backends (FTS5 + ChromaDB + embedder), caching book titles, and merging results with RRF. The service has internal state (`_book_cache`, lazy-initialized connections).

2. **CLI commands** call `ingest.py` functions directly (`ingest_book()`, `remove_book()`). The CLI `add` command (lines 116-124 of `cli.py`) calls `ingest_book(path, embed=True, force=should_force)` without any intermediate layer.

The new MCP tools mirror the CLI commands, not the search tools. They are one-shot operations that run a pipeline end-to-end, not stateful coordinators. Adding a service layer would be empty indirection:

```python
# BAD: Service layer that just proxies
class BookService:
    def add(self, path, force, embed):
        return ingest_book(path, force=force, embed=embed)  # Why?

# GOOD: Direct call, same as CLI
def _add_book_impl(file_path: str, force: bool = False, embed: bool = True) -> str:
    book, chunk_count = ingest_book(Path(file_path), force=force, embed=embed)
    return f"Added {book.title} ({book.id}) - {chunk_count} chunks"
```

### What About `update_book_metadata`?

`update_book_metadata` calls `BookRepository.update()` directly. This is consistent with how `_list_available_books_impl()` and `_get_book_info_impl()` already call `BookRepository` directly via `_get_book_repo()`. No service layer needed.

### When a Service Layer Would Be Warranted

If future tools need to coordinate across multiple operations (e.g., "re-index all books" or "sync metadata from Open Library"), a service layer might make sense then. For now, it would be premature abstraction.

---

## Question 2: MNEMO_BOOKS_DIR Configuration

**Recommendation: Add as an `os.environ.get()` lookup in the tool implementation, validated at first use. Do NOT create a new config class.**

### Evidence from Existing Code

The codebase does NOT use pydantic-settings for centralized configuration. Each component handles its own config:

| Component | Config Pattern | How Env Vars Are Read |
|-----------|---------------|----------------------|
| `EmbeddingConfig` | `@dataclass` with `from_env()` classmethod | `os.environ.get("DATABRICKS_HOST", "")` |
| `VectorConfig` | `@dataclass` with `persist_path` param | No env vars, path passed as argument |
| `database.py` | `get_db_path()` function | Hardcoded `~/.mnemo/mnemo.db` |
| `mcp/tools.py` | Module-level lazy globals | No env vars |

There is no `config.py` or `Settings` class despite what the milestone context suggested. The actual pattern is ad-hoc per component.

### Recommended Pattern

```python
# In mcp/tools.py, alongside existing _get_book_repo() helper

import os
from pathlib import Path

def _get_books_dir() -> Path | None:
    """Get configured books directory from MNEMO_BOOKS_DIR env var."""
    books_dir = os.environ.get("MNEMO_BOOKS_DIR")
    if books_dir is None:
        return None
    path = Path(books_dir)
    if not path.is_dir():
        return None  # Log warning, don't crash
    return path
```

### How `add_book` Uses It

`MNEMO_BOOKS_DIR` serves two purposes per the PRD:

1. **Path resolution** -- Claude can say "add python-cookbook.epub" and the tool resolves it against `MNEMO_BOOKS_DIR`. If the user provides an absolute path, the env var is unused.

2. **Optional path restriction** -- The PRD says "optional: restrict paths to this dir" for security. Start without restriction. If the path is absolute and valid, accept it.

```python
def _resolve_book_path(file_path: str) -> Path:
    """Resolve file_path, checking MNEMO_BOOKS_DIR for relative paths."""
    path = Path(file_path)
    if path.is_absolute():
        return path
    # Try relative to MNEMO_BOOKS_DIR
    books_dir = _get_books_dir()
    if books_dir:
        candidate = books_dir / path
        if candidate.exists():
            return candidate
    return path  # Let ingest_book() raise FileNotFoundError
```

### Why Not a Centralized Config Class

Adding `pydantic-settings` or a central `Settings` class would be scope creep for this milestone. The codebase has no precedent for it, and `MNEMO_BOOKS_DIR` is the only new env var. If a future milestone adds more configuration, centralization can happen then.

---

## Question 3: Long-Running Operations (Embedding)

**Recommendation: Keep tools synchronous. Use `async def` with `await ctx.report_progress()` for progress feedback if feasible, but do NOT background the work or add threading.**

### Why Synchronous Is Correct

1. **MCP stdio transport is request-response.** Claude sends a tool call, waits for the result, then responds to the user. There is no mechanism for Claude to "check back later" on an async job.

2. **The existing CLI is synchronous.** `ingest_book()` blocks until complete (parse, chunk, embed). The CLI shows a Rich spinner but the function itself is synchronous.

3. **Embedding time is bounded.** A typical book produces 500-2000 chunks. At 50 chunks/batch with ~2s per API call, embedding takes 20-80 seconds. This is well within MCP tool timeout expectations (Claude Desktop waits minutes).

### Progress Reporting (Optional Enhancement)

FastMCP 2.14+ supports `Context.report_progress()` (verified locally: `from fastmcp import Context`, method is async). This could give Claude progress feedback during embedding:

```python
from fastmcp import Context

@mcp.tool
async def add_book(file_path: str, force: bool = False, embed: bool = True, ctx: Context = None) -> str:
    """Add an EPUB to the library..."""
    # ingest_book() is synchronous -- call it directly
    # Progress reporting would require refactoring ingest.py to yield progress
    book, chunk_count = ingest_book(Path(file_path), force=force, embed=embed)
    return f"Added {book.title} ({book.id}) - {chunk_count} chunks"
```

**However:** Progress reporting requires the long-running function to yield progress checkpoints. The existing `ingest_book()` and `embed_book()` are monolithic synchronous functions. Refactoring them to accept a progress callback is out of scope for this milestone.

**Recommendation:** Ship synchronous tools first. If users report that Claude Desktop times out or feels unresponsive during ingestion, add progress reporting in a follow-up. This is a UX polish item, not a correctness concern.

### What About `async def` vs `def`?

The existing tools are all `def` (synchronous). FastMCP handles both. Since `ingest_book()` is synchronous and CPU/IO-bound (file parsing, HTTP calls for embeddings), and we are NOT using `report_progress()`, keeping the new tools as plain `def` is simpler and consistent:

```python
@mcp.tool
def add_book(file_path: str, force: bool = False, embed: bool = True) -> str:
    """Add an EPUB to the library..."""
    return _add_book_impl(file_path, force, embed)
```

---

## Question 4: Error Handling Through MCP Tool Responses

**Recommendation: Return error strings for operational failures (matching existing pattern). Use `ToolError` only if future needs require `isError` flag on the MCP response.**

### Evidence from Existing Code

Every existing tool returns error strings, never raises exceptions:

```python
# From tools.py - existing pattern
def _search_books_impl(...) -> str:
    if not query or not query.strip():
        return "Error: Query cannot be empty"
    try:
        ...
    except Exception as e:
        logger.exception("search_books failed")
        return f"Search error: {e}"

def _get_book_info_impl(book_id: str) -> str:
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"
```

This pattern works because Claude treats the return value as text content. "Error: ..." is sufficient for Claude to understand something went wrong and report it to the user.

### ToolError Alternative

FastMCP provides `ToolError` (import: `from fastmcp.exceptions import ToolError`, verified locally). When raised, it sets `isError=True` on the MCP response, which signals to the client that the tool call failed. Some MCP clients use this to display errors differently.

```python
from fastmcp.exceptions import ToolError

def _add_book_impl(file_path: str, ...) -> str:
    if not file_path.endswith(".epub"):
        raise ToolError("File must be an .epub file")
```

### Recommended Approach: Hybrid

For consistency with existing tools AND to benefit from `isError` signaling:

```python
def _add_book_impl(file_path: str, force: bool = False, embed: bool = True) -> str:
    """Implementation for add_book tool."""
    # Input validation -- return error string (consistent with existing tools)
    if not file_path:
        return "Error: file_path is required"

    path = _resolve_book_path(file_path)

    if not path.suffix.lower() == ".epub":
        return f"Error: Not an EPUB file: {path.name}"

    if not path.exists():
        return f"Error: File not found: {path}"

    try:
        book, chunk_count = ingest_book(path, force=force, embed=embed)
        authors = ", ".join(book.authors) if book.authors else "Unknown"
        return (
            f"Added **{book.title}** by {authors}\n\n"
            f"- **ID:** `{book.id}`\n"
            f"- **Chunks:** {chunk_count}\n"
            f"- **Embeddings:** {'generated' if embed else 'skipped'}"
        )
    except ValueError as e:
        # Duplicate book, embedding failures
        return f"Error: {e}"
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("add_book failed")
        return f"Error: Failed to add book: {e}"
```

**Why return strings instead of raising ToolError:** The existing tools all use this pattern. Mixing patterns (some tools raise, some return strings) creates inconsistency. If the project later decides to standardize on `ToolError`, that can be done as a refactor across all tools.

### Error Categories for New Tools

| Tool | Error Condition | Response |
|------|----------------|----------|
| `add_book` | Empty path | `"Error: file_path is required"` |
| `add_book` | Not .epub | `"Error: Not an EPUB file: {name}"` |
| `add_book` | File not found | `"Error: File not found: {path}"` |
| `add_book` | Duplicate (force=false) | `"Error: Book already indexed (id: {id}). Use force=true to re-index."` |
| `add_book` | Embedding credentials missing | `"Error: {message from ValueError}"` |
| `add_book` | Unexpected failure | `"Error: Failed to add book: {details}"` |
| `remove_book` | Invalid book_id format | `"Error: book_id must be a 6-character identifier"` |
| `remove_book` | Book not found | `"Book not found: {book_id}"` |
| `update_book_metadata` | No fields provided | `"Error: At least one of title, authors, or isbn must be provided"` |
| `update_book_metadata` | Book not found | `"Error: Book not found: {book_id}"` |

---

## Integration Map

### Existing Components (No Changes)

| Component | File | Why No Change |
|-----------|------|--------------|
| `ingest_book()` | `src/mnemo/ingest.py` | New tools call it as-is |
| `remove_book()` | `src/mnemo/ingest.py` | New tools call it as-is |
| `embed_book()` | `src/mnemo/ingest.py` | Called by `ingest_book()` internally |
| `EPUBParser` | `src/mnemo/epub/parser.py` | Called by `ingest_book()` internally |
| `Chunker` | `src/mnemo/chunking/chunker.py` | Called by `ingest_book()` internally |
| `SearchService` | `src/mnemo/search/service.py` | Unaffected |
| `mcp/server.py` | `src/mnemo/mcp/server.py` | No changes needed, tools auto-register |
| Database schema | `src/mnemo/storage/database.py` | No schema changes needed |

### Modified Components

| Component | File | Change |
|-----------|------|--------|
| `BookRepository` | `src/mnemo/storage/repository.py` | Add `update()` method |
| MCP tools | `src/mnemo/mcp/tools.py` | Add 3 new tool functions + impls |

### New Components: None

No new files or modules needed. Everything integrates into existing files.

---

## Detailed Data Flows

### add_book Flow

```
Claude calls add_book(file_path="/Users/joel/Books/python-cookbook.epub", embed=true)
    |
    v
_add_book_impl()
    |
    |- _resolve_book_path()  -- resolve relative paths against MNEMO_BOOKS_DIR
    |- Validate .epub extension and file existence
    |
    v
ingest_book(epub_path, force=false, embed=true)   [EXISTING - no changes]
    |
    |- EPUBParser.parse()       -> Book, content_blocks
    |- Duplicate check           -> ValueError if exists
    |- Chunker.chunk()           -> chunks[]
    |- BookRepository.add()      -> SQLite insert
    |- ChunkRepository.add_many() -> SQLite insert
    |- embed_book()              -> Databricks API + ChromaDB
    |
    v
Return: "Added Python Cookbook (a3f7c2) - 892 chunks"
```

### remove_book Flow

```
Claude calls remove_book(book_id="a3f7c2")
    |
    v
_remove_book_impl()
    |
    |- Validate book_id format (6 hex chars)
    |
    v
remove_book(book_id)   [EXISTING - no changes]
    |
    |- BookRepository.delete()   -> SQLite cascade delete (book + chunks)
    |- VectorStore.delete_by_book() -> ChromaDB vector cleanup
    |
    v
Return: "Removed a3f7c2 from the library."
```

### update_book_metadata Flow

```
Claude calls update_book_metadata(book_id="a3f7c2", authors=["David Beazley", "Brian K. Jones"])
    |
    v
_update_book_metadata_impl()
    |
    |- Validate at least one field provided
    |- Validate book_id format
    |
    v
BookRepository.update(book_id, authors=["David Beazley", "Brian K. Jones"])   [NEW METHOD]
    |
    |- Build dynamic UPDATE SET clause for provided fields only
    |- Execute SQL UPDATE
    |- Return updated Book or None
    |
    v
Return updated book info (same format as get_book_info)
```

---

## Tool Annotations

The MCP spec supports tool annotations to hint at tool behavior. FastMCP 2.14 supports them via `ToolAnnotations` from `mcp.types` (verified locally).

```python
from mcp.types import ToolAnnotations

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
def add_book(...) -> str: ...

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True))
def remove_book(...) -> str: ...

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True))
def update_book_metadata(...) -> str: ...
```

**Annotation rationale:**
- `add_book`: Not destructive (creates data), not open-world (reads local file only, embedding API is internal). Not idempotent unless `force=True`.
- `remove_book`: Destructive (deletes data). Idempotent (removing an already-removed book returns "not found").
- `update_book_metadata`: Not destructive (updates, doesn't delete). Idempotent (same update applied twice yields same state).

**Note:** The existing search/list/info tools do NOT have annotations. Adding annotations to the new tools only is fine; it is not a breaking change. If desired, annotations can be backfilled on existing tools later.

---

## Lazy Initialization Pattern

The existing tools use a module-level lazy init pattern:

```python
_search_service: SearchService | None = None
_db_connection = None

def _get_search_service() -> SearchService:
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service
```

The new management tools reuse the existing `_get_book_repo()` helper for `update_book_metadata`, and call `ingest.py` functions directly for `add_book`/`remove_book` (those functions manage their own connections internally via `init_db()` + `get_connection()`).

**No new lazy initialization needed** -- `ingest_book()` and `remove_book()` already handle their own DB connections.

---

## Build Order

The build order is driven by dependencies and testability:

### Step 1: BookRepository.update() (smallest, no dependencies)

- Add `update()` method to `BookRepository` in `src/mnemo/storage/repository.py`
- Unit tests with temp DB: update title only, authors only, isbn only, all fields, no fields (error), book not found (None)
- **Why first:** `update_book_metadata` tool depends on it, and it is independently testable

### Step 2: MCP Tool Implementations (depends on Step 1)

- Add `_add_book_impl()`, `_remove_book_impl()`, `_update_book_metadata_impl()` to `tools.py`
- Add `_resolve_book_path()` and `_get_books_dir()` helpers
- Register with `@mcp.tool` decorators with annotations
- Unit tests with mocks (same pattern as existing `TestSearchBooksIntegration`)
- **Why second:** Exercises the repository change and wires everything together

### Step 3: Integration Tests (depends on Step 2)

- Full-cycle test: add -> search -> update metadata -> search (title reflected)
- Add duplicate test: add -> add same (error) -> add with force (success)
- Remove test: add -> remove -> list (gone)
- MCP protocol test: verify tool schemas (names, parameters, annotations)
- **Why last:** Validates end-to-end after unit-level confidence

### MNEMO_BOOKS_DIR (integrated into Step 2)

Configuration is just a helper function in `tools.py`, not a separate phase. It ships with the tool implementations.

---

## Patterns to Follow

### Pattern: Implementation + Decorator Separation

Follow the existing pattern exactly:

```python
# 1. Implementation function (testable directly, prefixed with _)
def _add_book_impl(file_path: str, force: bool = False, embed: bool = True) -> str:
    """Implementation - see add_book for docs."""
    ...

# 2. Decorated registration (delegates to implementation)
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def add_book(file_path: str, force: bool = False, embed: bool = True) -> str:
    """Add an EPUB book to the library.

    Parses the book, chunks content, and generates embeddings for search.

    Args:
        file_path: Path to the .epub file (absolute, or relative to MNEMO_BOOKS_DIR)
        force: Re-index if the book already exists (default: false)
        embed: Generate search embeddings after indexing (default: true)

    Returns:
        Summary of the added book, or error message
    """
    return _add_book_impl(file_path, force, embed)
```

This pattern allows tests to call `_add_book_impl()` directly without going through MCP transport.

### Pattern: Consistent Error Response Format

All error messages start with `"Error: "` prefix. This is the established convention in the codebase (checked: `_search_books_impl`, `_get_book_info_impl`, `_list_available_books_impl` all use this).

### Pattern: Markdown-Formatted Success Responses

Success responses use markdown formatting that Claude can relay directly:

```python
return (
    f"Added **{book.title}** by {authors}\n\n"
    f"- **ID:** `{book.id}`\n"
    f"- **Chunks:** {chunk_count}\n"
    f"- **Embeddings:** {'generated' if embed else 'skipped'}"
)
```

---

## Anti-Patterns to Avoid

### Anti-Pattern: New Service Layer for Simple Delegation

**What:** Creating a `BookManagementService` class that wraps `ingest.py` functions
**Why bad:** Empty indirection. The CLI calls `ingest.py` directly; MCP tools should too.
**Instead:** Direct calls to `ingest_book()` and `remove_book()`

### Anti-Pattern: Async for CPU/IO-Bound Work Without Progress

**What:** Making tools `async def` when the underlying work is synchronous
**Why bad:** Adds complexity (event loop, potential blocking of event loop) without benefit. `ingest_book()` calls the Databricks API synchronously.
**Instead:** Keep tools as `def` (synchronous), matching existing tools

### Anti-Pattern: Silent Failure on MNEMO_BOOKS_DIR

**What:** Silently ignoring invalid `MNEMO_BOOKS_DIR` and proceeding with no path resolution
**Why bad:** User thinks they configured it but relative paths fail mysteriously
**Instead:** Log a warning at tool registration time if `MNEMO_BOOKS_DIR` is set but not a valid directory

### Anti-Pattern: Modifying ingest.py for MCP Concerns

**What:** Adding progress callbacks, MCP-specific error types, or formatting to `ingest.py`
**Why bad:** `ingest.py` is shared with CLI. MCP-specific concerns belong in `tools.py`.
**Instead:** All MCP-specific logic (path resolution, formatting, error wrapping) lives in `tools.py`

---

## Sources

- Existing codebase: `src/mnemo/mcp/tools.py`, `src/mnemo/ingest.py`, `src/mnemo/storage/repository.py`, `src/mnemo/cli.py`, `src/mnemo/mcp/server.py`
- PRD: `docs/prd-ebook-management.md`
- [FastMCP Tools Documentation](https://gofastmcp.com/servers/tools) -- tool annotations, ToolError
- [FastMCP Progress Reporting](https://gofastmcp.com/servers/progress) -- Context.report_progress()
- [FastMCP Context](https://gofastmcp.com/python-sdk/fastmcp-server-context) -- Context injection
- [MCP Error Handling Best Practices](https://mcpcat.io/guides/error-handling-custom-mcp-servers/) -- isError flag, ToolError patterns
- [MCP Tool Annotations](https://blog.marcnuri.com/mcp-tool-annotations-introduction) -- readOnlyHint, destructiveHint spec
- Local verification: `from fastmcp.exceptions import ToolError` (OK), `from mcp.types import ToolAnnotations` (OK), `from fastmcp import Context` (OK), all on FastMCP 2.14.4
