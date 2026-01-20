---
phase: 01-foundation
plan: 03
type: execute
wave: 2
depends_on: ["01-01"]
files_modified:
  - src/mnemo/storage/__init__.py
  - src/mnemo/storage/database.py
  - src/mnemo/storage/repository.py
  - tests/test_storage.py
autonomous: true

must_haves:
  truths:
    - "Books and chunks persist in SQLite"
    - "Deleting a book cascades to delete all its chunks"
    - "Full text search works on chunk content"
    - "Duplicate books are detected by file hash"
  artifacts:
    - path: "src/mnemo/storage/database.py"
      provides: "SQLite schema and connection management"
      exports: ["init_db", "get_connection"]
    - path: "src/mnemo/storage/repository.py"
      provides: "CRUD operations for books and chunks"
      exports: ["BookRepository", "ChunkRepository"]
  key_links:
    - from: "src/mnemo/storage/repository.py"
      to: "src/mnemo/models.py"
      via: "model imports"
      pattern: "from mnemo.models import Book, Chunk"
    - from: "src/mnemo/storage/database.py"
      to: "FTS5"
      via: "virtual table creation"
      pattern: "CREATE VIRTUAL TABLE.*fts5"
---

<objective>
Build SQLite storage layer with FTS5 for full-text search and proper cascade deletes.

Purpose: Provide persistent storage for books and chunks that supports keyword search (hybrid with vector search in Phase 3) and maintains referential integrity.

Output: Repository classes for Book and Chunk CRUD with FTS5 search capability.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phases/01-foundation/01-CONTEXT.md
@.planning/phases/01-foundation/01-01-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create database schema with FTS5</name>
  <files>src/mnemo/storage/__init__.py, src/mnemo/storage/database.py</files>
  <action>
Create src/mnemo/storage/__init__.py exporting main components.

Create database.py with schema and connection management:

1. Schema design:
```sql
-- Books table
CREATE TABLE IF NOT EXISTS books (
    id TEXT PRIMARY KEY,           -- 6-char hex hash
    title TEXT NOT NULL,
    authors TEXT NOT NULL,         -- JSON array
    isbn TEXT,
    file_hash TEXT UNIQUE NOT NULL, -- SHA256 for dedup
    default_language TEXT,
    structure_source TEXT NOT NULL, -- 'toc' or 'inferred'
    added_at TEXT NOT NULL         -- ISO timestamp
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
```

2. Connection management:
- get_db_path() -> Path (default: ~/.mnemo/mnemo.db)
- init_db(db_path: Path | None = None) -> create schema
- get_connection(db_path: Path | None = None) -> sqlite3.Connection
- Enable foreign keys: PRAGMA foreign_keys = ON
- Use WAL mode for better concurrency: PRAGMA journal_mode = WAL
  </action>
  <verify>
```python
from mnemo.storage.database import init_db, get_connection
import tempfile
with tempfile.TemporaryDirectory() as td:
    db_path = Path(td) / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    # Verify tables exist
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert ('books',) in tables
    assert ('chunks',) in tables
```
  </verify>
  <done>Database initializes with books, chunks, chunks_fts tables and all triggers</done>
</task>

<task type="auto">
  <name>Task 2: Implement repository classes with FTS search</name>
  <files>src/mnemo/storage/repository.py, tests/test_storage.py</files>
  <action>
Create repository.py with BookRepository and ChunkRepository:

1. BookRepository:
```python
class BookRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, book: Book) -> Book:
        """Insert book, return with confirmed id."""

    def get(self, book_id: str) -> Book | None:
        """Get book by id."""

    def get_by_hash(self, file_hash: str) -> Book | None:
        """Check for duplicate by file hash."""

    def list_all(self) -> list[Book]:
        """List all books."""

    def delete(self, book_id: str) -> bool:
        """Delete book (chunks cascade automatically)."""

    def find_similar_title(self, title: str, threshold: float = 0.8) -> list[Book]:
        """Find books with similar titles (for edition detection)."""
```

2. ChunkRepository:
```python
class ChunkRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add_many(self, chunks: list[Chunk]) -> list[Chunk]:
        """Bulk insert chunks efficiently."""

    def get(self, chunk_id: str) -> Chunk | None:
        """Get chunk by id."""

    def get_by_book(self, book_id: str) -> list[Chunk]:
        """Get all chunks for a book, ordered by sequence."""

    def search_fts(self, query: str, book_id: str | None = None,
                   content_type: ContentType | None = None,
                   limit: int = 20) -> list[Chunk]:
        """Full-text search with optional filters."""

    def count_by_book(self, book_id: str) -> int:
        """Count chunks for a book."""
```

3. FTS search implementation:
- Use MATCH operator: SELECT * FROM chunks_fts WHERE chunks_fts MATCH ?
- Join back to chunks table for full data
- Apply filters after FTS match
- Handle special characters in query (escape or strip)

4. JSON serialization helpers:
- authors: list[str] <-> JSON string
- section_path: list[str] <-> JSON string
- sections: list[str] <-> JSON string

5. Create tests/test_storage.py:
- Test book CRUD
- Test chunk bulk insert
- Test cascade delete (delete book -> chunks gone)
- Test FTS search with various queries
- Test duplicate detection by file_hash
- Test filtering by content_type
  </action>
  <verify>pytest tests/test_storage.py -v</verify>
  <done>All repository methods work, cascade delete verified, FTS search returns results</done>
</task>

</tasks>

<verification>
```bash
# Unit tests
pytest tests/test_storage.py -v

# Import check
python -c "from mnemo.storage import BookRepository, ChunkRepository, init_db; print('Storage OK')"

# Cascade delete verification
python -c "
import tempfile
from pathlib import Path
from mnemo.storage.database import init_db, get_connection
from mnemo.storage.repository import BookRepository, ChunkRepository
from mnemo.models import Book, Chunk, ContentType
from datetime import datetime
import uuid

with tempfile.TemporaryDirectory() as td:
    db_path = Path(td) / 'test.db'
    init_db(db_path)
    conn = get_connection(db_path)

    book_repo = BookRepository(conn)
    chunk_repo = ChunkRepository(conn)

    # Add book
    book = Book(id='abc123', title='Test', authors=['Author'],
                file_hash='hash123', structure_source='toc', added_at=datetime.now())
    book_repo.add(book)

    # Add chunks
    chunks = [Chunk(id=str(uuid.uuid4()), book_id='abc123', content='test content',
                    content_type=ContentType.TEXT, token_count=2, section_path=['Ch1'],
                    sections=['Ch1'], sequence=i) for i in range(3)]
    chunk_repo.add_many(chunks)

    # Verify chunks exist
    assert chunk_repo.count_by_book('abc123') == 3

    # Delete book
    book_repo.delete('abc123')

    # Verify cascade
    assert chunk_repo.count_by_book('abc123') == 0
    print('Cascade delete works!')
"
```
</verification>

<success_criteria>
1. init_db creates all tables, triggers, and indexes
2. BookRepository supports full CRUD operations
3. ChunkRepository supports bulk insert and search
4. Deleting a book automatically deletes all its chunks (FK cascade)
5. FTS5 search returns relevant chunks for keyword queries
6. Duplicate books detected by file_hash before insert
7. All tests pass
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-03-SUMMARY.md`
</output>
