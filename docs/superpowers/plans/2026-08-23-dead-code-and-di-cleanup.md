# Dead Code & DI Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete ~150 lines of dead, duplicated, and silently-broken code from the MCP and vector layers without changing any user-visible behavior.

**Architecture:** Six independent deletion/consolidation tasks against an existing, well-layered Python package. Every task is behavior-preserving: the existing 570-test suite is the contract and no existing test may be weakened or deleted to make a task pass. Each task adds characterization tests, so the total only grows — 570 → 572 → 575 → 579 → 580 → 584. No new abstractions are introduced; the only file created is `src/mnemo/mcp/_deps.py`, which absorbs three identical copies of existing code.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy (strict, currently non-gating), uv, SQLite/FTS5, ChromaDB, FastMCP.

**Spec:** This plan implements findings 1–5 and 7 from the architecture analysis recorded in this session. The findings are restated inline in each task's "Why" block — there is no separate spec file, so the reasoning travels with the plan.

## Global Constraints

- Python floor is `>=3.11` (`pyproject.toml`). Do not use 3.12-only syntax.
- Line length is 100 (`[tool.ruff]`). Run `uv run ruff format` before every commit.
- All commands run through `uv run`. The bare `pytest` binary is NOT on PATH; `uv run pytest` is the only working invocation.
- `uv sync --all-extras --dev` must have been run once in the worktree before any test command.
- Test command for every verification step: `uv run pytest -q -m "not integration"`. The `-m "not integration"` is required — integration tests need `DATABRICKS_HOST`/`DATABRICKS_TOKEN` and will error without them.
- Baseline to preserve: **570 passed, 8 deselected**. Coverage baseline: **84%**, and CI enforces `--cov-fail-under=80`.
- mypy baseline: **83 errors in 19 files**. mypy is `continue-on-error: true` in CI and stays that way in this plan. Errors may go down, never up.
- Do NOT touch `.github/workflows/ci.yml`. Flipping the mypy gate is explicitly out of scope.
- Do NOT change search scoring constants, chunking defaults, or the RRF blend in `src/mnemo/search/service.py`. Those are empirically tuned.
- Commit after every task. Do not `git push` — the repo owner pushes manually.
- Branch name for this work: `joel/dead-code-cleanup`.

---

### Task 0: Set up the branch

**Files:**
- Modify: none (branch creation only)

**Interfaces:**
- Consumes: nothing
- Produces: a clean working branch all later tasks commit onto

- [ ] **Step 1: Confirm you are starting from a clean main**

Run:
```bash
cd /Users/joel/Code/mnemo && git status --porcelain && git branch --show-current
```
Expected: no output from `git status --porcelain`, and `main` printed by the branch command. If there are uncommitted changes, STOP and ask the user.

- [ ] **Step 2: Create the branch**

Run:
```bash
cd /Users/joel/Code/mnemo && gt create joel/dead-code-cleanup
```

If `gt` is unavailable, fall back to:
```bash
cd /Users/joel/Code/mnemo && git checkout -b joel/dead-code-cleanup
```

- [ ] **Step 3: Install dev dependencies**

Run:
```bash
cd /Users/joel/Code/mnemo && uv sync --all-extras --dev
```
Expected: completes without error. A warning about `VIRTUAL_ENV=.direnv/python-3.12` not matching `.venv` is normal and can be ignored.

- [ ] **Step 4: Record the baseline**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest -q -m "not integration" 2>&1 | tail -3
cd /Users/joel/Code/mnemo && uv run mypy src/ 2>&1 | tail -1
```
Expected: `570 passed, 8 deselected` and `Found 83 errors in 19 files (checked 46 source files)`.

If these numbers differ, record the actual numbers and use those as your baseline for the rest of the plan.

---

### Task 1: Remove the dead, silently-broken vector section filter

**Why:** `VectorStore.query()` accepts a `section` argument and `_build_where()` turns it into `{"section_path": {"$contains": ...}}`. Two things are wrong. First, no caller ever passes it — `search/service.py:415` and `service.py:480` are the only two call sites and both omit it. Second, `$contains` is a ChromaDB **document** operator, not a metadata operator: verified against the installed chromadb, a metadata `where` clause using `$contains` raises no error and matches **zero** documents. So if anyone ever wired this up, section-filtered semantic search would return an empty list that looks exactly like "no matches". Section filtering already works correctly as a post-filter in `SearchService.search()`, which is the path actually used.

**Files:**
- Modify: `src/mnemo/vectors/store.py` (the `query` method and `_build_where`)

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `VectorStore.query(self, query_embedding: list[float], n_results: int = 10, book_id: str | None = None, content_type: str | None = None) -> list[QueryResult]` and `VectorStore._build_where(self, book_id: str | None, content_type: str | None) -> dict | None`

- [ ] **Step 1: Write the failing test**

Add this to `tests/test_vectors.py`, at the end of the file.

Note these tests inspect the class directly rather than taking a fixture. `tests/test_vectors.py` defines `populated_store` twice, both as *class-scoped* fixtures (inside the classes at lines 133 and 239), so a new top-level test class cannot reach either one. Signature inspection needs no instance and no ChromaDB.

```python
class TestNoSectionFilter:
    """The section filter was dead code using a document-only Chroma operator."""

    def test_query_has_no_section_parameter(self):
        """VectorStore.query no longer accepts a section argument."""
        import inspect

        from mnemo.vectors.store import VectorStore

        params = list(inspect.signature(VectorStore.query).parameters)
        assert params == ["self", "query_embedding", "n_results", "book_id", "content_type"]

    def test_build_where_has_no_section_parameter(self):
        """_build_where takes exactly book_id and content_type."""
        import inspect

        from mnemo.vectors.store import VectorStore

        params = list(inspect.signature(VectorStore._build_where).parameters)
        assert params == ["self", "book_id", "content_type"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest tests/test_vectors.py::TestNoSectionFilter -v
```
Expected: both tests FAIL, each with a trailing `'section'` in the actual list — e.g. `assert ['self', 'book_id', 'content_type', 'section'] == ['self', 'book_id', 'content_type']`.

- [ ] **Step 3: Remove the section parameter from `query`**

In `src/mnemo/vectors/store.py`, change the `query` method signature from:

```python
    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        book_id: str | None = None,
        content_type: str | None = None,
        section: str | None = None,
    ) -> list[QueryResult]:
```

to:

```python
    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        book_id: str | None = None,
        content_type: str | None = None,
    ) -> list[QueryResult]:
```

And in the same method, change the where-clause construction from:

```python
        # Build where clause for filtering
        where = self._build_where(book_id, content_type, section)
```

to:

```python
        # Build where clause for filtering
        where = self._build_where(book_id, content_type)
