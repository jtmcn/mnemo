# Pitfalls: Adding Management Tools to Mnemo MCP Server

**Domain:** Adding mutation/management MCP tools to an existing read-only MCP server
**Researched:** 2026-02-11
**Context:** Mnemo v1.0 has 3 read-only tools. Adding `add_book`, `remove_book`, `update_book_metadata`.
**Overall confidence:** HIGH (based on codebase analysis, MCP specification, and verified sources)

---

## Critical Pitfalls

Mistakes that cause security vulnerabilities, data loss, or require rewrites.

---

### 1. Path Traversal via `add_book` file_path Parameter

**What goes wrong:** The `add_book` tool accepts an absolute `file_path` from the LLM. Without validation against `MNEMO_BOOKS_DIR`, an attacker (or a confused LLM) can pass paths like `/etc/passwd`, `../../sensitive/file.epub`, or symlinks pointing outside the allowed directory. Even though `EPUBParser` will likely fail on non-EPUB files, the server still attempts to open and read arbitrary filesystem paths, which is a security violation.

**Why it matters for mnemo specifically:** The PRD explicitly says `MNEMO_BOOKS_DIR` restricts file access. The existing `ingest_book()` in `ingest.py` (line 129) only checks `epub_path.exists()` and does NOT validate against any base directory. The MCP tool layer must add this validation.

**Warning signs:**
- `add_book` works with any absolute path, not just paths under `MNEMO_BOOKS_DIR`
- No test verifies that paths outside the configured directory are rejected
- Path validation uses string prefix checking (`str.startswith()`) instead of resolved path comparison

**Prevention:**
```python
from pathlib import Path

def _validate_path(file_path: str, books_dir: str) -> Path:
    """Validate file_path is under MNEMO_BOOKS_DIR and is a real .epub file."""
    books_base = Path(books_dir).resolve(strict=True)
    target = Path(file_path).resolve(strict=True)  # Resolves symlinks

    if not target.is_relative_to(books_base):
        raise ValueError(
            f"Path {file_path} is outside configured books directory"
        )
    if target.suffix.lower() != ".epub":
        raise ValueError(f"Not an EPUB file: {file_path}")
    return target
```

Key details:
- Use `Path.resolve(strict=True)` to follow symlinks AND verify the path exists
- Use `Path.is_relative_to()` (Python 3.9+) instead of string prefix matching
- Resolve BOTH the base directory AND the target path before comparison
- Validate BEFORE passing to `ingest_book()`, not inside it

**Which phase should address it:** Phase 2 (MCP tool implementations) or Phase 3 (environment config). The validation function must be implemented BEFORE `add_book` is wired up. Do not defer to a later phase.

