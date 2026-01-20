"""Storage layer for Mnemo.

Provides SQLite persistence with FTS5 full-text search for books and chunks.

Main exports:
- init_db: Initialize database schema
- get_connection: Get a database connection
- get_db_path: Get default database path
- BookRepository: CRUD operations for books
- ChunkRepository: CRUD and search operations for chunks
"""

from mnemo.storage.database import get_connection, get_db_path, init_db
from mnemo.storage.repository import BookRepository, ChunkRepository

__all__ = [
    "init_db",
    "get_connection",
    "get_db_path",
    "BookRepository",
    "ChunkRepository",
]
