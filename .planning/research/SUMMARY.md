# Project Research Summary

**Project:** Mnemo v1.1 - Book Management MCP Tools
**Domain:** Adding mutation MCP tools to an existing read-only MCP server
**Researched:** 2026-02-11
**Confidence:** HIGH

## Executive Summary

Mnemo v1.1 adds three book management MCP tools (`add_book`, `remove_book`, `update_book_metadata`) to an existing server that already has three read-only search tools. This is a **wiring milestone, not a technology milestone**: zero new dependencies are needed, no schema migrations are required, and the core pipeline functions (`ingest_book()`, `remove_book()`) already exist and are used by the CLI. The only net-new code at the storage layer is a `BookRepository.update()` method for partial metadata edits. The tools wire into the existing FastMCP 2.14 server using the same decorator patterns already in use, with the addition of `ToolAnnotations` from `mcp.types` to signal destructive vs. read-only behavior to clients.

The recommended approach is direct delegation: MCP tools call `ingest.py` functions directly (matching the CLI pattern), not through a new service layer. Tools stay synchronous (`def`, not `async def`) because the underlying pipeline is synchronous and MCP STDIO transport is single-client. `MNEMO_BOOKS_DIR` follows the existing `os.environ.get()` pattern -- no new config libraries needed. Error handling returns structured error strings matching the existing convention. All six tools (three existing, three new) should carry `ToolAnnotations` for client-side UX optimization.

The primary risks are: (1) embedding timeout during `add_book` killing the MCP connection for large books (30-120s), (2) path traversal through the `file_path` parameter if `MNEMO_BOOKS_DIR` validation is skipped, (3) stale DB connections when mutation tools use `ingest_book()` (which manages its own connection) while the tool layer caches a separate connection, and (4) silent partial failure when `remove_book` commits the SQLite delete but ChromaDB cleanup fails. All four are preventable with straightforward design decisions made before implementation begins.

## Key Findings

### Recommended Stack

No stack changes. Every capability is already in `pyproject.toml`. See [STACK.md](STACK.md) for full details.

**Core technologies (all existing):**
- **FastMCP 2.14.4**: MCP server with `@mcp.tool` decorator and `ToolAnnotations` support -- verified working
- **mcp SDK 1.25.0**: Provides `mcp.types.ToolAnnotations` (transitive dep of FastMCP) -- verified import
- **SQLite (stdlib)**: Metadata storage; existing `books` table has all needed columns, no migration
- **ChromaDB 1.0+**: Vector storage; existing delete-by-book API used by `remove_book()`
- **Pydantic 2.0+**: Data models; existing `Book` model unchanged

**What NOT to add:** pydantic-settings, python-dotenv, SQLAlchemy, aiosqlite, pytest-asyncio, any new config file format. Each was evaluated and rejected -- see STACK.md "What NOT to Add" section.

### Expected Features

See [FEATURES.md](FEATURES.md) for full analysis.

**Must have (table stakes):**
- Tool annotations (`destructiveHint`, `readOnlyHint`) on all tools -- clients use these for confirmation prompts
- Structured error responses (return error strings, never raise exceptions that kill STDIO)
- Input validation with actionable messages (path exists? is .epub? book_id valid?)
- Duplicate detection with `force` override (already in `ingest_book()`)
- Confirmation-quality return messages (book title, ID, chunk count in response)
- Partial update semantics for `update_book_metadata` (PATCH, not PUT)

**Should have (differentiators):**
- Retroactive `readOnlyHint=True` on existing search tools
- LLM-tuned docstrings explaining when/why to use each tool
- `MNEMO_BOOKS_DIR` path scoping for `add_book` security
- Book title included in `remove_book` confirmation

**Defer (v2+):**
- Progress reporting via `Context.report_progress()` (requires async refactor)
- Tags/genres/comments metadata fields
- External metadata lookup (Open Library, Google Books)
- Batch import / directory scan
- PDF support
- Undo / soft delete
- Async tasks / background processing

### Architecture Approach

Direct delegation to existing pipeline functions, no new service layer, no new files. See [ARCHITECTURE.md](ARCHITECTURE.md) for data flows and integration map.

**Major components:**
1. **`BookRepository.update()`** (new method, existing class) -- Dynamic parameterized UPDATE for partial metadata edits
2. **Three MCP tool functions** (in existing `tools.py`) -- `_add_book_impl`, `_remove_book_impl`, `_update_book_metadata_impl` following the existing `_impl` + decorator pattern
3. **`_resolve_book_path()` helper** (in existing `tools.py`) -- Resolves relative paths against `MNEMO_BOOKS_DIR`, validates .epub extension

