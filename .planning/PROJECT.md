# Mnemo

## What This Is

A personal technical book library that lets you ask Claude questions and get answers grounded in your EPUB collection. Parses technical books preserving code blocks and structure, generates embeddings via Databricks GTE-large-en, stores vectors in ChromaDB, and exposes hybrid semantic+keyword search through an MCP server for Claude Desktop and Claude Code.

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

### Active

- [ ] Add book via MCP tool (ingest EPUB by file path)
- [ ] Remove book via MCP tool (delete book, chunks, and vectors)
- [ ] Update book metadata via MCP tool (title, authors, ISBN in SQLite)
- [ ] MNEMO_BOOKS_DIR environment config for ebook directory access
- [ ] Backward compatibility with existing CLI and search tools

### Out of Scope

- PDF or other formats — EPUB only, Calibre converts if needed
- Web UI — CLI only for management, Claude is the interface
- Multi-user authentication — personal use only
- Real-time sync with external sources — batch is fine for ~10 books
- HTTP transport for MCP — stdio sufficient for personal use
- Offline mode — local-only by design
- Tags/genre/comment metadata fields — future phase
- External metadata lookup (Open Library, Google Books) — future phase
- Modifying source .epub files — read-only by design
- Bulk import / directory scanning — depends on add_book working well first

## Context

**Shipped v1.0** with 4,097 LOC Python source + 4,197 LOC tests.
**Tech stack:** Python 3.11+, uv, ChromaDB, SQLite/FTS5, Databricks GTE-large-en, FastMCP 2.0, Typer, Rich.
**Test coverage:** 236 tests (234 passed, 2 skipped for credentials).
**Known items:** Code chunking heuristics need tuning with real data; similarity score thresholds need empirical calibration.
**Tech debt:** typer not in explicit dependencies (works via chromadb transitive dep).

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

## Current Milestone: v1.1 Book Management

**Goal:** Add MCP tools for book lifecycle management so Claude can add, remove, and edit ebook metadata without CLI context-switching.

**Target features:**
- `add_book` MCP tool — ingest EPUB by file path with duplicate detection
- `remove_book` MCP tool — remove book and all associated data
- `update_book_metadata` MCP tool — edit title, authors, ISBN in SQLite
- `MNEMO_BOOKS_DIR` environment variable for ebook directory configuration
- `BookRepository.update()` method for metadata writes

---
*Last updated: 2026-02-11 after v1.1 milestone start*
