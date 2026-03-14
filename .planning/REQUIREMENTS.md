# Requirements: Mnemo

**Defined:** 2026-03-12
**Core Value:** Ask Claude a question, get answers from your book collection.

## v1.3 Requirements

Requirements for the Quality & Polish milestone. Each maps to roadmap phases.

### Parsing

- [x] **PARSE-01**: EPUB text extraction preserves word boundaries across inline HTML elements (no joined words like "astrategy")
- [x] **PARSE-02**: Author names are split on semicolons and cleaned of trailing delimiters (e.g., "Smith; Jones;" → ["Smith", "Jones"])
- [x] **PARSE-03**: Front-matter and TOC content gets a descriptive section label instead of "Unknown section"

### Search

- [x] **SRCH-01**: Section filter matches against the full hierarchy path (e.g., "Chapter 5" matches chunks under any subsection of Chapter 5)

### MCP Tools

- [x] **TOOL-01**: New `get_book_structure` MCP tool returns the section hierarchy for a book
- [x] **TOOL-02**: Context window search results visually delineate matched chunks from surrounding context

## Future Requirements

Deferred from Active to future milestone.

### Advanced RAG

- **RAG-01**: Semantic chunking for text blocks (embedding-distance-based boundary detection)
- **RAG-02**: Cross-encoder re-ranking as optional post-retrieval step
- **RAG-03**: Query transformation / expansion for improved recall

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Re-embedding existing books automatically | Expensive; users re-ingest with `--force` when ready |
| Schema changes to SQLite or ChromaDB | All fixes work with existing data model |
| New dependencies | All features achievable with current stack |
| EPUB format support beyond EPUB | Calibre converts; EPUB-only by design |
| Author name lookup from external APIs | Future milestone |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PARSE-01 | Phase 10 | Complete |
| PARSE-02 | Phase 10 | Complete |
| PARSE-03 | Phase 10 | Complete |
| SRCH-01 | Phase 11 | Complete |
| TOOL-01 | Phase 11 | Complete |
| TOOL-02 | Phase 12 | Complete |

**Coverage:**
- v1.3 requirements: 6 total
- Mapped to phases: 6
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-12*
*Last updated: 2026-03-12 after roadmap creation*
