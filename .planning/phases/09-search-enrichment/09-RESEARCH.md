# Phase 9: Search Enrichment - Research

**Researched:** 2026-03-10
**Domain:** Context expansion, section filtering, contiguous chunk retrieval, SQLite query patterns
**Confidence:** HIGH

## Summary

Phase 9 adds three capabilities to the search system: (1) context window expansion that surrounds each search result with neighboring chunks, (2) section-based filtering for `search_books`, and (3) a new `get_book_chunks` MCP tool for fetching contiguous chunk ranges. All three features are implemented entirely in the existing stack (SQLite, ChromaDB, FastMCP) with zero new dependencies.

The chunks table already has `sequence` (integer ordering within a book), `section_path` (JSON array), `prev_chunk_id`/`next_chunk_id` (linked list), and an index on `(book_id, sequence)`. This means context expansion via sequence-based neighbor lookup is efficient and straightforward. Section filtering uses SQLite `LIKE` on the JSON-serialized `section_path` column. The `get_book_chunks` tool is a simple range query on the existing `(book_id, sequence)` index.

The key design challenge is deduplication when multiple search results are close together and their context windows overlap. This must be handled in the SearchService layer after expansion, merging overlapping windows into contiguous blocks. Section boundary detection uses the `section_path` field -- if a neighbor chunk has a different section path, the expansion stops in that direction.

**Primary recommendation:** Implement in three waves: (1) `get_book_chunks` tool (standalone, no dependencies on other work), (2) section filtering on `search_books`, (3) context window expansion with deduplication. All use existing SQLite indexes and require no schema changes.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SRCH-02 | Context enrichment expands each result with surrounding chunks (configurable window, default 1) | Use `sequence` field + `(book_id, sequence)` index to fetch neighbors. ChunkRepository already has `get_by_book` but needs a targeted range query method. |
| SRCH-03 | Context expansion respects section boundaries | Compare `section_path` of neighbor chunks to matched chunk. Stop expansion when section_path differs. |
| SRCH-04 | Overlapping expansion windows deduplicated into single context block | Post-expansion merge: sort expanded results by (book_id, sequence), merge overlapping ranges. Track which chunk was the original match. |
| SRCH-05 | `search_books` MCP tool accepts `context_window` parameter (0 = current behavior) | Add `context_window: int = 0` parameter to both `_search_books_impl` and the MCP `search_books` tool. Pass through to SearchService. |
| META-01 | `search_books` accepts `section` parameter for substring filtering | Add `section: str \| None = None` to search signature. Filter using `LIKE '%substring%'` on section_path column (stored as JSON string). |
| META-02 | Section filtering works in all three search modes | Apply section filter in SearchService.search() as a post-filter on results, or push down to both FTS and semantic queries. Post-filter is simpler and sufficient for the small result sets. |
| META-03 | New `get_book_chunks` MCP tool fetches contiguous chunk range | New tool in tools.py. Query: `SELECT * FROM chunks WHERE book_id = ? AND sequence BETWEEN ? AND ? ORDER BY sequence LIMIT 20`. |
| META-04 | `get_book_chunks` returns chunks with content, section_path, content_type, sequence | Select specific columns, format as markdown similar to search results but without scores. |
| META-05 | `get_book_chunks` caps range to max 20 chunks per request | Enforce `LIMIT 20` in SQL and validate input range `end - start + 1 <= 20`. |
</phase_requirements>

## Standard Stack

### Core (no changes, no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlite3 | stdlib | Chunk neighbor queries, section filtering, range queries | Already indexed on `(book_id, sequence)` |
| chromadb | 1.4.1 | Semantic search (unchanged) | Already in use |
| fastmcp | existing | New `get_book_chunks` tool registration | Already in use for all MCP tools |
| pydantic | existing | Data models for enriched results | Already in use for Book/Chunk models |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SQLite LIKE for section filter | JSON functions (json_each) | LIKE on serialized JSON is simpler and sufficient; json_each adds complexity for no benefit at this scale |
| Post-filter for section | Push-down to ChromaDB metadata filter | ChromaDB `$contains` on metadata exists but section_path is stored as a JSON string in metadata; SQLite post-filter is more reliable for substring matching |
| prev_chunk_id/next_chunk_id linked list | sequence-based range query | Sequence + index is faster (single range scan) vs. linked list (N individual lookups). Use sequence. |

