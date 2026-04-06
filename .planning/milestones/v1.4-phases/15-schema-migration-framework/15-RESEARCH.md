# Phase 15: Schema Migration Framework - Research

**Researched:** 2026-03-29
**Domain:** SQLite schema versioning, migration execution, Python database patterns
**Confidence:** HIGH

## Summary

Phase 15 replaces the fragile `try/except ALTER TABLE` pattern in `storage/database.py` with a numbered migration system backed by a `schema_version` table in SQLite. No external migration library is needed — the project's own requirements document explicitly calls out Alembic as out of scope ("overkill for personal tool; numbered scripts sufficient"). This is a well-understood, self-contained pattern.

The current live database (`~/.mnemo/mnemo.db`) has 12 books, no `schema_version` table, and a fully evolved schema (all 4 migrations from `_migrate_schema` have been applied). The migration system must bootstrap cleanly against this real database without corrupting it: it must detect the existing schema state, stamp it at the current version, and not re-apply any already-applied changes.

The design has two cases: (1) fresh database — run the baseline schema, stamp at the latest migration version without running incremental migrations; (2) existing database — detect missing `schema_version` table as "pre-versioning" state, introspect which columns exist to determine the current schema level, stamp at the inferred version, then apply only pending migrations.

**Primary recommendation:** Implement a `migrations/` module with numbered migration functions registered in a list, a `schema_version` table with a single integer row, and an `apply_pending_migrations(conn)` function called from `init_db`. The existing `_migrate_schema` function is deleted and its logic is captured as numbered migration scripts.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-04 | Schema changes are tracked with a `schema_version` table in SQLite | SQLite user_version PRAGMA or explicit table — explicit table is more transparent; supports inspection with standard SQL tools |
| DATA-05 | Each schema migration is a numbered script applied in order, replacing the try/except ALTER TABLE pattern | List of `(version, callable)` tuples applied in sequence; current `_migrate_schema` body becomes migrations 1–4 |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Version is defined in `pyproject.toml` (single source of truth). Follow semver: PATCH for bug fixes, MINOR for new features.
- Current version: 1.7.0 (verified from pyproject.toml — CLAUDE.md shows 1.4.4 but pyproject.toml is source of truth)
- No third-party migration library: REQUIREMENTS.md explicitly excludes Alembic

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `sqlite3` | stdlib | Schema versioning table, migration execution | Already used everywhere in the project; no new dependency |
| Python `pathlib` | stdlib | Migration script file discovery (if file-based) | Already used in `database.py` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` (existing) | >=8.0 | Tests for migration behavior | All tests — no change to test framework |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Explicit `schema_version` table | `PRAGMA user_version` | `user_version` is a single integer PRAGMA, no DDL needed, slightly less visible — but a real table is inspectable with standard SQL tools and matches the project's preference for transparency. Either works; explicit table is more idiomatic at this project's level. |
| In-memory list of migration functions | Separate `.sql` files on disk | File-based approach adds file I/O and discovery complexity with no benefit at this scale. Function list is simpler and keeps everything in one module. |
| Custom migration runner | Alembic / yoyo-migrations | Explicitly out of scope per REQUIREMENTS.md |

**Installation:** No new packages required.

## Architecture Patterns

### Recommended Project Structure

```
src/mnemo/storage/
├── database.py          # Modified: init_db calls migrations, _migrate_schema removed
└── migrations.py        # New: schema_version table DDL, migration list, apply function
```

### Pattern 1: schema_version Table

**What:** A single-row table recording the integer version number of the last applied migration.

**When to use:** Always — created during `init_db` on both fresh and existing databases.

```sql
-- Source: standard SQLite versioning pattern
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
```

On fresh database: insert the latest version number immediately after creating the main schema.
On existing database with no `schema_version` table: introspect to determine current version, then insert.

### Pattern 2: Migration Registry

**What:** An ordered list of `(version_number, migration_function)` tuples. Each function receives a `sqlite3.Connection` and applies exactly one schema change.

**When to use:** Every schema change that needs to be applied to existing databases.

```python
# Source: project-specific design, standard pattern for lightweight migration runners

def _migration_001_add_epub_path(conn: sqlite3.Connection) -> None:
    """Add epub_path column to books table (was added in v1.2)."""
    conn.execute("ALTER TABLE books ADD COLUMN epub_path TEXT")

