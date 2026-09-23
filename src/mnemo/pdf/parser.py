"""PDF parser for Mnemo using pdfminer.six."""

from __future__ import annotations

import hashlib
import logging
import math
import re
import statistics
from bisect import bisect_right
from collections import deque
from pathlib import Path
from typing import Any

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTChar, LTPage, LTTextBox, LTTextLine
from pdfminer.pdfdocument import (
    PDFDestinationNotFound,
    PDFDocument,
    PDFNoOutlines,
    PDFPasswordIncorrect,
)
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1
from pdfminer.psparser import PSLiteral
from pdfminer.utils import decode_text

from mnemo.models import Book, ContentType
from mnemo.parsing.models import ContentBlock
from mnemo.parsing.text import is_monospace_font, split_authors

logger = logging.getLogger(__name__)

# A word broken across lines has lowercase on both sides of the hyphen; capitals or
# digits ("LLM-\ndriven", "2023-\n2025") mark a real compound and are kept.
_SOFT_HYPHEN_BREAK = re.compile(r"(?<=[a-z])-\n(?=[a-z])")
_KEPT_HYPHEN_BREAK = re.compile(r"(?<=\S)-\n")
_WHITESPACE = re.compile(r"\s+")
_PAGE_NUMBER_TOKEN = re.compile(r"\b(?:\d+|[ivx]+)\b", re.IGNORECASE)
_PAGE_NUMBER = re.compile(r"\d{1,4}|[ivx]{1,7}", re.IGNORECASE)

# Running headers, footers and watermarks sit in the outer tenth of the page and
# recur within a few pages with only the page number changing. Comparing nearby
# pages only also keeps memory flat: a page is emitted once its neighbours are laid out.
_MARGIN_FRACTION = 0.1
_FURNITURE_WINDOW = 3

# (page index, negated y) so that ascending order is reading order.
_Position = tuple[int, float]

# Index of the "top" operand in an explicit destination, by fit type.
_TOP_OPERAND: dict[str | bytes, int] = {"XYZ": 3, "FitH": 2, "FitBH": 2}


