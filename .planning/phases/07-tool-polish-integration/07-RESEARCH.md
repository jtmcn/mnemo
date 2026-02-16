# Phase 7: Tool Polish & Integration - Research

**Researched:** 2026-02-16
**Domain:** MCP tool annotations, docstring optimization, error convention normalization, lifecycle testing
**Confidence:** HIGH

## Summary

Phase 7 is a polish phase that touches all six existing MCP tools without adding new functionality. The work breaks into four clear domains: (1) adding MCP tool annotations via the `ToolAnnotations` class, (2) improving docstrings for LLM-driven tool discovery, (3) normalizing error string conventions across all tools, and (4) writing a full lifecycle integration test.

The codebase uses FastMCP 2.14.4, which fully supports the `annotations` parameter on `@mcp.tool()`. The `ToolAnnotations` class is imported from `mcp.types` (the underlying MCP SDK). All annotation fields (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) are verified working with both dict and class-based syntax.

The main finding is that the current error convention has several inconsistencies: two tools use different prefixes for the same error type ("Search error:" vs "Error:"), and some "not found" responses lack the "Error:" prefix. The lifecycle test requires mocking the search service and ingest pipeline since the test cannot call the real embedding API.

**Primary recommendation:** Add `ToolAnnotations` to all six `@mcp.tool` decorators, normalize all error returns to use `"Error: "` prefix consistently, enhance docstrings with usage-scenario keywords, and write a lifecycle test using the existing `_impl` function testing pattern with temp DB and mocked services.

## Standard Stack

### Core (already in project, no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastmcp | 2.14.4 (>=2.14,<3) | MCP server framework with `@mcp.tool(annotations=...)` | Already used; annotations param verified working |
| mcp (SDK) | (fastmcp dep) | `mcp.types.ToolAnnotations` class | Provides the official annotation type |

### No New Dependencies
This phase requires **zero new packages**. The `ToolAnnotations` class comes from the `mcp` package which is already an implicit dependency of `fastmcp`. All other work is editing existing code.

**Installation:** None required.

## Architecture Patterns

### Recommended File Changes
```
src/mnemo/mcp/
├── server.py          # No changes needed
└── tools.py           # Modify: add annotations to all 6 @mcp.tool decorators,
                       #         normalize error strings, enhance docstrings

tests/
└── test_mcp.py        # Add: lifecycle test class, annotation verification tests
```

No new files. All changes are modifications to existing files.

### Pattern 1: ToolAnnotations on @mcp.tool Decorator

**What:** Add `annotations=ToolAnnotations(...)` parameter to every `@mcp.tool` decorator.
**When to use:** Every tool registration.
**Verified with:** FastMCP 2.14.4 -- both dict and class-based syntax confirmed working.

```python
# Source: verified locally against FastMCP 2.14.4
from mcp.types import ToolAnnotations

# Read-only tools (3 tools: search_books, list_available_books, get_book_info)
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def search_books(...) -> str:
    ...

# Destructive tool (1 tool: remove_book)
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    )
)
def remove_book(...) -> str:
    ...

# Idempotent mutation tool (1 tool: update_book_metadata)
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def update_book_metadata(...) -> str:
    ...

# Additive mutation tool (1 tool: add_book)
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
async def add_book(...) -> str:
    ...
```

**Key decisions for each tool:**

| Tool | readOnly | destructive | idempotent | openWorld | Rationale |
|------|----------|-------------|------------|-----------|-----------|
| search_books | True | False | -- | False | Pure read; searches local DB/ChromaDB only |
| list_available_books | True | False | -- | False | Pure read; lists from local SQLite |
| get_book_info | True | False | -- | False | Pure read; fetches from local SQLite |
| remove_book | False | **True** | False | False | Permanently deletes data; not idempotent (second call returns "not found") |
| update_book_metadata | False | False | **True** | False | Same update with same args produces same result; modifies but non-destructively |
| add_book | False | False | False | False | Adds new data; not idempotent (second call returns "already exists" error, unless force=true) |

**Note on defaults:** The MCP spec defaults are `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, `openWorldHint=true`. By explicitly setting all fields, we avoid relying on defaults that would incorrectly mark read-only tools as destructive and open-world.

### Pattern 2: Error String Convention (Normalization)

**What:** All error returns from MCP tools MUST start with `"Error: "` (capital E, colon, space).
**Why:** The current codebase has inconsistencies that this phase must fix.

**Current inconsistencies found:**

| Line | Current | Should Be |
|------|---------|-----------|
| 83 | `f"Search error: {e}"` | `f"Error: Search failed: {e}"` |
| 107 | `f"Error listing books: {e}"` | `f"Error: Failed to list books: {e}"` |
| 122 | `f"Book not found: {book_id}"` | `f"Error: Book not found: {book_id}"` |
| 300 | `f"Book not found: {book_id}"` | `f"Error: Book not found: {book_id}"` |

**Correct pattern (already used by most returns):**
```python
# Validation errors
return "Error: book_id must be a 6-character identifier"
return "Error: Query cannot be empty"

