# Requirements: Mnemo v1.1 Book Management

**Defined:** 2026-02-11
**Core Value:** Ask Claude a question, get answers from your book collection.

## v1.1 Requirements

Requirements for book management MCP tools. Each maps to roadmap phases.

### Ingestion

- [x] **INGEST-01**: Claude can add an EPUB by absolute file path via `add_book` MCP tool
- [x] **INGEST-02**: `add_book` validates file exists and has `.epub` extension
- [x] **INGEST-03**: `add_book` detects duplicates via file_hash and returns error with existing book ID
- [x] **INGEST-04**: `add_book` accepts `force=true` to re-index an existing book
- [x] **INGEST-05**: `add_book` returns book ID, title, authors, and chunk count on success

### Removal

- [x] **REMOVE-01**: Claude can remove a book by ID via `remove_book` MCP tool
- [x] **REMOVE-02**: `remove_book` cascade deletes book, chunks (SQLite), and vectors (ChromaDB)
- [x] **REMOVE-03**: `remove_book` returns not-found error for invalid book_id

### Metadata

- [x] **META-01**: Claude can update book title via `update_book_metadata` MCP tool
- [x] **META-02**: Claude can update book authors via `update_book_metadata` MCP tool
- [x] **META-03**: Claude can update book ISBN via `update_book_metadata` MCP tool
- [x] **META-04**: `update_book_metadata` requires at least one field provided
- [x] **META-05**: `update_book_metadata` returns updated book info on success
- [x] **META-06**: `update_book_metadata` returns not-found error for invalid book_id
- [x] **META-07**: Metadata changes reflected in search results and `get_book_info`

### Tool Quality

- [x] **TOOL-01**: New tools annotated (`destructiveHint` on remove, `idempotentHint` on update)
- [x] **TOOL-02**: Existing read-only tools annotated with `readOnlyHint=True`
- [x] **TOOL-03**: All tools return structured error strings matching existing convention
- [x] **TOOL-04**: All tools have LLM-tuned docstrings for tool discovery

## Future Requirements

Deferred to later milestones.

### Path Security

- **PATH-01**: `add_book` restricts file paths to configured `MNEMO_BOOKS_DIR`
- **PATH-02**: `MNEMO_BOOKS_DIR` env var configures allowed ebook directory

### Extended Metadata

- **EMETA-01**: Tags/genre/comment fields on books
- **EMETA-02**: External metadata lookup via Open Library or Google Books API

### Bulk Operations

- **BULK-01**: Scan books directory for unindexed EPUBs
- **BULK-02**: Bulk import multiple EPUBs in one operation

### Progress Reporting

- **PROG-01**: `add_book` reports progress stages (parsing, chunking, embedding) via MCP progress notifications

## Out of Scope

| Feature | Reason |
|---------|--------|
| PDF support | Different parser needed, EPUB only for now |
| Modifying source .epub files | Read-only by design, safety constraint |
| New database or storage system | SQLite + ChromaDB sufficient |
| Web UI for book management | Claude is the interface |
| Re-embedding after metadata change | Expensive, rarely needed, chunk metadata doesn't include title/author |
| Interactive confirmation in tools | MCP tools are request-response, confirmation is client's responsibility |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INGEST-01 | Phase 6 | Complete |
| INGEST-02 | Phase 6 | Complete |
| INGEST-03 | Phase 6 | Complete |
| INGEST-04 | Phase 6 | Complete |
| INGEST-05 | Phase 6 | Complete |
| REMOVE-01 | Phase 6 | Complete |
| REMOVE-02 | Phase 6 | Complete |
| REMOVE-03 | Phase 6 | Complete |
| META-01 | Phase 5 | Complete |
| META-02 | Phase 5 | Complete |
| META-03 | Phase 5 | Complete |
| META-04 | Phase 5 | Complete |
| META-05 | Phase 5 | Complete |
| META-06 | Phase 5 | Complete |
| META-07 | Phase 5 | Complete |
| TOOL-01 | Phase 7 | Complete |
| TOOL-02 | Phase 7 | Complete |
| TOOL-03 | Phase 7 | Complete |
| TOOL-04 | Phase 7 | Complete |

**Coverage:**
- v1.1 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0

---
*Requirements defined: 2026-02-11*
*Last updated: 2026-02-17 after Phase 7 completion*
