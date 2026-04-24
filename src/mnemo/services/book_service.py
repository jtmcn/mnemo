"""Shared book operations used by both CLI and MCP layers."""

from pathlib import Path

from mnemo.models import Book
from mnemo.parsing import SUPPORTED_FORMATS
from mnemo.storage import BookRepository


def validate_book_path(path: Path) -> str | None:
    """Validate a book file path. Returns error message or None if valid."""
    if not path.exists():
        return f"File not found: {path}"
    if path.suffix.lower() not in SUPPORTED_FORMATS:
        return (
            f"Unsupported format: {path.suffix} (supported: {', '.join(sorted(SUPPORTED_FORMATS))})"
        )
    return None


def find_duplicate(book_repo: BookRepository, file_hash: str) -> Book | None:
    """Check for an existing book with the same file hash."""
    return book_repo.get_by_hash(file_hash)


def list_all_books(book_repo: BookRepository) -> list[Book]:
    """Return all indexed books."""
    return book_repo.list_all()
