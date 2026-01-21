# Project State: Mnemo

**Last Updated:** 2026-01-21
**Current Phase:** 2 of 4 (Vector Pipeline) - COMPLETE
**Overall Progress:** 50%

## Project Reference

See: .planning/PROJECT.md
**Core value:** Ask Claude a question, get answers from your book collection.
**Current focus:** Phase 2 Complete - Ready for Phase 3

## Phase Status

| Phase | Name | Status | Progress |
|-------|------|--------|----------|
| 1 | Foundation | **Complete** | 100% (5/5 plans) |
| 2 | Vector Pipeline | **Complete** | 100% (3/3 plans) |
| 3 | Search & MCP | Pending | 0% |
| 4 | CLI & Integration | Pending | 0% |

## Current Plan

**Completed:** 02-03-PLAN.md (Integration: wire embeddings into ingest)
**Next:** Phase 3 - Search & MCP

Progress: [████████░░░░░░░░░░░░] 50% (8/16 total plans)

## Recent Activity

- 2026-01-21: Completed 02-03 (Integration: wire embeddings into ingest pipeline)
- 2026-01-21: Completed 02-02 (ChromaDB vector store with L2 normalization)
- 2026-01-21: Completed 02-01 (Databricks embedding client with retry logic)
- 2026-01-20: Completed 01-05-integration (end-to-end pipeline + 99 tests)
- 2026-01-20: Completed 01-04-chunker (smart chunking with code preservation)

## Phase 2 Complete

**Vector Pipeline - Complete**

| Plan | Name | Key Deliverable | Status |
|------|------|-----------------|--------|
| 02-01 | Embedding Client | DatabricksEmbedder with retry logic | **Complete** |
| 02-02 | Vector Store | ChromaDB with L2 normalization | **Complete** |
| 02-03 | Integration | Wire embeddings into ingest pipeline | **Complete** |

**New imports available:**
```python
from mnemo import ingest_book, embed_book, remove_book
from mnemo.embeddings import DatabricksEmbedder, EmbeddingConfig
from mnemo.vectors import VectorStore, VectorConfig, QueryResult
```

## Accumulated Context

### Key Decisions
| Decision | Rationale | Date |
|----------|-----------|------|
| GTE-large-en over BGE | BGE deprecated Feb 2026, GTE has 8192 token context | 2026-01-19 |
| Code-aware chunking Phase 1 | Cannot be retrofitted, critical for technical books | 2026-01-19 |
| Dual storage (ChromaDB + SQLite) | Avoid ChromaDB metadata limits, enable FTS | 2026-01-19 |
| 6-char hex book ID | SHA256 of content+title+author, collision-resistant at personal scale | 2026-01-20 |
| Hatchling build system | Modern, simple, well-maintained Python packaging | 2026-01-20 |
| Pydantic computed_field | Used for Chunk.is_code property (v2 best practice) | 2026-01-20 |
| FTS5 with auto-sync triggers | Ensures index consistency without explicit management | 2026-01-20 |
| Quote-wrapped FTS queries | Simple approach handling all special characters safely | 2026-01-20 |
| Publisher CSS classes for code | O'Reilly/Pragmatic/Manning specific class detection | 2026-01-20 |
| ASCII art heuristic threshold | >15% box chars and >5 total for diagram detection | 2026-01-20 |
| cl100k_base tokenizer | GPT-4/Claude compatible encoding for token counting | 2026-01-20 |
| Atomic code chunks | CODE/DIAGRAM/MATH/TABLE never split regardless of size | 2026-01-20 |
| Duplicate detection by file_hash | Prevents accidental re-indexing of same book | 2026-01-20 |
| force=True for re-indexing | Explicit intent required to replace existing book | 2026-01-20 |
| Sync httpx for embeddings | Simpler than async for CLI/batch context | 2026-01-21 |
| Tenacity retry predicates | Only retry transient failures (429, 5xx, timeout) | 2026-01-21 |
| Explicit embeddings in ChromaDB | No embedding function - embeddings provided explicitly | 2026-01-21 |
| L2 distance with normalization | GTE returns unnormalized vectors, normalize before storage | 2026-01-21 |
| Lazy imports for embeddings | Avoid hard dependency on Databricks credentials | 2026-01-21 |
| 50 chunks per batch | Matches Databricks API recommendation | 2026-01-21 |

### Technical Notes
- Pin FastMCP to `<3` to avoid breaking changes
- Test MCP against Claude Desktop early (Phase 3)
- Publisher-specific EPUB quirks need real-book testing
- WAL mode enabled for SQLite concurrency
- BeautifulSoup XML warning suppressed in pyproject.toml
- GTE-large-en returns unnormalized embeddings - L2 normalize before storage
- ChromaDB PersistentClient stores to ~/.mnemo/chroma by default

### Open Questions
- Code chunking heuristics need tuning with real data
- Similarity score thresholds need empirical calibration (Phase 3)

### Blockers
None

## Session Continuity

**Last session:** 2026-01-21T17:36:23Z
**Stopped at:** Completed Phase 2 (02-03-PLAN.md)
**Resume file:** None

---
*State initialized: 2026-01-19*
*Last updated: 2026-01-21*
