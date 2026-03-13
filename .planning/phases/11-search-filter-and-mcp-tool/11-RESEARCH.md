# Phase 11: Search Filter and MCP Tool - Research

**Researched:** 2026-03-13
**Domain:** Python search filtering, SQLite query design, FastMCP tool registration
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SRCH-01 | Section filter matches against the full hierarchy path (e.g., "Chapter 5" matches chunks under any subsection of Chapter 5) | Current filter checks individual path elements; needs to also match the joined path string to catch cross-level matches |
| TOOL-01 | New `get_book_structure` MCP tool returns the section hierarchy for a book | SQLite has all needed data; distinct `section_path` values in sequence order give the full structure |

</phase_requirements>

## Summary

Phase 11 has two tightly scoped changes: a one-line fix to the search section filter, and a new read-only MCP tool. Both changes operate entirely within existing infrastructure — no schema changes, no new dependencies, no new abstractions.

**SRCH-01** is a search filter precision fix. The existing filter (`any(section_lower in s.lower() for s in r.section_path)`) already handles hierarchy for the common case, but it compares the filter term against each individual path element in isolation. Joining the path into a single string before matching ("Chapter 5 > Section 5.2") makes the match more robust and covers partial cross-level inputs. The success criteria confirms the intent: "all subsections of Chapter 5" must match when filtering by "Chapter 5", which the join-based approach handles correctly.

**TOOL-01** adds a `get_book_structure` tool that reads distinct `section_path` values from SQLite in reading order and renders them as an indented markdown hierarchy. The implementation pattern mirrors existing read-only tools: `_get_book_structure_impl` function tested directly, `@mcp.tool` decorator delegates to it, `ToolAnnotations(readOnlyHint=True)` applied, and a `TestToolAnnotations` test added.

**Primary recommendation:** Fix SRCH-01 by joining `section_path` into a single string before substring matching. Implement TOOL-01 by querying `SELECT DISTINCT section_path FROM chunks WHERE book_id=?` ordered by first-occurrence `sequence`, then rendering indented output from the list depth.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlite3 | stdlib | Query chunks table for structure | Already used throughout; no ORM needed |
| FastMCP | <3.0 | MCP tool registration | Pinned project dependency |
| mcp.types.ToolAnnotations | current | readOnlyHint annotation | Used by all existing read-only tools |

No new dependencies required. This is confirmed by REQUIREMENTS.md: "New dependencies — All features achievable with current stack".

## Architecture Patterns

### Existing Tool Pattern (replicate exactly)
All MCP tools follow this structure:
1. `_tool_name_impl(...)` — pure function, no global state, returns `str`
2. `@mcp.tool(annotations=ToolAnnotations(...))` decorator wraps it
3. Decorated function delegates to impl: `return _tool_name_impl(...)`
4. Tests call `_tool_name_impl` directly — no MCP runtime needed

### Existing Section Filter Location
`mnemo/search/service.py`, lines 134-139:
```python
if section:
    section_lower = section.lower()
    results = [
        r for r in results
        if r.section_path and any(section_lower in s.lower() for s in r.section_path)
    ]
```

### SRCH-01 Fix Pattern
Change the filter to join the full path list before matching:
```python
if section:
    section_lower = section.lower()
    results = [
        r for r in results
        if r.section_path and section_lower in " > ".join(r.section_path).lower()
    ]
```

This is a single-line change. The join separator " > " is consistent with how the MCP output formats section paths (see `_format_search_results` and `_get_book_chunks_impl` in tools.py, both use `" > ".join(chunk.section_path)`).

**Why join is better than any():** The join-based check is strictly more capable — any term that matched with `any()` also matches with join (the individual elements are substrings of the joined string). Additionally, join handles cross-level matches (e.g., "Chapter 5 > Section 5") that `any()` cannot.

### TOOL-01 Implementation Pattern

The tool needs unique section paths in document reading order. The `sequence` column provides reading order. Since multiple chunks share the same `section_path`, we want the FIRST occurrence's sequence:

