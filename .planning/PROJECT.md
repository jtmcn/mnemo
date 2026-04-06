# Mnemo

## What This Is

A personal technical book library that lets you ask Claude questions and get answers grounded in your EPUB collection. Parses technical books preserving code blocks and structure, generates embeddings via Databricks GTE-large-en, stores vectors in ChromaDB, and exposes hybrid semantic+keyword search and full book lifecycle management through an MCP server for Claude Desktop and Claude Code.

## Core Value

**Ask Claude a question, get answers from your book collection.**

If the MCP search doesn't work, nothing else matters. Everything exists to serve this moment.

## Requirements

### Validated

- ✓ Parse EPUB files extracting text, code blocks, and chapter structure — v1.0
- ✓ Chunk content intelligently (keep code blocks intact, respect section boundaries) — v1.0
- ✓ Generate embeddings via Databricks GTE-large-en model — v1.0
- ✓ Store vectors in ChromaDB with book/chapter metadata — v1.0
- ✓ Track books and chunks in SQLite with cascade deletes — v1.0
- ✓ Expose semantic search via MCP server (stdio transport) — v1.0
- ✓ CLI for book management: add, remove, list — v1.0
- ✓ Search filtering by book and content type — v1.0
- ✓ Add book via MCP tool (ingest EPUB by file path) — v1.1
- ✓ Remove book via MCP tool (delete book, chunks, and vectors) — v1.1
- ✓ Update book metadata via MCP tool (title, authors, ISBN in SQLite) — v1.1
- ✓ Tool annotations (destructiveHint, idempotentHint, readOnlyHint) on all MCP tools — v1.1
- ✓ LLM-tuned docstrings and normalized error conventions — v1.1
- ✓ Full lifecycle integration test (add → search → update → verify → remove → verify) — v1.1

- ✓ ChromaDB uses cosine distance metric with safe migration path — v1.2
- ✓ Search results include cosine similarity scores (0-1) — v1.2
- ✓ Configurable chunk sizes per book at ingest time with validation — v1.2
- ✓ EPUB file path stored for future re-indexing — v1.2
- ✓ Context enrichment via chunk expansion (configurable window, section-boundary aware) — v1.2
- ✓ Section-based filtering on search results across all search modes — v1.2
- ✓ `get_book_chunks` tool for contiguous deep reading — v1.2

- ✓ Fix EPUB text parsing artifacts (joined words across HTML tags) — v1.3
- ✓ Clean author name parsing (strip semicolons, trailing delimiters) — v1.3
- ✓ Detect and label front-matter/TOC sections instead of "Unknown section" — v1.3
- ✓ Section filter matches against full hierarchy path (not just leaf name) — v1.3
- ✓ New `get_book_structure` MCP tool for browsing section hierarchy — v1.3
- ✓ Context window results visually delineate match vs surrounding chunks — v1.3

- ✓ Explicit dependency declarations (typer, rich) in pyproject.toml — v1.4
- ✓ Environment variable documentation via .env.example — v1.4
- ✓ Configurable log level via MNEMO_LOG_LEVEL — v1.4
- ✓ Versioned schema migrations replacing try/except ALTER TABLE — v1.4
- ✓ Full backup & restore for SQLite + ChromaDB vectors — v1.4
- ✓ content.py split into focused private modules (_models, _classify, _extract) — v1.4
- ✓ MCP tools split by domain (search, books, metadata) with service layer — v1.4
- ✓ Dependency injection for all MCP tool implementations — v1.4
- ✓ GitHub Actions CI pipeline with lint + test jobs — v1.4
- ✓ Coverage enforcement at 80% threshold — v1.4
- ✓ CI status badge in README — v1.4

### Active

(No active milestone — planning next)

### Out of Scope

- PDF or other formats — EPUB only, Calibre converts if needed
- Web UI — CLI only for management, Claude is the interface
- Multi-user authentication — personal use only
- Real-time sync with external sources — batch is fine for ~10 books
- HTTP transport for MCP — stdio sufficient for personal use
- Offline mode — local-only by design
- Tags/genre/comment metadata fields — future milestone
- External metadata lookup (Open Library, Google Books) — future milestone
- MNEMO_BOOKS_DIR environment config — deferred from v1.1
- Path security restricting add_book to configured directory — deferred from v1.1
- Modifying source .epub files — read-only by design
- Bulk import / directory scanning — future milestone
- Re-embedding after metadata change — expensive, rarely needed
- Interactive confirmation in tools — MCP is request-response
- Progress reporting via MCP notifications — future milestone
- LLM-based chunking — expensive per-chunk, overkill for ~10 books
- Parent-child chunk hierarchy — context expansion via neighbor chunks achieves same goal more simply
- GraphRAG / knowledge graph — high complexity, deferred until search quality baseline is solid
- Semantic chunking — mixed benchmarks, current chunking works well, deferred
- Cross-encoder re-ranking — future milestone
- Query transformation / expansion — future milestone

## Context

