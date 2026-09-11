"""Factory functions for creating test PDF files with reportlab."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas


@dataclass
class Heading:
    text: str
    level: int = 1


@dataclass
class Para:
    lines: list[str]


@dataclass
class Code:
    lines: list[str]


@dataclass
class Stamp:
    """Text rotated 90° in the left margin, like arXiv's identifier stamp."""

    text: str


class PageBreak:
    pass


Item = Heading | Para | Code | Stamp | PageBreak

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
) -> Path:
    """Draw items top-down, one line per string; headings become bookmarks when outline=True."""
    canvas = Canvas(str(output_path))
    canvas.setTitle(title)
    canvas.setAuthor(author)
    top = 770.0
    y = top

    for n, item in enumerate(items if items is not None else DEFAULT_ITEMS):
        if isinstance(item, PageBreak):
            canvas.showPage()
            y = top
        elif isinstance(item, Stamp):
            canvas.saveState()
            canvas.setFont("Times-Roman", 20)
            canvas.translate(36, 250)
            canvas.rotate(90)
            canvas.drawString(0, 0, item.text)
            canvas.restoreState()
        elif isinstance(item, Heading):
            y -= 10
            canvas.setFont("Times-Bold", 14)
            canvas.drawString(72, y, item.text)
            if outline:
                key = f"h{n}"
                canvas.bookmarkPage(key, fit="XYZ", top=y + 14)
                canvas.addOutlineEntry(item.text, key, level=item.level - 1)
            y -= 24
        else:
            font, size = ("Courier", 10) if isinstance(item, Code) else ("Times-Roman", 11)
            canvas.setFont(font, size)
            for line in item.lines:
                canvas.drawString(72, y, line)
                y -= size + 3
            y -= 16

    canvas.save()
    return output_path


def create_blank_pdf(output_path: Path) -> Path:
    """A PDF with a page but no text layer, like an un-OCR'd scan."""
    canvas = Canvas(str(output_path))
    canvas.rect(72, 500, 200, 200, fill=1)
    canvas.save()
    return output_path


def create_named_dest_pdf(output_path: Path) -> Path:
    """One page, bookmarked the way LaTeX hyperref does it: GoTo actions to named dests.

    reportlab only writes explicit destinations, so the objects are written by hand.
    The third bookmark names a destination that does not exist.
    """
    content = (
        b"BT /F1 11 Tf 72 700 Td (Intro body text.) Tj ET\n"
        b"BT /F1 11 Tf 72 500 Td (Methods body text.) Tj ET\n"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /Outlines 5 0 R /Names << /Dests << /Names ["
        b"(sec.intro) << /D [3 0 R /XYZ 72 720 null] >> "
        b"(sec.methods) << /D [3 0 R /XYZ 72 520 null] >>] >> >> >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Resources << /Font << /F1 4 0 R >> >> /Contents 9 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>",
        b"<< /Type /Outlines /First 6 0 R /Last 8 0 R /Count 3 >>",
        b"<< /Title (Intro) /Parent 5 0 R /Next 7 0 R /A << /S /GoTo /D (sec.intro) >> >>",
        b"<< /Title (Methods) /Parent 5 0 R /Prev 6 0 R /Next 8 0 R"
        b" /A << /S /GoTo /D (sec.methods) >> >>",
        b"<< /Title (Missing) /Parent 5 0 R /Prev 7 0 R /A << /S /GoTo /D (sec.gone) >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
        b"<< /Title (Named Dest Paper) >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 10 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref

    output_path.write_bytes(bytes(out))
    return output_path
