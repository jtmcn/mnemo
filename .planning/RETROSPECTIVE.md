# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.2 — RAG Improvements

**Shipped:** 2026-03-10
**Phases:** 2 | **Plans:** 5

### What Was Built
- ChromaDB cosine distance migration with CLI command and similarity scores
- Configurable chunk sizes per book with validation
- EPUB path storage for future re-indexing
- Section-based filtering on search results
- Context window expansion with section-boundary awareness and deduplication
- `get_book_chunks` MCP tool for contiguous deep reading

### What Worked
- Test-first approach (failing tests before implementation) caught edge cases early
- Zero new runtime dependencies — all features built on existing stack
- 3-day milestone execution with clean audit (18/18 requirements)
- Post-filter with over-fetch pattern for section filtering was simple and effective
- Research phase correctly deferred semantic chunking (mixed benchmarks, not worth complexity)

### What Was Inefficient
- Nyquist VALIDATION.md not formally signed off despite tests existing — process gap
- ROADMAP plan checkboxes for Phase 9 left unchecked (cosmetic, caught by audit)
- Phase 9 progress table row in ROADMAP had formatting inconsistency

### Patterns Established
- Two-phase collection migration (old→temp→final) for safe ChromaDB distance metric changes
- Post-filter with over-fetch (3x) for metadata filtering that can't be done in the vector store
- Section-boundary walking for context expansion (stop on first mismatch)
- Context window clamping (0-3) to prevent MCP response explosion

### Key Lessons
1. ChromaDB silently ignores distance metric changes on existing collections — always verify with explicit migration
2. Keeping features zero-dependency dramatically reduces integration risk and speeds delivery
3. Over-fetch + post-filter is a pragmatic pattern when the storage layer can't filter natively

### Cost Observations
- Sessions: ~4
- Notable: Fastest milestone yet (3 days vs 7 for v1.1, 15 for v1.0) — compound familiarity with codebase

---

## Milestone: v1.3 — Quality & Polish

**Shipped:** 2026-03-16
**Phases:** 4 | **Plans:** 5

### What Was Built
- EPUB text extraction fix preserving word boundaries across inline HTML elements
- Author semicolon splitting and cleanup in metadata extraction
- Front-matter section label inference from spine item filenames
- Hierarchy-aware section filter matching full path (not just leaf name)
- `get_book_structure` MCP tool for browsing section hierarchy from SQLite
- Enriched search result formatting with MATCH/Context labels and --- separators
- Audit gap closure: verification docs, SUMMARY frontmatter, stale test fixes

### What Worked
- Surgical scope — 4 phases, zero new dependencies, zero schema changes
- TDD approach continued to catch edge cases (28+ new tests added)
- Milestone audit process caught documentation gaps that Phase 13 closed
- Research phases correctly scoped each phase to minimal changes
- FRONT_MATTER_STEMS heuristic approach — extensible without complexity

### What Was Inefficient
- Phase 13 (Audit Gap Closure) was entirely documentation/test debt — could have been avoided with stricter SUMMARY frontmatter discipline during Phases 11-12
- Nyquist VALIDATION.md still only in draft status across all 4 phases
- ROADMAP progress table formatting inconsistencies persisted from v1.2 (Phases 11-13 missing milestone column)

### Patterns Established
- `get_text(separator=' ')` on inline elements as canonical fix for HTML word-boundary issues
- Exact + prefix/suffix filename matching for front-matter label inference
- Join-based substring matching for hierarchy-aware filtering (' > '.join path)
- Audit → gap closure phase pattern for milestone completion hygiene

### Key Lessons
1. Documentation gaps compound — fixing SUMMARY frontmatter during execution is cheaper than a gap closure phase
2. The audit → gap closure → re-audit loop is effective but adds ~1 day; front-loading verification reduces it
3. Heuristic-based parsing (FRONT_MATTER_STEMS) works well for personal-scale tools and is easy to extend

### Cost Observations
- Sessions: ~5
- Notable: 4-day milestone, smallest scope yet but high polish impact on user experience

---

## Milestone: v1.4 — Tech Debt Cleanup