# Not-found errors
return f"Error: Book not found: {book_id}"

# Operation errors (caught exceptions)
return f"Error: Search failed: {e}"
return f"Error: Failed to list books: {e}"
```

**Non-error responses that should NOT be changed:**
```python
# These are informational, not errors:
return f"No results found for: {query}"          # search_books - empty results
return "No books indexed yet. Use `mnemo add <path>` to add books."  # list - empty library
```

**Note on isError protocol flag:** FastMCP's `ToolResult` does not expose `isError`. The current pattern of returning error strings (without setting the MCP protocol `isError=True` flag) is the standard approach for FastMCP tools. The `"Error: "` prefix is the LLM-facing signal that an error occurred. This is adequate and consistent with FastMCP's design.

### Pattern 3: LLM-Tuned Docstrings

**What:** Tool docstrings should include scenario keywords that help Claude discover when to use each tool.
**Why:** Claude's tool search matches against names, descriptions, and parameter names. Richer descriptions improve discovery.

**Current docstrings are functional but minimal.** Enhancement strategy:
1. Add a one-sentence "when to use" hint in the description
2. Include common synonyms/keywords the user might say
3. Keep the description concise (not verbose -- tool descriptions consume context)
4. Structure: first sentence = what it does, second sentence = when to use it

```python
# Example enhancement for search_books (current is good, minor keyword additions)
"""Search your book library for relevant content.

Finds passages, code examples, and explanations from your indexed technical
books using hybrid search (combines keyword matching with semantic understanding).
Use this when the user asks about a topic, concept, API, or code pattern that
might be covered in their books.

Args:
    query: Search query - can be natural language questions, specific terms,
           or code patterns
    book_id: Optional 6-char book ID to search within one book only
    content_type: Optional filter - "text", "code", "table", "diagram", or "math"
    top_k: Maximum results to return (default 10, max 50)
    mode: Search mode - hybrid (default, recommended), semantic, or keyword

Returns:
    Markdown-formatted search results with source attribution,
    or an error message starting with "Error:"
"""
```

**Key docstring improvements per tool:**

| Tool | Current Gap | Enhancement |
|------|------------|-------------|
| search_books | No "when to use" guidance | Add scenario: "Use when user asks about topics in their books" |
| list_available_books | Missing connection to book_id usage | Add: "Call this first to discover book IDs for filtering searches" |
| get_book_info | Adequate | Minor: mention it shows ISBN, chunk count, structure info |
| remove_book | Missing permanence emphasis | Add: "This action is permanent and cannot be undone" |
| update_book_metadata | Missing isbn="" semantics in description | Add: "Pass isbn as empty string to clear it" |
| add_book | Missing size/time expectations | Add: "May take 1-5 minutes for large books due to embedding generation" |

### Anti-Patterns to Avoid

- **Over-annotating docstrings:** Don't add multi-paragraph descriptions. Tool descriptions go into the LLM context; keep them focused (3-6 sentences max for the description body).
- **Setting readOnlyHint without setting destructiveHint:** If you set `readOnlyHint=True`, explicitly set `destructiveHint=False` for clarity even though `destructiveHint` is "only meaningful when readOnlyHint is false."
- **Using ToolError for expected errors:** The current pattern of catching exceptions and returning error strings is correct. Don't switch to raising `ToolError` -- that would make errors bubble up as protocol-level errors instead of tool-level results.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tool annotation types | Custom dataclass for annotations | `mcp.types.ToolAnnotations` | Official MCP SDK type, validated by Pydantic |
| Error standardization | Custom exception hierarchy | Convention: `"Error: "` prefix strings | Existing pattern works; FastMCP ToolResult has no isError exposure |
| Lifecycle test orchestration | Custom test runner | pytest class with sequential test methods or single long test | pytest handles setup/teardown; no test framework needed |

## Common Pitfalls

### Pitfall 1: Forgetting to Set openWorldHint=False
**What goes wrong:** MCP spec defaults `openWorldHint` to `True`. All mnemo tools operate on local SQLite/ChromaDB, not external APIs. Leaving the default would incorrectly signal that tools access external systems.
**Why it happens:** Developers assume defaults are sensible for their use case.
**How to avoid:** Explicitly set `openWorldHint=False` on all six tools.
**Warning signs:** Tool annotations show `openWorldHint=None` (meaning default True applies).

### Pitfall 2: Breaking Existing Test Assertions on Error Strings
**What goes wrong:** Changing error message text breaks existing tests that assert on specific strings.
**Why it happens:** Tests like `assert "Error" in result` and `assert "not found" in result.lower()` depend on exact wording.
**How to avoid:** Audit all test assertions BEFORE changing error messages. Update tests in the same commit.
**Warning signs:** Tests in `TestRemoveBookIntegration`, `TestUpdateBookMetadataIntegration`, and others assert on error text.

**Specific tests to audit when normalizing errors:**

| Test | Current Assertion | Error Being Changed |
|------|-------------------|---------------------|
| `test_search_books_handles_exception` | `assert "Search error" in result` | Line 83: `"Search error: {e}"` -> `"Error: Search failed: {e}"` |
| `test_get_book_info_not_found` | `assert "not found" in result.lower()` | Line 122: `"Book not found: {book_id}"` -> `"Error: Book not found: {book_id}"` -- assertion still passes |
| `test_update_nonexistent_book` | `assert "not found" in result.lower()` | Line 300: `"Book not found: {book_id}"` -> `"Error: Book not found: {book_id}"` -- assertion still passes |
| `test_search_books_empty_query` | `assert "Error" in result or "empty" in result.lower()` | No change needed -- already correct |

### Pitfall 3: Lifecycle Test Requiring Real Embeddings
**What goes wrong:** The lifecycle test calls `add_book` which triggers `ingest_book(embed=True)`, requiring Databricks API credentials.
**Why it happens:** The success criterion says "A full lifecycle test passes: add book, search for content, update metadata, verify metadata in search, remove book, verify removal."
**How to avoid:** Mock the ingest pipeline (as done in existing tests). The lifecycle test verifies the MCP tool layer orchestration, not the embedding pipeline (which is tested elsewhere).
**Alternative:** Test at the `_impl` function level with a temp database and mocked `ingest.ingest_book` / `ingest.remove_book`.

### Pitfall 4: Annotation on Async Tool (add_book)
**What goes wrong:** The `add_book` tool is `async def` with a `Context` parameter. Annotations work the same on async tools, but this could be a concern.
**How to avoid:** Verified locally that `@mcp.tool(annotations=...)` works with both sync and async functions in FastMCP 2.14.4. No special handling needed.

### Pitfall 5: Duplicate Error Prefix After Normalization
**What goes wrong:** After adding `"Error: "` prefix to messages that already contain "Error", you get `"Error: Error: ..."`.
**Why it happens:** Some exception messages from lower layers already include "Error" in their text.
**How to avoid:** Use descriptive prefixes like `"Error: Search failed: {e}"` or `"Error: Failed to list books: {e}"` rather than `f"Error: {e}"` where `e` might itself start with "Error".

## Code Examples

### Adding ToolAnnotations Import and Usage
```python
# Source: verified against FastMCP 2.14.4 installed at project
# Add to imports in tools.py:
from mcp.types import ToolAnnotations

