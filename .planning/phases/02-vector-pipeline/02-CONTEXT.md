# Phase 2: Vector Pipeline - Context

**Gathered:** 2026-01-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Generate embeddings via Databricks GTE-large-en API and store vectors in ChromaDB for semantic search. This enables Phase 3's search functionality. User interaction happens through Phase 3 (MCP) and Phase 4 (CLI).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion

User opted for standard implementation patterns. Claude has flexibility on:

**Embedding preparation:**
- Query prefix format for GTE-large-en (instruction-based model)
- Text preprocessing (whitespace normalization, encoding handling)
- Handling chunks that approach token limits

**Rate limit strategy:**
- Exponential backoff timing and max retries
- Batch size optimization (starting point: 50 per batch per requirements)
- Concurrency limits for bulk indexing

**ChromaDB setup:**
- Collection naming convention
- Persistence location (likely alongside SQLite in data directory)
- Metadata schema for book/chapter attribution

**Error recovery:**
- Partial failure handling during bulk embedding
- Whether to support resume-from-checkpoint
- Cleanup behavior on fatal errors

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

**From project decisions (STATE.md):**
- GTE-large-en chosen over BGE (BGE deprecated Feb 2026, GTE has 8192 token context)
- Dual storage architecture (ChromaDB for vectors, SQLite for metadata/FTS)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-vector-pipeline*
*Context gathered: 2026-01-20*