**Installation:**
```bash
# No new dependencies needed
```

## Architecture Patterns

### Recommended Changes
```
src/mnemo/
  search/
    service.py           # Add context_window + section params to search()
    models.py            # Add context fields to SearchResult (or new EnrichedResult)
  storage/
    repository.py        # Add get_chunk_range() and get_chunks_by_sequence() methods
  mcp/
    tools.py             # Add context_window + section to search_books, add get_book_chunks tool
```

### Pattern 1: Sequence-Based Context Expansion
**What:** Fetch neighboring chunks by sequence number using the existing `(book_id, sequence)` index.
**When to use:** When `context_window >= 1` is requested in search.
**Example:**
```python
# In ChunkRepository - new method
def get_chunk_range(
    self, book_id: str, start_seq: int, end_seq: int, limit: int = 20
) -> list[Chunk]:
    """Fetch contiguous chunks by book_id and sequence range."""
    rows = self.conn.execute(
        """SELECT * FROM chunks
           WHERE book_id = ? AND sequence BETWEEN ? AND ?
           ORDER BY sequence
           LIMIT ?""",
        (book_id, start_seq, end_seq, limit),
    ).fetchall()
    return [self._row_to_chunk(row) for row in rows]
```

### Pattern 2: Section-Boundary-Aware Expansion
**What:** Expand context window but stop at section boundaries.
**When to use:** Context expansion (SRCH-03).
**Example:**
```python
# In SearchService - context expansion logic
def _expand_with_context(
    self, result: SearchResult, window: int
) -> list[Chunk]:
    """Expand a search result with neighboring chunks, stopping at section boundaries."""
    assert self._chunk_repo is not None
    matched_chunk = self._chunk_repo.get(result.chunk_id)
    if matched_chunk is None:
        return []

    book_id = matched_chunk.book_id
    seq = matched_chunk.sequence
    section = matched_chunk.section_path

    # Fetch candidate neighbors
    candidates = self._chunk_repo.get_chunk_range(
        book_id, seq - window, seq + window
    )

    # Filter to same section
    context_chunks = [
        c for c in candidates
        if c.section_path == section
    ]
    return context_chunks
```

### Pattern 3: Overlapping Window Deduplication
**What:** When multiple search results are near each other, their context windows overlap. Merge into contiguous blocks.
**When to use:** After expanding all search results (SRCH-04).
**Example:**
```python
def _deduplicate_context_windows(
    self, expanded_results: list[dict]
) -> list[dict]:
    """Merge overlapping context windows into single blocks.

    Each expanded_result contains:
      - matched_chunk_id: the original search hit
      - chunks: list of Chunk objects (the window)

    Returns merged blocks where overlapping windows are combined,
    preserving which chunks were original matches.
    """
    # Group by book_id, sort by sequence
    # Merge overlapping ranges
    # Track which chunks were original matches vs context
    ...
```

### Pattern 4: Section Filtering via SQLite LIKE
**What:** Filter search results by section path substring.
**When to use:** When `section` parameter is provided (META-01, META-02).
**Example:**
```python
# Option A: Post-filter in SearchService (simpler, recommended)
def search(self, query, ..., section: str | None = None):
    results = self._execute_search(...)  # existing logic
    if section:
        results = [
            r for r in results
            if any(section.lower() in s.lower() for s in r.section_path)
        ]
    return results

# Option B: Push-down to SQL for keyword search
# Add to search_fts query:
#   AND c.section_path LIKE '%substring%'
# This works because section_path is stored as JSON string like
#   '["Chapter 4", "Iterators and Generators"]'
```

**Recommendation:** Use Option A (post-filter) for simplicity. It works across all three modes consistently (META-02). The result sets are small (top_k max 50) so filtering in Python is negligible. For keyword mode, optionally push down to SQL for efficiency, but the post-filter is the primary mechanism for semantic and hybrid modes.

**Important nuance for hybrid/semantic modes with section filtering:** When section filter is active, we should over-fetch from backends (request more than top_k) to account for filtered-out results, then trim to top_k after filtering.

