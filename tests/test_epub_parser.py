"""Tests for EPUB parser module."""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag

from mnemo.epub import EPUBParser
from mnemo.epub.content import ContentBlock, _extract_math
from mnemo.epub.metadata import extract_metadata, normalize_isbn
from mnemo.models import Book, ContentType
from tests.fixtures.epub_factory import (
    create_epub_with_code,
    create_epub_with_front_matter,
    create_test_epub,
)


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


class TestWordBoundaryFix:
    """Tests for PARSE-01: word boundary preservation across inline elements."""

    def test_word_boundaries_preserved_across_inline_elements(self, tmp_path: Path) -> None:
        epub_path = create_test_epub(
            title="Word Boundary Test",
            authors=["Test Author"],
            chapters=[
                {
                    "title": "Chapter 1",
                    "content": "<p><span>a</span><span>strategy</span> for <em>success</em></p>",
                }
            ],
            output_path=tmp_path / "word_boundary.epub",
        )
        parser = EPUBParser()

        _, blocks = parser.parse(epub_path)

        text_blocks = [b for b in blocks if b.content_type == ContentType.TEXT]
        all_text = " ".join(b.content for b in text_blocks)
        assert "astrategy" not in all_text
        assert "a strategy" in all_text

    def test_inline_sibling_word_boundaries(self, tmp_path: Path) -> None:
        epub_path = create_test_epub(
            title="Sibling Boundary Test",
            authors=["Test Author"],
            chapters=[
                {
                    "title": "Chapter 1",
                    "content": "<p><em>bold</em><strong>text</strong> here</p>",
                }
            ],
            output_path=tmp_path / "sibling_boundary.epub",
        )
        parser = EPUBParser()

        _, blocks = parser.parse(epub_path)

        text_blocks = [b for b in blocks if b.content_type == ContentType.TEXT]
        all_text = " ".join(b.content for b in text_blocks)
        assert "boldtext" not in all_text
        assert "bold text" in all_text


class TestSemicolonAuthorSplit:
    """Tests for PARSE-02: semicolon-delimited author splitting."""

    def test_semicolon_delimited_authors(self, tmp_path: Path) -> None:
        epub_path = create_test_epub(
            title="Multi Author Book",
            raw_creators=["Smith, Alice; Jones, Bob;"],
            output_path=tmp_path / "multi_author.epub",
        )

        book = extract_metadata(epub_path)

        assert book.authors == ["Smith, Alice", "Jones, Bob"]

    def test_author_trailing_semicolon(self, tmp_path: Path) -> None:
        epub_path = create_test_epub(
            title="Single Author Book",
            raw_creators=["Alice Smith;"],
            output_path=tmp_path / "single_author.epub",
        )

        book = extract_metadata(epub_path)

        assert book.authors == ["Alice Smith"]


class TestFrontMatterLabels:
    """Tests for PARSE-03: front-matter section label inference."""

    def test_front_matter_cover_label(self, tmp_path: Path) -> None:
        epub_path = create_epub_with_front_matter(
            front_matter_items=[{"filename": "cover.xhtml", "content": "<p>Cover page</p>"}],
            output_path=tmp_path / "cover_fm.epub",
        )
        parser = EPUBParser()

        _, blocks = parser.parse(epub_path)

        cover_blocks = [b for b in blocks if "cover.xhtml" in b.source_file]
        assert len(cover_blocks) > 0, "Expected blocks from cover.xhtml"
        for block in cover_blocks:
            assert block.section_path == ["Cover"], f"Expected ['Cover'], got {block.section_path}"

    def test_front_matter_toc_label(self, tmp_path: Path) -> None:
        epub_path = create_epub_with_front_matter(
            front_matter_items=[{"filename": "toc.xhtml", "content": "<p>Table of Contents</p>"}],
            output_path=tmp_path / "toc_fm.epub",
        )
        parser = EPUBParser()

        _, blocks = parser.parse(epub_path)

        toc_blocks = [b for b in blocks if "toc.xhtml" in b.source_file]
        assert len(toc_blocks) > 0, "Expected blocks from toc.xhtml"
        for block in toc_blocks:
            assert block.section_path == ["Table of Contents"], (
                f"Expected ['Table of Contents'], got {block.section_path}"
            )

    def test_unknown_href_gets_filename_label(self, tmp_path: Path) -> None:
        """Unknown filenames get a title-cased filename stem as fallback section label."""
        epub_path = create_epub_with_front_matter(
            front_matter_items=[
                {"filename": "random_file.xhtml", "content": "<p>Unknown content</p>"}
            ],
            output_path=tmp_path / "unknown_fm.epub",
        )
        parser = EPUBParser()

        _, blocks = parser.parse(epub_path)

        unknown_blocks = [b for b in blocks if "random_file.xhtml" in b.source_file]
        assert len(unknown_blocks) > 0, "Expected blocks from random_file.xhtml"
        for block in unknown_blocks:
            assert block.section_path == ["Random File"], (
                f"Expected ['Random File'], got {block.section_path}"
            )

    def test_front_matter_prefix_match(self, tmp_path: Path) -> None:
        epub_path = create_epub_with_front_matter(
            front_matter_items=[
                {"filename": "preface_01.xhtml", "content": "<p>Preface content</p>"}
            ],
            output_path=tmp_path / "preface_fm.epub",
        )
        parser = EPUBParser()

        _, blocks = parser.parse(epub_path)

        preface_blocks = [b for b in blocks if "preface_01.xhtml" in b.source_file]
        assert len(preface_blocks) > 0, "Expected blocks from preface_01.xhtml"
        for block in preface_blocks:
            assert block.section_path == ["Preface"], (
                f"Expected ['Preface'], got {block.section_path}"
            )


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


# ============================================================================
# Math Extraction Tests
# ============================================================================


def _make_tag(html: str) -> Tag:
    """Parse HTML fragment and return the first tag."""
    soup = BeautifulSoup(html, "html.parser")
    return next(soup.children)


class TestExtractMath:
    """Tests for _extract_math function."""

    def test_wrapper_with_math_element(self) -> None:
        """Div wrapping a <math> element returns the <math> markup."""
        tag = _make_tag('<div class="math"><math><mrow><mi>x</mi></mrow></math></div>')
        result = _extract_math(tag)
        assert result == "<math><mrow><mi>x</mi></mrow></math>"

    def test_bare_mathml_elements_return_raw_markup(self) -> None:
        """Span with bare MathML elements returns raw markup, not spaced text."""
        tag = _make_tag('<span class="math"><mi>d</mi><mi>o</mi><mi>t</mi></span>')
        result = _extract_math(tag)
        # Should preserve markup, not produce "d o t"
        assert "<mi>" in result
        assert "d o t" not in result

    def test_latex_math_no_extra_spaces(self) -> None:
        """Plain LaTeX text is concatenated without extra spaces."""
        tag = _make_tag('<span class="math">$x^2$</span>')
        result = _extract_math(tag)
        assert result == "$x^2$"

    def test_math_root_element(self) -> None:
        """A <math> element itself returns raw markup."""
        tag = _make_tag("<math><mi>y</mi></math>")
        result = _extract_math(tag)
        assert result == "<math><mi>y</mi></math>"
