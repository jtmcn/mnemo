"""Route document parsing to the appropriate format-specific parser."""

from __future__ import annotations

import hashlib
from pathlib import Path

from mnemo.models import Book
from mnemo.parsing.models import ContentBlock

SUPPORTED_FORMATS = {".epub", ".docx", ".pdf"}


def pre_parse_metadata(file_path: Path | str) -> Book:
    """Extract preliminary metadata from a book file for duplicate detection.

    For EPUB files, delegates to the full metadata extractor (ISBN, language, etc.).
    For other formats, computes a file hash and builds a stub Book from the filename.

    Args:
        file_path: Path to the book file (.epub, .docx, .pdf)

    Returns:
        Book model with at least id, title, and file_hash populated

    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file format is not supported
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported file format: {suffix} (supported: {', '.join(sorted(SUPPORTED_FORMATS))})"
        )

    if suffix == ".epub":
        from mnemo.epub.metadata import extract_metadata

        return extract_metadata(file_path)

    file_bytes = file_path.read_bytes()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    return Book(
        id=Book.generate_id(file_bytes, file_path.stem),
        title=file_path.stem,
        file_hash=file_hash,
        structure_source="inferred",
    )


def content_hash(blocks: list[ContentBlock]) -> str:
    """SHA-256 over each block's type and content, independent of file metadata."""
    hasher = hashlib.sha256()
    for block in blocks:
        hasher.update(block.content_type.value.encode())
        hasher.update(b"\0")
        hasher.update(block.content.encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def parse_book(file_path: Path | str) -> tuple[Book, list[ContentBlock]]:
    """Parse a book file into metadata and content blocks.

    Routes to the correct parser based on file extension.

    Args:
        file_path: Path to the book file (.epub, .docx, .pdf)

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

        book, blocks = EPUBParser().parse(file_path)
    elif suffix == ".docx":
        from mnemo.docx import DocxParser

        book, blocks = DocxParser().parse(file_path)
    elif suffix == ".pdf":
        from mnemo.pdf import PdfParser

        book, blocks = PdfParser().parse(file_path)
    else:
        raise ValueError(
            f"Unsupported file format: {suffix} (supported: {', '.join(sorted(SUPPORTED_FORMATS))})"
        )

    # No text means no fingerprint: every empty book would otherwise hash alike.
    has_text = any(block.content.strip() for block in blocks)
    return book.model_copy(
        update={"content_hash": content_hash(blocks) if has_text else None}
    ), blocks
