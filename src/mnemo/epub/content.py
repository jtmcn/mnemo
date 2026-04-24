"""Backward-compatible re-exports from epub.content submodules.

All public and test-referenced symbols re-exported here so that existing
imports from mnemo.epub.content continue to work unchanged.
"""

from mnemo.epub._extract import _extract_math, extract_content  # noqa: F401
from mnemo.parsing.models import ContentBlock  # noqa: F401

__all__ = ["ContentBlock", "extract_content"]