**Key architectural decisions:**
- No service layer (empty indirection; CLI calls `ingest.py` directly, MCP tools should too)
- Sync tools (no `async def`; `ingest_book()` is sync, no concurrency benefit for STDIO)
- Use `ingest_book()` return values directly (avoid stale cached DB connections)
- MCP-specific logic (formatting, error wrapping, path resolution) stays in `tools.py`; do not modify `ingest.py`

### Critical Pitfalls

See [PITFALLS.md](PITFALLS.md) for all 13 pitfalls with prevention code.

1. **Path traversal via `add_book`** -- Use `Path.resolve(strict=True)` + `is_relative_to()` to validate against `MNEMO_BOOKS_DIR`. Never use string prefix matching.
2. **Embedding timeout kills MCP connection** -- `ingest_book()` with `embed=True` can take 30-120s. Either default `embed=False` with a separate embed step, or accept the timeout risk and document it. The existing `ingest_book(embed=False)` path completes in <5s.
3. **Stale DB connection after mutations** -- `ingest_book()` creates its own connection; the tool layer's cached `_db_connection` sees stale data. Prevention: use `ingest_book()` return values directly, never re-query through the cached connection.
4. **Silent ChromaDB cleanup failure in `remove_book`** -- SQLite delete commits before ChromaDB delete. If ChromaDB fails, book is gone from metadata but ghost vectors remain. Prevention: report partial success with clear instructions if ChromaDB cleanup fails.
5. **SQL injection in dynamic UPDATE** -- `BookRepository.update()` builds a dynamic SET clause. Prevention: hardcode column names, parameterize values only. Already patterned correctly in existing repository code.

## Implications for Roadmap

Based on research, the milestone decomposes into 4 phases ordered by dependency chain and testability.

### Phase 1: Repository Layer