**Shipped:** 2026-04-05
**Phases:** 6 | **Plans:** 7

### What Was Built
- Explicit dependency declarations (typer, rich) and configurable MNEMO_LOG_LEVEL
- Versioned schema migration framework with numbered scripts and auto-detection of legacy DBs
- Full backup & restore for SQLite + ChromaDB vectors via CLI commands
- content.py decomposed into _models, _classify, _extract private modules with re-export shim
- MCP tools split into domain modules with service layer and dependency injection
- GitHub Actions CI pipeline with parallel lint/test jobs, 80% coverage enforcement, CI badge

### What Worked
- TDD continued to shine — backup/restore implemented red-green-refactor with round-trip verification
- Re-export shim pattern (content.py, tools.py) enabled major refactors with zero caller changes
- Dependency injection with Optional[None] defaults kept validation-only tests simple
- Research phases correctly identified risks (ChromaDB export format, migration ordering)
- Parallel CI jobs (lint + test) give independent failure signals
- Phase sequencing was well-ordered — each phase built cleanly on the last

### What Was Inefficient
- mypy had 78 pre-existing errors requiring `continue-on-error` — ideally addressed before CI was added
- Nyquist VALIDATION.md still draft/missing across all 6 phases — persistent process gap
- SUMMARY.md one-liner extraction broken — summaries lack clean single-line accomplishment fields
- Phase 14 ROADMAP plan count showed 0/1 despite completion (cosmetic roadmap sync issue)
- `book_service.list_all_books` shipped as dead code — not caught during execution, only by audit

### Patterns Established
- Private module prefix (_models, _classify, _extract) for internal API boundaries
- Re-export shim for backward compatibility during module splits
- _impl functions with Optional deps (default None) for DI + easy test setup
- sqlite3.Connection.backup() for WAL-consolidated snapshots
- Flat tar archive members (no directory prefix) for simple extraction
- Marker-based test exclusion (`@pytest.mark.integration`) for CI vs local

### Key Lessons
1. Refactors that preserve public APIs via re-export shims are virtually risk-free — callers never break
2. Schema migration framework should exist from v1.0 — retrofitting version inference from column presence is fragile
3. mypy adoption is better done incrementally (per-file) than all-at-once — 78 errors is a wall
4. Dead code detection needs active tooling or review during execution, not just post-hoc audit
5. TDD for backup/restore was critical — round-trip tests caught ChromaDB export edge cases immediately

### Cost Observations
- Sessions: ~8
- Notable: Longest milestone (21 days) but most phases (6) and largest structural impact — no new user-facing features but dramatically improved maintainability

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Timeline | Key Change |
|-----------|--------|-------|----------|------------|
| v1.0 MVP | 4 | 11 | 15 days | Initial build, established all patterns |
| v1.1 Book Management | 3 | 5 | 7 days | Added MCP lifecycle tools, first audit |
| v1.2 RAG Improvements | 2 | 5 | 3 days | Advanced RAG, zero new deps |
| v1.3 Quality & Polish | 4 | 5 | 4 days | Parser fixes, search UX, audit gap closure |
| v1.4 Tech Debt Cleanup | 6 | 7 | 21 days | Module decomposition, DI, migrations, backup, CI |

### Cumulative Quality

| Milestone | Source LOC | Test LOC | MCP Tools | Requirements | Coverage |
|-----------|-----------|----------|-----------|-------------|----------|
| v1.0 | 4,097 | 4,197 | 3 | 33 | — |
| v1.1 | 4,458 | 5,053 | 6 | 19 | — |
| v1.2 | 5,135 | 6,583 | 7 | 18 | — |
| v1.3 | 5,360 | ~7,800 | 8 | 6 | — |
| v1.4 | 7,628 | ~10,000 | 10 | 17 | 83.24% |

### Top Lessons (Verified Across Milestones)

1. Test-first approach consistently catches edge cases and validates requirements
2. Zero or minimal new dependencies accelerates delivery and reduces risk
3. Simple patterns (over-fetch, clamping, lazy init) outperform complex abstractions at personal scale
4. Re-export shims make large refactors safe — verified across content.py (v1.4) and tools.py (v1.4) splits