### Pattern 5: get_book_chunks MCP Tool
**What:** New read-only MCP tool for fetching contiguous chunk ranges.
**When to use:** Deep reading of a section after initial search.
**Example:**
```python
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def get_book_chunks(
    book_id: str,
    start_sequence: int,
    end_sequence: int,
) -> str:
    """Fetch contiguous chunks from a book for deep reading.

    Returns up to 20 consecutive chunks between start_sequence and
    end_sequence (inclusive). Use this after search_books to read
    surrounding context or browse a section.

    Args:
        book_id: 6-character book identifier
        start_sequence: First chunk sequence number (inclusive)
        end_sequence: Last chunk sequence number (inclusive)

    Returns:
        Markdown-formatted chunk contents with section paths,
        or an error message starting with "Error:"
    """
    ...
```

### Anti-Patterns to Avoid
- **Using prev_chunk_id/next_chunk_id for context expansion:** Requires N individual lookups in a linked-list traversal. Use the `(book_id, sequence)` index for range queries instead.
- **Returning context chunks as separate SearchResults:** Context chunks should be clearly marked as context, not confused with actual search matches. Use a nested structure or clear delineation.
- **Filtering sections in ChromaDB metadata:** Section paths are stored as JSON strings in ChromaDB metadata. Substring matching on metadata is unreliable across ChromaDB versions. Do section filtering in SQLite/Python.
- **Modifying SearchResult model in-place:** Add new optional fields or a wrapper, don't break existing behavior for `context_window=0`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Range queries on chunks | Manual linked-list traversal via prev/next IDs | SQL `BETWEEN` on `(book_id, sequence)` index | Single indexed range scan vs N point queries |
| Section substring matching | Custom trie or tokenized matching | Python `in` operator or SQL `LIKE` | Section paths are short lists of strings; simple substring match is sufficient |
| Result deduplication | Complex set operations | Sort by (book_id, sequence), merge adjacent ranges | Chunks have natural ordering via sequence number |

## Common Pitfalls

### Pitfall 1: Context Expansion Tripling Response Size
**What goes wrong:** With `context_window=2` and 10 results, response could contain up to 50 chunks of text, overwhelming Claude's context.
**Why it happens:** Each result expands to up to 5 chunks (match + 2 before + 2 after).
**How to avoid:** Default `context_window=0` preserves current behavior. When > 0, consider reducing effective top_k or truncating context chunk content. Document the size implications in tool description.
**Warning signs:** MCP responses exceeding 50KB. Tool descriptions should guide Claude to use small windows.

### Pitfall 2: Section Path Comparison Semantics
**What goes wrong:** Section boundary detection fails because section_path comparison is too strict or too loose.
**Why it happens:** `section_path` is a list like `["Chapter 4", "Iterators and Generators"]`. Comparing full lists means a subsection change (e.g., `["Ch4", "Generators", "Basics"]` vs `["Ch4", "Generators", "Advanced"]`) stops expansion even though they're in the same general section.
**How to avoid:** Compare at the chapter/section level (first 2 elements), not the full path. Or use the deepest common prefix. The requirement says "section boundaries" which implies chapter-level boundaries, not subsection changes.
**Recommendation:** Compare the full section_path list. If they differ at all, the expansion stops. This is the safest interpretation and prevents accidentally mixing content from different subsections. Users can increase `context_window` if they want more.

### Pitfall 3: Off-by-One in Sequence Range
**What goes wrong:** Context window of 1 around sequence=5 should fetch [4,5,6] but fetches [4,5] or [5,6].
**Why it happens:** Inclusive vs exclusive range boundaries in BETWEEN clause.
**How to avoid:** SQLite `BETWEEN` is inclusive on both ends. `sequence BETWEEN 4 AND 6` returns 4, 5, 6. Verify with tests.

### Pitfall 4: Deduplication Losing Match Markers
**What goes wrong:** After merging overlapping windows, the output doesn't indicate which chunks were original search matches vs. context.
**Why it happens:** Naive deduplication treats all chunks equally.
**How to avoid:** Track a set of `matched_chunk_ids` separately from the expanded chunk list. When formatting output, mark matched chunks distinctly (e.g., bold header or `[MATCH]` marker).

