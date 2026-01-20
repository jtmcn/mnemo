# Project State: Mnemo

**Last Updated:** 2026-01-20
**Current Phase:** 1 of 4 (Foundation)
**Overall Progress:** 20%

## Project Reference

See: .planning/PROJECT.md
**Core value:** Ask Claude a question, get answers from your book collection.
**Current focus:** Phase 1: Foundation

## Phase Status

| Phase | Name | Status | Progress |
|-------|------|--------|----------|
| 1 | Foundation | In Progress | 80% (4/5 plans) |
| 2 | Vector Pipeline | Pending | 0% |
| 3 | Search & MCP | Pending | 0% |
| 4 | CLI & Integration | Pending | 0% |

## Current Plan

**Completed:** 01-04-chunker-PLAN.md
**Next:** 01-05-ingestion-PLAN.md

Progress: [████░░░░░░░░░░░░░░░░] 20% (4/~20 total plans)

## Recent Activity

- 2026-01-20: Completed 01-04-chunker (smart chunking with code preservation)
- 2026-01-20: Completed 01-02-epub-parser (EPUB parsing + content type detection)
- 2026-01-20: Completed 01-03-sqlite-storage (SQLite + FTS5 + repositories)
- 2026-01-20: Completed 01-01-project-setup (Python package + data models)
- 2026-01-19: Phase 1 plans created (5 plans)
- 2026-01-19: Roadmap created (4 phases, 33 requirements)
- 2026-01-19: Project initialized

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

### Technical Notes
- Pin FastMCP to `<3` to avoid breaking changes
- Test MCP against Claude Desktop early (Phase 3)
- Publisher-specific EPUB quirks need real-book testing
- Package imports work: `from mnemo.models import Book, Chunk, ContentType`
- Storage imports work: `from mnemo.storage import BookRepository, ChunkRepository, init_db`
- EPUB imports work: `from mnemo.epub import EPUBParser, ContentBlock`
- Chunking imports work: `from mnemo.chunking import Chunker, ChunkerConfig, count_tokens`
- WAL mode enabled for SQLite concurrency

### Open Questions
- Code chunking heuristics need tuning with real data
- Similarity score thresholds need empirical calibration

### Blockers
None

## Session Continuity

**Last session:** 2026-01-20T06:35:46Z
**Stopped at:** Completed 01-04-chunker-PLAN.md
**Resume file:** None

---
*State initialized: 2026-01-19*
*Last updated: 2026-01-20*
