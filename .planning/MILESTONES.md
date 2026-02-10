# Project Milestones: Mnemo

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
