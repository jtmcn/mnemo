# Requirements: Mnemo

**Defined:** 2026-01-19
**Core Value:** Ask Claude a question, get answers from your book collection.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### EPUB Parsing

- [ ] **EPUB-01**: System extracts text content from valid EPUB files
- [ ] **EPUB-02**: System preserves chapter/section hierarchy from EPUB TOC
- [ ] **EPUB-03**: System detects and preserves code blocks with language hints
- [ ] **EPUB-04**: System extracts Dublin Core metadata (title, authors, ISBN)
- [ ] **EPUB-05**: System handles tables, converting to searchable text

### Chunking

- [ ] **CHUNK-01**: System splits text into chunks of 400-800 tokens with overlap
- [ ] **CHUNK-02**: System keeps code blocks intact (never splits mid-block)
- [ ] **CHUNK-03**: System preserves chapter/section context per chunk
- [ ] **CHUNK-04**: System labels chunks by content type (text, code, table)

### Embedding

- [ ] **EMBED-01**: System generates embeddings via Databricks GTE-large-en API
- [ ] **EMBED-02**: System batches embedding requests (50 texts per batch)
- [ ] **EMBED-03**: System handles rate limiting with exponential backoff
- [ ] **EMBED-04**: System prefixes queries for BGE instruction format

### Storage

- [ ] **STORE-01**: System stores vectors in ChromaDB with book/chapter metadata
- [ ] **STORE-02**: System tracks books and chunks in SQLite
- [ ] **STORE-03**: System cascades deletes (remove book removes all chunks)
- [ ] **STORE-04**: System stores full text for keyword search (hybrid)

### Search

- [ ] **SRCH-01**: System performs semantic search returning top-k relevant chunks
- [ ] **SRCH-02**: System supports filtering by book
- [ ] **SRCH-03**: System supports filtering by content type (text/code/table)
- [ ] **SRCH-04**: System returns source attribution (book, chapter, section)
- [ ] **SRCH-05**: System performs keyword search for exact matches
- [ ] **SRCH-06**: System combines semantic and keyword results (hybrid)

### MCP Server

- [ ] **MCP-01**: System exposes `search_books` tool via MCP
- [ ] **MCP-02**: System exposes `list_available_books` tool via MCP
- [ ] **MCP-03**: System exposes `get_book_info` tool via MCP
- [ ] **MCP-04**: System supports stdio transport for Claude Desktop/Code
- [ ] **MCP-05**: Search results include chapter/section path in attribution

### CLI

- [ ] **CLI-01**: User can add EPUB via `mnemo add <path>`
- [ ] **CLI-02**: User can remove book via `mnemo remove <book_id>`
- [ ] **CLI-03**: User can list books via `mnemo list`
- [ ] **CLI-04**: User can search via `mnemo search <query>` (for testing)
- [ ] **CLI-05**: User can start MCP server via `mnemo serve`

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
| EPUB-01 | Phase 1 | Pending |
| EPUB-02 | Phase 1 | Pending |
| EPUB-03 | Phase 1 | Pending |
| EPUB-04 | Phase 1 | Pending |
| EPUB-05 | Phase 1 | Pending |
| CHUNK-01 | Phase 1 | Pending |
| CHUNK-02 | Phase 1 | Pending |
| CHUNK-03 | Phase 1 | Pending |
| CHUNK-04 | Phase 1 | Pending |
| EMBED-01 | Phase 2 | Pending |
| EMBED-02 | Phase 2 | Pending |
| EMBED-03 | Phase 2 | Pending |
| EMBED-04 | Phase 2 | Pending |
| STORE-01 | Phase 2 | Pending |
| STORE-02 | Phase 1 | Pending |
| STORE-03 | Phase 1 | Pending |
| STORE-04 | Phase 1 | Pending |
| SRCH-01 | Phase 3 | Pending |
| SRCH-02 | Phase 3 | Pending |
| SRCH-03 | Phase 3 | Pending |
| SRCH-04 | Phase 3 | Pending |
| SRCH-05 | Phase 3 | Pending |
| SRCH-06 | Phase 3 | Pending |
| MCP-01 | Phase 3 | Pending |
| MCP-02 | Phase 3 | Pending |
| MCP-03 | Phase 3 | Pending |
| MCP-04 | Phase 3 | Pending |
| MCP-05 | Phase 3 | Pending |
| CLI-01 | Phase 4 | Pending |
| CLI-02 | Phase 4 | Pending |
| CLI-03 | Phase 4 | Pending |
| CLI-04 | Phase 4 | Pending |
| CLI-05 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 33 total
- Mapped to phases: 33
- Unmapped: 0

---
*Requirements defined: 2026-01-19*
*Last updated: 2026-01-19 after roadmap creation*
