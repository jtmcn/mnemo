# Phase 5: Metadata Updates - Research

**Researched:** 2026-02-11
**Domain:** SQLite UPDATE operations, MCP tool registration, BookRepository extension
**Confidence:** HIGH

## Summary

Phase 5 adds the `update_book_metadata` MCP tool so Claude can modify a book's title, authors, and ISBN in SQLite. This is a focused, narrow phase: one new repository method (`BookRepository.update()`), one new MCP tool implementation, and one MCP tool registration.

The existing codebase provides everything needed. The SQLite `books` table already has `title`, `authors` (JSON array), and `isbn` columns. The MCP tool pattern is well-established in `mcp/tools.py` (three tools already registered). The PRD explicitly states that ChromaDB metadata does NOT need updating because `SearchService._get_book_title()` already resolves titles from SQLite at query time.

One critical finding: `SearchService` caches book titles in `_book_cache` (a dict in memory). After updating a title, subsequent searches in the same MCP server process will return the stale cached title. This cache must be invalidated or bypassed after metadata updates. The simplest fix is to clear the `_search_service` singleton in `mcp/tools.py` after a successful update, forcing a fresh `SearchService` on the next search.

**Primary recommendation:** Build `BookRepository.update()` with a dynamic SQL UPDATE that sets only the provided fields. Wire it through `_update_book_metadata_impl()` to a `@mcp.tool` registration. Invalidate the SearchService book title cache after updates. No schema changes, no ChromaDB changes, no new dependencies.

## Standard Stack

No new libraries needed. This phase uses only existing project dependencies.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlite3 | stdlib | Book metadata persistence | Already in use, `books` table has all needed columns |
| fastmcp | >=2.14,<3 | MCP tool registration | Already in use for 3 existing tools |
| pydantic | >=2.0 | Book model | Already used for `Book` model with validation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json (stdlib) | stdlib | Authors serialization | `authors` stored as JSON array string in SQLite |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Dynamic SQL UPDATE | Full row replacement | Dynamic UPDATE only touches changed columns; full replacement risks overwriting concurrent changes (not an issue here, but cleaner) |

**Installation:**
```bash
# No new dependencies needed
```

## Architecture Patterns

### Recommended Project Structure
```
src/mnemo/
├── storage/
│   └── repository.py   # ADD: BookRepository.update() method
├── mcp/
│   └── tools.py        # ADD: _update_book_metadata_impl() + @mcp.tool registration
└── ... (no other files changed)
```

Only two files are modified. No new files needed.

### Pattern 1: Dynamic SQL UPDATE with Parameterized Values
**What:** Build UPDATE statement dynamically based on which fields are provided, using `?` placeholders for values
**When to use:** `BookRepository.update()` - updating only the fields the caller provides
**Example:**
```python
# Source: Python sqlite3 stdlib documentation + project conventions
def update(
    self,
    book_id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> Book | None:
    """Update book metadata fields. Returns updated Book or None if not found."""
    # Build SET clause dynamically
    updates: list[str] = []
    params: list[str] = []

    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if authors is not None:
        updates.append("authors = ?")
        params.append(json.dumps(authors))
    if isbn is not None:
        updates.append("isbn = ?")
        params.append(isbn)

    if not updates:
        raise ValueError("At least one field must be provided")

    params.append(book_id)  # WHERE clause
    sql = f"UPDATE books SET {', '.join(updates)} WHERE id = ?"
    cursor = self.conn.execute(sql, params)
    self.conn.commit()

    if cursor.rowcount == 0:
        return None

    return self.get(book_id)
```

**Key details:**
- Column names are hardcoded strings (safe from SQL injection)
- Values use `?` parameterized placeholders (safe from SQL injection)
- `cursor.rowcount` tells us if the book existed
- `self.get(book_id)` returns the full updated Book object
- `json.dumps(authors)` matches existing serialization pattern in `BookRepository.add()`

### Pattern 2: MCP Tool Implementation + Registration (Existing Pattern)
**What:** Separate implementation function (`_impl`) from `@mcp.tool` decorated registration
**When to use:** All MCP tools in this project (established in Phase 3)
**Example:**
```python
# Source: Existing pattern in mcp/tools.py
def _update_book_metadata_impl(
    book_id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> str:
    """Update implementation - see update_book_metadata for docs."""
    # Validate book_id format
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    # Check at least one field provided
    if title is None and authors is None and isbn is None:
        return "Error: At least one of title, authors, or isbn must be provided"

    try:
        book_repo = _get_book_repo()
        updated = book_repo.update(
            book_id=book_id,
            title=title,
            authors=authors,
            isbn=isbn,
        )

        if updated is None:
            return f"Book not found: {book_id}"

        # Invalidate search service cache
        _invalidate_search_cache()

        # Return updated book info (same format as get_book_info)
        return _format_book_info(updated)

    except Exception as e:
        logger.exception("update_book_metadata failed")
        return f"Error: {e}"


@mcp.tool
def update_book_metadata(
    book_id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> str:
    """Update a book's metadata (title, authors, or ISBN).

    Changes are saved to the database and immediately reflected in
    search results and book info lookups.

    Args:
        book_id: 6-character book identifier (from list_available_books)
        title: New title for the book
        authors: New list of author names (replaces existing authors)
        isbn: New ISBN for the book

    Returns:
        Updated book details, or error message
    """
    return _update_book_metadata_impl(book_id, title, authors, isbn)
```

