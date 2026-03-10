---
phase: 08-infrastructure-quick-wins
plan: 01
subsystem: infra
tags: [chromadb, cosine-distance, vector-search, migration, cli]

# Dependency graph
requires:
  - phase: 03-semantic-search
    provides: VectorStore with ChromaDB, SearchService with RRF fusion
provides:
  - ChromaDB cosine distance migration script
  - VectorStore with cosine metric by default
  - CLI migrate-cosine command
  - Real cosine similarity scores in semantic search
affects: [09-search-improvements]

# Tech tracking
tech-stack:
  added: []
  patterns: [cosine-distance-metric, batch-migration-with-verification]

key-files:
  created:
    - src/mnemo/vectors/migrate.py
    - tests/test_migration.py
  modified:
    - src/mnemo/vectors/store.py
    - src/mnemo/cli.py
    - src/mnemo/search/service.py
    - tests/test_vectors.py
    - tests/test_cli.py
    - tests/test_search.py

key-decisions:
  - "Two-phase migration (old->temp->final) to preserve collection name through delete-recreate"
  - "Cosine similarity = max(0, min(1, 1-distance)) with clamping for safety"
  - "Keep L2 normalization in VectorStore._normalize() -- still needed for GTE-large-en embeddings"

patterns-established:
  - "Batch migration with count verification before destructive operations"
  - "Idempotent migration pattern: check metadata before migrating"

requirements-completed: [INFRA-01, INFRA-02, INFRA-03, INFRA-05, SRCH-01]

# Metrics
duration: 6min
completed: 2026-03-10
---

# Phase 8 Plan 1: Cosine Distance Migration Summary

**ChromaDB L2-to-cosine migration with batch copy verification, CLI command, and real similarity scores in semantic search**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-10T16:47:55Z
- **Completed:** 2026-03-10T16:54:00Z
- **Tasks:** 2 (both TDD: RED-GREEN)
- **Files modified:** 8

## Accomplishments
- migrate_to_cosine function handles empty, normal, idempotent, and error cases with batch copy and count verification
- VectorStore creates collections with cosine distance metric by default
- CLI migrate-cosine command with human-readable and JSON output
- Semantic search returns real cosine similarity scores (0-1) instead of RRF placeholders

## Task Commits

Each task was committed atomically (TDD: test then implementation):

1. **Task 1: Migration script and VectorStore cosine** - `decdd05` (test) + `35a38f1` (feat)
2. **Task 2: CLI command and cosine similarity scores** - `c87f4f0` (test) + `f786aa5` (feat)

## Files Created/Modified
- `src/mnemo/vectors/migrate.py` - Batch migration from L2 to cosine with verification
- `src/mnemo/vectors/store.py` - Changed hnsw:space from l2 to cosine
- `src/mnemo/cli.py` - Added migrate-cosine command with --json and --chroma-path
- `src/mnemo/search/service.py` - Cosine similarity scoring in _semantic_search
- `tests/test_migration.py` - 8 tests for migration logic
- `tests/test_vectors.py` - Added cosine metric assertion
- `tests/test_cli.py` - 5 tests for migrate-cosine CLI command
- `tests/test_search.py` - 4 tests for cosine similarity scoring

## Decisions Made
- Two-phase migration (old->temp->final) to preserve collection name through ChromaDB's delete-and-recreate requirement
- Cosine similarity = max(0, min(1, 1-distance)) with clamping for edge cases where distance > 1
- L2 normalization kept in VectorStore._normalize() as GTE-large-en returns unnormalized vectors
- Keyword and hybrid search scoring intentionally unchanged (RRF scores for consistency)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] EphemeralClient shared state in tests**
- **Found during:** Task 1 (migration tests)
- **Issue:** ChromaDB EphemeralClient instances share an in-process database, causing test pollution between migration test cases
- **Fix:** Added cleanup in fixture to delete all collections before each test
- **Files modified:** tests/test_migration.py
- **Verification:** All migration tests pass in sequence
- **Committed in:** 35a38f1 (Task 1 feat commit)

**2. [Rule 1 - Bug] CLI test mock targets incorrect**
- **Found during:** Task 2 (CLI tests)
- **Issue:** Tests patched `mnemo.cli.chromadb` but chromadb is imported inside the function, not at module level
- **Fix:** Changed patch targets to `chromadb.PersistentClient` and `mnemo.vectors.migrate.migrate_to_cosine`
- **Files modified:** tests/test_cli.py
- **Verification:** All CLI migrate tests pass
- **Committed in:** f786aa5 (Task 2 feat commit)

---

**Total deviations:** 2 auto-fixed (2 bugs in test setup)
**Impact on plan:** Both fixes necessary for test correctness. No scope creep.

## Issues Encountered
- Pre-existing test failures in test_mcp.py due to uncommitted chunker config changes (out of scope, not related to this plan)

## User Setup Required
None - no external service configuration required. Users should run `mnemo migrate-cosine` to migrate existing ChromaDB data.

## Next Phase Readiness
- Cosine distance foundation in place for improved search scoring
- Migration command available for existing installations
- Ready for search improvements in next phase

---
*Phase: 08-infrastructure-quick-wins*
*Completed: 2026-03-10*