```

- [ ] **Step 4: Remove the section branch from `_build_where`**

In `src/mnemo/vectors/store.py`, replace the entire `_build_where` method:

```python
    def _build_where(
        self,
        book_id: str | None,
        content_type: str | None,
        section: str | None = None,
    ) -> dict | None:
        """Build ChromaDB where clause for filtering."""
        conditions = []

        if book_id:
            conditions.append({"book_id": book_id})
        if content_type:
            conditions.append({"content_type": content_type})
        if section:
            # Normalize Unicode for accent-insensitive matching
            nfkd = unicodedata.normalize("NFKD", section)
            section_normalized = "".join(c for c in nfkd if not unicodedata.combining(c))
            conditions.append({"section_path": {"$contains": section_normalized}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}
```

with:

```python
    def _build_where(
        self,
        book_id: str | None,
        content_type: str | None,
    ) -> dict | None:
        """Build ChromaDB where clause for filtering.

        Section filtering is deliberately absent: Chroma's $contains is a
        document operator, not a metadata one. SearchService post-filters
        section paths in Python instead.
        """
        conditions = []

        if book_id:
            conditions.append({"book_id": book_id})
        if content_type:
            conditions.append({"content_type": content_type})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}
```

- [ ] **Step 5: Remove the now-unused `unicodedata` import**

`unicodedata` was used only by the section branch you just deleted. In `src/mnemo/vectors/store.py`, delete this line from the imports at the top of the file:

```python
import unicodedata
```

- [ ] **Step 6: Update the `query` docstring**

In `src/mnemo/vectors/store.py`, the `query` docstring's Args block currently omits `section` already but is otherwise fine. Confirm it reads:

```
        Args:
            query_embedding: 1024-dim query vector (will be normalized)
            n_results: Max results to return
            book_id: Filter to specific book
            content_type: Filter to content type (text, code, etc.)
```

If it lists a `section` arg, delete that line.

- [ ] **Step 7: Run the new tests to verify they pass**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest tests/test_vectors.py::TestNoSectionFilter -v
```
Expected: both PASS.

- [ ] **Step 8: Run the full suite**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest -q -m "not integration" 2>&1 | tail -3
```
Expected: `572 passed, 8 deselected` (570 baseline + the 2 new tests). Zero failures.

- [ ] **Step 9: Lint and format**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run ruff format src/ tests/ && uv run ruff check src/ tests/
```
Expected: `All checks passed!`

- [ ] **Step 10: Commit**

```bash
cd /Users/joel/Code/mnemo && git add src/mnemo/vectors/store.py tests/test_vectors.py
git commit -m "refactor(vectors): drop dead section filter from VectorStore.query

Chroma's \$contains is a document operator, not a metadata one — the
metadata where clause matched zero documents silently. No caller passed
section; SearchService post-filters section paths in Python."
```

---

### Task 2: Consolidate the three duplicated MCP dependency factories

**Why:** `mcp/tools_search.py`, `mcp/tools_books.py`, and `mcp/tools_metadata.py` each declare their own `_search_service` and `_db_connection` module globals plus byte-identical `_make_search_service`, `_make_book_repo`, and `_make_chunk_repo` functions. In a single MCP server process this opens up to **three separate SQLite connections** to the same database and constructs up to three `SearchService` instances, each with its own book-title cache. It is ~60 lines of triplicated code for something that should be one module.

**Files:**
- Create: `src/mnemo/mcp/_deps.py`
- Modify: `src/mnemo/mcp/tools_search.py` (delete lines 25–53, add import)
- Modify: `src/mnemo/mcp/tools_books.py` (delete lines 24–52, add import)
- Modify: `src/mnemo/mcp/tools_metadata.py` (delete lines 19–47, add import)

In all three files the block to delete runs from the `# Lazy-initialized services` comment through the closing line of `_make_chunk_repo`, stopping just before the `# Implementation functions (testable directly via DI)` comment. Match on that text rather than trusting the line numbers, which shift as you edit.
- Modify: `src/mnemo/mcp/tools.py` (re-export path changes; this file is deleted in Task 4 but must stay importable until then)
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: module `mnemo.mcp._deps` exposing `make_search_service() -> SearchService`, `make_book_repo() -> BookRepository`, `make_chunk_repo() -> ChunkRepository`, and `reset() -> None`

- [ ] **Step 1: Write the failing test**

Add this to `tests/test_mcp.py`, at the end of the file:

```python
class TestSharedDeps:
    """All MCP domain modules share one connection and one SearchService."""

    def test_all_domain_modules_use_the_same_factory(self):
        """tools_search, tools_books, and tools_metadata import from _deps."""
        from mnemo.mcp import _deps, tools_books, tools_metadata, tools_search

        assert tools_search.make_search_service is _deps.make_search_service
        assert tools_books.make_book_repo is _deps.make_book_repo
        assert tools_metadata.make_chunk_repo is _deps.make_chunk_repo

    def test_repos_share_one_connection(self, tmp_path, monkeypatch):
        """make_book_repo and make_chunk_repo hand out the same connection."""
        from mnemo.mcp import _deps

        monkeypatch.setattr(
            "mnemo.mcp._deps.get_db_path", lambda: tmp_path / "mnemo.db"
        )
        _deps.reset()
        try:
            book_repo = _deps.make_book_repo()
            chunk_repo = _deps.make_chunk_repo()
            assert book_repo.conn is chunk_repo.conn
        finally:
            _deps.reset()

    def test_search_service_is_a_singleton(self):
        """make_search_service returns the same instance on repeat calls."""
        from mnemo.mcp import _deps

        _deps.reset()
        try:
            assert _deps.make_search_service() is _deps.make_search_service()
        finally:
            _deps.reset()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest tests/test_mcp.py::TestSharedDeps -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'mnemo.mcp._deps'`.

- [ ] **Step 3: Confirm the repository attribute name**

The test asserts `book_repo.conn is chunk_repo.conn`. Verify that `BookRepository.__init__` stores the connection as `self.conn`:

Run:
```bash
cd /Users/joel/Code/mnemo && sed -n '25,32p;264,271p' src/mnemo/storage/repository.py
```

If the attribute is named something other than `conn` (e.g. `_conn`), update the test in Step 1 to use that name before continuing.

- [ ] **Step 4: Create the shared deps module**

Create `src/mnemo/mcp/_deps.py`:

```python
"""Shared lazily-initialized dependencies for the MCP tool modules.

One process, one SQLite connection, one SearchService. The domain tool
modules (tools_search, tools_books, tools_metadata) all pull from here.
"""

from __future__ import annotations

import sqlite3

from mnemo.search import SearchService
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db
from mnemo.storage.database import get_db_path

_search_service: SearchService | None = None
_db_connection: sqlite3.Connection | None = None


def _connection() -> sqlite3.Connection:
    """Get or open the process-wide SQLite connection (lazy init)."""
    global _db_connection
    if _db_connection is None:
        db_path = get_db_path()
        init_db(db_path)
        _db_connection = get_connection(db_path)
    return _db_connection


def make_search_service() -> SearchService:
    """Get or create the process-wide SearchService (lazy init)."""
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service


def make_book_repo() -> BookRepository:
    """Get a BookRepository over the shared connection."""
    return BookRepository(_connection())


def make_chunk_repo() -> ChunkRepository:
    """Get a ChunkRepository over the shared connection."""
    return ChunkRepository(_connection())


def reset() -> None:
    """Drop cached state. For tests only."""
    global _search_service, _db_connection
    if _db_connection is not None:
        _db_connection.close()
    _search_service = None
    _db_connection = None
```

Note: `_connection()` routes through `get_db_path()` rather than letting `init_db(None)` resolve the default internally. That is what makes the `monkeypatch.setattr("mnemo.mcp._deps.get_db_path", ...)` in the test work.

- [ ] **Step 5: Point `tools_search.py` at the shared module**

In `src/mnemo/mcp/tools_search.py`, delete this entire block (lines 25–53, comment through end of `_make_chunk_repo`):

```python
# Lazy-initialized services (avoid import-time DB connections)
_search_service: SearchService | None = None
_db_connection = None


def _make_search_service() -> SearchService:
    """Get or create SearchService (lazy init)."""
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service


def _make_book_repo() -> BookRepository:
    """Get BookRepository (lazy init)."""
    global _db_connection
    if _db_connection is None:
        init_db()
        _db_connection = get_connection()
    return BookRepository(_db_connection)


def _make_chunk_repo() -> ChunkRepository:
    """Get ChunkRepository (lazy init)."""
    global _db_connection
    if _db_connection is None:
        init_db()
        _db_connection = get_connection()
    return ChunkRepository(_db_connection)
```

Replace the module's storage import line:

```python
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db
```

with:

```python
from mnemo.mcp._deps import make_book_repo, make_chunk_repo, make_search_service
from mnemo.storage import BookRepository, ChunkRepository
```

`BookRepository` and `ChunkRepository` are still needed — they appear in the `_get_book_structure_impl` and `_get_book_chunks_impl` type annotations.

Then update the three call sites in this file, replacing `_make_search_service()` with `make_search_service()`, `_make_book_repo()` with `make_book_repo()`, and `_make_chunk_repo()` with `make_chunk_repo()`:

Run:
```bash
cd /Users/joel/Code/mnemo && sed -i '' 's/_make_search_service()/make_search_service()/g; s/_make_book_repo()/make_book_repo()/g; s/_make_chunk_repo()/make_chunk_repo()/g' src/mnemo/mcp/tools_search.py
```

- [ ] **Step 6: Point `tools_books.py` at the shared module**

In `src/mnemo/mcp/tools_books.py`, delete the identical block (lines 24–52 — same text as Step 5).

Replace its storage import line:

```python
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db
```

with:

```python
from mnemo.mcp._deps import make_book_repo, make_chunk_repo, make_search_service
from mnemo.storage import BookRepository, ChunkRepository
```

Then update call sites:
```bash
cd /Users/joel/Code/mnemo && sed -i '' 's/_make_search_service()/make_search_service()/g; s/_make_book_repo()/make_book_repo()/g; s/_make_chunk_repo()/make_chunk_repo()/g' src/mnemo/mcp/tools_books.py
```

- [ ] **Step 7: Point `tools_metadata.py` at the shared module**

In `src/mnemo/mcp/tools_metadata.py`, delete the identical block (lines 19–47).

Replace its storage import line:

```python
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db
```

with:

```python
from mnemo.mcp._deps import make_book_repo, make_chunk_repo, make_search_service
from mnemo.storage import BookRepository, ChunkRepository
```

Then update call sites:
```bash
cd /Users/joel/Code/mnemo && sed -i '' 's/_make_search_service()/make_search_service()/g; s/_make_book_repo()/make_book_repo()/g; s/_make_chunk_repo()/make_chunk_repo()/g' src/mnemo/mcp/tools_metadata.py
```

- [ ] **Step 8: Fix the re-export shim so it still imports**

`src/mnemo/mcp/tools.py` re-exports the old private factory names. It is deleted in Task 4, but must remain importable now. Replace these three lines in `src/mnemo/mcp/tools.py`:

```python
from mnemo.mcp.tools_search import _make_book_repo as _get_book_repo  # noqa: F401
from mnemo.mcp.tools_search import _make_chunk_repo as _get_chunk_repo  # noqa: F401

# Re-export domain module factory functions (tests that patch these)
from mnemo.mcp.tools_search import _make_search_service as _get_search_service  # noqa: F401
```

with:

```python
from mnemo.mcp._deps import make_book_repo as _get_book_repo  # noqa: F401
from mnemo.mcp._deps import make_chunk_repo as _get_chunk_repo  # noqa: F401
from mnemo.mcp._deps import make_search_service as _get_search_service  # noqa: F401
```

- [ ] **Step 9: Check for leftover references**

Run:
```bash
cd /Users/joel/Code/mnemo && grep -rn "_make_search_service\|_make_book_repo\|_make_chunk_repo" src/ tests/
```
Expected: no output. If anything remains, update it to the unprefixed name from `_deps`.

- [ ] **Step 10: Run the new tests**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest tests/test_mcp.py::TestSharedDeps -v
```
Expected: all three PASS.

- [ ] **Step 11: Run the full suite**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest -q -m "not integration" 2>&1 | tail -3
```
Expected: `575 passed, 8 deselected` (572 from Task 1 + 3 new). Zero failures.

- [ ] **Step 12: Lint and format**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run ruff format src/ tests/ && uv run ruff check src/ tests/
```
Expected: `All checks passed!`

- [ ] **Step 13: Commit**

```bash
cd /Users/joel/Code/mnemo && git add src/mnemo/mcp/ tests/test_mcp.py
git commit -m "refactor(mcp): consolidate dependency factories into _deps

