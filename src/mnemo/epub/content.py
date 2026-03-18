"""Content extraction with type detection from EPUB HTML.

Extracts content blocks from EPUB HTML items, detecting content types
(code, tables, diagrams, math, text) and preserving structure.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

from mnemo.models import ContentType

# EPUB content is XHTML but lxml HTML parser handles real-world EPUBs better
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Maps filename stems to human-readable front-matter section labels.
# Used by _infer_front_matter_label to assign descriptive labels to spine items
# that are absent from the EPUB's NAV/NCX table of contents.
FRONT_MATTER_STEMS: dict[str, str] = {
    "cover": "Cover",
    "toc": "Table of Contents",
    "contents": "Table of Contents",
    "copyright": "Copyright",
    "copyrights": "Copyright",
    "title": "Title Page",
    "titlepage": "Title Page",
    "title-page": "Title Page",
    "dedication": "Dedication",
    "preface": "Preface",
    "foreword": "Foreword",
    "introduction": "Introduction",
    "intro": "Introduction",
    "acknowledgements": "Acknowledgements",
    "acknowledgments": "Acknowledgements",
    "about": "About",
    "colophon": "Colophon",
    "halftitle": "Half Title",
    "half-title": "Half Title",
}

if TYPE_CHECKING:
    from ebooklib.epub import EpubBook


@dataclass
class ContentBlock:
    """Intermediate representation of parsed EPUB content.

    Represents a single block of content extracted from an EPUB document,
    with metadata about its type, location, and source.

    Attributes:
        content: The text content of the block
        content_type: Classification of the content (TEXT, CODE, etc.)
        section_path: Hierarchical path to this content (e.g., ["Chapter 1", "Section 1.1"])
        language: Programming language for code blocks (e.g., "python")
        source_file: EPUB item href where this content was found
    """

    content: str
    content_type: ContentType = ContentType.TEXT
    section_path: list[str] = field(default_factory=list)
    language: str | None = None
    source_file: str = ""


# Publisher-specific code block CSS classes
CODE_CLASSES = {
    # Standard
    "highlight",
    "sourceCode",
    "source-code",
    "listing",
    "codehilite",
    # O'Reilly
    "programlisting",
    "screen",
    # Pragmatic
    "code",
    "livecodelozenge",
    # Manning
    "listingblock",
    # General
    "syntax",
    "prettyprint",
}

# Classes that indicate ASCII diagrams
DIAGRAM_CLASSES = {"ascii", "diagram", "ascii-diagram", "ascii-art"}

# Math-related classes and patterns
MATH_CLASSES = {"equation", "math", "formula", "katex", "mathjax"}

# LaTeX delimiter patterns
LATEX_BLOCK_PATTERN = re.compile(r"\\\[.*?\\\]", re.DOTALL)
LATEX_INLINE_PATTERN = re.compile(r"\$[^$]+\$")


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
    epub_book: EpubBook,
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


def _is_code_block(element: Tag) -> bool:
    """Check if element is a code block.

    Detection rules:
    - <pre> with <code> child
    - <pre> with code-related class
    - <code> that's not inline (block-level)

    Args:
        element: BeautifulSoup Tag to check

    Returns:
        True if element is a code block
    """
    tag_name = element.name.lower() if element.name else ""

    if tag_name == "pre":
        # Check for <code> child
        if element.find("code"):
            return True

        # Check for code-related classes
        classes = set(element.get("class", []))
        if classes & CODE_CLASSES:
            return True

            # Check for diagram classes (not code); assume pre tags are code otherwise
        return not (classes & DIAGRAM_CLASSES)

    # Check for standalone <code> blocks (not inline)
    if tag_name == "code":
        # If parent is <pre>, let <pre> handle it
        parent = element.parent
        if parent and parent.name and parent.name.lower() == "pre":
            return False

        # Large code elements are probably blocks
        text = element.get_text()
        return "\n" in text or len(text) > 100

    return False


def _is_diagram(element: Tag) -> bool:
    """Check if element is an ASCII diagram.

    Args:
        element: BeautifulSoup Tag to check

    Returns:
        True if element appears to be an ASCII diagram
    """
    tag_name = element.name.lower() if element.name else ""

    if tag_name != "pre":
        return False

    classes = set(element.get("class", []))
    if classes & DIAGRAM_CLASSES:
        return True

    # Heuristic: check for ASCII art patterns
    text = element.get_text()
    return bool(_looks_like_ascii_art(text))


def _looks_like_ascii_art(text: str) -> bool:
    """Check if text looks like ASCII art.

    Heuristics:
    - High ratio of box-drawing characters
    - Alignment with spaces
    - Common ASCII art patterns (+, |, -, arrows)

    Args:
        text: Text content to check

    Returns:
        True if text appears to be ASCII art
    """
    if not text or len(text) < 20:
        return False

    # Count box-drawing and arrow characters
    box_chars = set("+-|\\/*><^v[]{}()=_")
    box_count = sum(1 for c in text if c in box_chars)

    # Check ratio (ASCII art typically has high ratio)
    total_printable = sum(1 for c in text if c.isprintable() and not c.isspace())

    if total_printable == 0:
        return False

    box_ratio = box_count / total_printable

    # If box characters are >15% of content and there are multiple lines
    # with similar structure, likely ASCII art
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return False

    return box_ratio > 0.15 and box_count > 5


def _is_math(element: Tag) -> bool:
    """Check if element contains math content.

    Args:
        element: BeautifulSoup Tag to check

    Returns:
        True if element contains math
    """
    tag_name = element.name.lower() if element.name else ""

    # MathML
    if tag_name == "math":
        return True

    # Class-based detection
    classes = set(element.get("class", []))
    if classes & MATH_CLASSES:
        return True

    # Check for LaTeX delimiters in text
    text = element.get_text()
    return bool(
        LATEX_BLOCK_PATTERN.search(text)
        or (LATEX_INLINE_PATTERN.search(text) and tag_name in ("span", "div", "p"))
    )


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


def _detect_code_language(element: Tag) -> str | None:
    """Detect programming language from code block element.

    Checks:
    - class="language-python"
    - class="python"
    - data-lang="python"
    - data-language="python"

    Args:
        element: BeautifulSoup Tag to check

    Returns:
        Language string or None
    """
    # Check the element and its code child
    elements_to_check = [element]
    code_child = element.find("code")
    if code_child and isinstance(code_child, Tag):
        elements_to_check.append(code_child)

    for el in elements_to_check:
        # Check class attribute
        classes = el.get("class", [])
        for cls in classes:
            if not isinstance(cls, str):
                continue
            # language-python, lang-python
            if cls.startswith("language-") or cls.startswith("lang-"):
                return cls.split("-", 1)[1]
            # Direct language name as class
            if cls in _KNOWN_LANGUAGES:
                return cls

        # Check data attributes
        for attr in ("data-lang", "data-language", "data-code-language"):
            lang = el.get(attr)
            if lang:
                return str(lang).lower()

    return None


# Common programming languages for detection
_KNOWN_LANGUAGES = {
    "python",
    "javascript",
    "typescript",
    "java",
    "go",
    "rust",
    "ruby",
    "php",
    "c",
    "cpp",
    "csharp",
    "swift",
    "kotlin",
    "scala",
    "shell",
    "bash",
    "sh",
    "sql",
    "html",
    "css",
    "json",
    "yaml",
    "xml",
    "markdown",
}


MATHML_ELEMENTS = frozenset(
    {
        "mi",
        "mo",
        "mn",
        "mrow",
        "msup",
        "msub",
        "mfrac",
        "mover",
        "munder",
        "msqrt",
        "mroot",
        "mtext",
        "mspace",
        "mtable",
        "mtr",
        "mtd",
        "mpadded",
        "mstyle",
    }
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