class PdfParser:
    """Parser for born-digital PDFs via pdfminer.six.

    Sections come from the bookmark outline; a PDF without a readable one
    yields unsectioned blocks. There is no OCR, so a scan without a text
    layer is rejected.
    """

    SUPPORTED_EXTENSIONS = {".pdf"}

    def parse(self, file_path: Path | str) -> tuple[Book, list[ContentBlock]]:
        """Parse a PDF file into Book metadata and ContentBlocks.

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If the PDF is password-protected or has no extractable text
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        file_bytes = file_path.read_bytes()

        # pdfminer reads objects lazily, so everything that touches doc stays in here.
        with file_path.open("rb") as f:
            try:
                doc = PDFDocument(PDFParser(f))
            except PDFPasswordIncorrect as e:
                raise ValueError(f"{file_path.name} is password-protected") from e
            pages = list(PDFPage.create_pages(doc))
            outline = self._resolve_outline(doc, {page.pageid: i for i, page in enumerate(pages)})
            blocks = self._extract_content(pages, outline)
            title = self._info_field(doc, "Title") or file_path.stem
            authors = split_authors(self._info_field(doc, "Author"))

        if not blocks:
            raise ValueError(f"{file_path.name} has no extractable text (a scan without OCR?)")

        book = Book(
            id=Book.generate_id(file_bytes, title, authors[0] if authors else None),
            title=title,
            authors=authors,
            file_hash=hashlib.sha256(file_bytes).hexdigest(),
            structure_source="toc" if outline else "inferred",
        )
        return book, blocks

    @staticmethod
    def _info_field(doc: PDFDocument, key: str) -> str:
        """First non-empty value for key across the document info dicts."""
        for info in doc.info:
            value = resolve1(info.get(key))
            text = decode_text(value) if isinstance(value, bytes) else value
            if isinstance(text, str) and text.strip():
                return text.strip()
        return ""

    def _resolve_outline(
        self, doc: PDFDocument, page_index: dict[object, int]
    ) -> list[tuple[_Position, list[str]]]:
        """Bookmarks as (position, section path), sorted into reading order."""
        try:
            raw = list(doc.get_outlines())
        except PDFNoOutlines:
            return []
        except Exception as e:
            # pdfminer recurses per sibling, so a cyclic or ~1000-long /Next chain
            # raises RecursionError; losing sections beats losing the book.
            logger.warning("Ignoring unreadable PDF outline (%s: %s)", type(e).__name__, e)
            return []

        entries: list[tuple[_Position, list[str]]] = []
        stack: list[str] = []
        for level, title, dest, action, _ in raw:
            del stack[level - 1 :]
            stack.append(str(title).strip())
            position = self._destination_position(doc, dest, action, page_index)
            if position is not None:
                entries.append((position, list(stack)))

        entries.sort(key=lambda entry: entry[0])
        return entries

    @staticmethod
    def _destination_position(
        doc: PDFDocument, dest: Any, action: Any, page_index: dict[object, int]
    ) -> _Position | None:
        """Resolve an outline destination (explicit, named or GoTo action) to a position."""
        if dest is None and action is not None:
            action = resolve1(action)
            dest = action.get("D") if isinstance(action, dict) else None
        dest = resolve1(dest)

        if isinstance(dest, PSLiteral | bytes | str):
            name = dest.name if isinstance(dest, PSLiteral) else dest
            try:
                dest = resolve1(doc.get_dest(name))
            except PDFDestinationNotFound:
                return None
        if isinstance(dest, dict):
            dest = resolve1(dest.get("D"))
        if not isinstance(dest, list) or not dest:
            return None

        page = page_index.get(getattr(dest[0], "objid", -1))
        if page is None:
            return None

        fit = dest[1].name if len(dest) > 1 and isinstance(dest[1], PSLiteral) else ""
        operand = _TOP_OPERAND.get(fit)
        top = resolve1(dest[operand]) if operand is not None and operand < len(dest) else None
        # No top means "this page", so the entry starts above everything on it.
        return (page, -float(top) if isinstance(top, int | float) else -math.inf)

    def _extract_content(
        self, pages: list[PDFPage], outline: list[tuple[_Position, list[str]]]
    ) -> list[ContentBlock]:
        """Lay out each page and emit ContentBlocks under their outline section."""
        starts = [position for position, _ in outline]
        resources = PDFResourceManager()
        device = PDFPageAggregator(resources, laparams=LAParams())
        interpreter = PDFPageInterpreter(resources, device)

        blocks: list[ContentBlock] = []
        text_run: list[str] = []
        code_run: list[LTTextLine] = []
        run_path: list[str] = []

        def _flush() -> None:
            if text_run:
                blocks.append(
                    ContentBlock(content="\n\n".join(text_run), section_path=list(run_path))
                )
                text_run.clear()
            if code_run:
                blocks.append(
                    ContentBlock(
                        content=_listing_text(code_run),
                        content_type=ContentType.CODE,
                        section_path=list(run_path),
                    )
                )
                code_run.clear()

        margin_keys: list[set[str]] = []
        pending: deque[tuple[int, LTPage]] = deque()

        def _emit(page_number: int, layout: LTPage) -> None:
            nonlocal run_path
            nearby = range(
                max(0, page_number - _FURNITURE_WINDOW),
                min(len(margin_keys), page_number + _FURNITURE_WINDOW + 1),
            )
            furniture = set().union(*(margin_keys[j] for j in nearby if j != page_number))

            for box in layout:
                if not isinstance(box, LTTextBox) or not box.get_text().strip():
                    continue
                if _in_margin(box, layout) and _furniture_key(box) in furniture:
                    continue

                chars = _visible_chars(box)
                # Sideways text is margin furniture (arXiv's identifier stamp), not content.
                if 2 * sum(not char.upright for char in chars) > len(chars):
                    continue

                # A box belongs to the last bookmark above its midline.
                i = bisect_right(starts, (page_number, -(box.y0 + box.y1) / 2)) - 1
                path = outline[i][1] if i >= 0 else []
                if path != run_path:
                    _flush()
                    run_path = path

                if _is_monospace(chars):
                    # Consecutive code boxes are one listing: indented lines often land in
                    # boxes of their own.
                    if text_run:
                        _flush()
                    code_run.extend(line for line in box if isinstance(line, LTTextLine))
                else:
                    if code_run:
                        _flush()
                    text = _SOFT_HYPHEN_BREAK.sub("", box.get_text())
                    text = _KEPT_HYPHEN_BREAK.sub("-", text)
                    text_run.append(_WHITESPACE.sub(" ", text).strip())

        for page_number, page in enumerate(pages):
            layout = self._upright_layout(interpreter, device, page)
            margin_keys.append(_margin_keys(layout))
            pending.append((page_number, layout))
            if len(pending) > _FURNITURE_WINDOW:
                _emit(*pending.popleft())
        while pending:
            _emit(*pending.popleft())

        _flush()
        return blocks

    def _upright_layout(
        self, interpreter: PDFPageInterpreter, device: PDFPageAggregator, page: PDFPage
    ) -> LTPage:
        """Lay out a rotated page with its /Rotate or without, whichever reads upright.

        /Rotate alone doesn't say which way text runs: pdflscape pre-rotates content
        to cancel it, while a page turned in a viewer keeps its content as drawn.
        """
        interpreter.process_page(page)
        layout = device.get_result()
        upright, total = self._upright_counts(layout)
        if not page.rotate or 2 * upright >= total:
            return layout

        original, page.rotate = page.rotate, 0
        interpreter.process_page(page)
        unrotated = device.get_result()
        page.rotate = original
        return unrotated if self._upright_counts(unrotated)[0] > upright else layout

    def _upright_counts(self, layout: LTPage) -> tuple[int, int]:
        """(upright, total) visible characters across the page's text boxes."""
        chars = [
            char for box in layout if isinstance(box, LTTextBox) for char in _visible_chars(box)
        ]
        return sum(char.upright for char in chars), len(chars)