**Rationale:** `BookRepository.update()` is the only net-new storage code and is a dependency for `update_book_metadata`. It is independently testable with no MCP concerns.
**Delivers:** `update()` method on `BookRepository` with parameterized dynamic UPDATE, rowcount checking, empty-value validation, and `json.dumps` for authors serialization.
**Addresses:** Partial update semantics (Feature #6), input validation for field values (Feature #3).
**Avoids:** SQL injection (Pitfall #5), silent no-op on nonexistent books (Pitfall #6), empty string corruption (Pitfall #11), authors double-serialization (Pitfall #13).

### Phase 2: MCP Tool Implementations

**Rationale:** This is the core of the milestone. All three tools depend on Phase 1 (for `update`) and existing pipeline functions (for `add`/`remove`). Grouping all three tools together allows consistent annotation, error handling, and formatting decisions.
**Delivers:** Three new MCP tools (`add_book`, `remove_book`, `update_book_metadata`) with annotations, input validation, structured error responses, and markdown-formatted success messages. Also: retroactive `readOnlyHint=True` on existing tools, `_resolve_book_path()` helper, LLM-tuned docstrings.
**Addresses:** Tool annotations (Feature #1), structured errors (Feature #2), input validation (Feature #3), duplicate detection (Feature #4), confirmation messages (Feature #5), retroactive annotations (Feature #8), LLM docstrings (Feature #9), book title in remove confirmation (Feature #11).
**Avoids:** Path traversal (Pitfall #1), embedding timeout (Pitfall #2 -- design decision needed), cascade failure (Pitfall #3), stale connections (Pitfall #4), missing annotations (Pitfall #7), inconsistent output format (Pitfall #10), no deletion feedback (Pitfall #12).

### Phase 3: Environment Configuration

**Rationale:** `MNEMO_BOOKS_DIR` is optional security hardening. The tools work without it (accepting any valid path). Adding it after tool implementations are stable avoids blocking the core work.
**Delivers:** `MNEMO_BOOKS_DIR` env var support with startup validation (warn, don't crash), path scoping for `add_book`, relative path resolution.
**Addresses:** MNEMO_BOOKS_DIR path scoping (Feature #10).
**Avoids:** MNEMO_BOOKS_DIR misconfiguration (Pitfall #8).

### Phase 4: Integration Tests

**Rationale:** Full-cycle tests require all three tools working. Test infrastructure must patch both the tool layer and the ingest layer to avoid writing to production `~/.mnemo/`.
**Delivers:** End-to-end tests: add -> search -> update metadata -> search -> remove -> verify gone. Duplicate detection tests. MCP protocol schema tests (tool names, parameters, annotations).
**Avoids:** Test state leakage (Pitfall #9).

### Phase Ordering Rationale

- **Phase 1 before Phase 2:** `BookRepository.update()` must exist before `update_book_metadata` can be wired up.
- **Phase 2 is the bulk:** All three tools share annotation, error handling, and formatting patterns. Implementing them together ensures consistency.
- **Phase 3 after Phase 2:** `MNEMO_BOOKS_DIR` is optional security polish. Tools must work without it first.
- **Phase 4 last:** Integration tests exercise the full pipeline and require all phases complete.
- **Phases 1-3 each have unit tests alongside implementation.** Phase 4 adds cross-cutting integration tests.

### Research Flags

Phases with well-documented patterns (skip `/gsd:research-phase`):
- **Phase 1:** Standard SQLite parameterized query pattern. Existing repository code provides the template.
- **Phase 3:** Single `os.environ.get()` lookup following the existing `EmbeddingConfig.from_env()` pattern.
- **Phase 4:** Existing test patterns in `test_mcp.py` and `test_integration.py` provide templates, though mutation test fixtures need care.

Phase needing a design decision before implementation:
- **Phase 2:** The embedding timeout question (Pitfall #2) must be resolved before implementing `add_book`. Two options: (A) keep `embed=True` default and accept timeout risk for large books, or (B) default `embed=False` and require a separate step. Recommendation: keep `embed=True` as default (matching CLI behavior) but document the timeout risk. The existing `ingest_book()` already supports `embed=False` as an escape valve.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new deps. All APIs verified by executing code against installed packages. |
| Features | MEDIUM-HIGH | Table stakes are clear. Differentiators are well-scoped. Progress reporting deferred due to async complexity. |
| Architecture | HIGH | Existing codebase examined line-by-line. Data flows traced through `ingest.py`, `tools.py`, `repository.py`. |
| Pitfalls | HIGH | 4 critical, 5 moderate, 4 minor pitfalls identified. All backed by codebase analysis or published MCP security research. |

**Overall confidence:** HIGH

### Gaps to Address

1. **Embedding timeout threshold**: The exact timeout varies by MCP client (Claude Desktop default ~60s, others vary). Real-world testing with a large book (1000+ chunks) is needed to determine if `embed=True` is viable as the default. If not, the tool interface may need adjustment.
2. **ChromaDB cleanup reliability**: The existing `remove_book()` error handling around ChromaDB needs inspection during Phase 2 implementation. The pitfall is identified but the fix may require modifying `ingest.py` (which is shared with CLI).
3. **Test fixture isolation for mutations**: The exact monkeypatch targets for isolating `ingest_book()` from production paths need validation during Phase 4 implementation.

## Sources

### Verified by Direct Execution (HIGH confidence)
- FastMCP 2.14.4 `@mcp.tool` decorator with `annotations` parameter
- `mcp.types.ToolAnnotations` class with all 5 fields on `mcp==1.25.0`
- `from fastmcp.exceptions import ToolError` import path
- `from fastmcp import Context` with `report_progress()` method
- Existing codebase: `tools.py`, `ingest.py`, `repository.py`, `database.py`, `cli.py`, `server.py`

### Official Documentation (HIGH confidence)
- [FastMCP Tools Documentation](https://gofastmcp.com/servers/tools)
- [MCP Specification - Tools and Annotations](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP Best Practices](https://modelcontextprotocol.info/docs/best-practices/)

### MCP Security and Patterns (HIGH confidence)
- [Snyk: Path Traversal in MCP Server Function Handlers](https://snyk.io/articles/preventing-path-traversal-vulnerabilities-in-mcp-server-function-handlers/)
- [MCPcat: Error Handling in MCP Servers](https://mcpcat.io/guides/error-handling-custom-mcp-servers/)
- [MCPcat: Fix MCP Error -32001 Request Timeout](https://mcpcat.io/guides/fixing-mcp-error-32001-request-timeout/)
- [54 Patterns for Building Better MCP Tools](https://blog.arcade.dev/mcp-tool-patterns)

### MCP Tool Design (MEDIUM-HIGH confidence)
- [Less is More: MCP Design Patterns](https://www.klavis.ai/blog/less-is-more-mcp-design-patterns-for-ai-agents)
- [MCP Tool Descriptions Best Practices](https://www.merge.dev/blog/mcp-tool-description)
- [MCP Server Safety: Human-in-the-Loop Controls](https://zeo.org/resources/blog/mcp-server-safety-human-in-the-loop-controls-risk-assessment)

---
*Research completed: 2026-02-11*
*Ready for roadmap: yes*
