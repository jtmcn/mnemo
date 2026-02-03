# Requirements: Mnemo

**Defined:** 2026-01-19
**Core Value:** Ask Claude a question, get answers from your book collection.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### EPUB Parsing

- [x] **EPUB-01**: System extracts text content from valid EPUB files
- [x] **EPUB-02**: System preserves chapter/section hierarchy from EPUB TOC
- [x] **EPUB-03**: System detects and preserves code blocks with language hints
- [x] **EPUB-04**: System extracts Dublin Core metadata (title, authors, ISBN)
- [x] **EPUB-05**: System handles tables, converting to searchable text

### Chunking

- [x] **CHUNK-01**: System splits text into chunks of 400-800 tokens with overlap
- [x] **CHUNK-02**: System keeps code blocks intact (never splits mid-block)
- [x] **CHUNK-03**: System preserves chapter/section context per chunk
- [x] **CHUNK-04**: System labels chunks by content type (text, code, table)

### Embedding

- [x] **EMBED-01**: System generates embeddings via Databricks GTE-large-en API
- [x] **EMBED-02**: System batches embedding requests (50 texts per batch)
- [x] **EMBED-03**: System handles rate limiting with exponential backoff
- [x] **EMBED-04**: System uses appropriate query format for embedding model (GTE requires no prefix)

### Storage

- [x] **STORE-01**: System stores vectors in ChromaDB with book/chapter metadata
- [x] **STORE-02**: System tracks books and chunks in SQLite
- [x] **STORE-03**: System cascades deletes (remove book removes all chunks)
- [x] **STORE-04**: System stores full text for keyword search (hybrid)

### Search

- [x] **SRCH-01**: System performs semantic search returning top-k relevant chunks
- [x] **SRCH-02**: System supports filtering by book
- [x] **SRCH-03**: System supports filtering by content type (text/code/table)
- [x] **SRCH-04**: System returns source attribution (book, chapter, section)
- [x] **SRCH-05**: System performs keyword search for exact matches
- [x] **SRCH-06**: System combines semantic and keyword results (hybrid)

### MCP Server

- [x] **MCP-01**: System exposes `search_books` tool via MCP
- [x] **MCP-02**: System exposes `list_available_books` tool via MCP
- [x] **MCP-03**: System exposes `get_book_info` tool via MCP
- [x] **MCP-04**: System supports stdio transport for Claude Desktop/Code
- [x] **MCP-05**: Search results include chapter/section path in attribution

### CLI

- [x] **CLI-01**: User can add EPUB via `mnemo add <path>`
- [x] **CLI-02**: User can remove book via `mnemo remove <book_id>`
- [x] **CLI-03**: User can list books via `mnemo list`
- [x] **CLI-04**: User can search via `mnemo search <query>` (for testing)
- [x] **CLI-05**: User can start MCP server via `mnemo serve`

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Search

- **SRCH-07**: System explains why result matched query
- **SRCH-08**: System synthesizes perspectives across multiple books

### Metadata Management

- **META-01**: User can scrub tracking metadata from EPUB before indexing
- **META-02**: System supports HTTP transport for shared deployments

### Reading Integration

- **READ-01**: System imports highlights/annotations from reading apps
- **READ-02**: System tracks reading progress

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| PDF support | EPUB only for v1, Calibre converts if needed |
| Web UI | CLI only, Claude is the interface |
| Multi-user auth | Personal use, single user |
| Book management via MCP | Retrieval only, management via CLI |
| Cloud sync | Local-only, users can use Dropbox themselves |
| Ebook reader | Users have readers they like |
| Format conversion | Calibre does this well |
| DRM handling | Legal complexity, require DRM-free |
| Real-time re-indexing | Batch is fine for ~10 books |
| Automatic book discovery | Not a bookstore |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| EPUB-01 | Phase 1 | Complete |
| EPUB-02 | Phase 1 | Complete |
| EPUB-03 | Phase 1 | Complete |
| EPUB-04 | Phase 1 | Complete |
| EPUB-05 | Phase 1 | Complete |
| CHUNK-01 | Phase 1 | Complete |
| CHUNK-02 | Phase 1 | Complete |
| CHUNK-03 | Phase 1 | Complete |
| CHUNK-04 | Phase 1 | Complete |
| EMBED-01 | Phase 2 | Complete |
| EMBED-02 | Phase 2 | Complete |
| EMBED-03 | Phase 2 | Complete |
| EMBED-04 | Phase 2 | Complete |
| STORE-01 | Phase 2 | Complete |
| STORE-02 | Phase 1 | Complete |
| STORE-03 | Phase 1 | Complete |
| STORE-04 | Phase 1 | Complete |
| SRCH-01 | Phase 3 | Complete |
| SRCH-02 | Phase 3 | Complete |
| SRCH-03 | Phase 3 | Complete |
| SRCH-04 | Phase 3 | Complete |
| SRCH-05 | Phase 3 | Complete |
| SRCH-06 | Phase 3 | Complete |
| MCP-01 | Phase 3 | Complete |
| MCP-02 | Phase 3 | Complete |
| MCP-03 | Phase 3 | Complete |
| MCP-04 | Phase 3 | Complete |
| MCP-05 | Phase 3 | Complete |
| CLI-01 | Phase 4 | Complete |
| CLI-02 | Phase 4 | Complete |
| CLI-03 | Phase 4 | Complete |
| CLI-04 | Phase 4 | Complete |
| CLI-05 | Phase 4 | Complete |

**Coverage:**
- v1 requirements: 33 total
- Mapped to phases: 33
- Unmapped: 0

---
*Requirements defined: 2026-01-19*
*Last updated: 2026-02-03 — Phase 4 requirements complete (all v1 complete)*