def _visible_chars(box: LTTextBox) -> list[LTChar]:
    """The box's non-whitespace glyphs, which carry font and orientation."""
    return [
        char
        for line in box
        if isinstance(line, LTTextLine)
        for char in line
        if isinstance(char, LTChar) and not char.get_text().isspace()
    ]


def _is_monospace(chars: list[LTChar]) -> bool:
    return bool(chars) and 2 * sum(is_monospace_font(c.fontname) for c in chars) > len(chars)


def _in_margin(box: LTTextBox, page: LTPage) -> bool:
    band = page.height * _MARGIN_FRACTION
    return box.y0 >= page.y1 - band or box.y1 <= page.y0 + band


def _furniture_key(box: LTTextBox) -> str | None:
    """Box text without page numbers or spacing, so "Contents • iv" matches "Contents • v".

    A bare page number keys as ""; code and number-only text such as a table row
    are never furniture and key as None.
    """
    if _is_monospace(_visible_chars(box)):
        return None
    text = box.get_text()
    if _PAGE_NUMBER.fullmatch(_WHITESPACE.sub("", text)):
        return ""
    return _WHITESPACE.sub("", _PAGE_NUMBER_TOKEN.sub("", text)).lower() or None


def _margin_keys(layout: LTPage) -> set[str]:
    keys = {
        _furniture_key(box)
        for box in layout
        if isinstance(box, LTTextBox) and _in_margin(box, layout)
    }
    return {key for key in keys if key is not None}


def _listing_text(lines: list[LTTextLine]) -> str:
    """Rebuild a code listing, turning each line's x-offset into leading spaces.

    pdfminer only emits spaces that exist as glyphs, and typeset listings usually
    indent by position instead.
    """
    left = min(line.x0 for line in lines)
    widths = [char.width for line in lines for char in line if isinstance(char, LTChar)]
    char_width = statistics.median(widths) if widths else 0.0
    rebuilt = []
    for line in lines:
        indent = round((line.x0 - left) / char_width) if char_width else 0
        rebuilt.append(" " * indent + line.get_text().rstrip())
    return "\n".join(rebuilt)
