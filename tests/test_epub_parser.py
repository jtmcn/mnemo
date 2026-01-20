"""Tests for EPUB parser module."""

from __future__ import annotations

from pathlib import Path

import pytest

from mnemo.epub import EPUBParser
from mnemo.epub.content import ContentBlock
from mnemo.epub.metadata import extract_metadata, normalize_isbn
from mnemo.models import Book, ContentType
from tests.fixtures.epub_factory import create_epub_with_code, create_test_epub


class TestNormalizeIsbn:
    """Tests for ISBN normalization."""

    def test_isbn13_with_hyphens(self) -> None:
        assert normalize_isbn("978-0-13-468599-1") == "9780134685991"

    def test_isbn10(self) -> None:
        assert normalize_isbn("0-13-468599-5") == "0134685995"

    def test_isbn10_with_x(self) -> None:
        assert normalize_isbn("0-596-00712-X") == "059600712X"

    def test_urn_format(self) -> None:
        assert normalize_isbn("urn:isbn:9780134685991") == "9780134685991"

    def test_invalid_isbn(self) -> None:
        assert normalize_isbn("not-an-isbn") is None

    def test_empty_isbn(self) -> None:
        assert normalize_isbn("") is None


class TestExtractMetadata:
    """Tests for metadata extraction."""

    def test_extracts_title_and_authors(self, tmp_path: Path) -> None:
        epub_path = create_test_epub(
            title="My Python Book",
            authors=["Alice Smith", "Bob Jones"],
            output_path=tmp_path / "test.epub",
        )

        book = extract_metadata(epub_path)

        assert book.title == "My Python Book"
        assert book.authors == ["Alice Smith", "Bob Jones"]
        assert len(book.id) == 6
        assert len(book.file_hash) == 64

    def test_extracts_isbn(self, tmp_path: Path) -> None:
        epub_path = create_test_epub(
            title="Book with ISBN",
            isbn="978-1-234-56789-0",
            output_path=tmp_path / "test.epub",
        )

        book = extract_metadata(epub_path)

        assert book.isbn == "9781234567890"

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            extract_metadata(Path("/nonexistent/book.epub"))


class TestContentExtraction:
    """Tests for content type detection."""

    def test_detects_code_blocks(self, tmp_path: Path) -> None:
        epub_path = create_epub_with_code(output_path=tmp_path / "code_book.epub")
        parser = EPUBParser()

        book, blocks = parser.parse(epub_path)

        code_blocks = [b for b in blocks if b.content_type == ContentType.CODE]
        assert len(code_blocks) >= 1

        # Check language detection
        python_blocks = [b for b in code_blocks if b.language == "python"]
        assert len(python_blocks) >= 1

    def test_detects_tables(self, tmp_path: Path) -> None:
        epub_path = create_epub_with_code(output_path=tmp_path / "table_book.epub")
        parser = EPUBParser()

        book, blocks = parser.parse(epub_path)

        table_blocks = [b for b in blocks if b.content_type == ContentType.TABLE]
        assert len(table_blocks) >= 1

        # Check table format
        table = table_blocks[0]
        assert "|" in table.content
        assert "Structure" in table.content  # Header

    def test_detects_diagrams(self, tmp_path: Path) -> None:
        epub_path = create_epub_with_code(output_path=tmp_path / "diagram_book.epub")
        parser = EPUBParser()

        book, blocks = parser.parse(epub_path)

        diagram_blocks = [b for b in blocks if b.content_type == ContentType.DIAGRAM]
        assert len(diagram_blocks) >= 1

    def test_preserves_code_whitespace(self, tmp_path: Path) -> None:
        epub_path = create_epub_with_code(output_path=tmp_path / "ws_book.epub")
        parser = EPUBParser()

        book, blocks = parser.parse(epub_path)

        code_blocks = [b for b in blocks if b.content_type == ContentType.CODE]
        # Code blocks should preserve indentation
        python_code = next((b for b in code_blocks if "def " in b.content), None)
        assert python_code is not None
        assert "    " in python_code.content or "\t" in python_code.content


class TestTocParsing:
    """Tests for TOC parsing and section hierarchy."""

    def test_extracts_section_paths(self, tmp_path: Path) -> None:
        epub_path = create_test_epub(
            title="Structured Book",
            chapters=[
                {"title": "Introduction", "content": "<p>Intro text</p>"},
                {"title": "Chapter 1", "content": "<p>Main content</p>"},
            ],
            output_path=tmp_path / "toc_book.epub",
        )
        parser = EPUBParser()

        book, blocks = parser.parse(epub_path)

        # Check that section paths are populated
        section_paths = [b.section_path for b in blocks if b.section_path]
        assert len(section_paths) > 0


class TestEPUBParser:
    """Tests for main EPUBParser class."""

    def test_parse_returns_book_and_blocks(self, tmp_path: Path) -> None:
        epub_path = create_test_epub(
            title="Test Book",
            authors=["Test Author"],
            output_path=tmp_path / "parser_test.epub",
        )
        parser = EPUBParser()

        result = parser.parse(epub_path)

        assert isinstance(result, tuple)
        assert len(result) == 2

        book, blocks = result
        assert isinstance(book, Book)
        assert isinstance(blocks, list)
        assert all(isinstance(b, ContentBlock) for b in blocks)

    def test_book_has_structure_source(self, tmp_path: Path) -> None:
        epub_path = create_test_epub(
            title="Structure Test",
            output_path=tmp_path / "structure.epub",
        )
        parser = EPUBParser()

        book, _ = parser.parse(epub_path)

        assert book.structure_source in ("toc", "inferred")

    def test_file_not_found_error(self) -> None:
        parser = EPUBParser()

        with pytest.raises(FileNotFoundError):
            parser.parse(Path("/nonexistent/book.epub"))

    def test_parser_import(self) -> None:
        """Verify parser can be imported from package."""
        from mnemo.epub import EPUBParser

        assert EPUBParser is not None
