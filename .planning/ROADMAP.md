# Roadmap: Mnemo

**Created:** 2026-01-19
**Phases:** 4
**Requirements:** 33 total (all v1)

## Phase Overview

| # | Name | Goal | Requirements | Success Criteria |
|---|------|------|--------------|------------------|
| 1 | Foundation | System can parse EPUBs and store structured content | 12 | 5 |
| 2 | Vector Pipeline | System can generate and store embeddings | 5 | 4 |
| 3 | Search & MCP | Claude can search the book library via MCP | 11 | 4 |
| 4 | CLI & Integration | User can manage library and connect Claude | 5 | 4 |

## Phase Details

### Phase 1: Foundation

**Goal:** System can parse technical EPUBs, chunk content intelligently, and store structured data with full text for later retrieval.

**Plans:** 5 plans

Plans:
- [x] 01-01-project-setup-PLAN.md — Python package structure and core data models
- [x] 01-02-epub-parser-PLAN.md — EPUB parsing with metadata, TOC, and content type detection
- [x] 01-03-sqlite-storage-PLAN.md — SQLite storage with FTS5 and cascade deletes
- [x] 01-04-chunker-PLAN.md — Smart chunking with code block preservation
- [x] 01-05-integration-PLAN.md — End-to-end pipeline and verification

**Requirements:**
- EPUB-01: System extracts text content from valid EPUB files
- EPUB-02: System preserves chapter/section hierarchy from EPUB TOC
- EPUB-03: System detects and preserves code blocks with language hints
- EPUB-04: System extracts Dublin Core metadata (title, authors, ISBN)
- EPUB-05: System handles tables, converting to searchable text
- CHUNK-01: System splits text into chunks of 400-800 tokens with overlap
- CHUNK-02: System keeps code blocks intact (never splits mid-block)
- CHUNK-03: System preserves chapter/section context per chunk
- CHUNK-04: System labels chunks by content type (text, code, table)
- STORE-02: System tracks books and chunks in SQLite
- STORE-03: System cascades deletes (remove book removes all chunks)
- STORE-04: System stores full text for keyword search (hybrid)

**Success Criteria:**
1. User can run a script that parses a technical EPUB and outputs structured chapter data with code blocks intact
2. Code blocks from Python/JavaScript books retain their original indentation and formatting
3. Chunks containing code are never split mid-function or mid-statement
4. Removing a book from SQLite automatically removes all associated chunks
5. Full chunk text is queryable via SQLite FTS for keyword matching

**Dependencies:** None

---

### Phase 2: Vector Pipeline

**Goal:** System can generate embeddings via Databricks GTE-large-en and store vectors in ChromaDB for semantic search.

**Plans:** 3 plans

Plans:
- [x] 02-01-PLAN.md — Databricks embedding client with retry logic (Wave 1)
- [x] 02-02-PLAN.md — ChromaDB vector store with L2 normalization (Wave 1)
- [x] 02-03-PLAN.md — Integration: wire embeddings into ingest pipeline (Wave 2)

**Requirements:**
- EMBED-01: System generates embeddings via Databricks GTE-large-en API
- EMBED-02: System batches embedding requests (50 texts per batch)
- EMBED-03: System handles rate limiting with exponential backoff
- EMBED-04: System prefixes queries for BGE instruction format
- STORE-01: System stores vectors in ChromaDB with book/chapter metadata

**Success Criteria:**
1. User can index a book and see vectors stored in ChromaDB with correct metadata
2. Bulk indexing of a 500-chunk book completes without rate limit failures
3. ChromaDB collection persists across process restarts
4. Query embeddings use correct instruction prefix for the embedding model

**Dependencies:** Phase 1 (needs chunks to embed)

---

### Phase 3: Search & MCP

**Goal:** Claude can search the book library via MCP and receive properly attributed results.

**Plans:** 2 plans

Plans:
- [x] 03-01-PLAN.md — Search service with RRF hybrid fusion (Wave 1)
- [x] 03-02-PLAN.md — FastMCP server with search/list/info tools (Wave 2)

**Requirements:**
- SRCH-01: System performs semantic search returning top-k relevant chunks
- SRCH-02: System supports filtering by book
- SRCH-03: System supports filtering by content type (text/code/table)
- SRCH-04: System returns source attribution (book, chapter, section)
- SRCH-05: System performs keyword search for exact matches
- SRCH-06: System combines semantic and keyword results (hybrid)
- MCP-01: System exposes `search_books` tool via MCP
- MCP-02: System exposes `list_available_books` tool via MCP
- MCP-03: System exposes `get_book_info` tool via MCP
- MCP-04: System supports stdio transport for Claude Desktop/Code
- MCP-05: Search results include chapter/section path in attribution

**Success Criteria:**
1. Claude Desktop can call `search_books` and receive relevant chunks with book/chapter attribution
2. User can ask Claude a technical question and get an answer citing specific books and sections
3. Search results can be filtered to show only code blocks or only a specific book
4. Hybrid search finds exact function names even when semantic meaning differs

**Dependencies:** Phase 2 (needs vectors for semantic search)

---

### Phase 4: CLI & Integration

**Goal:** User can manage their book library via command line and connect Claude to the MCP server.

**Plans:** 1 plan

Plans:
- [x] 04-01-PLAN.md — Typer CLI with add, remove, list, search, serve commands

**Requirements:**
- CLI-01: User can add EPUB via `mnemo add <path>`
- CLI-02: User can remove book via `mnemo remove <book_id>`
- CLI-03: User can list books via `mnemo list`
- CLI-04: User can search via `mnemo search <query>` (for testing)
- CLI-05: User can start MCP server via `mnemo serve`

**Success Criteria:**
1. User can add a book with `mnemo add book.epub` and see it indexed with progress feedback
2. User can remove a book and confirm all chunks are deleted via `mnemo list`
3. User can test search quality via `mnemo search "how to handle exceptions"` before connecting Claude
4. User can start MCP server and configure Claude Desktop to connect to it

**Dependencies:** Phase 3 (CLI wraps all functionality)

---

## Coverage Validation

All v1 requirements mapped: **Yes**
Unmapped: **None**

| Category | Requirements | Phase |
|----------|--------------|-------|
| EPUB Parsing | EPUB-01, EPUB-02, EPUB-03, EPUB-04, EPUB-05 | 1 |
| Chunking | CHUNK-01, CHUNK-02, CHUNK-03, CHUNK-04 | 1 |
| Embedding | EMBED-01, EMBED-02, EMBED-03, EMBED-04 | 2 |
| Storage | STORE-01 | 2 |
| Storage | STORE-02, STORE-03, STORE-04 | 1 |
| Search | SRCH-01, SRCH-02, SRCH-03, SRCH-04, SRCH-05, SRCH-06 | 3 |
| MCP Server | MCP-01, MCP-02, MCP-03, MCP-04, MCP-05 | 3 |
| CLI | CLI-01, CLI-02, CLI-03, CLI-04, CLI-05 | 4 |

**Total: 33/33 requirements mapped**

---

## Progress

| Phase | Status | Progress |
|-------|--------|----------|
| 1 - Foundation | Complete | 100% |
| 2 - Vector Pipeline | Complete | 100% (3/3 plans) |
| 3 - Search & MCP | Complete | 100% (2/2 plans) |
| 4 - CLI & Integration | Complete | 100% (1/1 plans) |

---
*Roadmap created: 2026-01-19*
*Phase 1 completed: 2026-01-20*
*Phase 2 completed: 2026-01-21*
*Phase 3 completed: 2026-01-24*
*Phase 4 completed: 2026-02-03*
