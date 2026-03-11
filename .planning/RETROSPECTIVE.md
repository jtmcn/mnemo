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

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Timeline | Key Change |
|-----------|--------|-------|----------|------------|
| v1.0 MVP | 4 | 11 | 15 days | Initial build, established all patterns |
| v1.1 Book Management | 3 | 5 | 7 days | Added MCP lifecycle tools, first audit |
| v1.2 RAG Improvements | 2 | 5 | 3 days | Advanced RAG, zero new deps |

### Cumulative Quality

| Milestone | Source LOC | Test LOC | MCP Tools | Requirements |
|-----------|-----------|----------|-----------|-------------|
| v1.0 | 4,097 | 4,197 | 3 | 33 |
| v1.1 | 4,458 | 5,053 | 6 | 19 |
| v1.2 | 5,135 | 6,583 | 7 | 18 |

### Top Lessons (Verified Across Milestones)

1. Test-first approach consistently catches edge cases and validates requirements
2. Zero or minimal new dependencies accelerates delivery and reduces risk
3. Simple patterns (over-fetch, clamping, lazy init) outperform complex abstractions at personal scale