```python
# SQLite query to get unique section paths in reading order
rows = conn.execute(
    """
    SELECT section_path, MIN(sequence) as first_seq
    FROM chunks
    WHERE book_id = ?
    GROUP BY section_path
    ORDER BY first_seq
    """,
    (book_id,),
).fetchall()
```

This uses `GROUP BY section_path` (since section_path is stored as a JSON string, grouping by it gives distinct paths) and `MIN(sequence)` to order by first appearance.

### Indented Hierarchy Rendering
Convert the list depth to indentation:

```python
import json

def _render_section_hierarchy(rows) -> str:
    lines = []
    for row in rows:
        sp = json.loads(row["section_path"])
        if not sp:
            continue
        depth = len(sp) - 1  # 0-indexed depth
        indent = "  " * depth
        label = sp[-1]  # leaf section name
        lines.append(f"{indent}- {label}")
    return "\n".join(lines)
```

This produces output like:
```
- Building AI Agents with LLMs...
  - Part I: Foundations
    - Chapter 1: Introduction
    - Chapter 2: LLM Basics
  - Part II: Advanced Topics
```

### Recommended Project Structure (no changes needed)
The new tool is added alongside existing tools in:
```
src/mnemo/mcp/tools.py      # Add _get_book_structure_impl + @mcp.tool
tests/test_mcp.py            # Add TestGetBookStructure + update TestToolAnnotations
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Unique section paths in order | Custom dedup loop with OrderedDict | SQL `GROUP BY section_path + MIN(sequence)` | DB handles dedup efficiently, same pattern used in existing queries |
| Tree/nested structure | Recursive tree builder | Flat list with depth from `len(section_path)` | Section paths already encode depth; flat list with indent is sufficient and already used by other tools |
| Section name normalization | String cleanup logic | Use section_path as-is from DB | Data is already clean from ingest; don't add fragile post-processing |

## Common Pitfalls

### Pitfall 1: GROUP BY on JSON string vs parsed value
**What goes wrong:** `GROUP BY section_path` groups by the JSON string representation. Since we always use `json.dumps(list)` for storage, identical paths produce identical JSON strings — so this works correctly. However, lists with different ordering of the same elements would NOT group together (not a real concern here since paths are ordered).
**How to avoid:** Trust the existing storage pattern: `json.dumps(chunk.section_path)` is used in `add_many`, and `GROUP BY` on the raw JSON column is correct.

### Pitfall 2: test_server_imports_without_side_effects assertion
**What goes wrong:** There is a pre-existing test failure `assert mcp.name == "mnemo"` that fails because the server now includes the version in the name (`"mnemo v1.2.1"`). Adding `get_book_structure` adds another registered tool, which would cause `test_tools_registered` to fail if the test checks for exactly 7 tools (or any exact count).
**How to avoid:** `test_tools_registered` currently checks for the presence of specific named tools with `assert "tool_name" in tool_names` — it does not assert an exact count. Add `assert "get_book_structure" in tool_names` to that test. Do NOT fix the unrelated `mcp.name` assertion — that's a pre-existing issue.

### Pitfall 3: Empty section_path rows
**What goes wrong:** Some chunks have `section_path = []` (7 rows in real data). Including them in book structure output would produce an empty line or crash `sp[-1]`.
**How to avoid:** Filter in SQL (`WHERE section_path != '[]'`) or in Python (`if not sp: continue`). Both work; SQL filter is cleaner.

### Pitfall 4: book_id validation
**What goes wrong:** `get_book_structure` must validate the book_id format (6-char hex) and return an error if the book doesn't exist. Existing tools all follow this pattern.
**How to avoid:** Follow the exact validation used by `_get_book_info_impl`:
```python
if not book_id or len(book_id) != 6:
    return "Error: book_id must be a 6-character identifier"
book = book_repo.get(book_id)
if not book:
    return f"Error: Book not found: {book_id}"
