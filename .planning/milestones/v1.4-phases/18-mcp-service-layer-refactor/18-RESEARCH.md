# Phase 18: MCP & Service Layer Refactor - Research

**Researched:** 2026-03-31
**Domain:** Python module decomposition, dependency injection, service layer pattern
**Confidence:** HIGH

## Summary

Phase 18 is the largest refactor in the v1.4 milestone. `mcp/tools.py` is 1,233 lines — three times the target — and contains module-level global singletons, duplicated validation logic (shared with CLI), and three distinct operational domains bundled together. The phase must split this file by domain, eliminate global singletons via dependency injection, and extract shared business logic into a service layer that both CLI and MCP delegate to.

The good news: the codebase already has strong separation of concerns at the storage and search layers. `BookRepository`, `ChunkRepository`, and `SearchService` all accept dependencies as constructor parameters. The refactor is primarily about wiring these existing components correctly, not redesigning them. The test suite (525 tests) uses public `_*_impl` function names directly — test imports must be updated as part of the refactor.

The key challenge is that FastMCP registers tools at import time via `@mcp.tool` decorators. The split must preserve the import chain (`server.py` imports tool modules to trigger registration) while allowing tool functions to receive injected dependencies. The current pattern of wrapping `_*_impl` functions with `@mcp.tool` decorated thin wrappers is worth keeping — it preserves testability by keeping business logic in non-decorated functions.

**Primary recommendation:** Split `tools.py` into `mcp/tools_search.py`, `mcp/tools_books.py`, and `mcp/tools_metadata.py`. Extract a `services/` package with `book_service.py` and `search_service_wrapper.py`. Pass `SearchService` and DB connections as function parameters to `_*_impl` functions; use lazy module-level factory functions only in the thin MCP wrappers (not in the implementation functions).

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STRC-01 | `mcp/tools.py` split into domain-specific modules (search, book management, metadata), no single file exceeding ~400 lines | 3-way domain split maps cleanly to existing tool groupings; line estimates below |
| STRC-03 | MCP module uses dependency injection — db connection and search service passed as parameters, not global singletons | Current `_get_search_service()` / `_get_book_repo()` pattern isolated in thin wrappers; impl functions can receive injected args |
| STRC-04 | Shared logic between CLI and MCP extracted into service layer, eliminating duplication | Validation logic, duplicate detection, ISBN normalization currently repeated; service layer unifies |
| STRC-05 | All existing tests pass after restructuring with no behavior changes | 525 tests currently green; test imports reference `mnemo.mcp.tools.*` — must be updated or re-exported |
</phase_requirements>

---

## Current State Audit

### File Sizes (as-is)

| File | Lines | Status |
|------|-------|--------|
| `mcp/tools.py` | 1,233 | FAR over ~400 limit |
| `mcp/server.py` | 31 | Fine — minimal wrapper |
| `mcp/__init__.py` | 17 | Fine — lazy import shim |
| `cli.py` | 648 | Within range (CLI-specific, no split needed) |
| `search/service.py` | 709 | Acceptable (established module) |

### Global Singletons in `mcp/tools.py`

```python
# Lines 30-31 — module-level globals (STRC-03 violation)
_search_service: SearchService | None = None
_db_connection = None
```

Three lazy-init factory functions (`_get_search_service`, `_get_book_repo`, `_get_chunk_repo`) read these globals. The DI fix is to pass these as parameters to `_*_impl` functions instead of having impls call the factories internally.

### Identified Tool Domains

**Domain: search** (3 tools, ~450 lines incl. formatters)
- `search_books` / `_search_books_impl` (lines 63–131)
- `get_book_structure` / `_get_book_structure_impl` (lines 1148–1204)
- `get_book_chunks` / `_get_book_chunks_impl` (lines 548–588)
- Formatter helpers: `_format_search_results`, `_format_enriched_results`, `_format_mixed_results`, `_truncate_at_boundary` (lines 591–812)

