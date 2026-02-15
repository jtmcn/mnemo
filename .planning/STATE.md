# Project State: Mnemo

**Last Updated:** 2026-02-14
**Current Phase:** Phase 6 — Book Lifecycle Tools (complete)
**Overall Progress:** v1.0 shipped, v1.1 Phase 6 complete

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-11)

**Core value:** Ask Claude a question, get answers from your book collection.
**Current focus:** v1.1 Book Management — MCP tools for add/remove/edit

## Current Position

Phase: 6 of 7 (Book Lifecycle Tools)
Plan: 2 of 2 in current phase
Status: Phase complete
Last activity: 2026-02-14 — Completed 06-02-PLAN.md (add_book MCP tool)

Progress: [##############......] 70% (14/20 plans complete)

## Performance Metrics

**Velocity:**
- Total plans completed: 14 (11 v1.0 + 3 v1.1)
- Average duration: varies
- Total execution time: ~15 days (v1.0) + 9 min (v1.1 phases 5-6)

**By Phase (v1.0):**

| Phase | Plans | Status |
|-------|-------|--------|
| 1. Foundation | 5 | Complete |
| 2. Vector Pipeline | 3 | Complete |
| 3. Search & MCP | 2 | Complete |
| 4. CLI & Integration | 1 | Complete |

**By Phase (v1.1):**

| Phase | Plans | Status |
|-------|-------|--------|
| 5. Metadata Updates | 1 | Complete |
| 6. Book Lifecycle | 2/2 | Complete |
| 7. Polish | TBD | Not started |

## Accumulated Context

### Decisions
See PROJECT.md for full decision log (11 decisions with outcomes).
Recent decisions affecting current work:

- v1.1: Direct delegation pattern — MCP tools call ingest.py functions directly (no service layer)
- v1.1: Sync tools (def, not async def) — ingest pipeline is sync, no concurrency benefit for STDIO
- v1.1: MNEMO_BOOKS_DIR descoped to future milestone (PATH-01, PATH-02)
- 05-01: isbn="" means "clear ISBN" — empty string normalized to NULL, displayed as "Not available"
- 05-01: Cache invalidation uses _book_cache.clear() (full clear, not selective)
- 06-01: Mock ingest.remove_book in tests (pipeline manages own DB connections, separate from test temp_db)
- 06-01: Pre-deletion info fetch pattern — capture book details before pipeline deletes them
- 06-02: _get_book_repo() for add_book duplicate checking (testability over raw init_db/get_connection)
- 06-02: Async timeout wrapper pattern — asyncio.wait_for(to_thread(sync_fn), timeout=300) for add_book

### Pending Todos
None yet.

### Blockers/Concerns
- Embedding timeout during add_book for large books (30-120s) — mitigated with 5-minute timeout in 06-02
- Code chunking heuristics need tuning with real data (carried from v1.0)

## Session Continuity

Last session: 2026-02-14
Stopped at: Completed 06-02-PLAN.md (add_book MCP tool) — Phase 6 complete
Resume file: None

---
*State initialized: 2026-01-19*
*Last updated: 2026-02-14*
