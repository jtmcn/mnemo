# Project State: Mnemo

**Last Updated:** 2026-01-20
**Current Phase:** 1 of 4 (Foundation) - COMPLETE
**Overall Progress:** 25%

## Project Reference

See: .planning/PROJECT.md
**Core value:** Ask Claude a question, get answers from your book collection.
**Current focus:** Phase 1 Complete - Ready for Phase 2

## Phase Status

| Phase | Name | Status | Progress |
|-------|------|--------|----------|
| 1 | Foundation | **Complete** | 100% (5/5 plans) |
| 2 | Vector Pipeline | Pending | 0% |
| 3 | Search & MCP | Pending | 0% |
| 4 | CLI & Integration | Pending | 0% |

## Current Plan

**Completed:** 01-05-integration-PLAN.md (Phase 1 complete!)
**Next:** Phase 2 planning needed

Progress: [█████░░░░░░░░░░░░░░░] 25% (5/~20 total plans)

## Recent Activity

- 2026-01-20: Completed 01-05-integration (end-to-end pipeline + 99 tests)
- 2026-01-20: Completed 01-04-chunker (smart chunking with code preservation)
- 2026-01-20: Completed 01-02-epub-parser (EPUB parsing + content type detection)
- 2026-01-20: Completed 01-03-sqlite-storage (SQLite + FTS5 + repositories)
- 2026-01-20: Completed 01-01-project-setup (Python package + data models)
- 2026-01-19: Phase 1 plans created (5 plans)
- 2026-01-19: Roadmap created (4 phases, 33 requirements)
- 2026-01-19: Project initialized

## Phase 1 Completion Summary

**Foundation layer complete with 99 passing tests and 83% code coverage.**

| Plan | Name | Key Deliverable |
|------|------|-----------------|
| 01-01 | Project Setup | Pydantic models (Book, Chunk, ContentType) |
| 01-02 | EPUB Parser | EPUBParser with content type detection |
| 01-03 | SQLite Storage | Repositories + FTS5 search |
| 01-04 | Chunker | Token-based splitting with code preservation |
| 01-05 | Integration | `ingest_book()` end-to-end pipeline |

**All imports work:**
```python
from mnemo.ingest import ingest_book, remove_book
from mnemo.models import Book, Chunk, ContentType
from mnemo.storage import BookRepository, ChunkRepository, init_db
from mnemo.epub import EPUBParser, ContentBlock
from mnemo.chunking import Chunker, ChunkerConfig, count_tokens
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

### Technical Notes
- Pin FastMCP to `<3` to avoid breaking changes
- Test MCP against Claude Desktop early (Phase 3)
- Publisher-specific EPUB quirks need real-book testing
- WAL mode enabled for SQLite concurrency
- BeautifulSoup XML warning suppressed in pyproject.toml

### Open Questions
- Code chunking heuristics need tuning with real data
- Similarity score thresholds need empirical calibration (Phase 2)

### Blockers
None

## Session Continuity

**Last session:** 2026-01-20T07:18:51Z
**Stopped at:** Completed 01-05-integration-PLAN.md (Phase 1 complete)
**Resume file:** None

---
*State initialized: 2026-01-19*
*Last updated: 2026-01-20*
