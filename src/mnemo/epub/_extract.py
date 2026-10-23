"""Content extraction logic for EPUB HTML items."""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from bs4.element import NavigableString

from mnemo.epub._classify import (
    _detect_code_language,
    _is_code_block,
    _is_diagram,
    _is_math,
)
from mnemo.epub._models import (
    FRONT_MATTER_STEMS,
    MATHML_ELEMENTS,
)
from mnemo.models import ContentType
from mnemo.parsing.models import ContentBlock

# EPUB content is XHTML but lxml HTML parser handles real-world EPUBs better
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

if TYPE_CHECKING:
    import ebooklib  # type: ignore[import-untyped]


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


def file_sections(
    toc_mapping: dict[str, list[str]], href: str
) -> tuple[list[str], dict[str, list[str]]]:
    """A file's TOC path and its "#fragment" entries by id.

    A file the TOC reaches only through fragments takes its first one's path.
    """
    prefix = f"{href}#"
    anchors = {k[len(prefix) :]: v for k, v in toc_mapping.items() if k.startswith(prefix)}
    own = toc_mapping.get(href)
    if own:
        # Drop entries from another branch (a List of Figures pointing at a figure).
        parents = {tuple(own), *(tuple(p) for p in anchors.values())}
        anchors = {
            k: p
            for k, p in anchors.items()
            if p[: len(own)] == own or tuple(p[:-1]) in parents or own[: len(p) - 1] == p[:-1]
        }
    path = own or next(iter(anchors.values()), [])
    return list(path), anchors


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
        section_path, anchors = file_sections(toc_mapping, href)

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
        cursor = _SectionCursor(section_path, anchors)
        item_blocks = _extract_blocks_from_element(body, cursor, href, default_language)
        blocks.extend(item_blocks)

    return blocks


@dataclass
class _SectionCursor:
    """Where extraction is in a file's TOC, so its headings nest under the right entry."""

    toc_path: list[str]
    anchors: dict[str, list[str]]
    # Level of the heading that names toc_path; None until one is seen.
    toc_level: int | None = None
    sub: list[tuple[int, str]] = field(default_factory=list)
    has_content: bool = False
    # toc_level came from a first heading that didn't name the entry.
    guessed: bool = False
    guessed_title: str = ""
    # Paths labelled under the guess, relabelled if it was a subsection after all.
    guessed_paths: list[list[str]] = field(default_factory=list)
    # toc_path came from an anchor, so the next heading is that entry's title.
    anchored: bool = False

    @property
    def path(self) -> list[str]:
        return self.toc_path + [title for _, title in self.sub]

    def label(self) -> list[str]:
        """The path for a block emitted now."""
        path = self.path
        if self.guessed:
            self.guessed_paths.append(path)
        return path

    def copy(self) -> _SectionCursor:
        return replace(self, toc_path=list(self.toc_path), sub=list(self.sub))

    def adopt(self, other: _SectionCursor) -> None:
        vars(self).update(vars(other))

    def enter(self, toc_path: list[str], level: int | None = None) -> None:
        self.toc_path, self.toc_level, self.sub = list(toc_path), level, []
        self.has_content = self.guessed = False
        self.guessed_paths, self.anchored = [], level is None

    def heading(self, level: int, title: str) -> None:
        entry = _name_key(self.toc_path[-1]) if self.toc_path else ""
        key = _name_key(title)
        named = bool(entry and key) and (entry in key or key in entry)
        if self.toc_level is None:
            # The file's first heading restates its entry, even after a chapter-number line.
            if named or (entry and not self.has_content):
                self._restate(level, title, guessed=not (named or self.anchored))
                return
            if self.has_content:
                # Body text came first, so the entry's own title wasn't a heading.
                self.toc_level = level - 1
        elif level <= self.toc_level and self.has_content and self.guessed:
            if named:
                # The guess was a page before the title (a Part sharing the file).
                self._restate(level, title, guessed=False)
                return
            # A same-level heading after body text: the guessed title was a subsection.
            for path in self.guessed_paths:
                path.insert(len(self.toc_path), self.guessed_title)
            self.toc_level, self.guessed, self.guessed_paths = level - 1, False, []
        if self.toc_level is None or level <= self.toc_level:
            if self.has_content or not entry:
                self.enter(self.toc_path[:-1] + [title], level)
            else:
                # A second line of the title ("8", then "Instance Matching").
                self._restate(level, title, guessed=self.guessed)
            return
        while self.sub and self.sub[-1][0] >= level:
            self.sub.pop()
        self.sub.append((level, title))

    def _restate(self, level: int, title: str, guessed: bool) -> None:
        self.toc_level, self.guessed = level, guessed
        if guessed:
            self.guessed_title = title
        # A fuller heading ("Chapter 3: Best Practices" for "Best Practices") names the entry.
        if self.toc_path[-1].lower() in title.lower():
            self.toc_path[-1] = title


