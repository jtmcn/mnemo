# Project Milestones: Mnemo

## v1.4 Tech Debt Cleanup (Shipped: 2026-04-06)

**Delivered:** Hardened codebase by addressing structural tech debt — dependency management, schema migrations, backup/restore, module decomposition, dependency injection, and CI pipeline.

**Phases completed:** 14-19 (7 plans total)

**Key accomplishments:**

- Declared missing dependencies (typer, rich) and added configurable logging via `MNEMO_LOG_LEVEL`
- Versioned schema migrations replacing fragile try/except ALTER TABLE with numbered migration scripts
- Full backup & restore for SQLite database and ChromaDB vectors via `mnemo backup` / `mnemo restore`
- Split content.py into focused private modules (_models, _classify, _extract) with re-export shim
- Refactored MCP tools into domain modules with service layer and dependency injection
- GitHub Actions CI pipeline with parallel lint/test jobs, 80% coverage threshold, and CI badge

**Stats:**

- 53 files modified (7,312 insertions, 2,445 deletions)
- 7,628 lines Python source
- 6 phases, 7 plans, 90 commits
- 21 days from milestone start to ship (2026-03-16 → 2026-04-05)
- 16/17 requirements satisfied (CICD-02 partial — mypy continue-on-error)
- 525 tests passing, 83.24% coverage

**Git range:** v1.3..HEAD

**Known Gaps:**

- CICD-02 partial: mypy has 78 pre-existing errors; CI uses `continue-on-error: true`
- `services/book_service.list_all_books` exported but never imported (dead code)
- `tests/test_backup.py` uses `tar.extractall()` without `filter=` (Python 3.14 deprecation warning)

**What's next:** Planning next milestone

---

## v1.3 Quality & Polish (Shipped: 2026-03-16)

**Delivered:** Parser quality fixes and search UX polish — clean EPUB text extraction, hierarchy-aware section filtering, structure browsing tool, and enriched result formatting.

**Phases completed:** 10-13 (5 plans total)

**Key accomplishments:**

- Fixed EPUB text extraction to preserve word boundaries across inline HTML elements (PARSE-01)
- Author names correctly split on semicolons and cleaned of trailing delimiters (PARSE-02)
- Front-matter/TOC spine items get descriptive section labels instead of "Unknown section" (PARSE-03)
- Section filter matches against full hierarchy path — "Chapter 5" finds all subsections (SRCH-01)
- New `get_book_structure` MCP tool returns indented section hierarchy from SQLite (TOOL-01)
- Context window search results visually delineate matched vs. surrounding chunks (TOOL-02)

**Stats:**

- 42 files modified (5,577 insertions, 1,262 deletions)
- 5,360 lines Python source
- 4 phases, 5 plans, 29 commits
- 4 days from milestone start to ship (2026-03-12 → 2026-03-15)
- 6/6 requirements satisfied, audit passed
- 367 tests passing

**Git range:** `docs(phase-11): research phase domain` → `docs(v1.3): final milestone audit`

**What's next:** Planning next milestone

---

## v1.2 RAG Improvements (Shipped: 2026-03-11)

**Delivered:** Advanced RAG techniques — cosine similarity scoring, context-aware search expansion, section filtering, configurable chunking, and deep reading via chunk ranges.

**Phases completed:** 8-9 (5 plans total)

**Key accomplishments:**

- Migrated ChromaDB from L2 to cosine distance with safe batch copy, count verification, and CLI command
- Search results include real cosine similarity scores (0-1) for relevance transparency
- Configurable chunk sizes per book at ingest time with validation (min/max token bounds)
- Section-based filtering on search results across all three search modes (keyword, semantic, hybrid)
- Context window expansion with section-boundary awareness and overlap deduplication
- New `get_book_chunks` MCP tool for contiguous deep reading of chunk ranges

**Stats:**

- 17 files modified (2,038 insertions, 19 deletions)
- 11,718 lines of Python (5,135 source + 6,583 tests)
- 2 phases, 5 plans, 15 commits
- 3 days from milestone start to ship (2026-03-08 → 2026-03-10)
- 18/18 requirements satisfied, audit passed

**Git range:** `test(08-02): add failing tests for epub_path` → `docs(phase-09): complete phase execution`

**What's next:** Planning next milestone

---

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
