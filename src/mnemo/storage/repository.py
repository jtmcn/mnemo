"""Repository classes for database operations.

Provides CRUD operations and search functionality for books and chunks:
- BookRepository: Book CRUD with duplicate detection
- ChunkRepository: Bulk insert and FTS5 search
"""

from __future__ import annotations

import json
import re
import sqlite3
from difflib import SequenceMatcher

from mnemo.models import Book, Chunk, ContentType


class BookRepository:
    """Repository for Book CRUD operations.

    Handles serialization of JSON fields (authors) and provides
    duplicate detection via file_hash.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize repository with database connection.

        Args:
            conn: SQLite connection with foreign keys enabled
        """
        self.conn = conn

    def add(self, book: Book) -> Book:
        """Insert a book into the database.

        Args:
            book: Book instance to insert

        Returns:
            The same book instance (confirms successful insert)

        Raises:
            sqlite3.IntegrityError: If book with same id or file_hash exists
        """
        self.conn.execute(
            """
            INSERT INTO books (id, title, authors, isbn, file_hash,
                             default_language, structure_source, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book.id,
                book.title,
                json.dumps(book.authors),
                book.isbn,
                book.file_hash,
                book.default_language,
                book.structure_source,
                book.added_at.isoformat(),
            ),
        )
        self.conn.commit()
        return book

    def get(self, book_id: str) -> Book | None:
        """Get a book by its ID.

        Args:
            book_id: 6-char hex book identifier

        Returns:
            Book instance if found, None otherwise
        """
        row = self.conn.execute(
            "SELECT * FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_book(row)

    def get_by_hash(self, file_hash: str) -> Book | None:
        """Check for duplicate by file hash.

        Args:
            file_hash: SHA256 hash of EPUB content

        Returns:
            Existing Book if duplicate found, None otherwise
        """
        row = self.conn.execute(
            "SELECT * FROM books WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_book(row)

    def list_all(self) -> list[Book]:
        """List all books in the database.

        Returns:
            List of all Book instances, ordered by added_at desc
        """
        rows = self.conn.execute(
            "SELECT * FROM books ORDER BY added_at DESC"
        ).fetchall()
        return [self._row_to_book(row) for row in rows]

    def delete(self, book_id: str) -> bool:
        """Delete a book by ID.

        Chunks are automatically deleted via FK cascade.

        Args:
            book_id: 6-char hex book identifier

        Returns:
            True if book was deleted, False if not found
        """
        cursor = self.conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def find_similar_title(self, title: str, threshold: float = 0.8) -> list[Book]:
        """Find books with similar titles.

        Uses SequenceMatcher for fuzzy matching. Useful for detecting
        different editions of the same book.

        Args:
            title: Title to search for
            threshold: Similarity threshold (0.0 to 1.0), default 0.8

        Returns:
            List of books with titles similar to the query
        """
        all_books = self.list_all()
        similar = []
        title_lower = title.lower()

        for book in all_books:
            ratio = SequenceMatcher(None, title_lower, book.title.lower()).ratio()
            if ratio >= threshold:
                similar.append(book)

        return similar

    def update(
        self,
        book_id: str,
        title: str | None = None,
        authors: list[str] | None = None,
        isbn: str | None = None,
    ) -> Book | None:
        """Update a book's metadata fields.

        Only provided (non-None) fields are updated. At least one field
        must be provided.

        Args:
            book_id: 6-char hex book identifier
            title: New title (if provided)
            authors: New author list (if provided)
            isbn: New ISBN (if provided)

        Returns:
            Updated Book instance, or None if book not found

        Raises:
            ValueError: If no fields are provided
        """
        # Build dynamic SET clause for provided fields only
        fields: list[str] = []
        values: list[str | None] = []

        if title is not None:
            fields.append("title = ?")
            values.append(title)
        if authors is not None:
            fields.append("authors = ?")
            values.append(json.dumps(authors))
        if isbn is not None:
            fields.append("isbn = ?")
            values.append(isbn)

        if not fields:
            raise ValueError(
                "At least one field (title, authors, isbn) must be provided"
            )

        values.append(book_id)
        sql = f"UPDATE books SET {', '.join(fields)} WHERE id = ?"

        cursor = self.conn.execute(sql, values)
        self.conn.commit()

        if cursor.rowcount == 0:
            return None

        return self.get(book_id)

    def _row_to_book(self, row: sqlite3.Row) -> Book:
        """Convert a database row to a Book instance."""
        from datetime import datetime

        return Book(
            id=row["id"],
            title=row["title"],
            authors=json.loads(row["authors"]),
            isbn=row["isbn"],
            file_hash=row["file_hash"],
            default_language=row["default_language"],
            structure_source=row["structure_source"],
            added_at=datetime.fromisoformat(row["added_at"]),
        )


class ChunkRepository:
    """Repository for Chunk operations including FTS5 search.

    Handles bulk inserts efficiently and provides full-text search
    with optional filtering.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize repository with database connection.

        Args:
            conn: SQLite connection with foreign keys enabled
        """
        self.conn = conn

    def add_many(self, chunks: list[Chunk]) -> list[Chunk]:
        """Bulk insert chunks efficiently.

        Uses executemany for better performance with large batches.

        Args:
            chunks: List of Chunk instances to insert

        Returns:
            The same list of chunks (confirms successful insert)

        Raises:
            sqlite3.IntegrityError: If any chunk violates constraints
        """
        if not chunks:
            return chunks

        self.conn.executemany(
            """
            INSERT INTO chunks (id, book_id, content, content_type, token_count,
                              section_path, sections, language, sequence,
                              prev_chunk_id, next_chunk_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.id,
                    chunk.book_id,
                    chunk.content,
                    chunk.content_type.value,
                    chunk.token_count,
                    json.dumps(chunk.section_path),
                    json.dumps(chunk.sections),
                    chunk.language,
                    chunk.sequence,
                    chunk.prev_chunk_id,
                    chunk.next_chunk_id,
                )
                for chunk in chunks
            ],
        )
        self.conn.commit()
        return chunks

    def get(self, chunk_id: str) -> Chunk | None:
        """Get a chunk by its ID.

        Args:
            chunk_id: UUID chunk identifier

        Returns:
            Chunk instance if found, None otherwise
        """
        row = self.conn.execute(
            "SELECT * FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_chunk(row)

    def get_by_book(self, book_id: str) -> list[Chunk]:
        """Get all chunks for a book, ordered by sequence.

        Args:
            book_id: 6-char hex book identifier

        Returns:
            List of Chunk instances in reading order
        """
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE book_id = ? ORDER BY sequence",
            (book_id,),
        ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def search_fts(
        self,
        query: str,
        book_id: str | None = None,
        content_type: ContentType | None = None,
        limit: int = 20,
    ) -> list[Chunk]:
        """Full-text search with optional filters.

        Uses FTS5 MATCH for efficient keyword search. Supports:
        - Simple words: "python"
        - Phrases: '"machine learning"'
        - Boolean: "python AND async"
        - Prefix: "async*"

        Args:
            query: FTS5 search query
            book_id: Optional filter by book
            content_type: Optional filter by content type
            limit: Maximum results to return (default 20)

        Returns:
            List of matching Chunk instances, ranked by relevance
        """
        # Sanitize query for FTS5 - escape special characters
        sanitized_query = self._sanitize_fts_query(query)
        if not sanitized_query:
            return []

        # Build query with optional filters
        sql = """
            SELECT c.* FROM chunks c
            JOIN chunks_fts fts ON c.rowid = fts.rowid
            WHERE chunks_fts MATCH ?
        """
        params: list[str | int] = [sanitized_query]

        if book_id is not None:
            sql += " AND c.book_id = ?"
            params.append(book_id)

        if content_type is not None:
            sql += " AND c.content_type = ?"
            params.append(content_type.value)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def count_by_book(self, book_id: str) -> int:
        """Count chunks for a book.

        Args:
            book_id: 6-char hex book identifier

        Returns:
            Number of chunks belonging to the book
        """
        row = self.conn.execute(
            "SELECT COUNT(*) as count FROM chunks WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        return row["count"]

    def _sanitize_fts_query(self, query: str) -> str:
        """Sanitize a query for FTS5.

        Wraps search terms in quotes to safely handle special characters.
        This provides simple, reliable search behavior.

        Args:
            query: Raw user query

        Returns:
            Sanitized query safe for FTS5 MATCH
        """
        # Strip leading/trailing whitespace
        query = query.strip()
        if not query:
            return ""

        # Simple approach: wrap each word in quotes to escape all special chars
        # This handles: C++, foo(bar), test@example.com, etc.
        # Split on whitespace, escape internal quotes, wrap each term
        words = query.split()
        if not words:
            return ""

        # Escape any quotes in words by doubling them (FTS5 escape sequence)
        escaped_words = [w.replace('"', '""') for w in words]
        return " ".join(f'"{w}"' for w in escaped_words if w)

    def _row_to_chunk(self, row: sqlite3.Row) -> Chunk:
        """Convert a database row to a Chunk instance."""
        return Chunk(
            id=row["id"],
            book_id=row["book_id"],
            content=row["content"],
            content_type=ContentType(row["content_type"]),
            token_count=row["token_count"],
            section_path=json.loads(row["section_path"]),
            sections=json.loads(row["sections"]),
            language=row["language"],
            sequence=row["sequence"],
            prev_chunk_id=row["prev_chunk_id"],
            next_chunk_id=row["next_chunk_id"],
        )
