"""Tests for the parsing dispatch module."""

from __future__ import annotations

from pathlib import Path

import pytest

from mnemo.parsing.dispatch import SUPPORTED_FORMATS, parse_book
from tests.fixtures.docx_factory import create_test_docx
from tests.fixtures.epub_factory import create_test_epub


class TestParseBook:
    """Tests for the parse_book dispatcher."""

    def test_routes_epub(self, tmp_path: Path) -> None:
        epub_path = create_test_epub(
            title="Dispatch Test",
            authors=["Author"],
            output_path=tmp_path / "test.epub",
        )
        book, blocks = parse_book(epub_path)
        assert book.title == "Dispatch Test"
        assert len(blocks) > 0

    def test_routes_docx(self, tmp_path: Path) -> None:
        docx_path = create_test_docx(tmp_path / "test.docx")
        book, blocks = parse_book(docx_path)
        assert book.title == "Test DOCX Book"
        assert len(blocks) > 0

    def test_rejects_unsupported_format(self, tmp_path: Path) -> None:
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("hello")
        with pytest.raises(ValueError, match="Unsupported file format"):
            parse_book(txt_file)

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            parse_book(Path("/nonexistent/file.epub"))

    def test_supported_formats_set(self) -> None:
        assert ".epub" in SUPPORTED_FORMATS
        assert ".docx" in SUPPORTED_FORMATS