**Shipped v1.4** with 7,628 LOC Python source, 525 tests passing (83.24% coverage). All structural tech debt addressed — modules decomposed, dependency injection applied, schema migrations versioned, backup/restore implemented, CI pipeline active.
**Tech stack:** Python 3.11+, uv, ChromaDB (cosine), SQLite/FTS5, Databricks GTE-large-en, FastMCP 2.0, Typer, Rich, GitHub Actions CI.
**MCP tools:** 10 total — search_books, list_available_books, get_book_info, get_book_chunks, get_book_structure, update_book_metadata, remove_book, add_book, enrich_book, reindex_all_books.
**Known items:** Code chunking heuristics need tuning with real data; MNEMO_BOOKS_DIR path restriction not yet implemented; semantic chunking deferred (mixed benchmarks); FRONT_MATTER_STEMS heuristic may need publisher-specific additions; 78 pre-existing mypy errors (CI non-blocking).
**Tech debt:** mypy `continue-on-error` in CI (78 errors); `book_service.list_all_books` dead export; `tests/test_backup.py` missing tar `filter=` arg.

## Constraints

- **Embedding API**: Databricks Foundation Model APIs (GTE-large-en, 1024 dimensions)
- **Stack**: Python 3.11+, uv for package management, modern tooling (ruff, mypy, pytest)
- **Storage**: Local-only (ChromaDB + SQLite in ~/.mnemo)
- **MCP Framework**: FastMCP 2.0 (pinned <3)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Databricks for embeddings | Existing access, good model quality | ✓ Good — works reliably with retry logic |
| GTE-large-en over BGE | BGE deprecated Feb 2026, GTE has 8192 token context | ✓ Good — better context window for code |
| ChromaDB for vectors | Simple, local, no server required | ✓ Good — persistent, filterable |
| SQLite for metadata | Lightweight, cascade deletes, no setup | ✓ Good — FTS5 enables keyword search |
| FastMCP for MCP server | Modern Python MCP framework | ✓ Good — clean API, stdio works |
| Code blocks as atomic chunks | Technical books are code-heavy, splitting breaks context | ✓ Good — critical design choice |
| Dual storage (ChromaDB + SQLite) | Avoid ChromaDB metadata limits, enable FTS | ✓ Good — hybrid search depends on this |
| RRF fusion for hybrid search | Best-of-both semantic + keyword | ✓ Good — standard approach |
| 6-char hex book ID | SHA256 of content+title+author | ✓ Good — collision-resistant at personal scale |
| Lazy imports for embeddings | Avoid hard dependency on credentials | ✓ Good — CLI works without Databricks config |
| print() for JSON output | Rich console adds formatting/wrapping | ✓ Good — clean machine-readable output |
| Service layer + DI for MCP tools | _impl functions accept deps as params, service layer for shared logic | ✓ Good — testable, CLI/MCP share validation |
| Sync MCP tool impls | Ingest pipeline is sync, no concurrency benefit for STDIO | ✓ Good — avoid unnecessary async complexity |
| Async timeout for add_book | asyncio.wait_for(to_thread(), timeout=300) | ✓ Good — prevents hung embedding calls |
| Cache clear over selective eviction | _book_cache.clear() on any mutation | ✓ Good — simpler at personal scale |
| isbn="" clears ISBN | Empty string normalized to NULL in DB | ✓ Good — clean UX for correcting metadata |
| MNEMO_BOOKS_DIR descoped | Path security not needed for personal use MVP | — Pending — deferred to future milestone |
| Cosine over L2 distance | Better similarity semantics, 0-1 scoring | ✓ Good — cleaner scores, migration worked smoothly |
| Two-phase collection migration | Preserve collection name through delete-recreate | ✓ Good — safe, idempotent |
| Post-filter with over-fetch | Section filtering in Python after ChromaDB/FTS5 retrieval | ✓ Good — reliable substring matching, 3x over-fetch compensates |
| Context window clamped 0-3 | Prevent response explosion from large windows | ✓ Good — practical limit for MCP responses |
| Semantic chunking deferred | Mixed benchmarks, current chunking works well | ✓ Good — avoided complexity without clear benefit |
| Section boundary walking | Context expansion stops at section boundaries | ✓ Good — prevents cross-section contamination |
| get_text(separator=' ') for inline elements | Preserve word boundaries without modifying code/table blocks | ✓ Good — surgical fix for PARSE-01 |
| Join-based section filter | ' > '.join hierarchy for substring match | ✓ Good — strict superset of leaf-only matching |
| get_book_structure from SQLite only | No EPUB re-parsing, reflects indexed data | ✓ Good — consistent with search results |
| FRONT_MATTER_STEMS heuristic | Exact + prefix/suffix filename matching | ✓ Good — covers major publishers, extensible |
| MATCH/Context labels with --- separators | Visual chunk delineation in enriched results | ✓ Good — immediately readable in Claude Desktop |
| Versioned schema migrations | Numbered scripts replace try/except ALTER TABLE | ✓ Good — safe, ordered, auditable |
| sqlite3.Connection.backup() for snapshots | WAL-consolidated DB copy without locking | ✓ Good — atomic, no WAL file in backup |
| Flat tar archive members | No directory prefix in backup archives | ✓ Good — simple extraction, no path confusion |
| Private module prefix (_models, _classify, _extract) | Signals internal API boundaries within epub package | ✓ Good — clear public vs internal boundary |
| Re-export shim for backward compat | content.py re-exports from private modules | ✓ Good — zero caller changes needed |
| Parallel CI jobs (lint + test) | Independent failure signals, faster feedback | ✓ Good — lint failure doesn't block test results |
| 80% coverage threshold | Enforced via --cov-fail-under in CI | ✓ Good — prevents coverage regression |
| mypy continue-on-error | 78 pre-existing errors, non-blocking for initial CI | ⚠️ Revisit — fix errors then enforce strictly |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-05 after v1.4 milestone*
