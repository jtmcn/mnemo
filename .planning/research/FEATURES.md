# Feature Landscape: MCP Book Management Tools

**Domain:** MCP resource management tools (add/remove/update) for a personal book library
**Milestone:** manage-books-mcp (subsequent milestone; search tools already exist)
**Researched:** 2026-02-11
**Confidence:** MEDIUM-HIGH

---

## Context

Mnemo already has read-only MCP tools (`search_books`, `get_book_info`, `list_available_books`) and a CLI for book lifecycle management (`mnemo add`, `mnemo remove`). This milestone adds write-capable MCP tools so Claude can manage the library without the user switching to a terminal.

Target tools per the PRD:
- `add_book(file_path, force=false, embed=true)` -- ingest EPUB
- `remove_book(book_id)` -- delete book + chunks + vectors
- `update_book_metadata(book_id, title?, authors?, isbn?)` -- edit SQLite only

---

## Table Stakes

Features users expect for MCP-based resource management. Missing any of these makes the tools feel broken or dangerous.

### 1. Tool Annotations (readOnlyHint, destructiveHint)

**Description:** MCP tool annotations signal behavioral characteristics to clients. Read-only tools should be marked `readOnlyHint=True`. Destructive tools (remove_book) should be marked `destructiveHint=True`. Mutating but non-destructive tools (add_book, update_book_metadata) should be marked with `readOnlyHint=False`.

**Complexity:** Low
- FastMCP 2.14+ supports `ToolAnnotations` via `@mcp.tool(annotations=...)` decorator
- The `mcp.types.ToolAnnotations` class is available with `destructiveHint`, `readOnlyHint`, `idempotentHint`, `openWorldHint` fields (verified in installed version)

**Dependencies:** None beyond existing FastMCP version.

**Why table stakes:** Clients like Claude Desktop use these annotations to decide when to show confirmation prompts. Without `destructiveHint=True` on `remove_book`, the client may auto-execute a deletion without user confirmation. The MCP spec explicitly recommends annotating tools to help clients make better UX decisions.

**Implementation notes:**
- `add_book`: `readOnlyHint=False`, `idempotentHint=False` (creates new records), `openWorldHint=False`
- `remove_book`: `readOnlyHint=False`, `destructiveHint=True`, `idempotentHint=True` (removing an already-removed book is a no-op)
- `update_book_metadata`: `readOnlyHint=False`, `destructiveHint=False`, `idempotentHint=True` (same update = same result)
- Existing read-only tools should also get `readOnlyHint=True` annotations retroactively

**Confidence:** HIGH (verified `mcp.types.ToolAnnotations` fields against installed package)

