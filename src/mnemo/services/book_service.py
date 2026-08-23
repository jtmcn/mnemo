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
