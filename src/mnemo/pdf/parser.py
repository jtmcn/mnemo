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

from mnemo.models import Book, ContentType, is_boilerplate_section
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

# pdfminer's default 0.5 splits books set at ~1.6x leading into one box per line;
# paragraph and heading gaps stay well above 0.8.
_LINE_MARGIN = 0.8
# A top-level entry set this much smaller than the chapter headings is a section.
_SECTION_SIZE_RATIO = 0.75
# An entry's heading is the largest of its first few boxes (a "CHAPTER 2" label sits above it).
_HEADING_BOXES = 3
_CHAPTER_PREFIX = re.compile(r"^(?:chapter|part)\s+\w+\s*[.:\-\u2013\u2014]?\s*")

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
        device = PDFPageAggregator(resources, laparams=LAParams(line_margin=_LINE_MARGIN))
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
        heads = self._entry_headings(interpreter, device, pages, outline)
        chapter_size = _chapter_size(
            [size for i, (size, text) in heads.items() if _names(text, outline[i][1][0])]
        )
        # Headings that don't spell out their entry still size back matter, as before.
        back_size = chapter_size or max((size for size, _ in heads.values()), default=0.0)
        styled = _section_styled(outline, heads, chapter_size)
        entered = -1
        unlisted: list[str] = []
        # The chapter a top-level entry printed as a section heading belongs under.
        parent: list[str] = []

        def _emit(page_number: int, layout: LTPage) -> None:
            nonlocal run_path, entered, unlisted, parent
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
                size = max((char.size for char in chars), default=0.0)
                if i != entered:
                    entered = i
                    unlisted = []
                    if len(path) == 1 and not styled[i]:
                        parent = path
                elif (i < 0 or i == len(outline) - 1) and _is_unlisted_heading(
                    box, size, chapter_size if i < 0 else back_size
                ):
                    # Front or back matter (a foreword, a glossary) the outline leaves out.
                    unlisted = parent = [_WHITESPACE.sub(" ", box.get_text()).strip()]
                if unlisted:
                    path = unlisted
                elif i >= 0 and styled[i] and parent:
                    path = parent + path
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

    def _entry_headings(
        self,
        interpreter: PDFPageInterpreter,
        device: PDFPageAggregator,
        pages: list[PDFPage],
        outline: list[tuple[_Position, list[str]]],
    ) -> dict[int, tuple[float, str]]:
        """(font size, text) of the heading box under each top-level outline entry."""
        starts = [position for position, _ in outline]
        heads: dict[int, tuple[float, str]] = {}
        seen: dict[int, int] = {}
        for page_number in sorted({pos[0] for pos, path in outline if len(path) == 1}):
            layout = self._upright_layout(interpreter, device, pages[page_number])
            for box in layout:
                if not isinstance(box, LTTextBox) or not box.get_text().strip():
                    continue
                chars = _visible_chars(box)
                if _in_margin(box, layout) or 2 * sum(not c.upright for c in chars) > len(chars):
                    continue
                i = bisect_right(starts, (page_number, -(box.y0 + box.y1) / 2)) - 1
                if i >= 0 and len(outline[i][1]) == 1 and seen.get(i, 0) < _HEADING_BOXES:
                    seen[i] = seen.get(i, 0) + 1
                    size = max((char.size for char in chars), default=0.0)
                    if size > heads.get(i, (0.0, ""))[0]:
                        heads[i] = (size, box.get_text().strip())
        return heads

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


def _is_unlisted_heading(box: LTTextBox, size: float, chapter_size: float) -> bool:
    """A short single line set like the outline's chapter headings (not a larger title)."""
    lines = [line for line in box if isinstance(line, LTTextLine)]
    return (
        chapter_size > 0
        and abs(size - chapter_size) <= 0.5
        and len(lines) == 1
        and len(box.get_text().split()) <= 8
    )


def _section_styled(
    outline: list[tuple[_Position, list[str]]],
    heads: dict[int, tuple[float, str]],
    chapter_size: float,
) -> list[bool]:
    """Per entry: is its top-level entry printed as a section heading, not a chapter one?

    Only a heading that names its entry counts; a bookmark landing on other text says
    nothing about its level.
    """
    styled: list[bool] = []
    current, top = False, ""
    for i, (_, path) in enumerate(outline):
        if len(path) == 1:
            size, text = heads.get(i, (chapter_size, ""))
            section_sized = size < _SECTION_SIZE_RATIO * chapter_size
            named = _names(text, path[0]) and not is_boilerplate_section(path)
            current, top = section_sized and named, path[0]
        styled.append(current and path[0] == top)
    return styled


def _chapter_size(sizes: list[float]) -> float:
    """The largest heading size at least two entries share, so one title page can't set it."""
    shared = [s for s in sizes if sum(abs(s - t) <= 0.5 for t in sizes) >= 2]
    return max(shared or sizes, default=0.0)


def _names(text: str, title: str) -> bool:
    """Whether one of a heading's first two lines is the title, or most of it when it wraps."""
    title = _CHAPTER_PREFIX.sub("", _plain(title))
    for line in text.split("\n")[:2]:
        line = _CHAPTER_PREFIX.sub("", _plain(line))
        # A bare numeral ("IV") starts its title too, but says nothing about the heading.
        if line and title.startswith(line) and 2 * len(line) >= len(title):
            return True
    return False


def _plain(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip(" 0123456789.").casefold()


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