**Sources:**
- [FastMCP Tools Documentation](https://gofastmcp.com/servers/tools)
- [MCP Specification - Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)

---

### 2. Structured Error Responses (Not Exceptions)

**Description:** MCP tools should catch all exceptions internally and return structured error messages that the LLM can understand and act on. Unhandled exceptions crash the connection; structured errors let the LLM retry or ask the user for help.

**Complexity:** Low
- Existing tools already follow this pattern (try/except returning error strings)
- New tools should match the same convention

**Dependencies:** Existing error handling pattern in `tools.py`.

**Why table stakes:** The MCP ecosystem consensus is clear: tool execution errors should be returned as `CallToolResult` with `isError=True`, not raised as exceptions. Exceptions kill the STDIO transport. Structured errors let Claude say "That book wasn't found, would you like to list available books?" instead of going silent.

**Implementation notes:**
- Catch `FileNotFoundError`, `ValueError`, `sqlite3.IntegrityError` and return descriptive strings
- Include actionable context: "Book not found: abc123. Use list_available_books to see valid IDs."
- Match the existing pattern: `return f"Error: {description}"`
- FastMCP can also surface `isError` through its return type handling, but the current approach of returning error strings works and is consistent

**Confidence:** HIGH (verified against existing codebase pattern and MCP best practice consensus)

**Sources:**
- [Error Handling in MCP Servers - MCPcat](https://mcpcat.io/guides/error-handling-custom-mcp-servers/)
- [MCP Best Practices](https://modelcontextprotocol.info/docs/best-practices/)

---

### 3. Input Validation with Actionable Error Messages

**Description:** Each tool must validate inputs before operating and return messages that tell the LLM exactly what was wrong and how to fix it. File path validation for `add_book` (exists? is .epub? readable?). Book ID validation for `remove_book` and `update_book_metadata` (6-char hex? exists?). At least one field provided for `update_book_metadata`.

**Complexity:** Low
- File existence check: `Path(file_path).exists()`
- Extension check: `.suffix.lower() == ".epub"`
- Book ID format: regex or length check (already exists in `_get_book_info_impl`)
- At least one optional field: simple `if not any([title, authors, isbn])` check

**Dependencies:** Existing validation in `_get_book_info_impl` as pattern reference.

**Why table stakes:** LLMs work best when error messages are specific. "Invalid input" is useless. "File not found: /path/to/book.pdf. Expected an .epub file. Check the path with your filesystem tools." lets Claude self-correct. The PRD already specifies validation behavior; this just needs implementing consistently.

**Implementation notes:**
- `add_book` validation order: (1) path exists, (2) is .epub, (3) check duplicate via file_hash, (4) if duplicate and not force, return error with existing book_id
- `remove_book` validation: (1) book_id format, (2) book exists (already handled by `remove_book()` returning False)
- `update_book_metadata` validation: (1) at least one field provided, (2) book_id exists, (3) field-level validation (non-empty title, non-empty authors list, ISBN format if provided)

**Confidence:** HIGH

---

### 4. Duplicate Detection with Force Override

**Description:** `add_book` must check whether a book with the same file hash already exists. If duplicate found and `force=false`, return an error message that includes the existing book's ID. If `force=true`, re-ingest (delete old + ingest fresh).

**Complexity:** Low
- Already implemented in `ingest_book()` via `book_repo.get_by_hash(book.file_hash)`
- MCP tool just needs to catch `ValueError` from the ingest pipeline and format it

**Dependencies:** Existing `ingest_book()` pipeline with force parameter.

**Why table stakes:** Without duplicate detection, users accidentally create duplicate entries when they say "add this book" and it's already indexed. Without force override, there's no way to re-index a book after a chunking or embedding improvement. Both paths exist in the CLI; the MCP tool just wraps them.

**Confidence:** HIGH (already implemented in ingest pipeline)

---

### 5. Confirmation-Quality Return Messages

**Description:** Each tool must return enough information for Claude to confirm the action to the user. `add_book` returns book ID, title, authors, chunk count. `remove_book` confirms what was removed. `update_book_metadata` returns the full updated book info.

**Complexity:** Low
- Format as markdown (matching existing tool return style)
- Include all fields the user would want to verify

**Dependencies:** `_get_book_info_impl` as formatting reference.

**Why table stakes:** When Claude says "Done!" without details, users feel anxious. "Added Python Cookbook by David Beazley (id: a3f7c2) -- 892 chunks indexed" is confidence-building. The PRD already specifies this expected output format.

**Implementation notes:**
- `add_book` returns same format as the CLI output: title, authors, book_id, chunk count
- `remove_book` returns: "Removed {title} ({book_id}) and {chunk_count} chunks from the library." or "Book not found: {book_id}"
- `update_book_metadata` returns the full book info (same as `get_book_info`) so the user sees the change

**Confidence:** HIGH

---

### 6. Partial Update Semantics for Metadata

**Description:** `update_book_metadata` must support updating any subset of fields (title only, authors only, ISBN only, or any combination). Fields not provided must be left unchanged. At least one field must be provided.

**Complexity:** Low
- Dynamic SQL UPDATE building from non-None fields
- Requires new `BookRepository.update()` method (PRD specifies this)

**Dependencies:** New `BookRepository.update()` method.

**Why table stakes:** Users fix one thing at a time. "Fix the author name" should not require re-specifying the title and ISBN. This is standard PATCH semantics; anything else feels broken.

**Implementation notes:**
- `None` means "don't change this field" (not "set to null")
- Build SET clause dynamically from provided fields
- Return updated Book object or None if not found

**Confidence:** HIGH

---

## Differentiators

Features that elevate the experience beyond basic functionality. Not strictly required, but significantly improve quality of life.

### 7. Progress Reporting for add_book

**Description:** Book ingestion (parse, chunk, embed) can take 10-60+ seconds depending on book size and embedding API latency. Report progress stages to the client via MCP progress notifications so Claude can relay status: "Parsing EPUB...", "Chunking content...", "Generating embeddings (batch 3/15)..."

**Complexity:** Medium
- FastMCP `Context` object provides `report_progress(progress, total)` (verified available in 2.14)
- Requires making `add_book` tool async and accepting `Context` parameter
- Need to thread progress callbacks through the ingestion pipeline or report at stage boundaries

**Dependencies:** FastMCP `Context` import, async tool function.

**Why differentiator (not table stakes):** Without progress, the tool still works -- Claude just says "Adding book, one moment..." and eventually gets a result. But for large books, 30+ seconds of silence is poor UX. Progress reporting turns "is it working?" into "embedding batch 5 of 12."

**Implementation notes:**
- Report at stage boundaries (simpler than per-batch): parsing (0.1), chunking (0.3), embedding (0.4-0.9), storing (1.0)
- If embedding is disabled (`embed=false`), skip embedding stage and adjust progress fractions
- Client support varies: Claude Desktop may not render progress bars yet, but the protocol is there for when it does
- Alternatively, a simpler approach: use `ctx.log("info", "Parsing EPUB...")` for status messages (less structured but universally visible)

**Confidence:** MEDIUM (Context.report_progress verified available; client rendering of progress is not guaranteed)

**Sources:**
- [FastMCP Context Documentation](https://gofastmcp.com/servers/context)
- [MCP Progress Specification](https://modelcontextprotocol.io/specification/2025-03-26/basic/utilities/progress)

---

### 8. Retroactive Annotations on Existing Read-Only Tools

**Description:** While adding annotations to the new write tools, also annotate the three existing read-only tools with `readOnlyHint=True`. This is a small change that improves the overall server quality.

**Complexity:** Low
- Three `@mcp.tool` decorators need `annotations=ToolAnnotations(readOnlyHint=True)` added

**Dependencies:** None.

**Why differentiator:** Not required for the new tools to work, but it completes the annotation picture and allows clients to optimize their UX for the entire mnemo tool set. Some MCP clients skip confirmation for read-only tools, speeding up search workflows.

**Confidence:** HIGH

---

### 9. Descriptive Tool Docstrings Tuned for LLM Consumption

**Description:** MCP tool descriptions are the primary way Claude understands what tools do. The docstrings should explain not just the API but the operational context: when to use each tool, what it affects, what it does NOT affect, and common workflows.

**Complexity:** Low
- Just writing better docstrings

**Dependencies:** None.

**Why differentiator:** MCP research emphasizes that "working" is not the same as "agent-usable." Tools can return the right data and still fail because the agent couldn't figure out when to call them. Well-written descriptions reduce Claude's ambiguity about which tool to use and how. For example, `update_book_metadata` should clarify "Updates SQLite only. Does NOT re-embed or modify ChromaDB. Search results will reflect the new metadata immediately because titles are resolved from SQLite at query time."

**Implementation notes:**
Example improved docstring for `remove_book`:
```
Remove a book and all its indexed content from the library.

This permanently deletes the book's metadata, text chunks, and vector
embeddings. The source .epub file on disk is NOT deleted.

Use list_available_books to find the book_id. After removal, the book
will no longer appear in search results.
```

**Confidence:** HIGH

**Sources:**
- [54 Patterns for Building Better MCP Tools](https://blog.arcade.dev/mcp-tool-patterns)
- [Less is More: MCP Design Patterns](https://www.klavis.ai/blog/less-is-more-mcp-design-patterns-for-ai-agents)

---

### 10. MNEMO_BOOKS_DIR Path Scoping for add_book

**Description:** Optionally restrict `add_book` to only accept file paths within the configured `MNEMO_BOOKS_DIR`. This prevents ingestion of arbitrary filesystem paths and provides a security boundary.

**Complexity:** Low
- Check that the resolved path starts with `MNEMO_BOOKS_DIR`
- If not configured, allow any path (backward compatible)
- If configured, reject paths outside the directory with an actionable error

**Dependencies:** `MNEMO_BOOKS_DIR` environment variable support in server startup (PRD Phase 3).

**Why differentiator:** Security-conscious design, but not strictly required for functionality. In single-user local setups, the risk is minimal. Matters more if someone exposes their MCP server over HTTP.

**Confidence:** HIGH

---

### 11. Book Title in remove_book Confirmation

**Description:** When removing a book, include the book's title in the confirmation message, not just the ID. Fetch the book info before deletion so the response says "Removed Python Cookbook (a3f7c2)" instead of just "Removed a3f7c2."

**Complexity:** Low
- Fetch book from repository before deleting
- Include title in the response message

**Dependencies:** Existing `BookRepository.get()`.

**Why differentiator:** Small touch that makes the interaction feel more human. Claude can relay "I've removed Python Cookbook from your library" instead of "I've removed a3f7c2."

**Confidence:** HIGH

---

## Anti-Features

Things to deliberately NOT build in this milestone. Each has a rationale.

### Complex Metadata Editing (Tags, Genres, Cover Art, Series Info)

**Why not:** The PRD explicitly defers tags/comments to a future phase. Calibre handles rich metadata management far better than we could. The current milestone only needs title, authors, and ISBN -- the three fields most likely to be wrong from EPUB extraction.

**What to do instead:** `update_book_metadata` takes only title, authors, isbn. Add more fields in a future milestone if demand materializes.

---

### External Metadata Lookup (Open Library, Google Books API)

**Why not:** Introduces external API dependency, rate limiting concerns, and the question of "which metadata source is authoritative?" The PRD explicitly lists this as a future extension.

**What to do instead:** Users tell Claude the correct metadata, Claude calls `update_book_metadata`. If we add lookup later, it becomes a separate tool (`lookup_book_metadata`) that returns suggestions for the user to confirm.

---

### Batch Import / Directory Scan

**Why not:** `scan_books_dir()` that finds un-indexed EPUBs is useful but not core. It requires defining behavior for partial failures, progress across multiple books, and whether to embed all at once (expensive).

**What to do instead:** Claude can use Filesystem MCP to list .epub files, compare against `list_available_books`, and call `add_book` for each one. The orchestration happens at the Claude layer, not in mnemo.

---

### Re-Embedding After Metadata Update

**Why not:** ChromaDB chunk metadata stores `book_id` and `section_path` but NOT title/author. The `SearchService` already resolves titles from SQLite at query time via `_get_book_title()`. Re-embedding after a title change is unnecessary and expensive.

**What to do instead:** Just update SQLite. Search results automatically reflect the new metadata. Document this clearly in the tool description.

---

### Undo / Soft Delete

**Why not:** Adds state complexity (deleted_at column, filter-everywhere logic, garbage collection). At personal library scale, re-adding a book from the .epub file is trivial recovery.

**What to do instead:** `remove_book` is permanent. The source .epub is never deleted. Users re-add if needed.

---

### Interactive Confirmation Within Tools

**Why not:** MCP tools are synchronous request-response. The tool cannot pause mid-execution to ask the user "Are you sure?" That is the client's job, guided by `destructiveHint=True`. The 2025-06-18 MCP spec adds server-initiated "elicitation" for requesting user input, but this is an advanced feature not yet widely supported in clients.

**What to do instead:** Annotate `remove_book` with `destructiveHint=True`. Trust the client (Claude Desktop) to surface confirmation. Design the tool to be safe by default (no `force` default for add_book, explicit book_id required for remove).

---

### Async Tasks / Background Processing

**Why not:** The 2025-11-25 MCP spec introduces experimental "Tasks" for long-running operations. This is cutting-edge and not widely supported in clients yet. Book ingestion (10-60s) is within the synchronous timeout window for STDIO transport.

**What to do instead:** Run ingestion synchronously. Use progress notifications if client supports them. If ingestion times grow beyond 2 minutes (very large books with slow embedding), revisit async tasks.

---

### PDF Support

**Why not:** Different parser, different content extraction challenges. The PRD scopes this milestone to EPUB only.

**What to do instead:** `add_book` validates `.epub` extension. Return clear error for other formats: "Only EPUB files are currently supported."

---

## Feature Dependencies

```
Existing Infrastructure (already built)
  |
  |-- BookRepository (CRUD for books table)
  |     |-- .add(), .get(), .get_by_hash(), .delete(), .list_all()
  |     |-- NEW: .update() method needed
  |
  |-- ingest_book() pipeline (parse -> chunk -> store -> embed)
  |-- remove_book() pipeline (delete from SQLite + ChromaDB)
  |-- FastMCP server with @mcp.tool registration
  |-- mcp.types.ToolAnnotations (available in fastmcp 2.14)
  |
  v
New MCP Tools
  |
  |-- add_book MCP tool
  |     |-- Wraps ingest_book()
  |     |-- Adds: path validation, .epub check, MCP error formatting
  |     |-- Depends on: ingest_book(), BookRepository
  |
  |-- remove_book MCP tool
  |     |-- Wraps remove_book() from ingest.py
  |     |-- Adds: title in confirmation, destructiveHint annotation
  |     |-- Depends on: remove_book(), BookRepository.get()
  |
  |-- update_book_metadata MCP tool
  |     |-- NEW: calls BookRepository.update()
  |     |-- Adds: partial update validation, field-level checking
  |     |-- Depends on: NEW BookRepository.update() method
```

### Critical Path

The only net-new code dependency is `BookRepository.update()`. Everything else wraps existing functionality. This suggests:

1. **Phase 1:** Add `BookRepository.update()` + unit tests (unblocks update_book_metadata)
2. **Phase 2:** Implement all three MCP tools (add, remove, update) + annotations
3. **Phase 3:** MNEMO_BOOKS_DIR config + path scoping
4. **Phase 4:** Integration tests

---

## MVP Recommendation

### Must Have (this milestone):

1. **Tool annotations** on all three new tools (and retroactively on existing tools) -- Low effort, high impact on safety
2. **Structured error responses** with actionable messages -- Already patterned; just follow it
3. **Input validation** (path checks, book_id format, at-least-one-field) -- Standard defensive programming
4. **Duplicate detection** via file_hash with force override -- Already in ingest pipeline
5. **Confirmation-quality return messages** including titles, IDs, chunk counts -- Low effort
6. **Partial update semantics** for update_book_metadata -- Requires BookRepository.update()
7. **Book title in remove_book confirmation** -- Tiny enhancement, big UX win

### Should Have (this milestone, if time permits):

8. **Progress reporting** for add_book via Context.report_progress -- Medium effort; nice UX
9. **MNEMO_BOOKS_DIR path scoping** -- Low effort security improvement
10. **Improved docstrings** tuned for LLM consumption -- Low effort; polish

### Explicitly Defer:

- Tags/genres/comments metadata fields
- External metadata lookup APIs
- Batch import / directory scan
- Re-embedding after metadata update
- Async tasks / background processing
- PDF support

---

## Sources

### MCP Specification and Best Practices
- [MCP Specification 2025-06-18 - Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP Specification 2025-03-26 - Progress](https://modelcontextprotocol.io/specification/2025-03-26/basic/utilities/progress)
- [MCP Best Practices](https://modelcontextprotocol.info/docs/best-practices/)
- [15 Best Practices for Building MCP Servers](https://thenewstack.io/15-best-practices-for-building-mcp-servers-in-production/)

### MCP Tool Design Patterns
- [54 Patterns for Building Better MCP Tools](https://blog.arcade.dev/mcp-tool-patterns)
- [Less is More: MCP Design Patterns](https://www.klavis.ai/blog/less-is-more-mcp-design-patterns-for-ai-agents)
- [MCP Tool Descriptions Best Practices](https://www.merge.dev/blog/mcp-tool-description)

### Error Handling
- [Error Handling in MCP Servers - MCPcat](https://mcpcat.io/guides/error-handling-custom-mcp-servers/)
- [MCP Best Practices for Exceptions](https://gist.github.com/eonist/1cbc3502305e0fc0aa6e977bae283b41)

### FastMCP
- [FastMCP Tools Documentation](https://gofastmcp.com/servers/tools)
- [FastMCP Context Documentation](https://gofastmcp.com/servers/context)

### Safety and Confirmation Patterns
- [MCP Server Safety: Human-in-the-Loop Controls](https://zeo.org/resources/blog/mcp-server-safety-human-in-the-loop-controls-risk-assessment)
- [MCP Async Tasks for Long-Running Workflows](https://workos.com/blog/mcp-async-tasks-ai-agent-workflows)
