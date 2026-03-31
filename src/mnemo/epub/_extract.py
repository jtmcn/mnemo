"""Content extraction logic for EPUB HTML items."""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

from mnemo.epub._classify import (
    _detect_code_language,
    _is_code_block,
    _is_diagram,
    _is_math,
)
from mnemo.epub._models import (
    FRONT_MATTER_STEMS,
    MATHML_ELEMENTS,
    ContentBlock,
)
from mnemo.models import ContentType

# EPUB content is XHTML but lxml HTML parser handles real-world EPUBs better
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

if TYPE_CHECKING:
    import ebooklib


def _infer_front_matter_label(href: str) -> list[str] | None:
    """Infer a section label for unmapped spine items via filename heuristics.

    Tries exact stem match, then prefix/suffix matching against FRONT_MATTER_STEMS.
    Returns None if no match found (content remains unlabeled).

    Args:
        href: EPUB item href (e.g., "OEBPS/cover.xhtml", "preface_01.xhtml")

    Returns:
        Single-element section path or None
    """
    stem = Path(href).stem.lower()
    # Exact match
    if stem in FRONT_MATTER_STEMS:
        return [FRONT_MATTER_STEMS[stem]]
    # Prefix/suffix match (e.g., "preface_01", "cover2")
    for key, label in FRONT_MATTER_STEMS.items():
        if stem.startswith(key) or stem.endswith(key):
            return [label]
    return None


def extract_content(
    epub_book: ebooklib.epub.EpubBook,
    toc_mapping: dict[str, list[str]],
    default_language: str | None = None,
) -> list[ContentBlock]:
    """Extract content blocks from EPUB items with type detection.

    Iterates through EPUB items in spine order, parsing HTML and detecting
    content types (code, tables, diagrams, math, text).

    Args:
        epub_book: Parsed EPUB book object from ebooklib
        toc_mapping: Mapping of item hrefs to section paths
        default_language: Default language for untagged code blocks

    Returns:
        List of ContentBlock items in document order
    """
    import ebooklib

    blocks: list[ContentBlock] = []

    # Get items in spine order
    spine_items = []
    for item_ref in epub_book.spine:
        item_id = item_ref[0] if isinstance(item_ref, tuple) else item_ref
        if item_id == "nav":
            continue
        item = epub_book.get_item_with_id(item_id)
        if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
            spine_items.append(item)

    # Process each document item
    for item in spine_items:
        href = item.get_name()
        section_path = toc_mapping.get(href, [])

        # PARSE-03: infer label for front-matter items not in TOC
        if not section_path:
            inferred = _infer_front_matter_label(href)
            if inferred:
                section_path = inferred

        # Last-resort fallback: use filename stem as section label
        if not section_path:
            stem = Path(href).stem
            label = stem.replace("-", " ").replace("_", " ").title()
            if label:
                section_path = [label]

        # Parse HTML content
        content = item.get_content()
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")

        soup = BeautifulSoup(content, "lxml")

        # Find body content
        body = soup.find("body")
        if not body:
            continue

        # Extract blocks from body
        item_blocks = _extract_blocks_from_element(body, section_path, href, default_language)
        blocks.extend(item_blocks)

    return blocks