# Read-only tool example:
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def search_books(
    query: str,
    book_id: str | None = None,
    content_type: Literal["text", "code", "table", "diagram", "math"] | None = None,
    top_k: int = 10,
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid",
) -> str:
    """Search your book library for relevant content.
    ...
    """
    return _search_books_impl(query, book_id, content_type, top_k, mode)
```

### Verifying Annotations in Tests
```python
# Source: verified locally
def test_read_only_tools_have_annotations(self):
    """Read-only tools should carry readOnlyHint=True."""
    from mnemo.mcp.server import mcp

    read_only_tools = ["search_books", "list_available_books", "get_book_info"]
    for name in read_only_tools:
        tool = mcp._tool_manager._tools[name]
        assert tool.annotations is not None, f"{name} missing annotations"
        assert tool.annotations.readOnlyHint is True, f"{name} should be readOnly"
        assert tool.annotations.openWorldHint is False, f"{name} should not be openWorld"

def test_remove_book_has_destructive_annotation(self):
    """remove_book should carry destructiveHint=True."""
    from mnemo.mcp.server import mcp

    tool = mcp._tool_manager._tools["remove_book"]
    assert tool.annotations is not None
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.readOnlyHint is False

def test_update_book_has_idempotent_annotation(self):
    """update_book_metadata should carry idempotentHint=True."""
    from mnemo.mcp.server import mcp

    tool = mcp._tool_manager._tools["update_book_metadata"]
    assert tool.annotations is not None
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.destructiveHint is False
```

### Lifecycle Test Pattern
```python
# Source: adapted from existing test patterns in test_mcp.py
class TestLifecycle:
    """End-to-end lifecycle test: add -> search -> update -> search -> remove -> verify."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database."""
        from mnemo.storage.database import get_connection, init_db
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        yield {"path": db_path, "conn": conn}
        conn.close()

    def test_full_lifecycle(self, tmp_path, temp_db):
        """Full lifecycle: add, search, update, verify, remove, verify gone."""
        from mnemo.mcp import tools

        # Setup: mock ingest pipeline, set temp DB
        epub_file = tmp_path / "book.epub"
        epub_file.write_bytes(b"fake epub")

        # ... (mock ingest_book, mock extract_metadata, etc.)
        # Step 1: Add book
        result = tools._add_book_impl(str(epub_file))
        assert "Added" in result

        # Step 2: Search (mock search service to return results)
        # Step 3: Update metadata
        result = tools._update_book_metadata_impl(book_id, title="Updated Title")
        assert "Updated Title" in result

        # Step 4: Verify metadata reflected in get_book_info
        result = tools._get_book_info_impl(book_id)
        assert "Updated Title" in result

        # Step 5: Remove book (mock ingest.remove_book)
        result = tools._remove_book_impl(book_id)
        assert "Removed" in result

        # Step 6: Verify removal
        result = tools._get_book_info_impl(book_id)
        assert "not found" in result.lower()
