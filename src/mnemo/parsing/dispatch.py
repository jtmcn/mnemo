"""Route document parsing to the appropriate format-specific parser."""

from __future__ import annotations

from pathlib import Path

from mnemo.models import Book
from mnemo.parsing.models import ContentBlock

SUPPORTED_FORMATS = {".epub", ".docx"}


def parse_book(file_path: Path | str) -> tuple[Book, list[ContentBlock]]:
    """Parse a book file into metadata and content blocks.

    Routes to the correct parser based on file extension.

    Args:
        file_path: Path to the book file (.epub, .docx)

    Returns:
        Tuple of (Book metadata, list of ContentBlocks)

    Raises:
        ValueError: If file format is not supported
        FileNotFoundError: If file does not exist
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()

    if suffix == ".epub":
        from mnemo.epub import EPUBParser

        return EPUBParser().parse(file_path)
    elif suffix == ".docx":
        from mnemo.docx import DocxParser

        return DocxParser().parse(file_path)
    else:
        raise ValueError(
            f"Unsupported file format: {suffix} (supported: {', '.join(sorted(SUPPORTED_FORMATS))})"
        )
