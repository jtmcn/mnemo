"""Schema migration framework for Mnemo SQLite database.

Replaces the try/except ALTER TABLE pattern with versioned,
numbered migration functions tracked by a schema_version table.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

# --- Migration functions ---
# Each receives a connection and applies exactly one schema change.
# The version gate ensures they only run when needed.


def _migration_001_add_epub_path(conn: sqlite3.Connection) -> None:
    """Add epub_path column to books table."""
    conn.execute("ALTER TABLE books ADD COLUMN epub_path TEXT")


def _migration_002_add_publisher(conn: sqlite3.Connection) -> None:
    """Add publisher column to books table."""
    conn.execute("ALTER TABLE books ADD COLUMN publisher TEXT")


def _migration_003_add_year(conn: sqlite3.Connection) -> None:
    """Add year column to books table."""
    conn.execute("ALTER TABLE books ADD COLUMN year TEXT")


def _migration_004_add_description(conn: sqlite3.Connection) -> None:
    """Add description column to books table."""
    conn.execute("ALTER TABLE books ADD COLUMN description TEXT")


# Ordered list of (version_number, migration_function)
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migration_001_add_epub_path),
    (2, _migration_002_add_publisher),
    (3, _migration_003_add_year),
    (4, _migration_004_add_description),
]

LATEST_VERSION: int = MIGRATIONS[-1][0]  # 4

# --- Version helpers ---


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Read current schema version. Returns 0 if no row exists."""
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    return row[0] if row else 0


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """Insert or update the schema version row."""
    existing = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    if existing:
        conn.execute("UPDATE schema_version SET version = ?", (version,))
    else:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))


def _is_fresh_database(conn: sqlite3.Connection) -> bool:
    """Return True if database was just created (no book rows, all columns present)."""
    count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    cols = {row[1] for row in conn.execute("PRAGMA table_info(books)")}
    return count == 0 and "description" in cols


def _infer_legacy_version(conn: sqlite3.Connection) -> int:
    """Infer migration level of a legacy (pre-versioning) database by checking columns."""
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


# --- Public API ---


def ensure_schema_version(conn: sqlite3.Connection) -> None:
    """Create the schema_version table if it doesn't exist."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    conn.commit()


def apply_pending_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations in version order.

    For fresh databases: stamps at LATEST_VERSION without running migrations.
    For legacy databases: infers current version, applies pending, stamps.
    For versioned databases: skips already-applied migrations.
    """
    current = _get_schema_version(conn)

    if current == 0:
        # No version row — either fresh or legacy
        if _is_fresh_database(conn):
            _set_schema_version(conn, LATEST_VERSION)
            conn.commit()
            return
        else:
            # Legacy DB: infer version from column presence
            inferred = _infer_legacy_version(conn)
            _set_schema_version(conn, inferred)
            conn.commit()
            current = inferred

    # Apply any pending migrations
    for version, migration_fn in MIGRATIONS:
        if version > current:
            migration_fn(conn)
            _set_schema_version(conn, version)
            conn.commit()
