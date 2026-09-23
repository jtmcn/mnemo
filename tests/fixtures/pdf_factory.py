"""Factory functions for creating test PDF files with reportlab."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

# Courier's advance width is 0.6 em, so 6pt per character at 10pt.
_COURIER_10_WIDTH = 6.0


@dataclass
class Heading:
    text: str
    level: int = 1


@dataclass
class Para:
    lines: list[str]


@dataclass
class Code:
    """Courier lines. With positional_indent, leading spaces become an x-offset
    instead of space glyphs, as typeset listings usually do it."""

    lines: list[str]
    positional_indent: bool = False


@dataclass
class Stamp:
    """Text rotated 90° in the left margin, like arXiv's identifier stamp."""

    text: str


@dataclass
class Footnote:
    """Text in the bottom margin of the current page only."""

    text: str
    font: str = "Times-Roman"


class PageBreak:
    pass


Item = Heading | Para | Code | Stamp | Footnote | PageBreak

DEFAULT_ITEMS: list[Item] = [
    Heading("Chapter 1: Basics"),
    Para(["Intro text for the basics chapter."]),
    Heading("Chapter 2: Storage"),
    Para(["Storage engines write data to disk."]),
    PageBreak(),
    Heading("2.1 Replication", level=2),
    Para(["Replication keeps copies of data on several nodes."]),
]


def create_test_pdf(
    output_path: Path,
    items: list[Item] | None = None,
    title: str = "Test PDF Book",
    author: str = "Test Author",
    outline: bool = True,
    rotation: int = 0,
    encrypt: str | None = None,
    header: str | None = None,
    footer: str | None = None,
) -> Path:
    """Draw items top-down, one line per string; headings become bookmarks when outline=True.

    rotation sets /Rotate on every page; encrypt sets a user password. header and
    footer go in the page margins on every page, with {page} or {roman} as the
    page number.
    """
    canvas = Canvas(str(output_path), encrypt=encrypt)
    canvas.setTitle(title)
    canvas.setAuthor(author)
    canvas.setPageRotation(rotation)
    # Body starts below the top tenth of an A4 page, where headers are treated as furniture.
    top = 740.0
    y = top
    page = 1

    def _furniture() -> None:
        canvas.setFont("Times-Roman", 8)
        if header:
            canvas.drawString(72, 770, header.format(page=page, roman=_roman(page)))
        if footer:
            canvas.drawString(72, 20, footer.format(page=page, roman=_roman(page)))

    for n, item in enumerate(items if items is not None else DEFAULT_ITEMS):
        if isinstance(item, PageBreak):
            _furniture()
            canvas.showPage()
            page += 1
            canvas.setPageRotation(rotation)
            y = top
        elif isinstance(item, Stamp):
            canvas.saveState()
            canvas.setFont("Times-Roman", 20)
            canvas.translate(36, 250)
            canvas.rotate(90)
            canvas.drawString(0, 0, item.text)
            canvas.restoreState()
        elif isinstance(item, Footnote):
            canvas.setFont(item.font, 8)
            canvas.drawString(72, 20, item.text)
        elif isinstance(item, Heading):
            y -= 10
            canvas.setFont("Times-Bold", 14)
            canvas.drawString(72, y, item.text)
            if outline:
                key = f"h{n}"
                canvas.bookmarkPage(key, fit="XYZ", top=y + 14)
                canvas.addOutlineEntry(item.text, key, level=item.level - 1)
            y -= 24
        elif isinstance(item, Code):
            canvas.setFont("Courier", 10)
            for line in item.lines:
                if item.positional_indent:
                    text = line.lstrip(" ")
                    x = 72 + (len(line) - len(text)) * _COURIER_10_WIDTH
                else:
                    text, x = line, 72
                canvas.drawString(x, y, text)
                y -= 13
            y -= 16
        else:
            canvas.setFont("Times-Roman", 11)
            for line in item.lines:
                canvas.drawString(72, y, line)
                y -= 14
            y -= 16

    _furniture()
    canvas.save()
    return output_path


def _roman(n: int) -> str:
    numerals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for value, numeral in numerals:
        count, n = divmod(n, value)
        out += numeral * count
    return out


def create_blank_pdf(output_path: Path) -> Path:
    """A PDF with a page but no text layer, like an un-OCR'd scan."""
    canvas = Canvas(str(output_path))
    canvas.rect(72, 500, 200, 200, fill=1)
    canvas.save()
    return output_path


