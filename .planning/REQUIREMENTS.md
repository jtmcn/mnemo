# Requirements: Mnemo v1.2

**Defined:** 2026-03-08
**Core Value:** Ask Claude a question, get answers from your book collection.

## v1.2 Requirements

Requirements for RAG improvements milestone. Each maps to roadmap phases.

### Infrastructure

- [ ] **INFRA-01**: ChromaDB collection uses cosine distance metric instead of L2
- [ ] **INFRA-02**: Migration script copies existing vectors from L2 collection to new cosine collection without re-embedding
- [ ] **INFRA-03**: Migration verifies vector counts match before deleting old collection
- [x] **INFRA-04**: EPUB file path stored in books table for future re-indexing
- [ ] **INFRA-05**: CLI `migrate-cosine` command runs the collection migration

### Search Quality

- [ ] **SRCH-01**: Search results include numeric relevance scores (cosine similarity 0-1)
- [ ] **SRCH-02**: Context enrichment expands each result with surrounding chunks (configurable window, default 1)
- [ ] **SRCH-03**: Context expansion respects section boundaries (does not cross into different sections)
- [ ] **SRCH-04**: Overlapping expansion windows are deduplicated into a single context block
- [ ] **SRCH-05**: `search_books` MCP tool accepts `context_window` parameter (0 = current behavior)

### Metadata Search

- [ ] **META-01**: `search_books` accepts `section` parameter for substring filtering on section path
- [ ] **META-02**: Section filtering works in all three search modes (keyword, semantic, hybrid)
- [ ] **META-03**: New `get_book_chunks` MCP tool fetches contiguous chunk range by book_id and sequence numbers
- [ ] **META-04**: `get_book_chunks` returns chunks with content, section_path, content_type, and sequence
- [ ] **META-05**: `get_book_chunks` caps range to max 20 chunks per request

### Configurable Chunking

- [x] **CHUNK-01**: `add_book` MCP tool accepts optional `chunk_min_tokens` and `chunk_max_tokens` parameters
- [x] **CHUNK-02**: Chunk size parameters validate: min >= 100, max <= 2000, min < max
- [x] **CHUNK-03**: Default chunk sizes remain 400/800 when not specified (backward compatible)

## Future Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Semantic Chunking

- **SEMCHK-01**: Embedding-distance boundary detection for text blocks
- **SEMCHK-02**: Min/max token guardrails to prevent fragment generation
- **SEMCHK-03**: Configurable threshold for boundary detection sensitivity
- **SEMCHK-04**: CLI `reindex-all` command re-ingests all books from stored EPUB paths

### Advanced Retrieval

- **ADVRT-01**: Cross-encoder re-ranking as optional post-retrieval step
- **ADVRT-02**: Query transformation / expansion for improved recall
- **ADVRT-03**: Hypothetical question generation per chunk at ingest time

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| LLM-based chunking | Expensive per-chunk, overkill for ~10 books |
| Agentic/multi-hop retrieval | Claude naturally multi-turns; tool-chaining adds complexity for marginal gain |
| Parent-child chunk hierarchy | Context enrichment via neighbor expansion achieves same goal more simply |
| Chunk-level summaries/keywords | Embedding captures semantic meaning; redundant for retrieval |
| Automatic re-chunking on config change | Destructive and confusing; users should explicitly re-add |
| GraphRAG / knowledge graph | High complexity, deferred until after search quality baseline is solid |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 8 | Pending |
| INFRA-02 | Phase 8 | Pending |
| INFRA-03 | Phase 8 | Pending |
| INFRA-04 | Phase 8 | Complete |
| INFRA-05 | Phase 8 | Pending |
| SRCH-01 | Phase 8 | Pending |
| SRCH-02 | Phase 9 | Pending |
| SRCH-03 | Phase 9 | Pending |
| SRCH-04 | Phase 9 | Pending |
| SRCH-05 | Phase 9 | Pending |
| META-01 | Phase 9 | Pending |
| META-02 | Phase 9 | Pending |
| META-03 | Phase 9 | Pending |
| META-04 | Phase 9 | Pending |
| META-05 | Phase 9 | Pending |
| CHUNK-01 | Phase 8 | Complete |
| CHUNK-02 | Phase 8 | Complete |
| CHUNK-03 | Phase 8 | Complete |

**Coverage:**
- v1.2 requirements: 18 total
- Mapped to phases: 18
- Unmapped: 0

---
*Requirements defined: 2026-03-08*
*Last updated: 2026-03-09 after roadmap creation*
