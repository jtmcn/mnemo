"""PDF parser for Mnemo using pdfminer.six."""

from __future__ import annotations

import hashlib
import math
import re
from bisect import bisect_right
from pathlib import Path
from typing import Any

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTChar, LTTextBox, LTTextLine
from pdfminer.pdfdocument import PDFDestinationNotFound, PDFDocument, PDFNoOutlines
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1
from pdfminer.psparser import PSLiteral
from pdfminer.utils import decode_text

from mnemo.models import Book, ContentType
from mnemo.parsing.models import ContentBlock
from mnemo.parsing.text import is_monospace_font, split_authors

# A word broken across lines has lowercase on both sides of the hyphen; capitals or
# digits ("LLM-\ndriven", "2023-\n2025") mark a real compound and are kept.
_SOFT_HYPHEN_BREAK = re.compile(r"(?<=[a-z])-\n(?=[a-z])")
_KEPT_HYPHEN_BREAK = re.compile(r"(?<=\S)-\n")
_WHITESPACE = re.compile(r"\s+")

# (page index, negated y) so that ascending order is reading order.
_Position = tuple[int, float]

# Index of the "top" operand in an explicit destination, by fit type.
_TOP_OPERAND: dict[str | bytes, int] = {"XYZ": 3, "FitH": 2, "FitBH": 2}


class PdfParser:
    """Parser for born-digital PDFs via pdfminer.six.

    Sections come from the bookmark outline; a PDF without one yields
    unsectioned blocks. There is no OCR, so a scan without a text layer is
    rejected.
    """

    SUPPORTED_EXTENSIONS = {".pdf"}

    def parse(self, file_path: Path | str) -> tuple[Book, list[ContentBlock]]:
        """Parse a PDF file into Book metadata and ContentBlocks.

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If the PDF has no extractable text
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        file_bytes = file_path.read_bytes()

        # pdfminer reads objects lazily, so everything that touches doc stays in here.
        with file_path.open("rb") as f:
            doc = PDFDocument(PDFParser(f))
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
        run_path: list[str] = []

        def _flush_text() -> None:
            if text_run:
                blocks.append(ContentBlock(content="\n\n".join(text_run), section_path=run_path))
                text_run.clear()

        for page_number, page in enumerate(pages):
            interpreter.process_page(page)
            for box in device.get_result():
                if not isinstance(box, LTTextBox) or not box.get_text().strip():
                    continue

                chars = self._visible_chars(box)
                # Sideways text is margin furniture (arXiv's identifier stamp), not content.
                if 2 * sum(not char.upright for char in chars) > len(chars):
                    continue

                # A box belongs to the last bookmark above its midline.
                i = bisect_right(starts, (page_number, -(box.y0 + box.y1) / 2)) - 1
                path = outline[i][1] if i >= 0 else []
                if path != run_path:
                    _flush_text()
                    run_path = path

                if chars and 2 * sum(is_monospace_font(c.fontname) for c in chars) > len(chars):
                    _flush_text()
                    lines = [line.rstrip() for line in box.get_text().split("\n")]
                    blocks.append(
                        ContentBlock(
                            content="\n".join(lines).strip("\n"),
                            content_type=ContentType.CODE,
                            section_path=list(path),
                        )
                    )
                else:
                    text = _SOFT_HYPHEN_BREAK.sub("", box.get_text())
                    text = _KEPT_HYPHEN_BREAK.sub("-", text)
                    text_run.append(_WHITESPACE.sub(" ", text).strip())

        _flush_text()
        return blocks

    @staticmethod
    def _visible_chars(box: LTTextBox) -> list[LTChar]:
        """The box's non-whitespace glyphs, which carry font and orientation."""
        return [
            char
            for line in box
            if isinstance(line, LTTextLine)
            for char in line
            if isinstance(char, LTChar) and not char.get_text().isspace()
        ]