```

### Pitfall 5: SRCH-01 test coverage gap
**What goes wrong:** The existing `TestSectionFilter` tests test the `any()` approach which passes today. After changing to join-based matching, those tests still pass (join is a superset), but the NEW capability (matching cross-level strings) would be untested.
**How to avoid:** Add a test that verifies the join-based behavior: filter for a parent section name ("Deep reinforcement learning") returns chunks from ALL subsections, including deeply nested ones. The existing data in real books shows 3-level hierarchies.

## Code Examples

### SRCH-01: One-line fix in service.py (source: direct code inspection)
```python
# BEFORE (service.py line 135-139)
if section:
    section_lower = section.lower()
    results = [
        r for r in results
        if r.section_path and any(section_lower in s.lower() for s in r.section_path)
    ]

# AFTER
if section:
    section_lower = section.lower()
    results = [
        r for r in results
        if r.section_path and section_lower in " > ".join(r.section_path).lower()
    ]
```

### TOOL-01: Full implementation skeleton (source: project code patterns)
```python
def _get_book_structure_impl(book_id: str) -> str:
    """Get book structure implementation - see get_book_structure for docs."""
    logger.info(f"get_book_structure: book_id={book_id}")

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    try:
        book_repo = _get_book_repo()
        book = book_repo.get(book_id)
        if not book:
            return f"Error: Book not found: {book_id}"

        chunk_repo = _get_chunk_repo()
        # Get distinct section paths in reading order
        rows = chunk_repo.get_section_structure(book_id)

        if not rows:
            return f"## {book.title}\n\nNo sections found."

        lines = [f"## {book.title}", ""]
        for sp in rows:
            if not sp:
                continue
            depth = len(sp) - 1
            indent = "  " * depth
            label = sp[-1]
            lines.append(f"{indent}- {label}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("get_book_structure failed")
        return f"Error: {e}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def get_book_structure(book_id: str) -> str:
    """Get the section hierarchy for a book.

    Returns an indented markdown outline of all sections in a book,
    ordered by reading sequence. Use this before searching to understand
    what chapters or sections exist, then pass a section name to
    search_books to filter results.

    Args:
        book_id: 6-character book identifier (from list_available_books)

    Returns:
        Indented markdown section outline, or an error message starting with "Error:"
    """
    return _get_book_structure_impl(book_id)
```

### ChunkRepository method for structure query
```python
def get_section_structure(self, book_id: str) -> list[list[str]]:
    """Get unique section paths in reading order for a book.

    Args:
        book_id: 6-char hex book identifier

    Returns:
        List of section path lists, ordered by first occurrence in book
    """
    rows = self.conn.execute(
        """
        SELECT section_path, MIN(sequence) as first_seq
        FROM chunks
        WHERE book_id = ? AND section_path != '[]'
        GROUP BY section_path
        ORDER BY first_seq
        """,
        (book_id,),
    ).fetchall()
    return [json.loads(row["section_path"]) for row in rows]
```

### TestToolAnnotations addition (test_mcp.py)
```python
def test_get_book_structure_has_read_only_annotations(self):
    """get_book_structure has readOnlyHint=True."""
    from mnemo.mcp.server import mcp

    tool = mcp._tool_manager._tools["get_book_structure"]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `any(term in s for s in path)` | `term in " > ".join(path)` | Phase 11 | Catches cross-level matches, same runtime cost |
| No structure browsing tool | `get_book_structure` tool | Phase 11 | Claude can orient itself before searching |

**No deprecated items** — both changes extend existing patterns cleanly.

## Open Questions

1. **Should `get_book_structure` deduplicate based on path hierarchy or flat list?**
   - What we know: Current data has max 3 levels and 192 unique paths for one book. Flat indented list is readable.
   - What's unclear: Very deep hierarchies (5+ levels) might be unwieldy for LLM consumption.
   - Recommendation: Start with flat indented list. Cap output if needed (e.g., warn if > 200 sections but include all).

2. **Should SRCH-01 fix also update the existing TestSectionFilter tests?**
   - What we know: Existing tests all pass with both `any()` and join-based approaches.
   - What's unclear: None of the existing tests specifically exercise the join's NEW capability.
   - Recommendation: Add a new test case for the cross-level match scenario; keep existing tests unchanged (they validate that the old behavior is preserved).

3. **Should `get_book_structure` accept an optional depth parameter?**
   - What we know: TOOL-01 success criteria makes no mention of a depth filter.
   - Recommendation: No depth parameter in Phase 11. Keep it simple.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (via pyproject.toml) |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_search.py tests/test_mcp.py -x -q --tb=short` |
| Full suite command | `python -m pytest -x -q --tb=short` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SRCH-01 | Join-based section filter matches parent section name | unit | `python -m pytest tests/test_search.py::TestSectionFilter -x -q` | ✅ (existing class; add new test method) |
| SRCH-01 | Filter returns subsection chunks when parent section name given | unit | `python -m pytest tests/test_search.py::TestSectionFilter::test_section_filter_matches_hierarchy_path -x` | ❌ Wave 0 |
| TOOL-01 | `get_book_structure` returns indented hierarchy | unit | `python -m pytest tests/test_mcp.py::TestGetBookStructure -x -q` | ❌ Wave 0 |
| TOOL-01 | `get_book_structure` has readOnlyHint=True in TestToolAnnotations | unit | `python -m pytest tests/test_mcp.py::TestToolAnnotations -x -q` | ✅ (class exists; add method) |
| TOOL-01 | `get_book_structure` appears in registered tools | unit | `python -m pytest tests/test_mcp.py::TestServerSetup::test_tools_registered -x -q` | ✅ (update existing test) |
| TOOL-01 | ChunkRepository.get_section_structure returns ordered unique paths | unit | `python -m pytest tests/test_storage.py -x -q -k structure` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_search.py tests/test_mcp.py -x -q --tb=short`
- **Per wave merge:** `python -m pytest -x -q --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_search.py::TestSectionFilter::test_section_filter_matches_hierarchy_path` — covers SRCH-01 new behavior (join-based matching for parent section names)
- [ ] `tests/test_mcp.py::TestGetBookStructure` class — covers TOOL-01 (structure output format, book_id validation, empty book handling)
- [ ] `tests/test_storage.py` — add `ChunkRepository.get_section_structure` method test (or inline in `TestGetBookStructure` via mock)
- [ ] Update `tests/test_mcp.py::TestServerSetup::test_tools_registered` to include `"get_book_structure"`
- [ ] Update `tests/test_mcp.py::TestToolAnnotations` with `test_get_book_structure_has_read_only_annotations`

*(No new framework installs needed — pytest already present)*

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `/Users/joel/Code/mnemo/src/mnemo/search/service.py` — filter logic at lines 134-139
- Direct code inspection of `/Users/joel/Code/mnemo/src/mnemo/mcp/tools.py` — all tool implementation patterns
- Direct code inspection of `/Users/joel/Code/mnemo/src/mnemo/storage/repository.py` — ChunkRepository methods
- Direct code inspection of `/Users/joel/Code/mnemo/src/mnemo/storage/database.py` — SQLite schema (section_path JSON column)
- Live DB query against `~/.mnemo/mnemo.db` — confirmed section_path stores full hierarchy list; max depth 3 in real data; 192 unique paths per book

### Secondary (MEDIUM confidence)
- `tests/test_search.py::TestSectionFilter` — confirms existing filter behavior and test patterns
- `tests/test_mcp.py::TestToolAnnotations` — confirms annotation test pattern to replicate

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all libraries already in use
- Architecture: HIGH — both changes follow established patterns exactly
- Pitfalls: HIGH — identified from direct code inspection and live DB queries

**Research date:** 2026-03-13
**Valid until:** 2026-04-13 (stable internal codebase)