**Confidence:** HIGH -- This is a well-documented MCP vulnerability pattern. Snyk published a specific article on [path traversal in MCP server function handlers](https://snyk.io/articles/preventing-path-traversal-vulnerabilities-in-mcp-server-function-handlers/). The [Anthropic MCP Git Server CVE](https://thehackernews.com/2026/01/three-flaws-in-anthropic-mcp-git-server.html) demonstrated real-world exploitation of path traversal in MCP servers (January 2026).

---

### 2. `add_book` Embedding Timeout Kills the MCP Connection

**What goes wrong:** `add_book` with `embed=True` (the default) calls `ingest_book()` which calls `embed_book()`. For a large technical book (500+ chunks at 50/batch), embedding takes 30-120+ seconds over the Databricks API. MCP clients have timeout limits -- Claude Desktop and many clients default to 60 seconds. The tool call times out, the client thinks the server is hung, and the connection may be torn down. Worse: the book is partially ingested (SQLite committed at line 172 of `ingest.py`) but embedding is incomplete or lost.

**Why it matters for mnemo specifically:** Looking at `ingest.py` lines 169-179, the SQLite commit happens on line 172, THEN embedding starts on line 177. If the MCP connection drops mid-embedding, the book is in SQLite with chunks but has no vectors in ChromaDB. Searches on that book will return FTS results but no semantic results -- a confusing partial state.

**Warning signs:**
- `add_book` works in tests (small fixtures) but fails with real books in Claude Desktop
- Books appear in `list_available_books` but `search_books` returns poor results for them
- Intermittent "request timeout" errors from the MCP client

**Prevention strategy -- two options:**

**Option A (Recommended): Two-phase ingestion with progress**
```python
@mcp.tool
async def add_book(file_path: str, force: bool = False, embed: bool = True) -> str:
    # Phase 1: Parse + store (fast, < 5 seconds)
    book, chunk_count = ingest_book(path, embed=False, force=force)

    if not embed:
        return f"Added {book.title} ({book.id}) - {chunk_count} chunks. Embedding skipped."

    # Phase 2: Embed (slow, with progress)
    # Send progress notifications to keep connection alive
    embedded = embed_book(book.id)
    return f"Added {book.title} ({book.id}) - {chunk_count} chunks, {embedded} embedded."
```

**Option B: Default embed=False, separate embed tool**
Add a separate `embed_book` MCP tool. This avoids timeout risk entirely for `add_book` but requires Claude to make two tool calls. This is simpler and more robust.

**Additional defense:** Regardless of approach, handle partial state gracefully. If embedding fails, the book should still be usable for FTS search, and the error message should tell Claude to retry embedding.

**Which phase should address it:** Phase 2 (MCP tool implementations). This is an architectural decision that must be made before implementing `add_book`, not after. The existing `ingest_book()` already supports `embed=False`.

**Confidence:** HIGH -- Multiple MCP timeout issues documented. The [MCPcat timeout guide](https://mcpcat.io/guides/fixing-mcp-error-32001-request-timeout/) documents the 60-second default. The [MCP Inspector issue #880](https://github.com/modelcontextprotocol/inspector/issues/880) confirms progress notifications don't reliably prevent timeouts in all clients as of January 2026.

---

### 3. `remove_book` Cascade Fails Silently on ChromaDB Cleanup

**What goes wrong:** Looking at `ingest.py` `remove_book()` (lines 182-219), the function deletes from SQLite first (line 204), commits (line 205), then attempts ChromaDB cleanup (line 213). If ChromaDB deletion fails (network error, file lock, corrupt index), the SQLite deletion has already been committed. The book is gone from SQLite but orphaned vectors remain in ChromaDB. The function returns `True` (success) because the SQLite delete succeeded.

**Why it matters for mnemo specifically:** The existing `remove_book()` wraps ChromaDB cleanup in a try/except that catches `ImportError` (line 216) but does NOT catch other ChromaDB exceptions. A `chromadb.errors.ChromaError` would propagate up and be caught by the MCP tool's generic `except Exception` handler, but by that point SQLite is already committed.

**Warning signs:**
- ChromaDB disk usage grows over time even after removing books
- `VectorStore.count()` reports vectors for book_ids that no longer exist in SQLite
- Semantic search returns ghost results from deleted books

**Prevention:**
1. Verify ChromaDB cleanup succeeded before reporting success
2. If ChromaDB cleanup fails, report partial success with clear instructions:
   ```
   "Book removed from database, but vector cleanup failed.
   Vectors for book_id {id} remain in ChromaDB. Run embed maintenance to clean up."
   ```
3. Consider wrapping both deletions in a try/finally that logs the orphaned state
4. Add a `verify_consistency()` utility that checks for orphaned vectors

**Do NOT try to make this transactional across SQLite + ChromaDB.** They are separate storage systems. Accept that partial failure is possible and handle it gracefully.

**Which phase should address it:** Phase 2 (MCP tool implementations). When wrapping `remove_book()` in the MCP tool, add error handling around the ChromaDB cleanup step. Consider modifying `ingest.py:remove_book()` to return richer status information.

**Confidence:** HIGH -- Directly observable in the existing code. Lines 198-219 of `ingest.py` show the non-atomic two-phase delete pattern.

---

### 4. Shared Mutable DB Connection in MCP Tool Layer

**What goes wrong:** The current `tools.py` uses a module-level `_db_connection` singleton (line 22). Read-only tools work fine with this pattern because SQLite reads don't conflict. But mutation tools (`add_book` calling `ingest_book()`, `remove_book`) create their OWN connections inside `ingest.py` (lines 134-135, 200-201). This means:

1. The MCP tool layer's `_db_connection` reads stale data after `ingest_book()` writes through a different connection
2. `ingest_book()` calls `conn.close()` on its own connection (line 173) -- this is fine, but the tool layer's `_db_connection` still sees the old state unless it re-queries
3. If `add_book` MCP tool uses `_get_book_repo()` to verify the result after calling `ingest_book()`, it reads from the stale connection

**Why it matters for mnemo specifically:** After calling `ingest_book()`, if `add_book` wants to return the book's info using the existing `_get_book_repo()`, it will use the cached `_db_connection` which has a different SQLite connection handle than the one `ingest_book()` used. With WAL mode (enabled in `database.py` line 103), the read connection MAY see the new data, but this is not guaranteed without a read transaction boundary reset.

**Warning signs:**
- `add_book` returns success but `list_available_books` called immediately after doesn't show the new book
- Tests pass (because they use fresh connections per test) but production fails
- Intermittent "book not found" errors right after adding

**Prevention:**
- Option A: Have mutation tools create fresh connections per call (matching CLI pattern)
- Option B: Refactor to use `ingest_book()` and read the result from its return value, never re-querying through the cached connection
- Option C: After any mutation, invalidate the cached `_db_connection` by setting it to `None`

**Recommended: Option B.** The `ingest_book()` function already returns `(Book, chunk_count)`. The MCP tool should use this return value directly to format the response, not re-query the database.

**Which phase should address it:** Phase 2 (MCP tool implementations). Design the tool implementations to use `ingest_book()` return values directly.

**Confidence:** HIGH -- Directly observable in existing code. The dual-connection pattern is clear: `tools.py` line 38 vs `ingest.py` line 135.

---

## Moderate Pitfalls

Mistakes that cause confusing behavior, test failures, or technical debt.

---

### 5. `update_book_metadata` SQL Injection via Dynamic UPDATE Construction

**What goes wrong:** The PRD specifies `BookRepository.update()` builds a "dynamic UPDATE statement for the provided fields." Dynamic SQL construction is the classic SQL injection vector. If column names or field values are interpolated as strings instead of parameterized, the method is vulnerable.

**Why it matters for mnemo specifically:** The update method must handle any combination of `title`, `authors`, `isbn` being provided or `None`. A naive implementation might do:
```python
# WRONG - SQL injection risk
fields = []
if title: fields.append(f"title = '{title}'")
sql = f"UPDATE books SET {', '.join(fields)} WHERE id = '{book_id}'"
```

**Prevention:**
```python
def update(self, book_id: str, title=None, authors=None, isbn=None):
    fields = []
    params = []
    if title is not None:
        fields.append("title = ?")
        params.append(title)
    if authors is not None:
        fields.append("authors = ?")
        params.append(json.dumps(authors))
    if isbn is not None:
        fields.append("isbn = ?")
        params.append(isbn)

    if not fields:
        raise ValueError("At least one field must be provided")

    params.append(book_id)
    sql = f"UPDATE books SET {', '.join(fields)} WHERE id = ?"
    cursor = self.conn.execute(sql, params)
    self.conn.commit()
    return cursor.rowcount > 0
```

Key: Column names are hardcoded strings (not user input), only values use `?` parameterization. This is safe because the set of allowed columns is fixed at `{title, authors, isbn}`.

**Which phase should address it:** Phase 1 (repository layer). Must be correct from the start.

**Confidence:** HIGH -- Standard secure coding practice. The existing repository code already uses parameterized queries correctly (see `repository.py` lines 45-61).

---

### 6. `update_book_metadata` Silently Does Nothing for Nonexistent Books

**What goes wrong:** A dynamic `UPDATE ... WHERE id = ?` on a nonexistent `book_id` executes without error -- `cursor.rowcount` is simply 0. If the tool returns "Updated book metadata" without checking rowcount, Claude tells the user the update succeeded when it did nothing.

**Why it matters for mnemo specifically:** The PRD says the method should return `None` if the book is not found, but the MCP tool layer must translate this to a clear error message. The existing `_get_book_info_impl` already validates book_id format (line 109 of `tools.py`) but the new `_update_book_metadata_impl` must also validate the book exists.

**Prevention:**
- Check `cursor.rowcount` or re-query the book after update
- Return `None` from the repository method when rowcount is 0
- MCP tool: `if result is None: return "Error: Book not found: {book_id}"`
- Validate `book_id` format (6-char hex) BEFORE attempting the update

**Which phase should address it:** Phase 1 (repository layer) for the return value; Phase 2 (MCP tool) for the user-facing error.

**Confidence:** HIGH -- Standard database pattern. Observable from the existing `BookRepository.delete()` pattern (line 120-121) which correctly checks `rowcount`.

---

### 7. Missing `ToolAnnotations` on New Tools

**What goes wrong:** The new management tools modify state but are registered with bare `@mcp.tool` decorators (like the existing read-only tools). Without `ToolAnnotations`, MCP clients cannot distinguish destructive tools from safe ones. Claude Desktop and other clients cannot surface confirmation prompts for `remove_book`. Worse, all tools look equally safe to the client.

**Why it matters for mnemo specifically:** The PRD explicitly calls out marking `remove_book` with `destructiveHint=True` (section 9). The existing tools should also be annotated with `readOnlyHint=True` for completeness. FastMCP 2.14+ (which mnemo uses, confirmed: `fastmcp>=2.14,<3` in `pyproject.toml`) supports annotations via the `mcp.types.ToolAnnotations` class.

**Prevention:**
```python
from mcp.types import ToolAnnotations

# Existing read-only tools - annotate for clarity
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def search_books(...) -> str: ...

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_available_books() -> str: ...

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_book_info(book_id: str) -> str: ...

# New mutation tools
@mcp.tool(annotations=ToolAnnotations(
    destructiveHint=False,  # add_book creates, doesn't destroy
    idempotentHint=False,   # calling twice with same path and force=False errors
))
def add_book(...) -> str: ...

@mcp.tool(annotations=ToolAnnotations(
    destructiveHint=True,   # permanently deletes data
    idempotentHint=True,    # removing already-removed book is a no-op (returns "not found")
))
def remove_book(...) -> str: ...

@mcp.tool(annotations=ToolAnnotations(
    destructiveHint=False,
    idempotentHint=True,    # setting same values again is a no-op
))
def update_book_metadata(...) -> str: ...
```

**Verified import path:** `from mcp.types import ToolAnnotations` -- confirmed working with the installed `fastmcp==2.14.4` and its `mcp` dependency. The class has fields: `title`, `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`.

**Which phase should address it:** Phase 2 (MCP tool implementations). Apply annotations when registering the new tools. Also backport `readOnlyHint=True` to existing tools in the same phase.

**Confidence:** HIGH -- Verified against installed package: `mcp.types.ToolAnnotations` class confirmed with the exact field names.

---

### 8. `MNEMO_BOOKS_DIR` Not Set or Invalid at Server Startup

**What goes wrong:** The PRD says `MNEMO_BOOKS_DIR` is configured via environment variable in the MCP server config. But the current `server.py` reads no environment variables -- it just creates `FastMCP("mnemo")` and imports tools. If the new `add_book` tool reads `MNEMO_BOOKS_DIR` at call time and it's not set, the tool either crashes or silently skips path validation.

**Why it matters for mnemo specifically:** The PRD says (section 4.2): "Validate the directory exists on server init (warn, don't crash)." This means:
- Read `MNEMO_BOOKS_DIR` at startup, not per-tool-call
- If not set, log a warning but let read-only tools work
- If set but directory doesn't exist, log a warning
- `add_book` must check at call time whether the variable was configured

**Warning signs:**
- `add_book` works in development (env var set) but fails in production (not set)
- Different behavior depending on whether the user configured the env var
- No clear error message explaining WHY `add_book` was rejected

**Prevention:**
```python
# In server.py or a config module:
import os

BOOKS_DIR = os.environ.get("MNEMO_BOOKS_DIR")
if BOOKS_DIR:
    books_path = Path(BOOKS_DIR)
    if not books_path.is_dir():
        logger.warning(f"MNEMO_BOOKS_DIR does not exist: {BOOKS_DIR}")
        BOOKS_DIR = None  # Treat as unconfigured
else:
    logger.info("MNEMO_BOOKS_DIR not set. add_book will accept any path.")
```

Then in the tool:
```python
def _add_book_impl(file_path: str, ...) -> str:
    if BOOKS_DIR:
        validated = _validate_path(file_path, BOOKS_DIR)
    else:
        # No restriction configured -- accept any valid .epub path
        validated = Path(file_path)
        if not validated.exists():
            return f"Error: File not found: {file_path}"
```

**Which phase should address it:** Phase 3 (environment config). But the tool implementations in Phase 2 must be DESIGNED to accept the config, even if Phase 3 wires it up.

**Confidence:** HIGH -- The PRD explicitly specifies this behavior. The current codebase has zero environment variable handling.

---

### 9. Tests Leak State Between Mutation Tool Tests

**What goes wrong:** The existing test pattern in `test_mcp.py` swaps module-level globals (`tools._db_connection`, `tools._search_service`) in `try/finally` blocks. This pattern works for read-only tests but becomes fragile with mutation tools because:

1. Mutation tools call `ingest_book()` which creates its OWN database connection to `~/.mnemo/mnemo.db` (the default path)
2. If a test doesn't pass `db_path` to `ingest_book()`, it writes to the production database
3. Tests that create and remove books may leave behind ChromaDB artifacts in `~/.mnemo/chroma/`

**Why it matters for mnemo specifically:** The existing integration tests (`test_integration.py`) handle this correctly by using `temp_db` fixtures and passing `db_path` to `ingest_book()`. But the MCP tool tests in `test_mcp.py` use global patching. The new mutation tool tests must either:
- Pass temp paths through to the underlying `ingest_book()` / `remove_book()` calls
- Or mock the ingest functions entirely

**Warning signs:**
- Tests pass individually but fail when run as a suite
- Running tests modifies `~/.mnemo/mnemo.db` on the developer's machine
- ChromaDB `~/.mnemo/chroma/` grows with test artifacts
- Flaky tests that depend on execution order

**Prevention:**
```python
# Pattern for mutation MCP tool tests:
class TestAddBookTool:
    @pytest.fixture
    def isolated_tools(self, tmp_path, monkeypatch):
        """Set up isolated DB and ChromaDB for mutation tests."""
        db_path = tmp_path / "test.db"
        chroma_path = tmp_path / "chroma"
        init_db(db_path)
        conn = get_connection(db_path)

        # Patch the tool layer's connection
        monkeypatch.setattr("mnemo.mcp.tools._db_connection", conn)

        # ALSO patch the ingest module's default paths
        monkeypatch.setattr("mnemo.storage.database.get_db_path", lambda: db_path)

        yield {"db_path": db_path, "chroma_path": chroma_path, "conn": conn}
        conn.close()
```

The key insight: you must patch BOTH the tool layer AND the ingest layer, because `ingest_book()` calls `init_db()` and `get_connection()` with `None` (default path).

**Which phase should address it:** Phase 4 (testing). But design the tool implementations in Phase 2 with testability in mind -- consider accepting `db_path` and `chroma_path` parameters or making them configurable.

**Confidence:** HIGH -- Directly observable from comparing `test_mcp.py` global-patching pattern with `ingest.py` default-path pattern.

---

## Minor Pitfalls

Issues that cause annoyance or confusion but are fixable without major rework.

---

### 10. `add_book` Returns Inconsistent Formats vs. Existing Tools

**What goes wrong:** The existing tools return markdown-formatted strings (tables for `list_available_books`, headers for `get_book_info`). If `add_book` returns a different format (plain text, JSON string, or differently structured markdown), Claude's responses become visually inconsistent. The LLM also handles structured responses better when formats are predictable.

**Prevention:** Match the existing format conventions:
- Use markdown headers and bold for labels
- Include the book ID in backticks (`` `a3f7c2` ``)
- Follow the same field ordering as `get_book_info`
- For errors, use the "Error: {message}" prefix (matching existing tools)

Example consistent format:
```python
def _format_add_result(book: Book, chunk_count: int, embedded: int | None) -> str:
    lines = [
        f"## Added: {book.title}",
        "",
        f"**ID:** `{book.id}`",
        f"**Authors:** {', '.join(book.authors) if book.authors else 'Unknown'}",
        f"**Chunks:** {chunk_count}",
    ]
    if embedded is not None:
        lines.append(f"**Embedded:** {embedded}")
    return "\n".join(lines)
```

**Which phase should address it:** Phase 2 (MCP tool implementations).

---

### 11. `update_book_metadata` Allows Empty Strings

**What goes wrong:** The PRD says "at least one of title, authors, isbn must be provided." But it doesn't say what happens with empty values. If someone calls `update_book_metadata(book_id="abc123", title="")`, the book gets an empty title. Similarly, `authors=[]` clears all authors.

**Prevention:**
- Validate that provided values are meaningful, not just non-`None`
- `title` must be non-empty string (matching `Book` model's `min_length=1`)
- `authors` must be non-empty list with non-empty strings
- `isbn` can be `None` (to clear it) but if provided must be non-empty
- Return clear validation errors: "Error: title cannot be empty"

**Which phase should address it:** Phase 1 (repository layer) for data validation, Phase 2 (tool layer) for user-facing messages.

---

### 12. `remove_book` Has No "Are You Sure?" Signal for Claude

**What goes wrong:** `remove_book` immediately deletes. The PRD says "Claude must confirm actions with the user" but this is a Claude-side behavior, not enforced by the tool. If Claude hallucinates or misidentifies a `book_id`, the wrong book gets deleted with no undo.

**Prevention:**
- The `destructiveHint=True` annotation (Pitfall #7) is the primary defense
- Additionally, return the book's title in a confirmation-style response so Claude can verify:
  ```
  "Removed 'Python Cookbook' by David Beazley (abc123) - 892 chunks deleted"
  ```
  This lets the user see WHAT was deleted and catch mistakes
- Consider adding a `get_book_info` call within `_remove_book_impl` before deletion to capture the title for the confirmation message
- Do NOT add a `confirm: bool` parameter -- MCP tools should not have multi-step confirmation flows

**Which phase should address it:** Phase 2 (MCP tool implementations).

---

### 13. `authors` Parameter Type Mismatch Between MCP Schema and SQLite

**What goes wrong:** The `update_book_metadata` tool takes `authors: list[str]`. FastMCP generates JSON Schema from type hints, so the MCP client sends a JSON array. But SQLite stores authors as a JSON string (`json.dumps(authors)`). If the tool layer forgets to serialize or the repository layer double-serializes, you get `'["[\"Author One\"]"]'` in the database.

**Prevention:**
- Repository `update()` must call `json.dumps(authors)` exactly once before storing
- Match the existing pattern in `BookRepository.add()` (line 56): `json.dumps(book.authors)`
- Test round-trip: update authors -> get book -> verify authors list matches
- Be especially careful if using `Book.model_validate()` on the updated row -- Pydantic expects `list[str]`, not a JSON string

**Which phase should address it:** Phase 1 (repository layer) with round-trip tests.

---

## Phase-Specific Warning Summary

| Phase | Pitfall | Severity | Key Action |
|-------|---------|----------|------------|
| Phase 1: Repository Layer | #5 SQL injection in dynamic UPDATE | Moderate | Use parameterized queries with hardcoded column names |
| Phase 1: Repository Layer | #6 Silent no-op on nonexistent book | Moderate | Check `rowcount`, return `None` if 0 |
| Phase 1: Repository Layer | #11 Empty string validation | Minor | Validate values are meaningful, not just non-None |
| Phase 1: Repository Layer | #13 Authors JSON double-serialization | Minor | `json.dumps()` exactly once; test round-trip |
| Phase 2: Tool Implementations | #1 Path traversal in add_book | **Critical** | Resolve + validate against MNEMO_BOOKS_DIR |
| Phase 2: Tool Implementations | #2 Embedding timeout kills MCP | **Critical** | Two-phase ingestion or separate embed tool |
| Phase 2: Tool Implementations | #3 Cascade delete fails silently | **Critical** | Handle ChromaDB cleanup failure gracefully |
| Phase 2: Tool Implementations | #4 Stale DB connection | **Critical** | Use `ingest_book()` return values, not re-query |
| Phase 2: Tool Implementations | #7 Missing ToolAnnotations | Moderate | Add annotations to ALL tools (new and existing) |
| Phase 2: Tool Implementations | #10 Inconsistent output format | Minor | Match existing markdown conventions |
| Phase 2: Tool Implementations | #12 No deletion feedback | Minor | Include book title in removal confirmation |
| Phase 3: Environment Config | #8 MNEMO_BOOKS_DIR not set | Moderate | Read at startup, warn don't crash, validate at call time |
| Phase 4: Testing | #9 Test state leakage | Moderate | Patch both tool layer AND ingest layer default paths |

---

## Pre-Implementation Checklist

Before starting each phase, verify:

**Before Phase 1 (Repository Layer):**
- [ ] `BookRepository.update()` uses `?` parameterization only
- [ ] `update()` returns `None` for nonexistent books (check `rowcount`)
- [ ] Empty string/empty list validation in place
- [ ] `json.dumps(authors)` applied exactly once
- [ ] Round-trip test: update -> get -> verify values match

**Before Phase 2 (Tool Implementations):**
- [ ] Path validation function implemented and tested (symlinks, traversal, non-.epub)
- [ ] Timeout strategy decided: two-phase ingestion or separate embed tool
- [ ] Tool implementations use `ingest_book()` return values, not cached connections
- [ ] `ToolAnnotations` applied to ALL tools (new + existing)
- [ ] Output format matches existing tools' markdown conventions
- [ ] `remove_book` response includes deleted book's title
- [ ] All error paths return "Error: ..." prefix strings

**Before Phase 3 (Environment Config):**
- [ ] `MNEMO_BOOKS_DIR` read at server startup
- [ ] Warning logged if directory doesn't exist (not crash)
- [ ] `add_book` works both with and without `MNEMO_BOOKS_DIR` configured
- [ ] Path validation correctly uses resolved, symlink-followed paths

**Before Phase 4 (Testing):**
- [ ] Test fixtures patch BOTH `tools._db_connection` AND `database.get_db_path`
- [ ] No test writes to `~/.mnemo/` (all use `tmp_path`)
- [ ] Integration tests cover: add -> search -> update -> search -> remove -> search
- [ ] Source `.epub` files verified unmodified after all operations (file hash check)
- [ ] ChromaDB temp directories cleaned up in fixtures

---

## Sources

- [Snyk: Preventing Path Traversal in MCP Servers](https://snyk.io/articles/preventing-path-traversal-vulnerabilities-in-mcp-server-function-handlers/) -- HIGH confidence
- [Snyk: Building Secure MCP Servers](https://snyk.io/articles/building-secure-mcp-servers/) -- HIGH confidence
- [MCPcat: Fix MCP Error -32001 Request Timeout](https://mcpcat.io/guides/fixing-mcp-error-32001-request-timeout/) -- HIGH confidence
- [MCP Inspector: Progress notifications not captured (Issue #880)](https://github.com/modelcontextprotocol/inspector/issues/880) -- HIGH confidence
- [MCP Specification: Tool Annotations](https://modelcontextprotocol.io/legacy/concepts/tools) -- HIGH confidence
- [FastMCP: Tools Documentation](https://gofastmcp.com/servers/tools) -- HIGH confidence
- [FastMCP: Testing Guide](https://gofastmcp.com/patterns/testing) -- MEDIUM confidence
- [MCPcat: Unit Testing MCP Servers](https://mcpcat.io/guides/writing-unit-tests-mcp-servers/) -- MEDIUM confidence
- [Salvatoresecurity: Preventing Directory Traversal in Python](https://salvatoresecurity.com/preventing-directory-traversal-vulnerabilities-in-python/) -- HIGH confidence
- [symlink path validation bypass (GitHub issue)](https://github.com/efforthye/fast-filesystem-mcp/issues/10) -- HIGH confidence
- [HackerNews: Three Flaws in Anthropic MCP Git Server (Jan 2026)](https://thehackernews.com/2026/01/three-flaws-in-anthropic-mcp-git-server.html) -- HIGH confidence