def create_landscape_pdf(output_path: Path) -> Path:
    """A portrait chapter page, then a /Rotate 90 page whose content is drawn
    pre-rotated so it reads upright once rotated — how LaTeX's pdflscape does it."""
    canvas = Canvas(str(output_path))
    canvas.setFont("Times-Bold", 14)
    canvas.drawString(72, 740, "Chapter 1")
    canvas.bookmarkPage("ch1", fit="XYZ", top=760)
    canvas.addOutlineEntry("Chapter 1", "ch1", level=0)
    canvas.setFont("Times-Roman", 11)
    canvas.drawString(72, 700, "Portrait body text.")
    canvas.showPage()

    canvas.setPageRotation(90)
    canvas.saveState()
    canvas.rotate(90)
    canvas.translate(0, -612)
    canvas.setFont("Times-Roman", 11)
    canvas.drawString(72, 500, "Landscape caption text.")
    canvas.restoreState()
    canvas.save()
    return output_path


def create_named_dest_pdf(output_path: Path) -> Path:
    """One page, bookmarked the way LaTeX hyperref does it: GoTo actions to named dests.

    "Preamble text." sits above every bookmark. Intro uses an /XYZ destination,
    Methods a /FitH one, and the third bookmark names a destination that does
    not exist.
    """
    content = (
        b"BT /F1 11 Tf 72 760 Td (Preamble text.) Tj ET\n"
        b"BT /F1 11 Tf 72 700 Td (Intro body text.) Tj ET\n"
        b"BT /F1 11 Tf 72 500 Td (Methods body text.) Tj ET\n"
    )
    return _write_raw_pdf(
        output_path,
        [
            b"<< /Type /Catalog /Pages 2 0 R /Outlines 5 0 R /Names << /Dests << /Names ["
            b"(sec.intro) << /D [3 0 R /XYZ 72 720 null] >> "
            b"(sec.methods) << /D [3 0 R /FitH 520] >>] >> >> >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            b" /Resources << /Font << /F1 4 0 R >> >> /Contents 9 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>",
            b"<< /Type /Outlines /First 6 0 R /Last 8 0 R /Count 3 >>",
            b"<< /Title (Intro) /Parent 5 0 R /Next 7 0 R /A << /S /GoTo /D (sec.intro) >> >>",
            b"<< /Title (Methods) /Parent 5 0 R /Prev 6 0 R /Next 8 0 R"
            b" /A << /S /GoTo /D (sec.methods) >> >>",
            b"<< /Title (Missing) /Parent 5 0 R /Prev 7 0 R /A << /S /GoTo /D (sec.gone) >> >>",
            _stream(content),
            b"<< /Title (Named Dest Paper) >>",
        ],
        info=10,
    )


def create_cyclic_outline_pdf(output_path: Path) -> Path:
    """One page whose two bookmarks point /Next at each other — a malformed outline."""
    return _write_raw_pdf(
        output_path,
        [
            b"<< /Type /Catalog /Pages 2 0 R /Outlines 5 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            b" /Resources << /Font << /F1 4 0 R >> >> /Contents 8 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>",
            b"<< /Type /Outlines /First 6 0 R /Last 7 0 R /Count 2 >>",
            b"<< /Title (A) /Parent 5 0 R /Next 7 0 R /Dest [3 0 R /XYZ 72 792 null] >>",
            b"<< /Title (B) /Parent 5 0 R /Prev 6 0 R /Next 6 0 R"
            b" /Dest [3 0 R /XYZ 72 792 null] >>",
            _stream(b"BT /F1 11 Tf 72 700 Td (Body text.) Tj ET\n"),
        ],
    )


def _stream(content: bytes) -> bytes:
    return b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream"


def _write_raw_pdf(output_path: Path, objects: list[bytes], info: int | None = None) -> Path:
    """Write numbered objects (1-based, in order) with a valid xref; object 1 is the catalog.

    reportlab can't produce named destinations or malformed outlines, so these
    fixtures are written by hand.
    """
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    info_ref = b" /Info %d 0 R" % info if info is not None else b""
    out += b"trailer\n<< /Size %d /Root 1 0 R%s >>\n" % (len(objects) + 1, info_ref)
    out += b"startxref\n%d\n%%%%EOF\n" % xref

    output_path.write_bytes(bytes(out))
    return output_path