```

### Normalizing Error Strings
```python
# Before (inconsistent):
return f"Search error: {e}"           # Line 83
return f"Error listing books: {e}"     # Line 107
return f"Book not found: {book_id}"    # Line 122, 300

# After (consistent "Error: " prefix):
return f"Error: Search failed: {e}"
return f"Error: Failed to list books: {e}"
return f"Error: Book not found: {book_id}"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No tool annotations | ToolAnnotations on all tools | MCP spec 2024-11-05+ | Clients can present confirmation prompts for destructive tools |
| Implicit defaults (destructive=true, openWorld=true) | Explicit annotation values | This phase | Correct behavior signaling to Claude clients |

**No deprecated patterns:** Everything in the current codebase uses current FastMCP 2.x patterns. No migrations needed.

## Open Questions

### 1. Lifecycle Test: Mock vs. Real Search

**What we know:** The success criterion says "search for content" and "verify metadata in search." This implies the search step should find content after add_book. But in tests, `add_book` is mocked (doesn't really ingest), so search can't find real content.

**What's unclear:** Whether the lifecycle test should mock search results to simulate finding content, or whether it should use a real (temp) database with pre-populated data.

**Recommendation:** Use a hybrid approach:
- Add a book to a temp DB (via direct `BookRepository.add()` and `ChunkRepository.add_many()`)
- Mock only the `ingest.ingest_book` return value (to avoid needing real EPUB parsing + embedding)
- Use a real `SearchService` backed by the temp DB for keyword search (no embeddings needed for FTS5)
- This tests the real search path end-to-end without requiring embedding credentials

### 2. Error Consistency: "Book not found" in get_book_info and update_book_metadata

**What we know:** Lines 122 and 300 return `"Book not found: {book_id}"` without the `"Error: "` prefix. This is arguably intentional -- "not found" might be informational, not an error.

**Recommendation:** Normalize to `"Error: Book not found: {book_id}"` for consistency with `_remove_book_impl` (line 161) which already uses the `"Error: "` prefix for the same condition. A tool consumer looking for errors can consistently check `result.startswith("Error:")`.

## Sources

### Primary (HIGH confidence)
- FastMCP 2.14.4 source code at `/Users/joel/.pyenv/versions/3.12.11/lib/python3.12/site-packages/fastmcp/` -- `ToolAnnotations` import, `@mcp.tool(annotations=...)` parameter, `ToolResult` behavior
- `mcp.types.ToolAnnotations` class verified via `inspect.getsource()` -- fields, defaults, Pydantic model
- [MCP Specification - Tools](https://modelcontextprotocol.io/legacy/concepts/tools) -- annotation defaults, semantics, best practices
- [FastMCP Tools Documentation](https://gofastmcp.com/servers/tools) -- decorator syntax, annotation usage

### Secondary (MEDIUM confidence)
- [MCP Tool Annotations Discussion](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/1138) -- community discussion on annotation improvements
- [MCP Tool Search and Discovery](https://www.atcyrus.com/stories/mcp-tool-search-claude-code-context-pollution-guide) -- tool search matching against descriptions

### Codebase Analysis (HIGH confidence)
- `src/mnemo/mcp/tools.py` -- all 6 tools reviewed, error conventions audited, docstrings analyzed
- `tests/test_mcp.py` -- 269 total tests, all assertion patterns audited for error string dependencies
- `pyproject.toml` -- fastmcp version constraint `>=2.14,<3` confirmed

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - verified against installed FastMCP 2.14.4, no new dependencies
- Architecture (annotations): HIGH - syntax verified locally with working test
- Architecture (error normalization): HIGH - complete audit of all error returns in tools.py
- Architecture (docstrings): MEDIUM - best practices sourced from MCP docs and community; specific wording is subjective
- Pitfalls: HIGH - identified from direct code analysis and test assertion audit
- Lifecycle test: MEDIUM - approach recommended but exact mock strategy has open questions

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (stable -- FastMCP 2.x API unlikely to change within constraint)