def _migration_002_add_publisher(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE books ADD COLUMN publisher TEXT")

def _migration_003_add_year(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE books ADD COLUMN year TEXT")

def _migration_004_add_description(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE books ADD COLUMN description TEXT")

MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migration_001_add_epub_path),
    (2, _migration_002_add_publisher),
    (3, _migration_003_add_year),
    (4, _migration_004_add_description),
]

LATEST_VERSION = MIGRATIONS[-1][0]  # 4
```

### Pattern 3: apply_pending_migrations

**What:** Called from `init_db`. Reads current version, applies all migrations with version > current, updates the version row.

```python
def apply_pending_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations in version order."""
    current = _get_schema_version(conn)
    for version, migration_fn in MIGRATIONS:
        if version > current:
            migration_fn(conn)
            _set_schema_version(conn, version)
            conn.commit()
```

Each migration updates the version row immediately after executing — so a crash mid-migration leaves the DB at the last successfully committed version rather than at zero.

### Pattern 4: Fresh Database Bootstrap

**What:** When `init_db` creates a brand-new database, it runs the full `_SCHEMA_SQL` (which already includes all columns in their final form), then stamps `schema_version` at `LATEST_VERSION` without executing any incremental migrations.

```python
def init_db(db_path: Path | None = None) -> None:
    # ... connect, pragmas ...
    conn.executescript(_SCHEMA_SQL)  # creates all tables in final form
    conn.commit()

    _ensure_schema_version_table(conn)  # CREATE TABLE IF NOT EXISTS schema_version

    if _get_schema_version(conn) == 0:
        # Fresh DB: the full schema is already correct, just stamp the version
        # But we must distinguish fresh from legacy-unversioned
        if _is_fresh_database(conn):
            _set_schema_version(conn, LATEST_VERSION)
        else:
            # Legacy DB: infer version and apply pending
            inferred = _infer_legacy_version(conn)
            _set_schema_version(conn, inferred)
            apply_pending_migrations(conn)
```

### Pattern 5: Legacy Database Detection

**What:** An existing database without `schema_version` was created before this system. Must determine which migrations have already been applied by inspecting the schema.

```python
def _infer_legacy_version(conn: sqlite3.Connection) -> int:
    """Infer migration level by checking which columns exist."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(books)")}
    if "description" in cols:
        return 4
    if "year" in cols:
        return 3
    if "publisher" in cols:
        return 2
    if "epub_path" in cols:
        return 1
    return 0
```

The live database has all 4 columns → inferred version is 4 → no migrations run.

### Pattern 6: Fresh vs Legacy Detection

**What:** Distinguish a brand-new (empty) database from an old database that predates versioning.

```python
def _is_fresh_database(conn: sqlite3.Connection) -> bool:
    """Return True if the books table was just created (no rows, and table exists)."""
    # A fresh DB has the books table but zero books AND no pre-existing data
    # A safer test: check if schema_version had a row before we created the table
    # Since we use CREATE TABLE IF NOT EXISTS, we can check the sqlite_master
    # for a pre-existing table that lacks our version columns.
    # Simpler: if books table exists with no rows AND has all current columns, it's fresh.
    count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    cols = {row[1] for row in conn.execute("PRAGMA table_info(books)")}
    return count == 0 and "description" in cols
