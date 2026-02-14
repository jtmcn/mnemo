# Phase 6: Book Lifecycle Tools - Research

**Researched:** 2026-02-13
**Domain:** MCP tool implementation wrapping existing ingest/remove pipeline
**Confidence:** HIGH

## Summary

Phase 6 wraps the existing `ingest_book()` and `remove_book()` functions from `mnemo/ingest.py` as MCP tools. The codebase already has all the heavy lifting done -- EPUB parsing, chunking, embedding, storage, and removal with cascade deletes. The existing MCP tool patterns from Phase 5 (`update_book_metadata`) provide a clear template for implementation.

The primary challenge is the `add_book` tool, which is more complex than previous tools due to: (1) input validation beyond what `ingest.py` currently does (`.epub` extension check), (2) duplicate detection with rich error messages per CONTEXT.md decisions, (3) a 5-minute timeout for the embedding step, (4) cleanup of partial data on failure, and (5) progress reporting via MCP Context (which requires the tool to be `async def`).

**Primary recommendation:** Create two new MCP tools (`add_book`, `remove_book`) following the existing `_impl` function + `@mcp.tool` decorator pattern. Make `add_book` async to enable progress reporting via `ctx.info()`. Wrap the existing `ingest_book()` pipeline with additional validation, timeout handling, and failure cleanup.

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastmcp | >=2.14,<3 | MCP server framework | Already used; provides `@mcp.tool`, `Context` |
| mnemo.ingest | local | `ingest_book()`, `remove_book()` | Existing pipeline -- direct delegation per v1.1 decision |
| mnemo.storage | local | `BookRepository`, `ChunkRepository` | Existing CRUD with cascade deletes |
| mnemo.vectors | local | `VectorStore` | Existing ChromaDB wrapper with `delete_by_book()` |

### Supporting (no new dependencies needed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| hashlib | stdlib | SHA256 file hashing | Duplicate detection (already used in `epub/metadata.py`) |
| pathlib | stdlib | Path validation | `.epub` extension check, existence check |
| signal/threading | stdlib | Timeout implementation | 5-minute timeout for `add_book` |

### No New Dependencies
This phase requires **zero new packages**. Everything needed is already in the project or stdlib.

## Architecture Patterns

### Recommended File Changes
```
src/mnemo/mcp/
├── server.py          # No changes needed
└── tools.py           # Add: _add_book_impl, _remove_book_impl, add_book, remove_book
```

No new files needed. Both tools go in the existing `tools.py` following the established pattern.

### Pattern 1: Implementation Function + Decorated Tool (Existing Pattern)
**What:** Separate testable `_impl` function from the `@mcp.tool` decorated function.
**When to use:** Every MCP tool in this project.
**Why:** The `_impl` functions can be tested directly without MCP infrastructure. The decorated functions are thin wrappers.

```python
# Source: existing tools.py pattern (lines 143-189, 290-312)
def _add_book_impl(
    file_path: str,
    force: bool = False,
) -> str:
    """Add book implementation - see add_book for docs."""
    # ... validation, ingest, error handling ...

@mcp.tool
async def add_book(
    file_path: str,
    force: bool = False,
    ctx: Context = CurrentContext(),
) -> str:
    """Add an EPUB book to your library. ..."""
    await ctx.info(f"Adding book from {file_path}...")
    return _add_book_impl(file_path, force)
```

Note: The `_impl` function stays sync (calls sync `ingest_book()`). The `@mcp.tool` wrapper is async only to use `ctx.info()` for progress logging. FastMCP supports mixing sync and async tools in the same server.

### Pattern 2: Lazy-Initialized Shared Connection (Existing Pattern)
**What:** Global `_db_connection` variable with `_get_book_repo()` lazy init.
**When to use:** For read-only operations (list, get, update).
**Important caveat for add_book/remove_book:** The existing `ingest_book()` and `remove_book()` in `ingest.py` create their own connections internally (they call `init_db()` + `get_connection()` themselves). The MCP tools should NOT pass the shared `_db_connection` to them -- let them manage their own connections as designed.

