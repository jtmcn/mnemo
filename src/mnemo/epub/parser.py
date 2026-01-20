"""Main EPUB parser class.

Coordinates metadata extraction, TOC parsing, and content extraction
to produce structured data from EPUB files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from bs4 import BeautifulSoup
from ebooklib import epub

from mnemo.epub.content import ContentBlock, extract_content
from mnemo.epub.metadata import extract_metadata
from mnemo.models import Book

if TYPE_CHECKING:
    from ebooklib.epub import EpubBook

logger = logging.getLogger(__name__)


class EPUBParser:
    """Parser for extracting structured content from EPUB files.

    Handles:
    - Dublin Core metadata extraction
    - TOC parsing (EPUB3 nav or EPUB2 NCX, with heading fallback)
    - Content extraction with type detection
    - Section hierarchy preservation

    Example:
        parser = EPUBParser()
        book, blocks = parser.parse("my_book.epub")
    """

    def parse(self, epub_path: Path | str) -> tuple[Book, list[ContentBlock]]:
        """Parse an EPUB file and return structured data.

        Extracts:
        - Book metadata (title, authors, ISBN, etc.)
        - Content blocks with type detection (code, tables, diagrams, math, text)
        - Section hierarchy from TOC or inferred from headings

        Args:
            epub_path: Path to the EPUB file

        Returns:
            Tuple of (Book metadata, list of ContentBlock items in document order)

        Raises:
            FileNotFoundError: If EPUB file doesn't exist
            ebooklib.epub.EpubException: If file is not a valid EPUB
        """
        epub_path = Path(epub_path)

        if not epub_path.exists():
            raise FileNotFoundError(f"EPUB file not found: {epub_path}")

        # Read EPUB file
        epub_book = epub.read_epub(str(epub_path), options={"ignore_ncx": False})

        # Extract metadata
        book = extract_metadata(epub_path)

        # Parse TOC and get section mapping
        toc_mapping, structure_source = self._parse_toc(epub_book)

        # Update book with structure source
        book = Book(
            id=book.id,
            title=book.title,
            authors=book.authors,
            isbn=book.isbn,
            file_hash=book.file_hash,
            default_language=book.default_language,
            structure_source=structure_source,
            added_at=book.added_at,
        )

        # Extract content blocks
        blocks = extract_content(epub_book, toc_mapping, book.default_language)

        return book, blocks

    def _parse_toc(
        self, epub_book: "EpubBook"
    ) -> tuple[dict[str, list[str]], Literal["toc", "inferred"]]:
        """Parse TOC from EPUB and build section path mapping.

        Tries in order:
        1. EPUB3 navigation document (nav.xhtml)
        2. EPUB2 NCX table of contents
        3. Infer from HTML headings

        Args:
            epub_book: Parsed EPUB book object

        Returns:
            Tuple of (mapping from href to section path, structure source)
        """
        # Try EPUB3 nav document first
        toc_mapping = self._parse_epub3_nav(epub_book)
        if toc_mapping:
            return toc_mapping, "toc"

        # Try EPUB2 NCX
        toc_mapping = self._parse_epub2_ncx(epub_book)
        if toc_mapping:
            return toc_mapping, "toc"

        # Fall back to heading inference
        logger.warning(
            "No TOC found in EPUB. Structure will be inferred from HTML headings."
        )
        toc_mapping = self._infer_from_headings(epub_book)
        return toc_mapping, "inferred"

    def _parse_epub3_nav(self, epub_book: "EpubBook") -> dict[str, list[str]]:
        """Parse EPUB3 navigation document.

        Looks for the nav element with epub:type="toc" and builds
        section hierarchy from nested <ol>/<li> structure.

        Args:
            epub_book: Parsed EPUB book object

        Returns:
            Mapping from item href to section path, or empty dict if no nav found
        """
        # Find nav document
        nav_item = epub_book.get_item_with_href("nav.xhtml")
        if not nav_item:
            # Try alternative nav locations
            for item in epub_book.get_items():
                if hasattr(item, "get_type") and item.get_type() == 4:  # EpubNav type
                    nav_item = item
                    break

        if not nav_item:
            return {}

        content = nav_item.get_content()
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")

        soup = BeautifulSoup(content, "lxml")

        # Find toc nav element
        nav = soup.find("nav", attrs={"epub:type": "toc"})
        if not nav:
            # Try finding by id or just the first nav with ol
            nav = soup.find("nav", id="toc") or soup.find("nav")

        if not nav:
            return {}

        toc_mapping: dict[str, list[str]] = {}
        ol = nav.find("ol")
        if ol:
            self._parse_nav_ol(ol, [], toc_mapping)

        return toc_mapping

    def _parse_nav_ol(
        self,
        ol_element: object,
        current_path: list[str],
        mapping: dict[str, list[str]],
    ) -> None:
        """Recursively parse nav <ol> element to build section paths.

        Args:
            ol_element: BeautifulSoup ol Tag
            current_path: Current section path
            mapping: Mapping to populate (modified in place)
        """
        for li in ol_element.find_all("li", recursive=False):
            # Get link and title
            a = li.find("a")
            if not a:
                continue

            href = a.get("href", "")
            title = a.get_text(strip=True)

            if not href or not title:
                continue

            # Remove fragment from href
            href = href.split("#")[0]

            # Build path for this item
            item_path = current_path + [title]

            # Store mapping
            if href:
                mapping[href] = item_path

            # Process nested items
            nested_ol = li.find("ol")
            if nested_ol:
                self._parse_nav_ol(nested_ol, item_path, mapping)

    def _parse_epub2_ncx(self, epub_book: "EpubBook") -> dict[str, list[str]]:
        """Parse EPUB2 NCX table of contents.

        Looks for the NCX file and parses navPoint elements to build
        section hierarchy.

        Args:
            epub_book: Parsed EPUB book object

        Returns:
            Mapping from item href to section path, or empty dict if no NCX found
        """
        # Find NCX item
        ncx_item = None
        for item in epub_book.get_items():
            if item.get_name().endswith(".ncx"):
                ncx_item = item
                break

        if not ncx_item:
            return {}

        content = ncx_item.get_content()
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")

        soup = BeautifulSoup(content, "xml")

        toc_mapping: dict[str, list[str]] = {}
        nav_map = soup.find("navMap")
        if nav_map:
            self._parse_ncx_navpoint(nav_map, [], toc_mapping)

        return toc_mapping

    def _parse_ncx_navpoint(
        self,
        element: object,
        current_path: list[str],
        mapping: dict[str, list[str]],
    ) -> None:
        """Recursively parse NCX navPoint elements.

        Args:
            element: BeautifulSoup element containing navPoints
            current_path: Current section path
            mapping: Mapping to populate (modified in place)
        """
        for navpoint in element.find_all("navPoint", recursive=False):
            # Get label text
            nav_label = navpoint.find("navLabel")
            text_elem = nav_label.find("text") if nav_label else None
            title = text_elem.get_text(strip=True) if text_elem else ""

            # Get content href
            content = navpoint.find("content")
            href = content.get("src", "") if content else ""

            if not href or not title:
                continue

            # Remove fragment from href
            href = href.split("#")[0]

            # Build path
            item_path = current_path + [title]

            # Store mapping
            if href:
                mapping[href] = item_path

            # Process nested navPoints
            self._parse_ncx_navpoint(navpoint, item_path, mapping)

    def _infer_from_headings(self, epub_book: "EpubBook") -> dict[str, list[str]]:
        """Infer section structure from HTML headings.

        Parses h1-h6 tags in document items to build a best-effort
        section hierarchy. Used as fallback when TOC is missing.

        Args:
            epub_book: Parsed EPUB book object

        Returns:
            Mapping from item href to inferred section path
        """
        import ebooklib

        toc_mapping: dict[str, list[str]] = {}

        for item in epub_book.get_items():
            if item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            href = item.get_name()
            content = item.get_content()
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")

            soup = BeautifulSoup(content, "lxml")

            # Find first heading to use as section title
            first_heading = None
            for level in range(1, 7):
                heading = soup.find(f"h{level}")
                if heading:
                    first_heading = heading.get_text(strip=True)
                    break

            if first_heading:
                toc_mapping[href] = [first_heading]
            else:
                # Use filename as fallback
                filename = Path(href).stem
                toc_mapping[href] = [filename]

        return toc_mapping
