# Project State: Mnemo

**Last Updated:** 2026-01-20
**Current Phase:** 1 of 4 (Foundation)
**Overall Progress:** 5%

## Project Reference

See: .planning/PROJECT.md
**Core value:** Ask Claude a question, get answers from your book collection.
**Current focus:** Phase 1: Foundation

## Phase Status

| Phase | Name | Status | Progress |
|-------|------|--------|----------|
| 1 | Foundation | In Progress | 20% (1/5 plans) |
| 2 | Vector Pipeline | Pending | 0% |
| 3 | Search & MCP | Pending | 0% |
| 4 | CLI & Integration | Pending | 0% |

## Current Plan

**Completed:** 01-01-project-setup-PLAN.md
**Next:** 01-02-epub-parser-PLAN.md

Progress: [█░░░░░░░░░░░░░░░░░░░] 5% (1/~20 total plans)

## Recent Activity

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

### Technical Notes
- Pin FastMCP to `<3` to avoid breaking changes
- Test MCP against Claude Desktop early (Phase 3)
- Publisher-specific EPUB quirks need real-book testing
- Package imports work: `from mnemo.models import Book, Chunk, ContentType`

### Open Questions
- Code chunking heuristics need tuning with real data
- Similarity score thresholds need empirical calibration

### Blockers
None

## Session Continuity

**Last session:** 2026-01-20T06:23:13Z
**Stopped at:** Completed 01-01-project-setup-PLAN.md
**Resume file:** None

---
*State initialized: 2026-01-19*
*Last updated: 2026-01-20*
