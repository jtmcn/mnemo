"""SQLite database schema and connection management for Mnemo.

Provides database initialization with:
- Books table for metadata storage
- Chunks table with FK cascade to books
- FTS5 virtual table for full-text search
- Triggers to keep FTS index in sync
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Schema SQL statements
_SCHEMA_SQL = """
-- Books table
CREATE TABLE IF NOT EXISTS books (
    id TEXT PRIMARY KEY,           -- 6-char hex hash
    title TEXT NOT NULL,
    authors TEXT NOT NULL,         -- JSON array
    isbn TEXT,
    file_hash TEXT UNIQUE NOT NULL, -- SHA256 for dedup
    default_language TEXT,
    structure_source TEXT NOT NULL, -- 'toc' or 'inferred'
    added_at TEXT NOT NULL,         -- ISO timestamp
    epub_path TEXT                  -- absolute path to source EPUB
);

-- Chunks table with FK cascade
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,           -- UUID
    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    content_type TEXT NOT NULL,    -- TEXT, CODE, etc.
    token_count INTEGER NOT NULL,
    section_path TEXT NOT NULL,    -- JSON array
    sections TEXT NOT NULL,        -- JSON array (for spanning)
    language TEXT,
    sequence INTEGER NOT NULL,
    prev_chunk_id TEXT,
    next_chunk_id TEXT
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content=chunks,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_chunks_book_id ON chunks(book_id);
CREATE INDEX IF NOT EXISTS idx_chunks_content_type ON chunks(content_type);
CREATE INDEX IF NOT EXISTS idx_chunks_sequence ON chunks(book_id, sequence);
"""


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply schema migrations for existing databases.

    Idempotent - safe to call multiple times. Each migration
    handles its own "already applied" case gracefully.
    """
    # Migration: add epub_path column to books table
    try:
        conn.execute("ALTER TABLE books ADD COLUMN epub_path TEXT")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e):
            raise


def get_db_path() -> Path:
    """Get the default database path.

    Returns:
        Path to ~/.mnemo/mnemo.db (creates directory if needed)
    """
    db_dir = Path.home() / ".mnemo"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "mnemo.db"


def init_db(db_path: Path | None = None) -> None:
    """Initialize the database schema.

    Creates all tables, triggers, and indexes if they don't exist.
    Safe to call multiple times (uses IF NOT EXISTS).

    Args:
        db_path: Path to database file. Defaults to ~/.mnemo/mnemo.db
    """
    if db_path is None:
        db_path = get_db_path()

    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys = ON")
        # Use WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode = WAL")
        # Execute schema
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
        # Apply migrations for existing databases
        _migrate_schema(conn)
    finally:
        conn.close()


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a database connection with proper settings.

    The connection has:
    - Foreign keys enabled (for cascade deletes)
    - WAL journal mode (for better concurrency)
    - Row factory set to sqlite3.Row (for named column access)

    Args:
        db_path: Path to database file. Defaults to ~/.mnemo/mnemo.db

    Returns:
        Configured SQLite connection

    Note:
        Caller is responsible for closing the connection or using it
        as a context manager.
    """
    if db_path is None:
        db_path = get_db_path()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