**Domain: book management** (3 tools, ~250 lines)
- `add_book` / `_add_book_impl` (lines 258–387)
- `remove_book` / `_remove_book_impl` (lines 217–255)
- `reindex_all_books` / `_reindex_all_books_impl` (lines 1074–1145)

**Domain: metadata** (4 tools, ~350 lines)
- `list_available_books` / `_list_available_books_impl` (lines 133–163)
- `get_book_info` / `_get_book_info_impl` (lines 166–214)
- `update_book_metadata` / `_update_book_metadata_impl` (lines 390–441)
- `enrich_book` / `_enrich_book_impl` (lines 444–545)

### Duplicated Validation Logic (STRC-04)

| Validation | In MCP tools.py | In CLI cli.py | Notes |
|------------|----------------|---------------|-------|
| file exists + `.epub` extension | `_add_book_impl` lines 293–299 | `add()` lines 78–91 | Identical logic |
| file hash duplicate detection | `_add_book_impl` lines 317–325 | `add()` lines 99–102 | Same BookRepository.get_by_hash call |
| ISBN normalization via `normalize_isbn` | `_update_book_metadata_impl` lines 418–423 | Not in CLI (CLI doesn't expose update) | Partial overlap |
| book_id length check (6 chars) | Multiple `_*_impl` functions | Not in CLI (CLI uses book_id from args without validation) | |

The CLI `remove` command (lines 258–283) simply calls `ingest.remove_book(book_id)` without validation. The MCP `_remove_book_impl` validates, fetches book info before deletion, and returns a human-readable response. These serve different UX goals (CLI prints to terminal, MCP returns strings), so the service layer extraction should focus on **business logic** (duplicate detection, ingestion, removal) not **output formatting**.

### Test Import Coupling

Tests in `tests/test_mcp.py` import private implementation functions directly:

```python
from mnemo.mcp.tools import _search_books_impl
from mnemo.mcp.tools import _get_book_info_impl
from mnemo.mcp.tools import _update_book_metadata_impl
from mnemo.mcp.tools import _format_search_results
from mnemo.mcp import tools  # accesses tools._search_service directly
```

After the split, these imports must work. Two valid approaches:
1. **Re-export shim**: Keep `mcp/tools.py` as a re-export module (same pattern used for `epub/content.py` in Phase 17)
2. **Update test imports**: Change test file to import from the new domain modules directly

The re-export shim approach preserves backward compatibility at zero cost and matches the established project pattern. However, the test that accesses `tools._search_service` directly (line 128 in test_mcp.py) will need updating regardless, since the DI refactor removes that global.

---

## Standard Stack

### Core (already installed — no new dependencies)

| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| fastmcp | existing | MCP tool registration via `@mcp.tool` decorator | No API changes needed |
| sqlite3 | stdlib | Database connections passed as parameters | Already used via `get_connection()` |
| pytest + pytest-mock | existing | Test suite (525 tests) | No new test deps needed |

### No New Dependencies Required

This phase is purely a structural refactor. All libraries are already installed. The service layer is plain Python — no frameworks, no new abstractions beyond what already exists.

---

## Architecture Patterns

### Recommended Final Structure

```
src/mnemo/
├── mcp/
│   ├── __init__.py         # lazy import shim (unchanged)
│   ├── __main__.py         # entry point (unchanged)
│   ├── server.py           # FastMCP instance + imports domain modules
│   ├── tools.py            # re-export shim for backward compat (test imports)
│   ├── tools_search.py     # search_books, get_book_structure, get_book_chunks
│   ├── tools_books.py      # add_book, remove_book, reindex_all_books
│   └── tools_metadata.py   # list_available_books, get_book_info, update_book_metadata, enrich_book
└── services/
    ├── __init__.py
    └── book_service.py     # shared business logic (add, remove, list, validate)
```

### Pattern 1: Dependency Injection via Function Parameters

**What:** `_*_impl` functions receive `db_conn` and/or `search_service` as parameters instead of calling module-level factory functions.

**When to use:** All implementation functions that currently call `_get_book_repo()`, `_get_chunk_repo()`, or `_get_search_service()`.

**Example — before:**
```python
# In tools.py (current)
def _list_available_books_impl() -> str:
    book_repo = _get_book_repo()  # reads global _db_connection
    books = book_repo.list_all()
    ...
```

**Example — after:**
```python
# In tools_metadata.py
def _list_available_books_impl(
    book_repo: BookRepository,
) -> str:
    books = book_repo.list_all()
    ...

# MCP wrapper in same file (thin adapter)
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, ...))
def list_available_books() -> str:
    """..."""
    return _list_available_books_impl(_make_book_repo())

# _make_book_repo() is the lazy factory, confined to MCP adapters only
def _make_book_repo() -> BookRepository:
    global _db_connection
    if _db_connection is None:
        init_db()
        _db_connection = get_connection()
    return BookRepository(_db_connection)
```

**Note on global scope:** Module-level globals can move to each domain module rather than one central location. This is acceptable since each domain module initializes its own connection. Alternatively, the globals can be confined to a `_deps.py` helper shared by all three domain modules. Either approach satisfies STRC-03 as long as impl functions receive deps as parameters (not call globals themselves).

### Pattern 2: Service Layer for Shared Business Logic

**What:** A `services/book_service.py` module with pure functions that both CLI and MCP delegate to.

**When to use:** Operations where CLI and MCP share the same decision logic (not output formatting).

**Candidate functions for service layer extraction:**

```python
# services/book_service.py

def validate_epub_path(path: Path) -> str | None:
    """Returns error string or None if valid."""
    if not path.exists():
        return f"File not found: {path}"
    if path.suffix.lower() != ".epub":
        return f"Not an EPUB file: {path} (expected .epub extension)"
    return None

def check_duplicate(
    book_repo: BookRepository,
    file_hash: str,
) -> Book | None:
    """Returns existing book if duplicate exists, else None."""
    return book_repo.get_by_hash(file_hash)

def list_books(book_repo: BookRepository) -> list[Book]:
    """Return all books."""
    return book_repo.list_all()
```

**What does NOT belong in the service layer:**
- Output formatting (markdown, Rich tables, JSON)
- MCP-specific async wrappers and timeout logic
- CLI-specific progress spinners and console output
- FastMCP `@mcp.tool` decorator registration

### Pattern 3: MCP Tool Registration via Import Side Effects

**What:** `server.py` imports each domain module at startup, which triggers `@mcp.tool` registration.

**When to use:** Standard FastMCP pattern — already used.

**After split, `server.py` becomes:**
```python
# server.py — unchanged structure, just more imports
mcp = FastMCP(f"mnemo v{__version__}")

import mnemo.mcp.tools_search    # registers: search_books, get_book_structure, get_book_chunks
import mnemo.mcp.tools_books     # registers: add_book, remove_book, reindex_all_books
import mnemo.mcp.tools_metadata  # registers: list_available_books, get_book_info, update_book_metadata, enrich_book
```

### Pattern 4: Re-export Shim for Backward Compatibility

**What:** Keep `mcp/tools.py` as a thin re-export module.

**When to use:** After splitting, to avoid breaking test imports and any external code that references `mnemo.mcp.tools.*`.

**Example:**
```python
# mcp/tools.py — re-export shim (like epub/content.py from Phase 17)
from mnemo.mcp.tools_search import (
    _search_books_impl,
    _get_book_structure_impl,
    _get_book_chunks_impl,
    _format_search_results,
    _format_enriched_results,
    _format_mixed_results,
    _truncate_at_boundary,
)
from mnemo.mcp.tools_books import (
    _add_book_impl,
    _remove_book_impl,
    _reindex_all_books_impl,
)
from mnemo.mcp.tools_metadata import (
    _list_available_books_impl,
    _get_book_info_impl,
    _update_book_metadata_impl,
    _enrich_book_impl,
)
# Note: _search_service global is NOT re-exported (removed by DI refactor)
# Tests that accessed tools._search_service must be updated to use injection pattern
```

### Anti-Patterns to Avoid

- **Leaving globals in impl functions:** Even after splitting files, if `_*_impl` functions still call `_get_book_repo()` internally, STRC-03 is not satisfied. The injection must reach the impl layer.
- **Service layer doing formatting:** If `book_service.list_books()` returns markdown strings, it can't serve both CLI (rich tables) and MCP (markdown). Services return data (lists, dicts, domain objects); formatters are in the caller.
- **Circular imports via server:** All domain tool modules import from `server.py` to get `mcp = FastMCP(...)`. `server.py` must NOT import from domain modules at module level — only at the bottom after `mcp` is defined (current pattern, must be preserved).
- **One connection per impl call:** Creating a new DB connection on every `_*_impl` call is expensive. The global-per-module pattern (one connection per domain module, lazily initialized) is acceptable. Per-request connection injection is ideal for tests but overkill for production.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ISBN validation | Custom checksum logic | `mnemo.epub.metadata.normalize_isbn` already exists | Already handles ISBN-10 and ISBN-13 |
| Thread-safe DB connection | Connection pool | `sqlite3.Connection` in thread-local via `get_connection()` | Already handles the threading model used by FastMCP |
| Test DB isolation | Complex fixture setup | Existing `tmp_path` + `init_db(db_path)` pattern in test_storage.py | Established pattern throughout test suite |
| MCP tool registration | Manual tool registry | `@mcp.tool` decorator (FastMCP) | Current approach, no change needed |

---

## Common Pitfalls

### Pitfall 1: Breaking Tool Registration Order

**What goes wrong:** If domain modules import `from mnemo.mcp.server import mcp` but `server.py` imports those modules before `mcp` is defined, Python raises `ImportError`.

**Why it happens:** Circular import at module level.

**How to avoid:** Keep tool registration imports at the BOTTOM of `server.py`, after `mcp = FastMCP(...)` is assigned. Current `server.py` already does this correctly — preserve the pattern.

**Warning signs:** `ImportError: cannot import name 'mcp'` during `python -m mnemo.mcp.server`.

### Pitfall 2: Tests That Access `tools._search_service` Directly

**What goes wrong:** `test_mcp.py` lines 128-138 set `tools._search_service = mock_service` to inject a mock. After DI refactor removes this global, those tests break.

**Why it happens:** Tests were written against the global singleton pattern.

**How to avoid:** Update the affected test to pass mock as parameter to `_search_books_impl(query, ..., search_service=mock_service)` instead of patching the global.

**Warning signs:** `AttributeError: module 'mnemo.mcp.tools' has no attribute '_search_service'`

### Pitfall 3: Service Layer Growing Output Formatting

**What goes wrong:** Convenience leads to putting markdown formatting into `book_service.py` functions to "save the caller from doing it." Now service layer cannot serve CLI (which needs Rich output) without carrying MCP-specific string formatting.

**Why it happens:** Short-term convenience in plan execution.

**How to avoid:** Service layer functions always return typed data (list[Book], Book | None, bool). Formatting stays in the tool/command layer.

### Pitfall 4: Partial DI (Impl Functions Still Call Factories)

**What goes wrong:** Some `_*_impl` functions are updated to accept injected deps, but others still call `_get_book_repo()` internally. STRC-03 is technically still violated.

**Why it happens:** Incomplete application of the refactor pattern across all 10 tools.

**How to avoid:** After split, grep for `_get_book_repo`, `_get_chunk_repo`, `_get_search_service` in impl functions (not in wrappers). Zero hits = STRC-03 satisfied.

**Verification command:**
```bash
grep -n "_get_book_repo\|_get_chunk_repo\|_get_search_service" \
    src/mnemo/mcp/tools_search.py \
    src/mnemo/mcp/tools_books.py \
    src/mnemo/mcp/tools_metadata.py \
    | grep "_impl"
# Should be empty
```

### Pitfall 5: Connection Lifetime Mismatch in `_add_book_impl`

**What goes wrong:** `_add_book_impl` creates its own connection (`init_db(); conn = get_connection()`) in a `try/finally` block. If refactored to accept an injected conn, the caller must manage the lifetime — but `add_book` MCP wrapper calls `asyncio.to_thread()`, so the connection must be created INSIDE the thread, not before it.

**Why it happens:** SQLite connections are not thread-safe when created in one thread and used in another.

**How to avoid:** For `_add_book_impl` specifically, inject a connection factory (callable) rather than a connection object, or keep the current pattern of creating the connection inside the impl function. Document this exception explicitly.

---

## Line Count Estimates After Split

| File | Estimated Lines | Under 400? |
|------|----------------|------------|
| `mcp/tools_search.py` | ~450 | No — formatters add bulk |
| `mcp/tools_books.py` | ~250 | Yes |
| `mcp/tools_metadata.py` | ~350 | Yes |
| `mcp/tools.py` (shim) | ~30 | Yes |
| `services/book_service.py` | ~100 | Yes |

**Note on tools_search.py:** The formatter functions (`_format_search_results`, `_format_enriched_results`, `_format_mixed_results`, `_truncate_at_boundary`) account for ~220 lines. If `tools_search.py` exceeds 400 lines, extract formatters to `mcp/formatters.py` (~220 lines). This keeps all domain modules under the limit. The requirement says "no single file exceeding ~400 lines" — the tilde gives wiggle room, but a `formatters.py` split is clean and straightforward.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (no config file detected — uses pyproject.toml) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_mcp.py -x -q` |
| Full suite command | `python -m pytest -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STRC-01 | No single mcp/ file > ~400 lines | structural check | `wc -l src/mnemo/mcp/*.py` | N/A |
| STRC-03 | No global singletons in impl functions | structural check + unit | `grep -n "_get_book_repo\|_get_chunk_repo\|_get_search_service" src/mnemo/mcp/tools_*.py` | N/A |
| STRC-04 | CLI and MCP share service layer | unit | `python -m pytest tests/test_mcp.py tests/test_cli.py -x -q` | ✅ |
| STRC-05 | All 525 existing tests pass | regression | `python -m pytest -x -q` | ✅ |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_mcp.py tests/test_cli.py -x -q`
- **Per wave merge:** `python -m pytest -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

None — existing test infrastructure covers all phase requirements. New test cases for service layer functions should be added to `tests/test_mcp.py` or a new `tests/test_services.py`.

---

## Code Examples

### Dependency-Injected Impl Function Pattern

```python
# tools_metadata.py — after refactor

from mnemo.storage import BookRepository

def _list_available_books_impl(book_repo: BookRepository) -> str:
    """List implementation."""
    books = book_repo.list_all()
    if not books:
        return "No books indexed yet. Use `mnemo add <path>` to add books."
    lines = ["| ID | Title | Authors | Description |", "|---|---|---|---|"]
    for book in books:
        authors = ", ".join(book.authors) if book.authors else "Unknown"
        desc = (book.description[:80] + "...") if book.description and len(book.description) > 80 else (book.description or "")
        lines.append(f"| `{book.id}` | {book.title} | {authors} | {desc} |")
    return "\n".join(lines)

# MCP adapter (thin wrapper) — still in same file
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, ...))
def list_available_books() -> str:
    """..."""
    return _list_available_books_impl(_make_book_repo())
```

### Service Layer Function Pattern

```python
# services/book_service.py

from pathlib import Path
from mnemo.storage import BookRepository
from mnemo.models import Book

def validate_epub_path(path: Path) -> str | None:
    """Validate an EPUB file path. Returns error message or None."""
    if not path.exists():
        return f"File not found: {path}"
    if path.suffix.lower() != ".epub":
        return f"Not an EPUB file: {path} (expected .epub extension)"
    return None

def find_duplicate(book_repo: BookRepository, file_hash: str) -> Book | None:
    """Check for an existing book with the same file hash."""
    return book_repo.get_by_hash(file_hash)

def list_all_books(book_repo: BookRepository) -> list[Book]:
    """Return all indexed books."""
    return book_repo.list_all()
```

### CLI Delegating to Service Layer

```python
# cli.py — after refactor (add command)
from mnemo.services.book_service import validate_epub_path, find_duplicate

@app.command()
def add(paths: ...) -> None:
    for path in paths:
        error = validate_epub_path(path)  # shared with MCP
        if error:
            console.print(f"[red]{error}[/red]")
            raise typer.Exit(1)

        init_db()
        conn = get_connection()
        book_repo = BookRepository(conn)
        existing = find_duplicate(book_repo, hashlib.sha256(path.read_bytes()).hexdigest())
        conn.close()
        # ... rest of CLI-specific logic
```

---

## Environment Availability

Step 2.6: SKIPPED — phase is purely code/structural changes with no external tool dependencies.

---

## Open Questions

1. **Connection globals: per-module or shared `_deps.py`?**
   - What we know: After DI, impl functions don't need globals; only MCP wrapper functions do.
   - What's unclear: Whether one global per domain module or a shared `mcp/_deps.py` is cleaner.
   - Recommendation: Per-module globals. Simpler, avoids a new import dependency. Three modules can each have their own `_db_connection = None`. The planner can choose either.

2. **`_add_book_impl` connection handling**
   - What we know: It creates its own connection in a `try/finally` inside a thread. Injecting a connection object would be thread-unsafe.
   - What's unclear: Whether to inject a factory callable or keep the current self-managed connection.
   - Recommendation: Keep `_add_book_impl` creating its own connection internally. Document as intentional exception to DI pattern (thread-safety requirement). The STRC-03 requirement is about not accessing module-level globals from impl functions — creating a fresh connection per call is different from caching one globally.

3. **How much service layer extraction is "enough" for STRC-04?**
   - What we know: STRC-04 says "Adding a new operation requires implementing it once in the service layer, not twice in CLI and MCP."
   - What's unclear: Whether extracting just `validate_epub_path` and `find_duplicate` satisfies the requirement, or if more shared logic must move.
   - Recommendation: The minimum viable service layer should contain any function where today both CLI and MCP call the same underlying storage/ingest function with the same logic. At minimum: epub path validation, duplicate detection, book listing. The planner should identify all code blocks that appear in both `cli.py` and `tools.py` performing identical operations.

---

## Sources

### Primary (HIGH confidence)

- Direct codebase inspection: `src/mnemo/mcp/tools.py` (1,233 lines, full read)
- Direct codebase inspection: `src/mnemo/cli.py` (648 lines, full read)
- Direct codebase inspection: `tests/test_mcp.py` (full read — identified test coupling)
- `python -m pytest -x -q` baseline: 525 passed, 2 warnings

### Secondary (MEDIUM confidence)

- Phase 17 `epub/content.py` re-export shim pattern — established project precedent for this exact backward-compat approach
- `mcp/server.py` import-at-bottom pattern — established project precedent for tool registration

---

## Metadata

**Confidence breakdown:**
- Current state audit: HIGH — direct code inspection
- Domain split line estimates: MEDIUM — based on manual line counting with some uncertainty in edge cases
- DI pattern: HIGH — established Python pattern, already present in SearchService and repositories
- Service layer scope: MEDIUM — exact boundary between "enough" and "overkill" requires planner judgment

**Research date:** 2026-03-31
**Valid until:** 2026-04-30 (stable codebase, no external dependencies)