### Pattern 3: Cache Invalidation After Mutation
**What:** Clear the `SearchService._book_cache` after updating metadata so search results reflect new titles
**When to use:** After any successful metadata update in `_update_book_metadata_impl`
**Example:**
```python
# Source: Analysis of SearchService._get_book_title() caching behavior

def _invalidate_search_cache() -> None:
    """Clear cached book titles in SearchService after metadata update."""
    global _search_service
    if _search_service is not None:
        _search_service._book_cache.clear()
```

**Why this is needed:** `SearchService._get_book_title()` caches `book_id -> title` in a dict. Without invalidation, search results will show the old title until the MCP server process restarts. Clearing the cache dict is simpler and safer than resetting the entire `_search_service` singleton (which would force reconnection to SQLite and ChromaDB).

### Anti-Patterns to Avoid
- **Updating ChromaDB metadata:** The PRD explicitly says NOT to update ChromaDB. Chunk metadata in ChromaDB has `book_id` but not title/authors. `SearchService` resolves titles from SQLite.
- **Re-embedding after metadata change:** Out of scope. Changing title/author/ISBN doesn't affect chunk content or embeddings.
- **Accepting empty string as valid title:** Pydantic `Book` model requires `title: str = Field(min_length=1)`. The update method should also reject empty titles.
- **Forgetting to serialize authors as JSON:** Authors are stored as a JSON array string. Must use `json.dumps(authors)` when writing and `json.loads(row["authors"])` when reading (already handled by `_row_to_book`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SQL parameterization | String formatting for values | `?` placeholders | SQL injection prevention |
| Book model validation | Manual field validation | Pydantic `Book` model | Already validates id format, title min_length |
| Tool schema generation | Manual JSON schema | FastMCP type hints + docstring | Automatic schema from Python types |
| Authors serialization | Custom format | `json.dumps`/`json.loads` | Matches existing pattern in `BookRepository.add()` |

**Key insight:** The entire metadata update pipeline uses existing patterns and libraries. No new abstractions needed.

## Common Pitfalls

### Pitfall 1: Stale Title Cache in SearchService
**What goes wrong:** After updating a book's title, `search_books` still shows the old title
**Why it happens:** `SearchService._book_cache` is an in-memory dict that caches `book_id -> title`. Once populated, it never re-queries SQLite for that book_id.
**How to avoid:** Call `_search_service._book_cache.clear()` after successful metadata updates
**Warning signs:** Updated title visible in `get_book_info` but not in `search_books` results

### Pitfall 2: Validation Mismatch Between Tool and Repository
**What goes wrong:** Tool-level validation accepts values that repository or Pydantic model rejects
**Why it happens:** Validation done in two places: `_update_book_metadata_impl()` and `BookRepository.update()`
**How to avoid:** Validate "at least one field" in the impl function, validate field values via the existing Pydantic model constraints when `self.get()` returns the updated Book. Keep `BookRepository.update()` raising `ValueError` for empty updates.
**Warning signs:** Unhandled exceptions leaking through MCP, or confusing error messages

### Pitfall 3: Empty Authors List
**What goes wrong:** `authors=[]` is accepted, leaving book with no authors
**Why it happens:** An empty list is technically "provided" (not None)
**How to avoid:** This is actually fine - the Book model has `authors: list[str] = Field(default_factory=list)`, meaning empty list is valid. The existing `get_book_info` shows "Unknown" for empty authors. Decide whether to allow or reject.
**Warning signs:** Book displayed as "Unknown" authors after update

### Pitfall 4: ISBN Validation
**What goes wrong:** Invalid ISBN strings accepted (wrong length, wrong format)
**Why it happens:** The Book model has `isbn: str | None` with no format validation
**How to avoid:** Since the existing model doesn't validate ISBN format, don't add validation now. Consistent with existing behavior where EPUBs store arbitrary ISBN strings. Could be a future enhancement.
**Warning signs:** None - this matches existing behavior

### Pitfall 5: Concurrent Connection Issues
**What goes wrong:** `BookRepository.update()` uses a different connection than `_get_book_repo()` in tools
**Why it happens:** Creating multiple connections to the same SQLite database
**How to avoid:** Use the same `_db_connection` singleton from `mcp/tools.py` - the `_get_book_repo()` helper already handles this
**Warning signs:** Updates not visible to subsequent reads (WAL mode should prevent this, but best to use same connection)

### Pitfall 6: Tool Registration Breaks Existing Tools
**What goes wrong:** Adding the new tool causes import errors or breaks existing tool registration
**Why it happens:** Import-time side effects or circular imports
**How to avoid:** Follow the exact same pattern as existing tools: add impl function, add `@mcp.tool` decorated function, both in `mcp/tools.py`. The tools module is imported by `server.py` via `import mnemo.mcp.tools`.
**Warning signs:** Server fails to start, tools not listed

## Code Examples

Verified patterns from the existing codebase:

### BookRepository.update() - Complete Implementation
```python
# Source: Follows pattern of BookRepository.add() and BookRepository.delete()
import json

def update(
    self,
    book_id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> Book | None:
    """Update book metadata fields.

    Only the provided fields are updated; others remain unchanged.

    Args:
        book_id: 6-char hex book identifier
        title: New title (must be non-empty if provided)
        authors: New author list (replaces existing)
        isbn: New ISBN (or None to clear)

    Returns:
        Updated Book instance, or None if book not found

    Raises:
        ValueError: If no fields are provided
    """
    updates: list[str] = []
    params: list[str | None] = []

    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if authors is not None:
        updates.append("authors = ?")
        params.append(json.dumps(authors))
    if isbn is not None:
        updates.append("isbn = ?")
        params.append(isbn)

    if not updates:
        raise ValueError("At least one field (title, authors, isbn) must be provided")

    params.append(book_id)
    sql = f"UPDATE books SET {', '.join(updates)} WHERE id = ?"
    cursor = self.conn.execute(sql, params)
    self.conn.commit()

    if cursor.rowcount == 0:
        return None

    return self.get(book_id)
```

### MCP Tool Implementation - Follows Existing Pattern
```python
# Source: Follows pattern of _get_book_info_impl in mcp/tools.py
def _update_book_metadata_impl(
    book_id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> str:
    """Update implementation - see update_book_metadata for docs."""
    logger.info(
        f"update_book_metadata: book_id={book_id}, "
        f"title={title!r}, authors={authors!r}, isbn={isbn!r}"
    )

    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    if title is None and authors is None and isbn is None:
        return "Error: At least one of title, authors, or isbn must be provided"

    try:
        book_repo = _get_book_repo()
        updated = book_repo.update(
            book_id=book_id,
            title=title,
            authors=authors,
            isbn=isbn,
        )

        if updated is None:
            return f"Book not found: {book_id}"

        # Invalidate cached book titles so search reflects changes
        global _search_service
        if _search_service is not None:
            _search_service._book_cache.clear()

        # Return updated info (reuse get_book_info format)
        return _get_book_info_impl(book_id)

    except Exception as e:
        logger.exception("update_book_metadata failed")
        return f"Error: {e}"
```

### Testing Pattern - Follows Existing test_storage.py
```python
# Source: Follows pattern of TestBookRepository in test_storage.py
class TestBookRepositoryUpdate:
    """Tests for BookRepository.update() method."""

    def test_update_title(self, book_repo, sample_book):
        book_repo.add(sample_book)
        updated = book_repo.update(sample_book.id, title="New Title")
        assert updated is not None
        assert updated.title == "New Title"
        assert updated.authors == sample_book.authors  # unchanged

    def test_update_authors(self, book_repo, sample_book):
        book_repo.add(sample_book)
        updated = book_repo.update(sample_book.id, authors=["New Author"])
        assert updated is not None
        assert updated.authors == ["New Author"]
        assert updated.title == sample_book.title  # unchanged

    def test_update_isbn(self, book_repo, sample_book):
        book_repo.add(sample_book)
        updated = book_repo.update(sample_book.id, isbn="978-0000000000")
        assert updated is not None
        assert updated.isbn == "978-0000000000"

    def test_update_multiple_fields(self, book_repo, sample_book):
        book_repo.add(sample_book)
        updated = book_repo.update(
            sample_book.id,
            title="New Title",
            authors=["Author A", "Author B"],
        )
        assert updated is not None
        assert updated.title == "New Title"
        assert updated.authors == ["Author A", "Author B"]

    def test_update_no_fields_raises(self, book_repo, sample_book):
        book_repo.add(sample_book)
        with pytest.raises(ValueError, match="At least one field"):
            book_repo.update(sample_book.id)

    def test_update_nonexistent_returns_none(self, book_repo):
        result = book_repo.update("notfnd", title="New Title")
        assert result is None

    def test_update_persists(self, book_repo, sample_book):
        book_repo.add(sample_book)
        book_repo.update(sample_book.id, title="Persisted Title")
        refetched = book_repo.get(sample_book.id)
        assert refetched.title == "Persisted Title"
```

### MCP Tool Test Pattern - Follows Existing test_mcp.py
```python
# Source: Follows pattern of TestIntegrationWithTempStorage in test_mcp.py
class TestUpdateBookMetadataValidation:
    def test_empty_book_id(self):
        result = _update_book_metadata_impl("", title="New")
        assert "Error" in result

    def test_no_fields_provided(self):
        result = _update_book_metadata_impl("abc123")
        assert "Error" in result
        assert "at least one" in result.lower()

class TestUpdateBookMetadataIntegration:
    def test_update_title_reflected_in_get_book_info(self, temp_db):
        # Setup: inject temp connection
        tools._db_connection = temp_db["conn"]
        try:
            result = tools._update_book_metadata_impl("abc123", title="Updated Title")
            assert "Updated Title" in result

            info = tools._get_book_info_impl("abc123")
            assert "Updated Title" in info
        finally:
            tools._db_connection = original_conn

    def test_update_nonexistent_book(self, temp_db):
        tools._db_connection = temp_db["conn"]
        try:
            result = tools._update_book_metadata_impl("xyz789", title="New")
            assert "not found" in result.lower()
        finally:
            tools._db_connection = original_conn
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Full row UPDATE | Dynamic partial UPDATE | Always preferred | Only touches changed columns |
| Separate validation layer | Pydantic model validation | Pydantic 2.0 | Validation built into model |
| Manual JSON-RPC | FastMCP decorators | FastMCP 2.0 | Automatic schema from types |

**Deprecated/outdated:**
- Nothing relevant to this phase. All patterns are stable.

## Open Questions

1. **Should empty string title be rejected?**
   - What we know: Pydantic `Book` model has `title: str = Field(min_length=1)`, so empty titles would fail model validation when `self.get()` returns the Book. But the UPDATE itself would succeed in SQLite.
   - What's unclear: Whether to validate before UPDATE or let Pydantic catch it on read-back.
   - Recommendation: Validate in `_update_book_metadata_impl()` before calling `book_repo.update()`. Return clear error: "Error: title cannot be empty". This is simpler than handling the Pydantic ValidationError.

2. **Should `isbn=""` clear the ISBN or be rejected?**
   - What we know: The Book model has `isbn: str | None = None`. An empty string is different from None.
   - What's unclear: Whether users would pass `isbn=""` to mean "remove ISBN" or by accident.
   - Recommendation: Treat empty string as "clear ISBN" by converting `isbn=""` to `isbn=None` in the impl function. This is the most intuitive behavior for Claude.

3. **Tool annotations (readOnlyHint, idempotentHint)**
   - What we know: Phase 7 will add tool annotations to all tools.
   - What's unclear: Whether to add annotations now or defer to Phase 7.
   - Recommendation: Defer to Phase 7 per the roadmap. Phase 5 focuses on functionality.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/mnemo/storage/repository.py` - BookRepository patterns (add, get, delete)
- Existing codebase: `src/mnemo/mcp/tools.py` - MCP tool implementation patterns (_impl + @mcp.tool)
- Existing codebase: `src/mnemo/search/service.py` - SearchService._book_cache (cache invalidation need)
- Existing codebase: `src/mnemo/models.py` - Book model with Pydantic validation
- [Python sqlite3 documentation](https://docs.python.org/3/library/sqlite3.html) - Parameterized queries
- [FastMCP Tools documentation](https://gofastmcp.com/servers/tools) - Tool annotations syntax

### Secondary (MEDIUM confidence)
- [PRD](docs/prd-ebook-management.md) - Section 6.2 defines `BookRepository.update()` signature
- [SQLite Tutorial: Python UPDATE](https://www.sqlitetutorial.net/sqlite-python/update/) - UPDATE with parameterized values

### Tertiary (LOW confidence)
- None. All findings verified against existing codebase and official documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new libraries; all patterns from existing codebase
- Architecture: HIGH - Follows established patterns in repository.py and tools.py
- Pitfalls: HIGH - Cache invalidation issue verified by reading SearchService source code
- Code examples: HIGH - All examples follow existing codebase conventions exactly

**Research date:** 2026-02-11
**Valid until:** 2026-03-11 (stable patterns, no external dependencies changing)
