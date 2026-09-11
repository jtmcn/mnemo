"""Tests for text helpers shared by the format parsers."""

from __future__ import annotations

import pytest

from mnemo.parsing.text import is_monospace_font, split_authors


@pytest.mark.parametrize(
    ("font", "want"),
    [
        ("Courier New", True),
        ("Courier", True),
        ("Source Code Pro", True),
        ("ABCDEF+SourceCodePro-Regular", True),
        ("NimbusMonL-Regu", True),
        ("CMTT10", True),
        ("Menlo-Regular", True),
        ("Times-Roman", False),
        ("NimbusRomNo9L-Regu", False),
        ("Calibri", False),
    ],
)
def test_is_monospace_font(font: str, want: bool) -> None:
    assert is_monospace_font(font) is want


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("Mohamad Abou Ali; Fadi Dornaika", ["Mohamad Abou Ali", "Fadi Dornaika"]),
        ("Alice, Bob", ["Alice", "Bob"]),
        ("Solo Author", ["Solo Author"]),
        ("  ", []),
        ("", []),
    ],
)
def test_split_authors(raw: str, want: list[str]) -> None:
    assert split_authors(raw) == want