```

Note: This heuristic is safe because the full `_SCHEMA_SQL` creates `books` with all columns. Legacy databases may have zero books but will be missing columns → `_is_fresh_database` returns False → falls through to `_infer_legacy_version`.

### Anti-Patterns to Avoid

- **try/except on ALTER TABLE:** The current pattern — silently swallowing `sqlite3.OperationalError` "duplicate column name" hides other errors. Replaced by version-checked application.
- **Re-running migrations on every startup:** Use the `schema_version` table to skip already-applied migrations.
- **Wrapping all migrations in one transaction:** If a multi-step migration fails halfway through, a single transaction rollback loses all progress. Apply and commit each migration individually.
- **Hard-coding column checks inside migration functions:** Migration functions should only contain the DDL for that migration, not defensive "if column exists" guards. The version gate handles idempotency.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SQL schema inspection | Custom parser | `PRAGMA table_info(table_name)` | SQLite built-in, returns column names, types, constraints |
| SQLite version tracking | External file | `schema_version` table in same DB | Atomic with the data, inspectable with `sqlite3` CLI |
| Migration atomicity | Multi-step transactions | Commit after each migration + version update | Simpler recovery, version row reflects committed state |

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | Live `~/.mnemo/mnemo.db` — 12 books, schema at version 4 equivalent (all columns present), no `schema_version` table | Migration bootstrap must detect and stamp at version 4 without re-running DDL |
| Live service config | None — local SQLite, no service registration | None |
| OS-registered state | None | None |
| Secrets/env vars | None relevant to this migration | None |
| Build artifacts | None | None |

**Key risk:** The live database must survive the first `init_db` call after this phase. The `_infer_legacy_version` logic must correctly return 4 for databases that have all four columns (`epub_path`, `publisher`, `year`, `description`).

## Common Pitfalls

### Pitfall 1: Bootstrapping the Version Row Twice

**What goes wrong:** `_ensure_schema_version_table` creates the table but doesn't insert a row. `_get_schema_version` then returns 0 (no rows). Both fresh and legacy databases would run all 4 migrations again.

**Why it happens:** `CREATE TABLE IF NOT EXISTS` is silent. The row must be explicitly inserted (or the empty case handled).

**How to avoid:** `_get_schema_version` should return 0 when no row exists (meaning "apply all migrations"). For fresh databases, detect this case and stamp at `LATEST_VERSION` directly. For legacy databases with no row, use `_infer_legacy_version` to determine the starting point.

**Warning signs:** Tests fail with `sqlite3.OperationalError: duplicate column name` when opening an existing DB.

### Pitfall 2: Incorrect Fresh DB Detection

**What goes wrong:** A fresh database (created by `_SCHEMA_SQL`) is mistaken for a legacy one at version 0, causing all 4 migrations to try adding columns that already exist.

**Why it happens:** `_SCHEMA_SQL` already includes all columns (it's always been updated to the latest schema). No `schema_version` row exists yet. Code checks version == 0 and tries to run all migrations.

**How to avoid:** Check column presence in `PRAGMA table_info(books)`. If all current columns are present AND the `books` table has zero rows, it's almost certainly fresh. Better: check whether `description` exists in `books` before running any migration — if it does, the table was created with current DDL.

**Warning signs:** Tests that create a fresh DB and immediately inspect it show `description` column already present but `schema_version` set to 0.

### Pitfall 3: Missing schema_version Row After Table Creation

**What goes wrong:** `_ensure_schema_version_table` creates an empty `schema_version` table. `_get_schema_version` does `SELECT version FROM schema_version` and gets 0 rows → Python error or wrong return value.

**How to avoid:** `_get_schema_version` should handle zero rows: `row = conn.execute("SELECT version FROM schema_version").fetchone(); return row[0] if row else 0`.

### Pitfall 4: Test Fixtures Creating Fresh vs Legacy DBs

**What goes wrong:** Existing tests in `test_storage.py` call `init_db(db_path)` on a fresh temporary path. After this change, `init_db` must still work correctly — it should produce a versioned database at `LATEST_VERSION` with no extra work.

**How to avoid:** The test `test_init_db_idempotent` already covers calling `init_db` twice. New tests should verify `schema_version` is populated correctly after a fresh `init_db`, and after opening a legacy-style DB (one created without the versioning system).

### Pitfall 5: WAL Mode and Transaction Boundaries

**What goes wrong:** `init_db` calls `conn.executescript(_SCHEMA_SQL)` which issues an implicit `COMMIT` before the script runs. If subsequent migration code assumes a transaction is open, it may not be.

**Why it happens:** SQLite's `executescript()` commits any pending transaction before running.

**How to avoid:** After `executescript`, the connection is in autocommit mode. Use explicit `conn.execute("BEGIN")` + `conn.commit()` for migration transactions, or rely on individual `conn.commit()` calls per migration (already the recommended pattern above).

## Code Examples

### schema_version Table DDL

```sql
-- Source: standard SQLite single-version-row pattern
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
```

### Version Read/Write Helpers

```python
# Source: project-specific, sqlite3 stdlib
def _get_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    return row[0] if row else 0

def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    existing = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    if existing:
        conn.execute("UPDATE schema_version SET version = ?", (version,))
    else:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