def _name_key(name: str) -> str:
    """A heading or TOC title without case, punctuation or spacing ("8.4 Two-Step")."""
    return re.sub(r"\W+", "", name).lower()


def _anchored_path(tag: Tag, anchors: dict[str, list[str]], deep: bool) -> list[str] | None:
    """The TOC path of a fragment id on tag (or, if deep, inside it), if any."""
    if not anchors:
        return None
    tags = [tag, *tag.find_all(id=True)] if deep else [tag]
    for t in tags:
        anchor = t.get("id")
        if isinstance(anchor, str) and anchor in anchors:
            return anchors[anchor]
    return None


_CONTAINER_TAGS = ("div", "section", "article", "aside", "blockquote", "figure")


def _extract_blocks_from_element(
    element: Tag,
    cursor: _SectionCursor,
    source_file: str,
    default_language: str | None,
) -> list[ContentBlock]:
    """Extract content blocks from an HTML element.

    Recursively processes elements, detecting content types and building
    ContentBlock instances. A nested container gets its own copy of the cursor,
    so its headings don't relabel what follows it.

    Args:
        element: BeautifulSoup Tag to process
        cursor: Section state, advanced by TOC anchors and headings
        source_file: Source EPUB item href
        default_language: Default language for untagged code

    Returns:
        List of ContentBlock items
    """
    blocks: list[ContentBlock] = []
    current_text_parts: list[str] = []

    def flush_text() -> None:
        if current_text_parts:
            text = _normalize_text(" ".join(current_text_parts))
            if text:
                emit(text, ContentType.TEXT)
            current_text_parts.clear()

    def emit(content: str, content_type: ContentType) -> None:
        blocks.append(
            ContentBlock(
                content=content,
                content_type=content_type,
                section_path=cursor.label(),
                source_file=source_file,
            )
        )
        cursor.has_content = True

    for child in element.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                current_text_parts.append(text)
            continue

        if not isinstance(child, Tag):
            continue

        tag_name = child.name.lower() if child.name else ""
        is_heading = tag_name in ("h1", "h2", "h3", "h4", "h5", "h6")
        is_container = tag_name in _CONTAINER_TAGS

        anchored = _anchored_path(child, cursor.anchors, deep=not is_container)
        if anchored is not None and not is_container:
            flush_text()
            cursor.enter(anchored, int(tag_name[1]) if is_heading else None)
            if is_heading:
                continue

        # Check for headings to update section path
        if is_heading:
            flush_text()
            heading_text = child.get_text(strip=True)
            if heading_text:
                cursor.heading(int(tag_name[1]), heading_text)
            continue

        # Check for code blocks
        if _is_code_block(child):
            flush_text()
            code_block = _extract_code_block(child, cursor.label(), source_file, default_language)
            if code_block and code_block.content.strip():
                blocks.append(code_block)
                cursor.has_content = True
            continue

        # Check for diagrams (ASCII art in pre tags)
        if _is_diagram(child):
            flush_text()
            diagram_content = child.get_text()
            if diagram_content.strip():
                emit(diagram_content, ContentType.DIAGRAM)
            continue

        # Check for tables
        if tag_name == "table":
            flush_text()
            table_text = _table_to_text(child)
            if table_text.strip():
                emit(table_text, ContentType.TABLE)
            continue

        # Check for math content
        if _is_math(child):
            flush_text()
            math_content = _extract_math(child)
            if math_content.strip():
                emit(math_content, ContentType.MATH)
            continue

        # Check for block-level elements that should be processed recursively
        if is_container:
            flush_text()
            nested = cursor.copy()
            if anchored is not None:
                nested.enter(anchored)
            nested_blocks = _extract_blocks_from_element(
                child, nested, source_file, default_language
            )
            blocks.extend(nested_blocks)
            if nested_blocks:
                cursor.has_content = True
            else:
                # A wrapper holding only a heading or anchor (DocBook's titlepage div).
                cursor.adopt(nested)
            continue

        # For other elements, accumulate their text.
        # Use separator=" " so adjacent inline children (span, em, strong) produce
        # space-separated words instead of joined strings like "astrategy".
        text = child.get_text(separator=" ", strip=True)
        if text:
            current_text_parts.append(text)

    flush_text()
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
    for tr in table.find_all("tr"):
        cells = []
        for td in tr.find_all(["th", "td"]):
            cell_text = td.get_text(strip=True)
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
