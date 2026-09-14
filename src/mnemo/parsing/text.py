"""Text helpers shared by the format-specific parsers."""

from __future__ import annotations

import re

# Matched against the lowercased name with non-letters removed, so "Source Code Pro"
# and "ABCDEF+SourceCodePro-Regular" both hit "sourcecode".
_MONOSPACE_FONT_HINTS = (
    "courier",
    "consolas",
    "mono",
    "menlo",
    "sourcecode",
    "cmtt",
    "nimbusmon",
    "inconsolata",
    "sftt",
    "txtt",
    "lucidaconsole",
    "firacode",
)


def is_monospace_font(name: str) -> bool:
    """Guess from a font name (Word style or embedded PDF font) whether it is monospace."""
    normalized = re.sub(r"[^a-z]", "", name.split("+")[-1].lower())
    return any(hint in normalized for hint in _MONOSPACE_FONT_HINTS)


def split_authors(raw: str) -> list[str]:
    """Split a metadata author string on semicolons, or on commas if there are none."""
    separator = ";" if ";" in raw else ","
    return [author.strip() for author in raw.split(separator) if author.strip()]