tools_search, tools_books, and tools_metadata each carried identical
_make_* factories over their own _db_connection global — up to three
SQLite connections and three SearchService caches in one process."
```

---

### Task 3: Guard the optional DI parameters instead of dereferencing them

**Why:** Six `_impl` functions take dependencies typed `X | None = None` and then dereference them without a guard — e.g. `tools_search.py` does `service = search_service` followed by `service.search(...)`, and `tools_metadata.py:_get_book_info_impl` calls `book_repo.get(book_id)` on a parameter defaulting to `None`. These are the 13 `union-attr` mypy errors. Today no production call site omits the dep, and the tests that pass nothing (`_search_books_impl("")`, `_get_book_info_impl("abc")`) only exercise early-return validation paths that never touch the dep — so nothing crashes yet. It is a trap for the next caller.

The fix follows the convention already established in `src/mnemo/search/service.py`, which uses `assert self._chunk_repo is not None` in nine places: add one assert per function, placed **after** the existing validation guards so the validation-only tests keep working unchanged.

**Files:**
- Modify: `src/mnemo/mcp/tools_search.py` (`_search_books_impl`, `_get_book_structure_impl`, `_get_book_chunks_impl`)
- Modify: `src/mnemo/mcp/tools_metadata.py` (`_get_book_info_impl`, `_update_book_metadata_impl`)
- Modify: `src/mnemo/mcp/tools_books.py` (`_remove_book_impl`)
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `make_book_repo`, `make_chunk_repo`, `make_search_service` from `mnemo.mcp._deps` (Task 2)
- Produces: no signature changes. All six `_impl` functions keep their existing parameter lists exactly.

**CRITICAL — assert only on UNCONDITIONALLY dereferenced dependencies.**

Some of these functions dereference a dependency only inside an `if x is not None:` guard. Those must NOT get an assert. After Task 2, the `@mcp.tool` wrappers for `remove_book`, `update_book_metadata`, and `reindex_all_books` pass `make_search_service() if _search_service is not None else None` — and `_search_service` is now permanently `None`, so **they always pass `None` for `search_service`**. An unconditional assert there would break all three MCP tools at runtime, and no test would catch it: every test calls these `_impl` functions directly with an explicit mock, never through the wrapper.

Use exactly this table. Do not add an assert that is not in the "assert these" column.

| Function | File | Assert these | Never assert these |
|---|---|---|---|
| `_search_books_impl` | `tools_search.py` | `search_service` | — |
| `_get_book_structure_impl` | `tools_search.py` | `book_repo`, `chunk_repo` | — |
| `_get_book_chunks_impl` | `tools_search.py` | `chunk_repo` | — |
| `_get_book_info_impl` | `tools_metadata.py` | `book_repo`, `chunk_repo` | — |
| `_update_book_metadata_impl` | `tools_metadata.py` | `book_repo`, `chunk_repo` | `search_service` (guarded, always None from the wrapper) |
| `_remove_book_impl` | `tools_books.py` | `book_repo`, `chunk_repo` | `search_service` (guarded, always None from the wrapper) |
| `_reindex_all_books_impl` | `tools_books.py` | — (nothing) | `search_service` (guarded, always None from the wrapper) |

Every assert goes **after** the function's existing early-return validation guards and **before** the first unconditional use of that dependency.

- [ ] **Step 1: Write the failing test**

Add this to `tests/test_mcp.py`, at the end of the file:

```python
class TestDIGuards:
    """Omitting a required dependency fails loudly, not with AttributeError."""

    def test_search_books_impl_asserts_on_missing_service(self):
        """A valid query with no search_service raises AssertionError."""
        import pytest

        from mnemo.mcp.tools_search import _search_books_impl

        with pytest.raises(AssertionError):
            _search_books_impl("a real query")

    def test_get_book_info_impl_asserts_on_missing_repo(self):
        """A valid book_id with no book_repo raises AssertionError."""
        import pytest

        from mnemo.mcp.tools_metadata import _get_book_info_impl

        with pytest.raises(AssertionError):
            _get_book_info_impl("abc123")

    def test_get_book_structure_impl_asserts_on_missing_repo(self):
        """A valid book_id with no book_repo raises AssertionError."""
        import pytest

        from mnemo.mcp.tools_search import _get_book_structure_impl

        with pytest.raises(AssertionError):
            _get_book_structure_impl("abc123")

    def test_validation_errors_still_return_before_the_assert(self):
        """Guards run first: bad input returns a string, never raises."""
        from mnemo.mcp.tools_metadata import _get_book_info_impl
        from mnemo.mcp.tools_search import _search_books_impl

        assert _search_books_impl("").startswith("Error:")
        assert _get_book_info_impl("abc").startswith("Error:")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest tests/test_mcp.py::TestDIGuards -v
