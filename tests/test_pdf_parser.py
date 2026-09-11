"""Tests for the PDF parser."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mnemo.models import ContentType
from mnemo.parsing.models import ContentBlock
from mnemo.pdf import PdfParser
from tests.fixtures.pdf_factory import (
    Code,
    Heading,
    Para,
    Stamp,
    create_blank_pdf,
    create_named_dest_pdf,
    create_test_pdf,
)


@pytest.fixture
def parser() -> PdfParser:
    return PdfParser()


def _block_containing(blocks: list[ContentBlock], needle: str) -> ContentBlock:
    matches = [b for b in blocks if needle in b.content]
    assert len(matches) == 1, f"expected one block containing {needle!r}, got {matches}"
    return matches[0]


class TestPdfMetadata:
    def test_extracts_title_and_split_authors(self, parser: PdfParser, tmp_path: Path) -> None:
        path = create_test_pdf(
            tmp_path / "book.pdf", title="Distributed Systems", author="Alice Smith; Bob Jones"
        )
        book, _ = parser.parse(path)
        assert book.title == "Distributed Systems"
        assert book.authors == ["Alice Smith", "Bob Jones"]

    def test_missing_title_falls_back_to_filename(self, parser: PdfParser, tmp_path: Path) -> None:
        path = create_test_pdf(tmp_path / "2510.25445v1.pdf", title="", author="")
        book, _ = parser.parse(path)
        assert book.title == "2510.25445v1"
        assert book.authors == []

    def test_hash_is_sha256_of_file_bytes(self, parser: PdfParser, tmp_path: Path) -> None:
        path = create_test_pdf(tmp_path / "book.pdf")
        book, _ = parser.parse(path)
        assert book.file_hash == hashlib.sha256(path.read_bytes()).hexdigest()
        assert len(book.id) == 6

    def test_file_not_found(self, parser: PdfParser) -> None:
        with pytest.raises(FileNotFoundError):
            parser.parse(Path("/nonexistent/book.pdf"))


class TestPdfSections:
    def test_text_lands_under_the_outline_entry_above_it(
        self, parser: PdfParser, tmp_path: Path
    ) -> None:
        # Chapters 1 and 2 share page 1, so placement depends on y-position, not just page.
        book, blocks = parser.parse(create_test_pdf(tmp_path / "book.pdf"))
        assert _block_containing(blocks, "Intro text").section_path == ["Chapter 1: Basics"]
        assert _block_containing(blocks, "Storage engines").section_path == ["Chapter 2: Storage"]
        assert _block_containing(blocks, "Replication keeps").section_path == [
            "Chapter 2: Storage",
            "2.1 Replication",
        ]
        assert book.structure_source == "toc"

    def test_sibling_section_replaces_previous_at_same_level(
        self, parser: PdfParser, tmp_path: Path
    ) -> None:
        items = [
            Heading("Chapter 1"),
            Heading("1.1 First", level=2),
            Para(["First body."]),
            Heading("1.2 Second", level=2),
            Para(["Second body."]),
        ]
        _, blocks = parser.parse(create_test_pdf(tmp_path / "book.pdf", items=items))
        assert _block_containing(blocks, "Second body").section_path == ["Chapter 1", "1.2 Second"]

    def test_hyperref_named_destinations_resolve(self, parser: PdfParser, tmp_path: Path) -> None:
        # GoTo actions to named destinations; the third bookmark's target is missing.
        book, blocks = parser.parse(create_named_dest_pdf(tmp_path / "paper.pdf"))
        assert book.title == "Named Dest Paper"
        assert book.structure_source == "toc"
        assert _block_containing(blocks, "Intro body").section_path == ["Intro"]
        assert _block_containing(blocks, "Methods body").section_path == ["Methods"]

    def test_no_outline_is_inferred_with_empty_paths(
        self, parser: PdfParser, tmp_path: Path
    ) -> None:
        book, blocks = parser.parse(create_test_pdf(tmp_path / "flat.pdf", outline=False))
        assert book.structure_source == "inferred"
        assert blocks
        assert all(b.section_path == [] for b in blocks)


class TestPdfText:
    def _parse_para(self, parser: PdfParser, tmp_path: Path, lines: list[str]) -> str:
        items = [Heading("Chapter 1"), Para(lines)]
        _, blocks = parser.parse(create_test_pdf(tmp_path / "book.pdf", items=items))
        return _block_containing(blocks, lines[-1].split()[-1]).content

    def test_wrapped_lines_join_with_a_space(self, parser: PdfParser, tmp_path: Path) -> None:
        content = self._parse_para(parser, tmp_path, ["the first line", "and the second"])
        assert "the first line and the second" in content

    def test_lowercase_hyphenation_is_rejoined(self, parser: PdfParser, tmp_path: Path) -> None:
        content = self._parse_para(parser, tmp_path, ["the core con-", "cepts of storage"])
        assert "the core concepts of storage" in content

    def test_compound_hyphen_is_kept(self, parser: PdfParser, tmp_path: Path) -> None:
        content = self._parse_para(parser, tmp_path, ["an LLM-", "driven agent"])
        assert "an LLM-driven agent" in content

    def test_monospace_block_becomes_code_keeping_lines(
        self, parser: PdfParser, tmp_path: Path
    ) -> None:
        items = [
            Heading("Chapter 1"),
            Para(["Here is an example:"]),
            Code(["def hello():", "    print('hi')"]),
            Para(["Text after the code."]),
        ]
        _, blocks = parser.parse(create_test_pdf(tmp_path / "book.pdf", items=items))
        code = _block_containing(blocks, "def hello")
        assert code.content_type == ContentType.CODE
        assert [line.strip() for line in code.content.splitlines()] == [
            "def hello():",
            "print('hi')",
        ]
        assert code.section_path == ["Chapter 1"]
        assert _block_containing(blocks, "Text after").content_type == ContentType.TEXT

    def test_rotated_margin_stamp_is_dropped(self, parser: PdfParser, tmp_path: Path) -> None:
        items = [Stamp("arXiv:2510.25445v1 [cs.AI] 29 Oct 2025"), Heading("Intro"), Para(["Body."])]
        _, blocks = parser.parse(create_test_pdf(tmp_path / "paper.pdf", items=items))
        assert [b.content for b in blocks] == ["Intro\n\nBody."]

    def test_pdf_without_text_raises(self, parser: PdfParser, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="no extractable text"):
            parser.parse(create_blank_pdf(tmp_path / "scan.pdf"))