### Pattern 3: Return Strings for MCP Tools (Existing Pattern)
**What:** All MCP tools return `str` with markdown formatting.
**When to use:** Always. MCP tools communicate via text responses.
**Example success response for add_book:**
```
Added: Python Cookbook by Test Author (abc123) - 42 chunks
```
**Example error response:**
```
Error: Book already exists - "Python Cookbook" by Test Author (ID: abc123). Use force=true to re-index.
```

### Pattern 4: Cache Invalidation After Mutations (Phase 5 Pattern)
**What:** Clear `_search_service._book_cache` after adding or removing books.
**When to use:** After any mutation that affects book metadata or chunk data.
**Source:** Phase 5's `_update_book_metadata_impl` (tools.py line 182-183)

```python
# After successful add or remove
global _search_service
if _search_service is not None:
    _search_service._book_cache.clear()
```

### Anti-Patterns to Avoid
- **Don't create a service layer:** v1.1 decision explicitly says "direct delegation -- MCP tools call ingest.py functions directly"
- **Don't make _impl functions async:** The ingest pipeline is entirely sync (httpx sync client, sqlite3 sync). Making `_impl` async adds complexity with no benefit. Only the `@mcp.tool` wrapper needs `async` for context logging.
- **Don't share DB connections across ingest calls:** `ingest_book()` manages its own connection lifecycle. Passing the shared `_db_connection` would break its internal connection management.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| EPUB parsing/chunking/embedding | Custom pipeline | `ingest_book()` from `mnemo.ingest` | Already handles full pipeline including force re-index |
| Book removal with cascade | Manual multi-table delete | `remove_book()` from `mnemo.ingest` | Already deletes SQLite records + ChromaDB vectors |
| File hashing for dedup | Custom hash logic | `BookRepository.get_by_hash()` | Already exists; `extract_metadata()` computes SHA256 |
| Duplicate detection | Custom dedup logic | `book_repo.get_by_hash()` + `book_repo.find_similar_title()` | Both methods exist in `BookRepository` |
| FTS index cleanup | Manual FTS trigger management | SQLite triggers (ON DELETE CASCADE + FTS triggers) | Already configured in `database.py` schema |

**Key insight:** The entire ingest and removal pipeline already exists and is tested. Phase 6 tools are thin wrappers that add: (1) MCP-specific validation, (2) richer error messages, (3) timeout protection, and (4) progress logging.

## Common Pitfalls

### Pitfall 1: Partial Data on Failed Ingestion
**What goes wrong:** If `ingest_book()` succeeds at storing the book+chunks in SQLite but `embed_book()` fails (API timeout, credential error), the book exists in SQLite but has no vectors. The book appears in `list_available_books` but semantic search won't find it.
**Why it happens:** `ingest_book()` commits to SQLite (line 172: `conn.commit()`) before calling `embed_book()` (line 178). If embedding fails, the SQLite data persists.
**How to avoid:** The CONTEXT.md decision says "clean up everything on failure." The `_add_book_impl` must catch exceptions from `ingest_book(embed=True)` and, on failure, call `remove_book()` to clean up. This is new logic that wraps around the existing pipeline.
**Implementation:**
```python
try:
    book, chunk_count = ingest_book(path, embed=True, force=should_force)
except Exception:
    # Clean up partial data - the book may have been stored before embedding failed
    # Use ingest.remove_book which handles both SQLite and ChromaDB cleanup
    try:
        remove_book(book_id_if_known)  # Need to figure out the book ID
    except Exception:
        pass  # Best effort cleanup
    raise
```
**Warning sign:** A tricky detail -- if `ingest_book` fails during parsing (before `book_repo.add()`), there's nothing to clean up. If it fails during embedding (after `conn.commit()`), we need the book ID to remove it. The book object is created during parsing (line 141), so we may need to parse first, then wrap storage+embedding in the try/except. Alternatively, we can compute the file hash ourselves, check for the book by hash after failure, and remove it.