```

### PRAGMA table_info Usage

```python
# Source: SQLite documentation — stdlib, no external deps
cols = {row[1] for row in conn.execute("PRAGMA table_info(books)")}
has_epub_path = "epub_path" in cols
```

### Existing Tests That Must Continue to Pass

From `test_storage.py`:
- `TestDatabaseInitialization::test_init_db_creates_tables` — must still find all expected tables
- `TestDatabaseInitialization::test_init_db_idempotent` — `init_db` called twice must not raise
- `TestEpubPath::test_existing_db_without_epub_path_gets_migrated` — creates a bare-bones `books` table without `epub_path`, then calls `init_db`, then asserts `epub_path` is present. This test will exercise the migration path for version 0 → 1. It must continue to pass.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies — pure Python stdlib sqlite3 changes only)

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_storage.py -q` |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-04 | Fresh `init_db` creates `schema_version` table | unit | `pytest tests/test_storage.py::TestSchemaVersion::test_fresh_db_has_schema_version -x` | ❌ Wave 0 |
| DATA-04 | Fresh `init_db` sets version to LATEST_VERSION | unit | `pytest tests/test_storage.py::TestSchemaVersion::test_fresh_db_at_latest_version -x` | ❌ Wave 0 |
| DATA-04 | `init_db` on existing versioned DB is idempotent | unit | `pytest tests/test_storage.py::TestSchemaVersion::test_versioned_db_idempotent -x` | ❌ Wave 0 |
| DATA-05 | Legacy DB (no schema_version) gets stamped at inferred version | unit | `pytest tests/test_storage.py::TestSchemaVersion::test_legacy_db_gets_stamped -x` | ❌ Wave 0 |
| DATA-05 | DB missing columns has pending migrations applied | unit | `pytest tests/test_storage.py::TestSchemaVersion::test_partial_legacy_db_migrated -x` | ❌ Wave 0 |
| DATA-05 | `test_existing_db_without_epub_path_gets_migrated` continues to pass | regression | `pytest tests/test_storage.py::TestEpubPath::test_existing_db_without_epub_path_gets_migrated -x` | ✅ |
| DATA-05 | All 505 existing tests pass unchanged | regression | `python -m pytest -q` | ✅ |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_storage.py -q`
- **Per wave merge:** `python -m pytest -q`
- **Phase gate:** Full suite green (505+ tests) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_storage.py` — add `TestSchemaVersion` class with the 5 new test cases above. The existing file already contains fixtures (`db_path`) that the new tests can reuse.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| try/except duplicate column | schema_version table + numbered functions | Phase 15 | Explicit version tracking, no swallowed errors, auditable history |
| `PRAGMA user_version` (common) | Explicit `schema_version` table | Project design choice | Table is visible with `SELECT * FROM schema_version`, no PRAGMA knowledge needed |

**Deprecated/outdated after this phase:**
- `_migrate_schema(conn)` function in `database.py`: replaced entirely by the new migration runner
- The `try/except sqlite3.OperationalError` pattern: replaced by version-gated application

## Open Questions

1. **Where should the migrations module live?**
   - What we know: `storage/database.py` is the current home for all DB init logic
   - What's unclear: whether migrations belong in `storage/migrations.py` (co-located) or a new `storage/migrations/` package
   - Recommendation: `storage/migrations.py` as a single file — the planner can decide if a package structure is needed

2. **Should future migration scripts be SQL strings or Python callables?**
   - What we know: Current migrations are simple `ALTER TABLE ... ADD COLUMN` calls
   - What's unclear: Whether future phases will need multi-statement migrations (e.g., data migrations, index changes)
   - Recommendation: Python callables (functions receiving `conn`) — more flexible than SQL strings, no SQL injection risk, easier to write conditional logic if needed

3. **Version number scheme: sequential integers vs. timestamps?**
   - What we know: Requirements say "numbered scripts applied in order" — integers implied
   - Recommendation: Sequential integers (1, 2, 3, ...) matching migration number — simpler than timestamps for a single-developer tool

## Sources

### Primary (HIGH confidence)

- SQLite `PRAGMA table_info` — standard SQLite documentation, introspection mechanism
- SQLite `user_version` PRAGMA — standard SQLite documentation, alternative versioning approach
- Project source: `src/mnemo/storage/database.py` — read directly, current implementation analyzed
- Project tests: `tests/test_storage.py` — read directly, existing test coverage mapped

### Secondary (MEDIUM confidence)

- Standard schema migration pattern for SQLite without frameworks — widely used across Python projects at this scale; cross-verified with SQLite documentation

### Tertiary (LOW confidence)

- None — no claims made from unverified sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — stdlib only, no new dependencies
- Architecture: HIGH — pattern derived directly from reading existing code and SQLite docs
- Pitfalls: HIGH — identified by analyzing existing `_migrate_schema` code and the live DB state

**Research date:** 2026-03-29
**Valid until:** Stable indefinitely (SQLite stdlib, no external dependencies)
