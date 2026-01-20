"""EPUB parsing module for Mnemo.

This module provides functionality for parsing EPUB files, extracting metadata,
detecting content types, and preserving document structure.

Main exports:
- EPUBParser: Main parser class for EPUB files
- ContentBlock: Intermediate representation of parsed content
- extract_metadata: Dublin Core metadata extraction
- extract_content: Content extraction with type detection
"""

from mnemo.epub.content import ContentBlock, extract_content
from mnemo.epub.metadata import extract_metadata
from mnemo.epub.parser import EPUBParser

__all__ = [
    "EPUBParser",
    "ContentBlock",
    "extract_metadata",
    "extract_content",
]
