"""Format-agnostic document parsing for Mnemo.

Routes to format-specific parsers (EPUB, DOCX) and provides shared types.
"""

from mnemo.parsing.dispatch import SUPPORTED_FORMATS, hash_file, parse_book, pre_parse_metadata
from mnemo.parsing.models import ContentBlock

__all__ = ["ContentBlock", "SUPPORTED_FORMATS", "hash_file", "parse_book", "pre_parse_metadata"]
