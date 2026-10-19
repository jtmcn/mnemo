"""Route document parsing to the appropriate format-specific parser."""

from __future__ import annotations

import hashlib
from pathlib import Path

from mnemo.models import Book
from mnemo.parsing.models import ContentBlock

SUPPORTED_FORMATS = {".epub", ".docx", ".pdf"}


def hash_file(file_path: Path | str) -> str:
    """SHA-256 of the file bytes: a Book's `file_hash`, without parsing."""
    return hashlib.sha256(Path(file_path).read_bytes()).hexdigest()


# Below this, text is a watermark or stray caption that distinct scans share.
MIN_HASHED_TEXT_CHARS = 200


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

    text_chars = sum(len("".join(block.content.split())) for block in blocks)
    enough = text_chars >= MIN_HASHED_TEXT_CHARS
    return book.model_copy(
        update={"content_hash": content_hash(blocks) if enough else None}
    ), blocks
