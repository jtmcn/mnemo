# Project Milestones: Mnemo

## v1.1 Book Management (Shipped: 2026-02-17)

**Delivered:** MCP tools for full book lifecycle management — Claude can add, remove, and edit ebook metadata without CLI context-switching.

**Phases completed:** 5-7 (5 plans total)

**Key accomplishments:**

- `update_book_metadata` MCP tool with dynamic SQL updates and cache invalidation
- `remove_book` MCP tool with cascade deletes across SQLite and ChromaDB
- `add_book` MCP tool with EPUB validation, hash-based duplicate detection, async timeout, and failure cleanup
- ToolAnnotations on all 6 MCP tools (destructiveHint, idempotentHint, readOnlyHint)
- Normalized error conventions and LLM-tuned docstrings for tool discovery
- Full lifecycle integration test (add → search → update → verify → remove → verify removal)

**Stats:**

- 30 files created/modified (6,535 insertions, 1,298 deletions)
- 9,511 lines of Python (4,458 source + 5,053 tests)
- 3 phases, 5 plans, ~10 tasks
- 7 days from milestone start to ship (2026-02-11 → 2026-02-17)
- 19/19 requirements satisfied, audit passed

**Git range:** `docs: start milestone v1.1 Book Management` → `docs(07): complete tool-polish-integration phase`

**What's next:** Planning next milestone

---

## v1.0 MVP (Shipped: 2026-02-10)

**Delivered:** Personal technical book library with MCP search — parse EPUBs preserving code blocks, generate embeddings, and search via Claude through MCP.

**Phases completed:** 1-4 (11 plans total)

**Key accomplishments:**

- EPUB parsing with publisher-specific code block detection (O'Reilly, Pragmatic, Manning)
- Content-aware chunking that never splits code blocks, diagrams, or tables
- Databricks GTE-large-en embedding pipeline with batch processing and retry logic
- Hybrid search combining semantic (ChromaDB) and keyword (FTS5) via RRF fusion
- FastMCP server with 3 tools for Claude Desktop and Claude Code
- Typer CLI with add, remove, list, search, serve commands

**Stats:**

- 88 files created/modified
- 8,294 lines of Python (4,097 source + 4,197 tests)
- 4 phases, 11 plans, 33 requirements
- 15 days from project start to ship (2026-01-19 → 2026-02-03)
- 236 tests (234 passed, 2 skipped for credentials)

**Git range:** `docs: initialize project` → `docs(04): complete CLI & Integration phase`

**What's next:** Planning next milestone

---