```
Expected: the first three FAIL — `_search_books_impl("a real query")` raises `AttributeError: 'NoneType' object has no attribute 'search'` rather than `AssertionError`, and the two repo cases raise `AttributeError: 'NoneType' object has no attribute 'get'`. The fourth test PASSES already (that is the behavior being protected).

- [ ] **Step 3: Guard `_search_books_impl`**

In `src/mnemo/mcp/tools_search.py`, inside `_search_books_impl`, the body currently reads:

```python
    top_k = min(max(1, top_k), 50)  # Clamp to 1-50
    context_window = min(max(0, context_window), 3)  # Clamp to 0-3
    max_chars = min(max(100, max_chars), 10000)  # Clamp to 100-10000

    try:
        service = search_service
        results = service.search(
```

Replace those lines with:

```python
    top_k = min(max(1, top_k), 50)  # Clamp to 1-50
    context_window = min(max(0, context_window), 3)  # Clamp to 0-3
    max_chars = min(max(100, max_chars), 10000)  # Clamp to 100-10000

    assert search_service is not None, "search_service is required"

    try:
        service = search_service
        results = service.search(
```

- [ ] **Step 4: Guard `_get_book_structure_impl`**

In `src/mnemo/mcp/tools_search.py`, inside `_get_book_structure_impl`, replace:

```python
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    try:
        book = book_repo.get(book_id)
```

with:

```python
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    assert book_repo is not None, "book_repo is required"
    assert chunk_repo is not None, "chunk_repo is required"

    try:
        book = book_repo.get(book_id)
```

- [ ] **Step 5: Guard `_get_book_chunks_impl`**

In `src/mnemo/mcp/tools_search.py`, inside `_get_book_chunks_impl`, replace:

```python
    if end_sequence < start_sequence:
        return "Error: end_sequence must be >= start_sequence"

    try:
        chunks = chunk_repo.get_chunk_range(book_id, start_sequence, end_sequence)
```

with:

```python
    if end_sequence < start_sequence:
        return "Error: end_sequence must be >= start_sequence"

    assert chunk_repo is not None, "chunk_repo is required"

    try:
        chunks = chunk_repo.get_chunk_range(book_id, start_sequence, end_sequence)
```

- [ ] **Step 6: Guard `_get_book_info_impl`**

In `src/mnemo/mcp/tools_metadata.py`, inside `_get_book_info_impl`, replace:

```python
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    try:
        book = book_repo.get(book_id)
```

with:

```python
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    assert book_repo is not None, "book_repo is required"
    assert chunk_repo is not None, "chunk_repo is required"

    try:
        book = book_repo.get(book_id)
```

- [ ] **Step 7: Guard `_update_book_metadata_impl`**

In `src/mnemo/mcp/tools_metadata.py`, find `_update_book_metadata_impl`. Its validation guards run first (book_id length, then empty-title and ISBN checks). Insert the asserts immediately **after the last early-return validation guard** and immediately **before the first use of `book_repo`**.

Locate the first line in the function that dereferences `book_repo` — run:
```bash
cd /Users/joel/Code/mnemo && sed -n '141,240p' src/mnemo/mcp/tools_metadata.py | grep -n "book_repo\.\|chunk_repo\.\|search_service\."
```

Insert directly above that line, exactly these two and no others (see the CRITICAL table above — `search_service` here is guarded and must NOT be asserted):

```python
    assert book_repo is not None, "book_repo is required"
    assert chunk_repo is not None, "chunk_repo is required"
```

`chunk_repo` earns its assert because this function passes it on to `_get_book_info_impl`, which asserts it in Step 6.

The asserts must land after the last early-return validation guard, or the tests at `tests/test_mcp.py:177–214` — which pass only `book_id` and metadata kwargs — will break.

- [ ] **Step 8: Guard `_remove_book_impl`**

In `src/mnemo/mcp/tools_books.py`, inside `_remove_book_impl`, replace:

```python
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"
```

with:

```python
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"

    assert book_repo is not None, "book_repo is required"
```

Then check whether the function dereferences `chunk_repo` and `search_service`:
```bash
cd /Users/joel/Code/mnemo && sed -n '202,245p' src/mnemo/mcp/tools_books.py | grep -n "chunk_repo\.\|search_service\."
```
Add the matching asserts only for dependencies it actually dereferences.

- [ ] **Step 9: Run the new tests**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest tests/test_mcp.py::TestDIGuards -v
```
Expected: all four PASS.

- [ ] **Step 10: Run the full suite**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest -q -m "not integration" 2>&1 | tail -3
```
Expected: `579 passed, 8 deselected` (575 from Task 2 + 4 new). Zero failures.

If any pre-existing test now fails with `AssertionError`, you placed an assert **before** a validation guard or asserted on a dependency the function does not use. Move or remove that assert — do not change the test.

- [ ] **Step 11: Record the mypy improvement**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run mypy src/ 2>&1 | tail -1
cd /Users/joel/Code/mnemo && uv run mypy src/ 2>&1 | grep -c "union-attr"
```
Expected: total errors down from 83 to roughly 70, and the `union-attr` count down from 13 to 0 or near it.

This is the full extent of mypy work in this plan. Do NOT chase the remaining errors and do NOT modify `.github/workflows/ci.yml`.

- [ ] **Step 12: Lint and format**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run ruff format src/ tests/ && uv run ruff check src/ tests/
```
Expected: `All checks passed!`

- [ ] **Step 13: Commit**

```bash
cd /Users/joel/Code/mnemo && git add src/mnemo/mcp/ tests/test_mcp.py
git commit -m "fix(mcp): assert injected deps before dereferencing them

Six _impl functions dereferenced X | None = None parameters with no
guard. Matches the assert convention already used in search/service.py
and clears the union-attr mypy errors."
```

---

### Task 4: Delete the `mcp/tools.py` re-export shim

**Why:** `src/mnemo/mcp/tools.py` is a 51-line backward-compatibility shim created when the monolithic tools module was split by domain. Its only consumers are this repo's own tests (94 import statements) — there is no external caller. Its own comment concedes that the two module-level globals at the bottom do not work: *"setting these on the shim module does NOT affect domain module globals."* A compat shim with exactly one in-repo consumer and a documented non-working half is not compatibility, it is indirection.

Verified before writing this task: all 94 references are plain `from mnemo.mcp.tools import ...` statements inside test functions. **Zero** tests use `patch("mnemo.mcp.tools....")`, so nothing depends on the shim's module identity — the rewrite is purely mechanical.

**Files:**
- Delete: `src/mnemo/mcp/tools.py`
- Modify: `src/mnemo/mcp/__main__.py` (line 7 imports the shim — see Step 7b)
- Modify: `tests/test_mcp.py` (88 references), `tests/test_enrich.py` (5), `tests/test_storage.py` (1)

**Interfaces:**
- Consumes: the domain modules established in Tasks 2 and 3
- Produces: nothing new. Name-to-module mapping used by the rewrite:
  - `mnemo.mcp.formatters` — `_format_enriched_results`, `_format_mixed_results`, `_format_search_results`, `_truncate_at_boundary`
  - `mnemo.mcp.tools_books` — `_add_book_impl`, `_reindex_all_books_impl`, `_remove_book_impl`
  - `mnemo.mcp.tools_metadata` — `_enrich_book_impl`, `_get_book_info_impl`, `_list_available_books_impl`, `_update_book_metadata_impl`
  - `mnemo.mcp.tools_search` — `_get_book_chunks_impl`, `_get_book_structure_impl`, `_search_books_impl`

- [ ] **Step 1: Write the failing test**

Add this to `tests/test_mcp.py`, at the end of the file:

```python
class TestShimRemoved:
    """The mnemo.mcp.tools compat shim is gone."""

    def test_shim_module_does_not_exist(self):
        import pytest

        with pytest.raises(ImportError):
            import mnemo.mcp.tools  # noqa: F401
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest tests/test_mcp.py::TestShimRemoved -v
```
Expected: FAIL — `DID NOT RAISE <class 'ImportError'>`, because the shim still exists.

- [ ] **Step 3: Confirm no test patches the shim module**

Run:
```bash
cd /Users/joel/Code/mnemo && grep -rn 'patch("mnemo.mcp.tools\.\|patch('"'"'mnemo.mcp.tools\.' tests/
```
Expected: no output. If there IS output, those patch targets must be repointed at the domain module that actually owns the name — handle them by hand before continuing.

- [ ] **Step 4: Rewrite the 91 single-name imports**

Run:
```bash
cd /Users/joel/Code/mnemo
for n in _format_enriched_results _format_mixed_results _format_search_results _truncate_at_boundary; do
  sed -i '' "s/^\( *\)from mnemo\.mcp\.tools import $n\$/\1from mnemo.mcp.formatters import $n/" tests/*.py
done
for n in _add_book_impl _reindex_all_books_impl _remove_book_impl; do
  sed -i '' "s/^\( *\)from mnemo\.mcp\.tools import $n\$/\1from mnemo.mcp.tools_books import $n/" tests/*.py
done
for n in _enrich_book_impl _get_book_info_impl _list_available_books_impl _update_book_metadata_impl; do
  sed -i '' "s/^\( *\)from mnemo\.mcp\.tools import $n\$/\1from mnemo.mcp.tools_metadata import $n/" tests/*.py
done
for n in _get_book_chunks_impl _get_book_structure_impl _search_books_impl; do
  sed -i '' "s/^\( *\)from mnemo\.mcp\.tools import $n\$/\1from mnemo.mcp.tools_search import $n/" tests/*.py
done
```

- [ ] **Step 5: Rewrite the two comma-separated imports**

`tests/test_mcp.py:673` and `tests/test_mcp.py:711` both read:

```python
        from mnemo.mcp.tools import _get_book_info_impl, _update_book_metadata_impl
```

Both names live in `tools_metadata`, so one substitution handles both:

```bash
cd /Users/joel/Code/mnemo && sed -i '' 's/^\( *\)from mnemo\.mcp\.tools import _get_book_info_impl, _update_book_metadata_impl$/\1from mnemo.mcp.tools_metadata import _get_book_info_impl, _update_book_metadata_impl/' tests/test_mcp.py
```

- [ ] **Step 6: Rewrite the one multi-line import**

`tests/test_mcp.py:1221` opens a parenthesized import spanning four names across two modules. Replace this block:

```python
        from mnemo.mcp.tools import (
            _add_book_impl,
            _get_book_info_impl,
            _remove_book_impl,
            _search_books_impl,
        )
```

with:

```python
        from mnemo.mcp.tools_books import _add_book_impl, _remove_book_impl
        from mnemo.mcp.tools_metadata import _get_book_info_impl
        from mnemo.mcp.tools_search import _search_books_impl
```

- [ ] **Step 7: Verify nothing references the shim**

Run:
```bash
cd /Users/joel/Code/mnemo && grep -rn "mnemo\.mcp\.tools\b" tests/ src/
```
Expected: no output. Any hit is a reference the sed patterns missed — fix it by hand using the mapping in the Interfaces block above.

Note the `\b` in the pattern: it excludes `mnemo.mcp.tools_books`, `tools_search`, and `tools_metadata`, which are the correct new targets.

**Expect exactly one hit in `src/`: `src/mnemo/mcp/__main__.py:7`.** Step 7b handles it. Any hit in `tests/` is a straggler to fix by hand.

- [ ] **Step 7b: Fix the module entry point**

`src/mnemo/mcp/__main__.py` line 7 imports the shim to trigger tool registration:

```python
# Import tools to ensure they're registered
import mnemo.mcp.tools  # noqa: F401
from mnemo.mcp.server import mcp
```

This line is now both redundant and about to break: `mnemo/mcp/server.py` already imports `tools_books`, `tools_metadata`, and `tools_search` at module scope to trigger `@mcp.tool` registration, and line 8 imports `mcp` from that same server module. Delete the comment and the import so the file reads:

```python
"""Entry point for running MCP server as a module.

Usage: python -m mnemo.mcp
"""

from mnemo.mcp.server import mcp

if __name__ == "__main__":
    mcp.run()
```

This is load-bearing and untested — `__main__.py` sits at 0% coverage, so the suite will stay green even if you get it wrong. Step 10b is the check that actually catches it.

- [ ] **Step 8: Delete the shim**

Run:
```bash
cd /Users/joel/Code/mnemo && git rm src/mnemo/mcp/tools.py
```

- [ ] **Step 9: Run the full suite**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest -q -m "not integration" 2>&1 | tail -3
```
Expected: `580 passed, 8 deselected` (579 from Task 3 + 1 new). Zero failures.

A `ModuleNotFoundError: No module named 'mnemo.mcp.tools'` here means Step 7's grep was run before a file was saved. Re-run Step 7 and fix the stragglers.

- [ ] **Step 10: Verify the MCP server still starts**

Deleting a module that the server package imports is the one real risk in this task. Confirm the server still boots and registers its ten tools:

```bash
cd /Users/joel/Code/mnemo && uv run python -c "
import mnemo.mcp.server as s
import asyncio
names = sorted(t.name for t in asyncio.run(s.mcp.get_tools()).values())
print(len(names), names)
"
```
Expected: `10` tools listed, including `search_books`, `add_book`, `remove_book`, `reindex_all_books`, `list_available_books`, `get_book_info`, `update_book_metadata`, `enrich_book`, `get_book_structure`, `get_book_chunks`.

If `get_tools()` is not awaitable in the installed FastMCP version, fall back to `uv run python -c "import mnemo.mcp.server"` and confirm it exits 0 with no traceback.

- [ ] **Step 10b: Verify the `python -m mnemo.mcp` entry point still imports**

This is the check for Step 7b. `__main__.py` has no test coverage, so the suite cannot catch a mistake here.

```bash
cd /Users/joel/Code/mnemo && uv run python -c "
import runpy, sys
sys.argv = ['mnemo.mcp']
mod = runpy.run_module('mnemo.mcp', run_name='__not_main__')
print('entry point imports OK, mcp =', mod['mcp'].name)
"
```
Expected: `entry point imports OK, mcp = mnemo v1.12.0` (the version string updates to 1.12.1 in Task 6). Using `run_name='__not_main__'` loads the module without entering the `if __name__ == "__main__"` block, so the server does not actually start and block.

A `ModuleNotFoundError: No module named 'mnemo.mcp.tools'` here means Step 7b was skipped.

Also confirm the CLI's `serve` command still works:
```bash
cd /Users/joel/Code/mnemo && uv run mnemo serve --help
```
Expected: help text, exit 0, no traceback.

- [ ] **Step 11: Lint and format**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run ruff format src/ tests/ && uv run ruff check src/ tests/
```
Expected: `All checks passed!`

- [ ] **Step 12: Commit**

```bash
cd /Users/joel/Code/mnemo && git add -A src/mnemo/mcp/ tests/
git commit -m "refactor(mcp): delete tools.py re-export shim

The shim's only consumers were this repo's own tests; no test patched
it by module path. Imports now point at the domain modules directly."
```

---

### Task 5: Trim the pass-through wrappers from `book_service.py`

**Why:** `src/mnemo/services/book_service.py` holds three functions. `list_all_books(repo)` is `return repo.list_all()` and has **no callers at all**. `find_duplicate(repo, hash)` is `return repo.get_by_hash(hash)` — one caller, one line, no added behavior. Only `validate_book_path` does real work (existence plus extension check against `SUPPORTED_FORMATS`) and is worth keeping. The module sits at 64% coverage precisely because two thirds of it is unreachable indirection.

Note `find_duplicate` is patched by name in three CLI tests (`tests/test_cli.py:102, 140, 181`). Removing it means those `@patch` decorators must go too.

**Files:**
- Modify: `src/mnemo/services/book_service.py`
- Modify: `src/mnemo/cli.py:82` (import) and `cli.py:106` (call site)
- Modify: `tests/test_cli.py` (three `@patch` decorators and their injected parameters)

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `mnemo.services.book_service.validate_book_path(path: Path) -> str | None` as the module's only export

- [ ] **Step 1: Write the failing test**

Add this to `tests/test_cli.py`, at the end of the file:

```python
class TestBookServiceSurface:
    """book_service keeps only the function that does real work."""

    def test_only_validate_book_path_is_exported(self):
        from mnemo.services import book_service

        public = [n for n in dir(book_service) if not n.startswith("_")]
        assert "validate_book_path" in public
        assert "find_duplicate" not in public
        assert "list_all_books" not in public

    def test_validate_book_path_rejects_missing_file(self, tmp_path):
        from mnemo.services.book_service import validate_book_path

        result = validate_book_path(tmp_path / "nope.epub")
        assert result is not None
        assert "File not found" in result

    def test_validate_book_path_rejects_bad_extension(self, tmp_path):
        from mnemo.services.book_service import validate_book_path

        bad = tmp_path / "book.pdf"
        bad.write_text("x")
        result = validate_book_path(bad)
        assert result is not None
        assert "Unsupported format" in result

    def test_validate_book_path_accepts_epub(self, tmp_path):
        from mnemo.services.book_service import validate_book_path

        good = tmp_path / "book.epub"
        good.write_text("x")
        assert validate_book_path(good) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest tests/test_cli.py::TestBookServiceSurface -v
```
Expected: `test_only_validate_book_path_is_exported` FAILS on `assert "find_duplicate" not in public`. The other three PASS (they document behavior being preserved).

- [ ] **Step 3: Inline `find_duplicate` at its single call site**

In `src/mnemo/cli.py`, change the import at line 82 from:

```python
    from mnemo.services.book_service import find_duplicate, validate_book_path
```

to:

```python
    from mnemo.services.book_service import validate_book_path
```

Then change the call at line 106 from:

```python
        existing = find_duplicate(book_repo, file_hash)
```

to:

```python
        existing = book_repo.get_by_hash(file_hash)
```

- [ ] **Step 4: Delete the two pass-throughs**

Replace the whole of `src/mnemo/services/book_service.py` with:

```python
"""Shared book operations used by both CLI and MCP layers."""

from pathlib import Path

from mnemo.parsing import SUPPORTED_FORMATS


def validate_book_path(path: Path) -> str | None:
    """Validate a book file path. Returns error message or None if valid."""
    if not path.exists():
        return f"File not found: {path}"
    if path.suffix.lower() not in SUPPORTED_FORMATS:
        return (
            f"Unsupported format: {path.suffix} (supported: {', '.join(sorted(SUPPORTED_FORMATS))})"
        )
    return None
```

The `Book` and `BookRepository` imports go with the functions that used them.

- [ ] **Step 5: Update the three CLI tests that patch `find_duplicate`**

At `tests/test_cli.py` lines 102, 140, and 181, each test carries a stacked decorator pair:

```python
    @patch("mnemo.services.book_service.find_duplicate", return_value=None)
    @patch("mnemo.services.book_service.validate_book_path", return_value=None)
```

Delete the `find_duplicate` decorator line from all three, keeping the `validate_book_path` one.

Because `@patch` injects one positional argument per decorator, you must also remove the corresponding parameter from each test function's signature. Decorators apply bottom-up, so the `validate_book_path` mock is the first injected parameter and the `find_duplicate` mock is the second — delete the **second** mock parameter from each of the three signatures.

Inspect them before editing:
```bash
cd /Users/joel/Code/mnemo && sed -n '100,112p;138,150p;179,191p' tests/test_cli.py
```

These tests previously relied on `find_duplicate` being patched to return `None`. Now the real `book_repo.get_by_hash` runs against the test's temp database, which is empty — so it returns `None` on its own and the tests still pass. If one fails because a book IS found, the test is using a pre-populated database; in that case patch `mnemo.storage.repository.BookRepository.get_by_hash` instead.

- [ ] **Step 6: Run the new tests**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest tests/test_cli.py::TestBookServiceSurface -v
```
Expected: all four PASS.

- [ ] **Step 7: Run the full suite**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest -q -m "not integration" 2>&1 | tail -3
```
Expected: `584 passed, 8 deselected` (580 from Task 4 + 4 new). Zero failures.

- [ ] **Step 8: Verify `mnemo add` still works end to end**

This task touched the CLI's duplicate-detection path, so exercise it against the real fixture EPUB in a throwaway database:

```bash
cd /Users/joel/Code/mnemo && rm -rf /tmp/mnemo-t5 && mkdir -p /tmp/mnemo-t5
cd /Users/joel/Code/mnemo && HOME=/tmp/mnemo-t5 uv run mnemo add tests/fixtures/sample.epub
cd /Users/joel/Code/mnemo && HOME=/tmp/mnemo-t5 uv run mnemo list
cd /Users/joel/Code/mnemo && HOME=/tmp/mnemo-t5 uv run mnemo add tests/fixtures/sample.epub
```
Expected: the first `add` succeeds, `list` shows one book, and the second `add` reports the book is already indexed (the duplicate path you just changed). Then clean up: `rm -rf /tmp/mnemo-t5`.

- [ ] **Step 9: Lint and format**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run ruff format src/ tests/ && uv run ruff check src/ tests/
```
Expected: `All checks passed!`

- [ ] **Step 10: Commit**

```bash
cd /Users/joel/Code/mnemo && git add src/mnemo/services/book_service.py src/mnemo/cli.py tests/test_cli.py
git commit -m "refactor(services): drop pass-through wrappers from book_service

list_all_books had no callers; find_duplicate was a one-line alias for
BookRepository.get_by_hash, now inlined at its single CLI call site."
```

---

### Task 6: Refresh the stale concerns document and bump the version

**Why:** `.planning/codebase/CONCERNS.md` is dated 2026-03-26 and five of its entries are now false: it claims there is no CI (`.github/workflows/ci.yml` exists), no coverage enforcement (`--cov-fail-under=80` is enforced), manual `try/except ALTER TABLE` migrations (replaced by the versioned framework in `storage/migrations.py`), that `mcp/tools.py` is 1233 lines (it is deleted as of Task 4), and that `typer`/`rich` are undeclared dependencies (both are listed in `pyproject.toml`). It also references a `books.epub_path` column where the current column is `file_path`. A concerns file that lists solved problems trains its readers to ignore it.

Per `CLAUDE.md`, the version in `pyproject.toml` is the single source of truth and must be updated. This plan is behavior-preserving cleanup, so it is a PATCH bump: `1.12.0` → `1.12.1`.

**Files:**
- Modify: `.planning/codebase/CONCERNS.md`
- Modify: `pyproject.toml` (version)
- Modify: `uv.lock` (regenerated)

**Interfaces:**
- Consumes: the completed state of Tasks 1–5
- Produces: nothing consumed by other tasks

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, change:

```toml
version = "1.12.0"
```

to:

```toml
version = "1.12.1"
```

- [ ] **Step 2: Update the version reference in CLAUDE.md**

`CLAUDE.md` ends with a `Current version:` line. Change:

```markdown
- Current version: 1.12.0
```

to:

```markdown
- Current version: 1.12.1
```

- [ ] **Step 3: Sync the lockfile**

Run:
```bash
cd /Users/joel/Code/mnemo && uv sync --all-extras --dev
```
Expected: `uv.lock` picks up the new version. Confirm with `git diff --stat uv.lock` — it should show a small change.

CI runs `uv sync --locked`, which fails if the lockfile is out of date, so this step is not optional.

- [ ] **Step 4: Delete the five resolved entries from CONCERNS.md**

In `.planning/codebase/CONCERNS.md`, delete these blocks entirely:

- Under **Technical Debt**, the `### Large Files` bullet for `mcp/tools.py (1233 lines)` — the file no longer exists.
- Under **Technical Debt**, the whole `### Manual Schema Migrations` section — superseded by `storage/migrations.py`.
- Under **Missing Capabilities**, the whole `### No CI/CD` section — `.github/workflows/ci.yml` runs lint, format, mypy, and a 3.11/3.12 test matrix.
- Under **Missing Capabilities**, the whole `### No Coverage Enforcement` section — CI enforces `--cov-fail-under=80`.
- Under **Dependency Risks**, the whole `### Missing Declared Dependencies` section — `typer` and `rich` are both in `[project.dependencies]`.

- [ ] **Step 5: Correct the stale column name**

In `.planning/codebase/CONCERNS.md`, under **Security Considerations** → **File Path Exposure**, change:

```markdown
- `books.epub_path` stores absolute filesystem paths — exposed via MCP tools and `--json` CLI output
```

to:

```markdown
- `books.file_path` stores absolute filesystem paths — exposed via MCP tools and `--json` CLI output
```

- [ ] **Step 6: Record what this plan resolved**

In `.planning/codebase/CONCERNS.md`, replace the `### Global Mutable State` block under **Technical Debt**:

```markdown
### Global Mutable State
- MCP module uses global singletons (`_search_service`, `_db_connection`) with lazy init. Works for single-process STDIO but would complicate testing or multi-instance scenarios
```

with:

```markdown
### Global Mutable State
- MCP lazy singletons (`_search_service`, `_db_connection`) now live in one place, `mcp/_deps.py`, with a `reset()` for tests. Still process-global — fine for single-process STDIO, would complicate multi-instance scenarios

### mypy Not Enforced
- `[tool.mypy] strict = true` in `pyproject.toml`, but CI runs mypy with `continue-on-error: true`. ~70 errors remain, dominated by bare `dict`/`list` annotations (`type-arg`) and missing third-party stubs (`import-untyped`)
```

- [ ] **Step 7: Update the CLI/MCP duplication entry**

In `.planning/codebase/CONCERNS.md`, replace:

```markdown
### CLI/MCP Code Duplication
- CLI commands and MCP tools implement similar logic (add book, search, list). The MCP tools call implementation functions directly, but there's overlap in validation and formatting logic
```

with:

```markdown
### CLI/MCP Code Duplication
- CLI commands and MCP tools implement similar logic (add book, search, list). `services/book_service.py` holds the one genuinely shared piece (`validate_book_path`); validation and formatting overlap remains
```

- [ ] **Step 8: Update the analysis date**

In `.planning/codebase/CONCERNS.md`, change the header line:

```markdown
**Analysis Date:** 2026-03-26
```

to:

```markdown
**Analysis Date:** 2026-08-23
```

And the footer line at the bottom of the file:

```markdown
*Concerns analysis: 2026-03-26*
```

to:

```markdown
*Concerns analysis: 2026-08-23*
```

- [ ] **Step 9: Verify the version is readable at runtime**

`src/mnemo/__init__.py` reads the version via `importlib.metadata`, so a stale install would report the old number:

```bash
cd /Users/joel/Code/mnemo && uv run python -c "import mnemo; print(mnemo.__version__)"
```
Expected: `1.12.1`

- [ ] **Step 10: Run the full suite one final time**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run pytest -q -m "not integration" 2>&1 | tail -3
```
Expected: `584 passed, 8 deselected`. Zero failures.

- [ ] **Step 11: Confirm the coverage gate still passes**

CI fails the build below 80%. This plan deleted mostly-uncovered code, so coverage should rise:

```bash
cd /Users/joel/Code/mnemo && uv run pytest -q -m "not integration" --cov=mnemo --cov-report=term --cov-fail-under=80 2>&1 | tail -3
```
Expected: passes, TOTAL at or above the 84% baseline.

- [ ] **Step 12: Confirm mypy did not regress**

Run:
```bash
cd /Users/joel/Code/mnemo && uv run mypy src/ 2>&1 | tail -1
```
Expected: at or below the ~70 errors recorded in Task 3 Step 11, and strictly below the 83 baseline. If it went up, find what regressed before committing.

- [ ] **Step 13: Commit**

```bash
cd /Users/joel/Code/mnemo && git add .planning/codebase/CONCERNS.md pyproject.toml uv.lock CLAUDE.md
git commit -m "docs: refresh CONCERNS.md, bump to 1.12.1

Five entries were resolved since 2026-03-26 (CI, coverage gate, migration
framework, tools.py size, undeclared deps). Adds the mypy-not-enforced
entry and corrects books.epub_path to books.file_path."
```

- [ ] **Step 14: Review the full diff**

Run:
```bash
cd /Users/joel/Code/mnemo && git diff main --stat
```
Expected shape: `src/mnemo/mcp/tools.py` deleted (~51 lines), `src/mnemo/mcp/_deps.py` added (~55 lines), net reduction across `tools_search.py`/`tools_books.py`/`tools_metadata.py` of roughly 84 lines, `vectors/store.py` down ~10, `services/book_service.py` down ~12, and additions in `tests/`.

Do NOT push. Report the diff stat and the final test/mypy/coverage numbers to the user and let them decide when to push.

---

## Notes for the executor

**What "done" looks like:** six commits on `joel/dead-code-cleanup`, 584 tests passing, coverage at or above 84%, mypy at or below ~70 errors, and no change to any user-visible behavior of the CLI or MCP tools.

**Explicitly out of scope — do not do these even if tempted:**
- Fixing the remaining ~70 mypy errors, or flipping `continue-on-error` in CI.
- Touching search scoring constants (`BOILERPLATE_PENALTY`, `SEMANTIC_FLOOR`, `MIN_SEMANTIC_SCORE`, `SHORT_CONTENT_PENALTY`) or the RRF blend weights. These are empirically tuned against a real library.
- Refactoring `epub/_extract.py`, `epub/parser.py`, or `cli.py`. They are large but not part of these findings.
- Adding new abstractions. The only file created is `_deps.py`, and it exists purely to absorb three existing copies of the same code.
- Running `git push`.

**If a task's test count does not match:** the expected counts assume every prior task landed. If you are executing tasks out of order or skipped one, recompute from the actual baseline rather than forcing the number.
