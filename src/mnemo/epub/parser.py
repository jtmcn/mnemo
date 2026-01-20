"""Main EPUB parser class.

Coordinates metadata extraction, TOC parsing, and content extraction
to produce structured data from EPUB files.
"""

from __future__ import annotations

from pathlib import Path

from mnemo.epub.content import ContentBlock
from mnemo.models import Book


class EPUBParser:
    """Parser for extracting structured content from EPUB files.

    Placeholder - full implementation in Task 3.
    """

    def parse(self, epub_path: Path | str) -> tuple[Book, list[ContentBlock]]:
        """Parse an EPUB file and return structured data.

        Placeholder - full implementation in Task 3.

        Args:
            epub_path: Path to the EPUB file

        Returns:
            Tuple of (Book metadata, list of ContentBlock items)
        """
        # Placeholder - will be implemented in Task 3
        raise NotImplementedError("EPUBParser.parse() not yet implemented")
