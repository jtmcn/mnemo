# Requirements: Mnemo v1.1 Book Management

**Defined:** 2026-02-11
**Core Value:** Ask Claude a question, get answers from your book collection.

## v1.1 Requirements

Requirements for book management MCP tools. Each maps to roadmap phases.

### Ingestion

- [ ] **INGEST-01**: Claude can add an EPUB by absolute file path via `add_book` MCP tool
- [ ] **INGEST-02**: `add_book` validates file exists and has `.epub` extension
- [ ] **INGEST-03**: `add_book` detects duplicates via file_hash and returns error with existing book ID
- [ ] **INGEST-04**: `add_book` accepts `force=true` to re-index an existing book
- [ ] **INGEST-05**: `add_book` returns book ID, title, authors, and chunk count on success

### Removal

- [ ] **REMOVE-01**: Claude can remove a book by ID via `remove_book` MCP tool
- [ ] **REMOVE-02**: `remove_book` cascade deletes book, chunks (SQLite), and vectors (ChromaDB)
- [ ] **REMOVE-03**: `remove_book` returns not-found error for invalid book_id

### Metadata

- [ ] **META-01**: Claude can update book title via `update_book_metadata` MCP tool
- [ ] **META-02**: Claude can update book authors via `update_book_metadata` MCP tool
- [ ] **META-03**: Claude can update book ISBN via `update_book_metadata` MCP tool
- [ ] **META-04**: `update_book_metadata` requires at least one field provided
- [ ] **META-05**: `update_book_metadata` returns updated book info on success
- [ ] **META-06**: `update_book_metadata` returns not-found error for invalid book_id
- [ ] **META-07**: Metadata changes reflected in search results and `get_book_info`

### Tool Quality

- [ ] **TOOL-01**: New tools annotated (`destructiveHint` on remove, `idempotentHint` on update)
- [ ] **TOOL-02**: Existing read-only tools annotated with `readOnlyHint=True`
- [ ] **TOOL-03**: All tools return structured error strings matching existing convention
- [ ] **TOOL-04**: All tools have LLM-tuned docstrings for tool discovery

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
| INGEST-01 | Phase 6 | Pending |
| INGEST-02 | Phase 6 | Pending |
| INGEST-03 | Phase 6 | Pending |
| INGEST-04 | Phase 6 | Pending |
| INGEST-05 | Phase 6 | Pending |
| REMOVE-01 | Phase 6 | Pending |
| REMOVE-02 | Phase 6 | Pending |
| REMOVE-03 | Phase 6 | Pending |
| META-01 | Phase 5 | Pending |
| META-02 | Phase 5 | Pending |
| META-03 | Phase 5 | Pending |
| META-04 | Phase 5 | Pending |
| META-05 | Phase 5 | Pending |
| META-06 | Phase 5 | Pending |
| META-07 | Phase 5 | Pending |
| TOOL-01 | Phase 7 | Pending |
| TOOL-02 | Phase 7 | Pending |
| TOOL-03 | Phase 7 | Pending |
| TOOL-04 | Phase 7 | Pending |

**Coverage:**
- v1.1 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0

---
*Requirements defined: 2026-02-11*
*Last updated: 2026-02-11 after roadmap creation*
