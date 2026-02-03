# Project State: Mnemo

**Last Updated:** 2026-02-03
**Current Phase:** 4 of 4 (CLI & Integration) - COMPLETE
**Overall Progress:** 100%

## Project Reference

See: .planning/PROJECT.md
**Core value:** Ask Claude a question, get answers from your book collection.
**Current focus:** All phases complete - Ready for milestone audit

## Phase Status

| Phase | Name | Status | Progress |
|-------|------|--------|----------|
| 1 | Foundation | **Complete** | 100% (5/5 plans) |
| 2 | Vector Pipeline | **Complete** | 100% (3/3 plans) |
| 3 | Search & MCP | **Complete** | 100% (2/2 plans) |
| 4 | CLI & Integration | **Complete** | 100% (1/1 plans) |

## Current Plan

**Completed:** 04-01-PLAN.md (Typer CLI with 5 commands)
**Next:** Milestone audit

Progress: [████████████████████] 100% (11/11 total plans)

## Recent Activity

- 2026-02-03: Completed 04-01 (Typer CLI with add, remove, list, search, serve)
- 2026-01-24: Completed 03-02 (FastMCP server with MCP tools)
- 2026-01-22: Completed 03-01 (SearchService with RRF hybrid search)
- 2026-01-21: Completed 02-03 (Integration: wire embeddings into ingest pipeline)
- 2026-01-21: Completed 02-02 (ChromaDB vector store with L2 normalization)

## Phase 4 Complete

**CLI & Integration - Complete**

| Plan | Name | Key Deliverable | Status |
|------|------|-----------------|--------|
| 04-01 | CLI Commands | Typer CLI with 5 commands | **Complete** |

**CLI commands available:**
```bash
mnemo add book.epub       # Add EPUB to library with progress spinner
mnemo list                # List indexed books (Rich table)
mnemo list --json         # JSON output mode
mnemo remove <id>         # Remove book by ID
mnemo search "query"      # Search with attribution
mnemo serve               # Start MCP server for Claude
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
| RRF k=60 | Standard smoothing constant per literature | 2026-01-22 |
| Lazy SearchService init | Avoid credential requirements at import time | 2026-01-22 |
| 2x fetch for hybrid | More candidates for RRF fusion improves quality | 2026-01-22 |
| __main__.py for MCP | Avoid circular imports when running as -m | 2026-01-24 |
| Full Python path in config | Claude Desktop has limited PATH | 2026-01-24 |
| print() for JSON output | Rich console adds formatting/wrapping, use plain print | 2026-02-03 |
| Remove nonexistent exits 0 | Idempotent operation, not an error condition | 2026-02-03 |

### Technical Notes
- Pin FastMCP to `<3` to avoid breaking changes
- Publisher-specific EPUB quirks need real-book testing
- WAL mode enabled for SQLite concurrency
- BeautifulSoup XML warning suppressed in pyproject.toml
- GTE-large-en returns unnormalized embeddings - L2 normalize before storage
- ChromaDB PersistentClient stores to ~/.mnemo/chroma by default
- SearchService caches book title lookups for performance
- MCP server runs via `python -m mnemo.mcp` (not mnemo.mcp.server)
- CLI entry point: `mnemo = "mnemo.cli:main"` in pyproject.toml

### Open Questions
- Code chunking heuristics need tuning with real data
- Similarity score thresholds need empirical calibration (ongoing)

### Blockers
None

## Session Continuity

**Last session:** 2026-02-03
**Stopped at:** Completed Phase 4 (CLI & Integration) - All phases complete
**Resume file:** None

---
*State initialized: 2026-01-19*
*Last updated: 2026-02-03*