### Pitfall 5: Section Filter on Empty section_path
**What goes wrong:** Chunks with empty `section_path` (`[]`) are either always included or always excluded from section-filtered results.
**Why it happens:** Substring match on `"[]"` may behave unexpectedly.
**How to avoid:** If section_path is empty, the chunk should NOT match any section filter (it has no section assignment).

### Pitfall 6: Over-fetching for Section Filter
**What goes wrong:** User requests `section="Chapter 3"` but only 2 of top_k results match, returning sparse results.
**Why it happens:** Post-filtering on a fixed result set.
**How to avoid:** When section filter is active, fetch more results from backends (e.g., `top_k * 3`) before filtering, then trim to requested top_k.

## Code Examples

### ChunkRepository.get_chunk_range (new method)
```python
# Source: Existing codebase patterns, SQLite documentation
def get_chunk_range(
    self,
    book_id: str,
    start_seq: int,
    end_seq: int,
    limit: int = 20,
) -> list[Chunk]:
    """Fetch contiguous chunks by book and sequence range.

    Uses the idx_chunks_sequence index for efficient range scan.

    Args:
        book_id: 6-char hex book identifier
        start_seq: Start sequence (inclusive), clamped to 0
        end_seq: End sequence (inclusive)
        limit: Max chunks to return (default 20)

    Returns:
        List of chunks ordered by sequence
    """
    start_seq = max(0, start_seq)
    rows = self.conn.execute(
        """SELECT * FROM chunks
           WHERE book_id = ? AND sequence BETWEEN ? AND ?
           ORDER BY sequence
           LIMIT ?""",
        (book_id, start_seq, end_seq, limit),
    ).fetchall()
    return [self._row_to_chunk(row) for row in rows]
```

### Context Expansion in SearchService
```python
# Source: Derived from codebase patterns
def _expand_result_context(
    self,
    result: SearchResult,
    window: int,
) -> dict:
    """Expand a single search result with context chunks.

    Returns dict with:
      - matched_chunk_id: str
      - book_id: str
      - start_seq: int
      - end_seq: int
      - chunks: list[Chunk]  (includes match + context)
    """
    assert self._chunk_repo is not None
    chunk = self._chunk_repo.get(result.chunk_id)
    if chunk is None:
        return {"matched_chunk_id": result.chunk_id, "chunks": []}

    seq = chunk.sequence
    candidates = self._chunk_repo.get_chunk_range(
        chunk.book_id, seq - window, seq + window
    )

    # Stop at section boundaries
    section = chunk.section_path
    filtered = []
    for c in candidates:
        if c.section_path == section:
            filtered.append(c)
        elif c.sequence < seq:
            # Before match but different section: reset (only keep contiguous)
            filtered = []
        else:
            # After match and different section: stop
            break

    return {
        "matched_chunk_id": result.chunk_id,
        "book_id": chunk.book_id,
        "start_seq": filtered[0].sequence if filtered else seq,
        "end_seq": filtered[-1].sequence if filtered else seq,
        "chunks": filtered,
    }
```

### Formatting Enriched Results
```python
# Source: Existing _format_search_results pattern in tools.py
def _format_enriched_result(result: SearchResult, context_chunks: list, matched_id: str) -> str:
    """Format a search result with surrounding context.

    Clearly delineates matched chunk from context chunks.
    """
    lines = []
    section = " > ".join(result.section_path) if result.section_path else "Unknown"
    lines.append("---")
    lines.append(f"**Source:** {result.book_title} > {section}")
    lines.append(
        f"**Book ID:** `{result.book_id}` | "
        f"**Type:** {result.content_type} | "
        f"**Match:** {result.source}"
    )
    lines.append("")

    for chunk in context_chunks:
        if chunk.id == matched_id:
            lines.append(f"**>>> MATCHED CHUNK (seq {chunk.sequence}) <<<**")
            lines.append("")
            lines.append(chunk.content)
            lines.append("")
        else:
            lines.append(f"*[context, seq {chunk.sequence}]*")
            lines.append("")
            lines.append(chunk.content)
            lines.append("")

    return "\n".join(lines)
```

