"""Shared book operations used by both CLI and MCP layers."""
from pathlib import Path

from mnemo.storage import BookRepository
from mnemo.models import Book


def validate_epub_path(path: Path) -> str | None:
    """Validate an EPUB file path. Returns error message or None if valid."""
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