### Pitfall 2: Timeout Implementation for Sync Code
**What goes wrong:** The 5-minute timeout needs to kill a synchronous operation (`embed_book` makes HTTP calls via httpx sync client with tenacity retries).
**Why it happens:** Python doesn't have a native "timeout this sync function" mechanism. `signal.alarm` only works on the main thread. `threading.Timer` can set a flag but can't interrupt a blocking HTTP call.
**How to avoid:** The simplest approach: run `ingest_book()` in a thread with `concurrent.futures.ThreadPoolExecutor` and use `future.result(timeout=300)`. If it times out, the thread will eventually complete or fail on its own, and we clean up the partial data. Alternatively, since `add_book` can be async, use `asyncio.wait_for(asyncio.to_thread(ingest_book, ...), timeout=300)`.
**Recommendation:** Use `asyncio.to_thread()` + `asyncio.wait_for()` since the `@mcp.tool` function is already async. This is the cleanest approach.

### Pitfall 3: force=true Creates New Book ID (or Same ID?)
**What goes wrong:** CONTEXT.md says "force=true re-index creates a new book ID (delete old, create fresh)." But `ingest_book()` with `force=True` already handles this -- it deletes the old book and re-ingests, and the book ID is derived from content hash + title + author. Same content = same ID. So `force=True` actually produces the same book ID (since content hasn't changed).
**Why it matters:** The CONTEXT.md says "new book ID (delete old, create fresh) -- clean slate." But the existing `ingest_book(force=True)` produces the same ID because `Book.generate_id()` is deterministic. This is actually fine and probably better -- same book should keep same ID.
**How to handle:** Accept the existing behavior. The "clean slate" aspect is still achieved: old book/chunks/vectors are deleted, new ones are created fresh. The ID being the same is a feature, not a bug (existing references to the book ID remain valid). Document this in the tool's response.

### Pitfall 4: Extension Validation Not in ingest_book()
**What goes wrong:** `ingest_book()` validates `epub_path.exists()` but does NOT check `.epub` extension. INGEST-02 requires extension validation.
**Why it matters:** A user could pass a `.txt` file, which `ebooklib.epub.read_epub()` would fail on with an unhelpful error.
**How to avoid:** Add `.epub` extension validation in `_add_book_impl()` before calling `ingest_book()`. This is MCP-layer validation, not a change to `ingest.py`.

### Pitfall 5: Stale _db_connection After remove_book
**What goes wrong:** `remove_book()` in `ingest.py` creates its own connection, commits, and closes it. But the global `_db_connection` in tools.py is a separate connection. After removing a book via the new `remove_book` MCP tool, the `_db_connection` still works (SQLite handles multiple connections fine with WAL mode), but any cached repo objects remain valid.
**Why it's okay:** WAL mode allows concurrent readers. The shared `_db_connection` will see the deletion on next query. Cache invalidation (`_book_cache.clear()`) handles the search cache.

### Pitfall 6: Getting Book Info Before Removal for Response
**What goes wrong:** CONTEXT.md says `remove_book` response includes "deleted book's title, authors, and chunk count." But `ingest.remove_book()` returns `bool` and the data is gone after deletion.
**How to avoid:** Fetch book info BEFORE calling `remove_book()`. Use the shared `_db_connection` and `_get_book_repo()` to get the book details, then call `ingest.remove_book()`.

## Code Examples

### add_book Tool Implementation Skeleton

```python
# Source: derived from existing patterns in tools.py + ingest.py

import asyncio
from pathlib import Path

from fastmcp import Context
from fastmcp.dependencies import CurrentContext


def _add_book_impl(
    file_path: str,
    force: bool = False,
) -> str:
    """Add book implementation."""
    logger.info(f"add_book: file_path={file_path!r}, force={force}")

    # 1. Validate path
    path = Path(file_path)
    if not path.exists():
        return f"Error: File not found: {file_path}"
    if path.suffix.lower() != ".epub":
        return f"Error: Not an EPUB file: {file_path} (expected .epub extension)"

    # 2. Check for duplicate by hash (richer error than ingest_book provides)
    import hashlib
    from mnemo.storage import BookRepository, get_connection, init_db

    init_db()
    conn = get_connection()
    book_repo = BookRepository(conn)

    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    existing = book_repo.get_by_hash(file_hash)
    conn.close()

    if existing and not force:
        authors_str = ", ".join(existing.authors) if existing.authors else "Unknown"
        return (
            f"Error: Book already exists - \"{existing.title}\" "
            f"by {authors_str} (ID: `{existing.id}`). "
            f"Use force=true to re-index."
        )

    # 3. Check for soft duplicate (same title+author) -- warning only
    # (This needs the file to be parsed first to get the title, so
    #  we do it within the ingest flow or skip for simplicity)

    # 4. Ingest with embedding
    from mnemo.ingest import ingest_book, remove_book as pipeline_remove

    try:
        book, chunk_count = ingest_book(path, embed=True, force=force)
    except Exception as e:
        # Clean up partial data
        # Compute what book_id would have been, or look up by hash
        try:
            init_db()
            conn2 = get_connection()
            repo2 = BookRepository(conn2)
            partial = repo2.get_by_hash(file_hash)
            conn2.close()
            if partial:
                pipeline_remove(partial.id)
        except Exception:
            pass  # Best effort cleanup
        return f"Error: Failed to add book: {e}"

    # 5. Invalidate search cache
    global _search_service
    if _search_service is not None:
        _search_service._book_cache.clear()

    # 6. Format success response
    authors_str = ", ".join(book.authors) if book.authors else "Unknown"
    return (
        f"Added: {book.title} by {authors_str} "
        f"(ID: `{book.id}`) - {chunk_count} chunks"
    )


@mcp.tool
async def add_book(
    file_path: str,
    force: bool = False,
    ctx: Context = CurrentContext(),
) -> str:
    """Add an EPUB book to your library.

    Parses the EPUB, chunks content, generates embeddings, and makes
    the book searchable. This may take a few minutes for large books.

    Args:
        file_path: Absolute path to the EPUB file
        force: If true, re-indexes even if the book already exists

    Returns:
        Book details on success, or error message
    """
    await ctx.info(f"Adding book from {file_path}...")
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_add_book_impl, file_path, force),
            timeout=300,  # 5 minutes
        )
    except asyncio.TimeoutError:
        return "Error: Book ingestion timed out after 5 minutes. The book may be too large."
    return result
```

### remove_book Tool Implementation Skeleton

```python
# Source: derived from existing patterns

def _remove_book_impl(book_id: str) -> str:
    """Remove book implementation."""
    logger.info(f"remove_book: book_id={book_id}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    # Fetch book info BEFORE deletion (for response)
    book_repo = _get_book_repo()
    book = book_repo.get(book_id)
    if not book:
        return f"Error: Book not found: {book_id}"

    chunk_repo = ChunkRepository(_db_connection)
    chunk_count = chunk_repo.count_by_book(book_id)

    # Perform deletion via existing pipeline
    from mnemo.ingest import remove_book as pipeline_remove
    pipeline_remove(book_id)

    # Invalidate search cache
    global _search_service
    if _search_service is not None:
        _search_service._book_cache.clear()

    # Format response with deleted book info
    authors_str = ", ".join(book.authors) if book.authors else "Unknown"
    return (
        f"Removed: {book.title} by {authors_str} "
        f"(ID: `{book.id}`) - {chunk_count} chunks deleted"
    )


@mcp.tool
def remove_book(book_id: str) -> str:
    """Remove a book from your library.

    Permanently deletes the book, all its chunks, and search vectors.
    The original EPUB file on disk is not affected.

    Args:
        book_id: 6-character book identifier (from list_available_books)

    Returns:
        Confirmation with deleted book details, or error message
    """
    return _remove_book_impl(book_id)
```

### Soft Duplicate Warning Pattern

```python
# Soft duplicate: title+author match (warning, not blocking)
# BookRepository.find_similar_title() already exists
similar = book_repo.find_similar_title(parsed_title, threshold=0.8)
if similar:
    # Return warning alongside success, don't block
    warning = f"Note: Similar book exists - \"{similar[0].title}\" (ID: {similar[0].id})"
```

The challenge with soft duplicate detection: we need the title from the EPUB, which requires parsing it first. But `ingest_book()` does parsing internally. Options:
1. Pre-parse just metadata with `extract_metadata()` before calling `ingest_book()` (reads the file twice)
2. Skip soft duplicate detection in the MCP tool (keep it simple)
3. Add a title+author check parameter to `ingest_book()` (changes pipeline interface)

**Recommendation:** Option 1 -- pre-parse metadata. `extract_metadata()` is fast (just reads metadata, not content). The double-read is negligible compared to the embedding step. This gives us both the title for soft duplicate warning and the hash for hard duplicate detection in one step.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Sync MCP tools only | Mix sync + async tools | FastMCP 2.x | `add_book` can be async for ctx.info() logging |
| No progress in STDIO | `ctx.info()` sends log messages | MCP spec 2025+ | Clients can show status during long operations |

**Note on progress reporting:** MCP progress notifications (`ctx.report_progress()`) require a `progressToken` from the client. Not all clients send one. `ctx.info()` log messages are simpler and more reliably displayed. Use `ctx.info()` for status updates ("Parsing EPUB...", "Generating embeddings..."), not `ctx.report_progress()`.

## Open Questions

1. **Soft duplicate detection timing**
   - What we know: `find_similar_title()` exists. CONTEXT.md says "soft warning but still allows add."
   - What's unclear: Whether to pre-parse metadata (double file read) or skip soft duplicate detection. The hard duplicate (file hash) is straightforward.
   - Recommendation: Pre-parse with `extract_metadata()` for both hash-based dedup and title similarity check. Negligible overhead.

2. **Thread cleanup on timeout**
   - What we know: `asyncio.wait_for()` cancels the coroutine, but `asyncio.to_thread()` runs in a real thread that can't be interrupted.
   - What's unclear: After a 5-minute timeout, the background thread continues running until the HTTP call completes or fails. This is a resource leak.
   - Recommendation: Accept this as a minor issue. The thread will eventually complete/fail on its own. The MCP tool returns the timeout error immediately. The user can retry. If partial data was stored before timeout, cleanup handles it.

3. **add_book async vs sync tradeoff**
   - What we know: Making `add_book` async enables `ctx.info()` progress logging AND `asyncio.wait_for()` timeout. Both are valuable.
   - What's unclear: Whether Claude Desktop and other MCP clients actually display `ctx.info()` messages during tool execution.
   - Recommendation: Make it async anyway. The timeout benefit alone justifies it. If clients don't show progress, no harm done.

## Sources

### Primary (HIGH confidence)
- Codebase analysis: `src/mnemo/ingest.py` -- existing `ingest_book()` and `remove_book()` functions
- Codebase analysis: `src/mnemo/mcp/tools.py` -- existing tool patterns (4 tools with `_impl` pattern)
- Codebase analysis: `src/mnemo/storage/repository.py` -- `BookRepository` with `get_by_hash()`, `find_similar_title()`, `delete()`, `update()`
- Codebase analysis: `src/mnemo/storage/database.py` -- schema with FK CASCADE and FTS triggers
- Codebase analysis: `src/mnemo/vectors/store.py` -- `VectorStore.delete_by_book()`
- Codebase analysis: `src/mnemo/epub/metadata.py` -- `extract_metadata()` with SHA256 hashing

### Secondary (MEDIUM confidence)
- [FastMCP Context docs](https://gofastmcp.com/servers/context) -- `ctx.info()`, `ctx.report_progress()` require async
- [FastMCP Tools docs](https://gofastmcp.com/servers/tools) -- mix of sync/async tools supported
- [MCP Progress specification](https://modelcontextprotocol.io/specification/2025-03-26/basic/utilities/progress) -- progress notification protocol

### Tertiary (LOW confidence)
- Whether Claude Desktop displays `ctx.info()` messages during tool execution (unverified)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all code examined directly in the codebase, zero new dependencies
- Architecture: HIGH -- follows exact patterns from Phase 5 tools, no novel patterns needed
- Pitfalls: HIGH -- identified from direct code analysis (partial data cleanup, timeout, pre-deletion fetch)
- Progress reporting: MEDIUM -- FastMCP docs confirm API, but client display behavior unverified

**Research date:** 2026-02-13
**Valid until:** 2026-03-13 (stable codebase, no external dependency changes expected)
