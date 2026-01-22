---
phase: 03-search-mcp
plan: 01
subsystem: search
tags: [rrf, hybrid-search, fts5, chromadb]

dependency_graph:
  requires:
    - 01-05 (SQLite storage with FTS5)
    - 02-02 (ChromaDB vector store)
    - 02-01 (Databricks embedder)
  provides:
    - SearchService unified search interface
    - SearchResult with full attribution
    - RRF fusion algorithm
  affects:
    - 03-02 (MCP server will use SearchService)
    - 03-03 (Advanced tools will extend search)

tech_stack:
  added: []
  patterns:
    - Reciprocal Rank Fusion (RRF) with k=60
    - Lazy initialization to avoid import-time side effects
    - Facade pattern for multi-backend coordination
    - Book title caching for repeated lookups

key_files:
  created:
    - src/mnemo/search/__init__.py
    - src/mnemo/search/models.py
    - src/mnemo/search/hybrid.py
    - src/mnemo/search/service.py
    - tests/test_search.py
  modified: []

decisions:
  - id: rrf-k-60
    choice: "Use k=60 for RRF smoothing constant"
    rationale: "Standard in literature (Microsoft, OpenSearch), no tuning needed"
  - id: lazy-search-init
    choice: "Lazy initialization of backends in SearchService"
    rationale: "Avoid credential requirements at import time, match existing pattern"
  - id: 2x-fetch-hybrid
    choice: "Fetch 2x top_k from each backend for hybrid mode"
    rationale: "More candidates for RRF fusion improves result quality"
  - id: rrf-score-fallback
    choice: "Use RRF-style scores (1/(k+rank)) even for single-mode search"
    rationale: "Consistent score semantics across all modes"

metrics:
  duration: "~5 minutes"
  completed: "2026-01-22"
---

# Phase 3 Plan 1: Search Service Summary

**One-liner:** Hybrid search combining FTS5 keyword and ChromaDB semantic search via RRF fusion, with full book/chapter attribution.

## What Was Built

### SearchResult and SearchFilter Models (`models.py`)
- `SearchResult` dataclass with full attribution fields:
  - `chunk_id`, `book_id`, `book_title`, `content`, `content_type`
  - `section_path` (full hierarchy), `score` (RRF), `source` (keyword/semantic/both)
- `SearchFilter` dataclass for optional filters

### RRF Fusion Algorithm (`hybrid.py`)
- `reciprocal_rank_fusion()` function implementing standard RRF
- Formula: `RRF_score(doc) = sum(1/(k + rank))` across ranked lists
- Default k=60 per research literature
- Items in multiple lists score higher automatically

### SearchService (`service.py`)
- Unified interface coordinating FTS5 and ChromaDB backends
- Three search modes:
  - `"keyword"`: FTS5 only
  - `"semantic"`: ChromaDB only
  - `"hybrid"`: Both backends + RRF fusion (default)
- Lazy initialization avoiding import-time side effects
- Book title caching for performance
- Graceful fallback to keyword-only when semantic fails

### Comprehensive Test Suite (`test_search.py`)
- 46 tests, 91% coverage
- RRF unit tests verifying score formula
- SearchService unit tests with mocked backends
- Integration tests with real SQLite storage
- Edge case coverage (empty queries, invalid filters, etc.)

## Key Implementation Details

### Search Flow (Hybrid Mode)
1. Validate inputs, initialize backends lazily
2. Query FTS5 for 2x top_k keyword matches
3. Generate query embedding, query ChromaDB for 2x top_k semantic matches
4. Extract chunk IDs preserving rank order
5. Compute RRF scores merging both lists
6. Sort by score, take top_k results
7. Load book titles (cached), build SearchResult objects

### Attribution Loading
- ChunkRepository provides chunk data (content, section_path, content_type)
- BookRepository provides book metadata (title)
- Results cached per book_id to avoid repeated queries

### Error Handling
- Empty query returns empty list immediately
- Invalid content_type logged as warning, filter ignored
- Semantic search failure triggers fallback to keyword-only
- Missing chunks in ChromaDB logged as warning, skipped

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

| Check | Result |
|-------|--------|
| Unit tests pass | 46 passed, 2 skipped |
| Import chain works | `from mnemo.search import SearchService, SearchResult` OK |
| RRF math correct | Verified via unit tests |
| Attribution populated | Integration tests confirm book_title populated |
| Coverage >80% | 91% achieved |

## Usage Example

```python
from mnemo.search import SearchService

# Create service (lazy init)
service = SearchService()

# Hybrid search (default)
results = service.search("async generators Python", top_k=5)

for r in results:
    print(f"{r.book_title} > {' > '.join(r.section_path)}")
    print(f"  [{r.source}] score={r.score:.4f}")
    print(f"  {r.content[:100]}...")
```

## Next Phase Readiness

### For 03-02 (MCP Server)
- SearchService provides complete search interface
- Results formatted with full attribution
- No import-time side effects (safe for MCP server init)

### For 03-03 (Advanced Tools)
- Search modes allow tool-specific optimization
- Filters support book_id and content_type scoping
- Score field enables relevance-based filtering

## Commits

| Hash | Message |
|------|---------|
| 172b5f9 | feat(03-01): create search models and RRF fusion |
| ae8bbec | feat(03-01): implement SearchService with hybrid search |
| e1ef263 | test(03-01): add comprehensive search module tests |
