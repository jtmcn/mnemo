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