def _extract_blocks_from_element(
    element: Tag,
    section_path: list[str],
    source_file: str,
    default_language: str | None,
) -> list[ContentBlock]:
    """Extract content blocks from an HTML element.

    Recursively processes elements, detecting content types and building
    ContentBlock instances.

    Args:
        element: BeautifulSoup Tag to process
        section_path: Current section path for hierarchy
        source_file: Source EPUB item href
        default_language: Default language for untagged code

    Returns:
        List of ContentBlock items
    """
    blocks: list[ContentBlock] = []
    current_text_parts: list[str] = []
    current_section_path = list(section_path)

    for child in element.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                current_text_parts.append(text)
            continue

        if not isinstance(child, Tag):
            continue

        tag_name = child.name.lower() if child.name else ""

        # Check for headings to update section path
        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            # Flush accumulated text before heading
            if current_text_parts:
                text = _normalize_text(" ".join(current_text_parts))
                if text:
                    blocks.append(
                        ContentBlock(
                            content=text,
                            content_type=ContentType.TEXT,
                            section_path=list(current_section_path),
                            source_file=source_file,
                        )
                    )
                current_text_parts = []

            # Update section path based on heading level
            heading_text = child.get_text(strip=True)
            if heading_text:
                level = int(tag_name[1])
                # Trim section path to appropriate depth
                current_section_path = current_section_path[: level - 1]
                current_section_path.append(heading_text)
            continue

        # Check for code blocks
        if _is_code_block(child):
            # Flush accumulated text
            if current_text_parts:
                text = _normalize_text(" ".join(current_text_parts))
                if text:
                    blocks.append(
                        ContentBlock(
                            content=text,
                            content_type=ContentType.TEXT,
                            section_path=list(current_section_path),
                            source_file=source_file,
                        )
                    )
                current_text_parts = []

            # Extract code block
            code_block = _extract_code_block(
                child, current_section_path, source_file, default_language
            )
            if code_block and code_block.content.strip():
                blocks.append(code_block)
            continue

        # Check for diagrams (ASCII art in pre tags)
        if _is_diagram(child):
            if current_text_parts:
                text = _normalize_text(" ".join(current_text_parts))
                if text:
                    blocks.append(
                        ContentBlock(
                            content=text,
                            content_type=ContentType.TEXT,
                            section_path=list(current_section_path),
                            source_file=source_file,
                        )
                    )
                current_text_parts = []

            diagram_content = child.get_text()
            if diagram_content.strip():
                blocks.append(
                    ContentBlock(
                        content=diagram_content,
                        content_type=ContentType.DIAGRAM,
                        section_path=list(current_section_path),
                        source_file=source_file,
                    )
                )
            continue

        # Check for tables
        if tag_name == "table":
            if current_text_parts:
                text = _normalize_text(" ".join(current_text_parts))
                if text:
                    blocks.append(
                        ContentBlock(
                            content=text,
                            content_type=ContentType.TEXT,
                            section_path=list(current_section_path),
                            source_file=source_file,
                        )
                    )
                current_text_parts = []

            table_text = _table_to_text(child)
            if table_text.strip():
                blocks.append(
                    ContentBlock(
                        content=table_text,
                        content_type=ContentType.TABLE,
                        section_path=list(current_section_path),
                        source_file=source_file,
                    )
                )
            continue

        # Check for math content
        if _is_math(child):
            if current_text_parts:
                text = _normalize_text(" ".join(current_text_parts))
                if text:
                    blocks.append(
                        ContentBlock(
                            content=text,
                            content_type=ContentType.TEXT,
                            section_path=list(current_section_path),
                            source_file=source_file,
                        )
                    )
                current_text_parts = []

            math_content = _extract_math(child)
            if math_content.strip():
                blocks.append(
                    ContentBlock(
                        content=math_content,
                        content_type=ContentType.MATH,
                        section_path=list(current_section_path),
                        source_file=source_file,
                    )
                )
            continue

        # Check for block-level elements that should be processed recursively
        if tag_name in ("div", "section", "article", "aside", "blockquote", "figure"):
            # Flush accumulated text
            if current_text_parts:
                text = _normalize_text(" ".join(current_text_parts))
                if text:
                    blocks.append(
                        ContentBlock(
                            content=text,
                            content_type=ContentType.TEXT,
                            section_path=list(current_section_path),
                            source_file=source_file,
                        )
                    )
                current_text_parts = []

            # Recursively process container
            nested_blocks = _extract_blocks_from_element(
                child, current_section_path, source_file, default_language
            )
            blocks.extend(nested_blocks)
            continue

        # For other elements, accumulate their text.
        # Use separator=" " so adjacent inline children (span, em, strong) produce
        # space-separated words instead of joined strings like "astrategy".
        text = child.get_text(separator=" ", strip=True)
        if text:
            current_text_parts.append(text)

    # Flush any remaining text
    if current_text_parts:
        text = _normalize_text(" ".join(current_text_parts))
        if text:
            blocks.append(
                ContentBlock(
                    content=text,
                    content_type=ContentType.TEXT,
                    section_path=list(current_section_path),
                    source_file=source_file,
                )
            )

    return blocks


def _extract_code_block(
    element: Tag,
    section_path: list[str],
    source_file: str,
    default_language: str | None,
) -> ContentBlock:
    """Extract code content from a code block element.

    Args:
        element: BeautifulSoup Tag containing code
        section_path: Current section path
        source_file: Source EPUB item href
        default_language: Default language for untagged code

    Returns:
        ContentBlock with CODE type
    """
    # Get language from various sources
    language = _detect_code_language(element) or default_language

    # Get code content, preserving whitespace
    code_element = element.find("code") or element
    content = code_element.get_text()

    return ContentBlock(
        content=content,
        content_type=ContentType.CODE,
        section_path=list(section_path),
        language=language,
        source_file=source_file,
    )


def _extract_math(element: Tag) -> str:
    """Extract math content from element.

    Preserves raw notation (LaTeX, MathML) for later processing.

    Args:
        element: BeautifulSoup Tag containing math

    Returns:
        Math content string
    """
    tag_name = element.name.lower() if element.name else ""

    # MathML root element — return raw markup
    if tag_name == "math":
        return str(element)

    # Wrapper containing a <math> element — extract it
    math_root = element.find("math")
    if math_root:
        return str(math_root)

    # Bare MathML presentation elements without <math> wrapper —
    # return raw markup to preserve structure
    if element.find(list(MATHML_ELEMENTS)):
        return str(element)

    # LaTeX or plain-text math — concatenate without extra spaces
    return element.get_text(separator="")


def _table_to_text(table: Tag) -> str:
    """Convert HTML table to searchable pipe-delimited text.

    Output format:
    | Header1 | Header2 |
    | ------- | ------- |
    | Cell1   | Cell2   |

    Args:
        table: BeautifulSoup table Tag

    Returns:
        Pipe-delimited table text
    """
    rows: list[list[str]] = []

    # Process all rows (thead and tbody)
    for row in table.find_all("tr"):
        cells = []
        for cell in row.find_all(["th", "td"]):
            cell_text = cell.get_text(strip=True)
            # Escape pipes in cell content
            cell_text = cell_text.replace("|", "\\|")
            cells.append(cell_text)
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    # Determine column count
    max_cols = max(len(row) for row in rows)

    # Pad rows to have same number of columns
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    # Build output
    lines = []
    for i, row in enumerate(rows):
        line = "| " + " | ".join(row) + " |"
        lines.append(line)

        # Add separator after first row (header)
        if i == 0:
            separator = "| " + " | ".join("-" * max(1, len(cell)) for cell in row) + " |"
            lines.append(separator)

    return "\n".join(lines)


def _normalize_text(text: str) -> str:
    """Normalize text content by collapsing whitespace.

    Args:
        text: Raw text content

    Returns:
        Normalized text with collapsed whitespace
    """
    # Replace multiple whitespace with single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()