### Section Filtering
```python
# Source: Derived from codebase patterns
def _matches_section_filter(section_path: list[str], section_filter: str) -> bool:
    """Check if a section path matches the section filter substring.

    Case-insensitive substring match against any element of the section path.
    """
    filter_lower = section_filter.lower()
    return any(filter_lower in s.lower() for s in section_path)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Return only matched chunk | Return match + surrounding context | This phase | Users can read in context without manual follow-up queries |
| No section filtering | Section substring filter across all modes | This phase | Users can scope searches to specific parts of a book |
| No contiguous reading | `get_book_chunks` for range retrieval | This phase | Claude can fetch consecutive chunks for deep reading |

## Open Questions

1. **Enriched result format: nested vs flat**
   - What we know: SearchResult currently has `content` as a string. Context expansion adds surrounding chunks.
   - What's unclear: Should we add `context_before: list[str]` and `context_after: list[str]` fields to SearchResult, or format everything into a single markdown string?
   - Recommendation: Format into a single markdown string in the MCP tool layer (tools.py). The SearchService can return a richer internal structure, but the MCP output is always a formatted string. This avoids model changes that break backward compatibility.

2. **Over-fetch multiplier for section filtering**
   - What we know: Post-filtering may reduce result count below top_k.
   - What's unclear: How much to over-fetch (2x? 3x?).
   - Recommendation: Use 3x over-fetch when section filter is active. For a personal library of ~10 books, this is negligible performance-wise.

3. **Context window interaction with top_k**
   - What we know: Context expansion increases response size significantly.
   - What's unclear: Whether to auto-reduce top_k when context_window > 0.
   - Recommendation: Do NOT auto-reduce. Let the caller decide. Document in tool description that large windows with large top_k may produce verbose output.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v --tb=short` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SRCH-02 | Context expansion returns neighboring chunks | unit | `python -m pytest tests/test_search.py -x -k context_window` | Wave 0 |
| SRCH-03 | Context stops at section boundaries | unit | `python -m pytest tests/test_search.py -x -k section_boundary` | Wave 0 |
| SRCH-04 | Overlapping windows deduplicated | unit | `python -m pytest tests/test_search.py -x -k dedup` | Wave 0 |
| SRCH-05 | context_window=0 preserves current behavior | unit | `python -m pytest tests/test_search.py -x -k context_window_zero` | Wave 0 |
| META-01 | section parameter filters results | unit | `python -m pytest tests/test_search.py -x -k section_filter` | Wave 0 |
| META-02 | Section filter works in all modes | unit | `python -m pytest tests/test_search.py -x -k section_all_modes` | Wave 0 |
| META-03 | get_book_chunks fetches range | unit | `python -m pytest tests/test_mcp.py -x -k get_book_chunks` | Wave 0 |
| META-04 | get_book_chunks returns expected fields | unit | `python -m pytest tests/test_mcp.py -x -k book_chunks_fields` | Wave 0 |
| META-05 | get_book_chunks caps at 20 | unit | `python -m pytest tests/test_mcp.py -x -k book_chunks_limit` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] New tests in `tests/test_search.py` -- covers SRCH-02, SRCH-03, SRCH-04, SRCH-05, META-01, META-02
- [ ] New tests in `tests/test_mcp.py` -- covers META-03, META-04, META-05
- [ ] New tests in `tests/test_storage.py` -- covers `get_chunk_range` repository method

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/mnemo/search/service.py`, `src/mnemo/storage/repository.py`, `src/mnemo/storage/database.py`, `src/mnemo/mcp/tools.py`, `src/mnemo/models.py`, `src/mnemo/vectors/store.py`
- SQLite documentation: `BETWEEN` clause semantics (inclusive), index usage for range queries
- Existing schema: `idx_chunks_sequence ON chunks(book_id, sequence)` index already exists (verified in database.py)

### Secondary (MEDIUM confidence)
- Phase 8 research: Confirmed cosine distance migration complete, section filtering decision (SQLite, not ChromaDB)
- STATE.md: Confirmed "Context enrichment can triple response size" concern already tracked

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- zero new dependencies, all existing libraries
- Architecture: HIGH -- all patterns derived from existing codebase analysis, verified index existence
- Pitfalls: HIGH -- response size concern already documented in project state; section comparison semantics verified against actual data model

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable stack, no fast-moving dependencies)
