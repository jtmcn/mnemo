"""EPUB parsing module for Mnemo.

This module provides functionality for parsing EPUB files, extracting metadata,
detecting content types, and preserving document structure.

Main exports:
- EPUBParser: Main parser class for EPUB files
- ContentBlock: Intermediate representation of parsed content
- extract_metadata: Dublin Core metadata extraction
- extract_content: Content extraction with type detection
"""

# Suppress BeautifulSoup warnings about using HTML parser on XHTML
# This must be done before any BeautifulSoup imports in submodules
import warnings

from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from mnemo.epub.content import ContentBlock, extract_content  # noqa: E402
from mnemo.epub.metadata import extract_metadata  # noqa: E402
from mnemo.epub.parser import EPUBParser  # noqa: E402

__all__ = [
    "EPUBParser",
    "ContentBlock",
    "extract_metadata",
    "extract_content",
]
