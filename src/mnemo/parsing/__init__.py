"""Format-agnostic document parsing for Mnemo.

Routes to format-specific parsers (EPUB, DOCX) and provides shared types.
"""

from mnemo.parsing.dispatch import SUPPORTED_FORMATS, parse_book
from mnemo.parsing.models import ContentBlock

__all__ = ["ContentBlock", "SUPPORTED_FORMATS", "parse_book"]
