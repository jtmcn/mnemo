"""Data models and constants for EPUB content extraction."""

from __future__ import annotations

import re

# Maps filename stems to human-readable front-matter section labels.
# Used by _infer_front_matter_label to assign descriptive labels to spine items
# that are absent from the EPUB's NAV/NCX table of contents.
FRONT_MATTER_STEMS: dict[str, str] = {
    "cover": "Cover",
    "toc": "Table of Contents",
    "contents": "Table of Contents",
    "copyright": "Copyright",
    "copyrights": "Copyright",
    "title": "Title Page",
    "titlepage": "Title Page",
    "title-page": "Title Page",
    "dedication": "Dedication",
    "preface": "Preface",
    "foreword": "Foreword",
    "introduction": "Introduction",
    "intro": "Introduction",
    "acknowledgements": "Acknowledgements",
    "acknowledgments": "Acknowledgements",
    "about": "About",
    "colophon": "Colophon",
    "halftitle": "Half Title",
    "half-title": "Half Title",
}


# Publisher-specific code block CSS classes
CODE_CLASSES = {
    # Standard
    "highlight",
    "sourceCode",
    "source-code",
    "listing",
    "codehilite",
    # O'Reilly
    "programlisting",
    "screen",
    # Pragmatic
    "code",
    "livecodelozenge",
    # Manning
    "listingblock",
    # General
    "syntax",
    "prettyprint",
}

# Tags that mean an element is a container of other content, not a leaf.
# A math node is a leaf: anything holding these is a chapter or section.
BLOCK_LEVEL_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "pre",
        "table",
        "ul",
        "ol",
        "li",
        "blockquote",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
)

# Classes that indicate ASCII diagrams
DIAGRAM_CLASSES = {"ascii", "diagram", "ascii-diagram", "ascii-art"}

# Math-related classes and patterns
MATH_CLASSES = {"equation", "math", "formula", "katex", "mathjax"}

# LaTeX delimiter patterns
# Bounded so one stray delimiter pair cannot swallow a whole chapter.
LATEX_BLOCK_PATTERN = re.compile(r"\\\[.{1,2000}?\\\]", re.DOTALL)
# Single-line and bounded: real inline math is short, while "$x ... $y" spanning
# lines matches PHP/shell variables in any code sample.
LATEX_INLINE_PATTERN = re.compile(r"\$[^$\n]{1,200}\$")

# Common programming languages for detection
_KNOWN_LANGUAGES = {
    "python",
    "javascript",
    "typescript",
    "java",
    "go",
    "rust",
    "ruby",
    "php",
    "c",
    "cpp",
    "csharp",
    "swift",
    "kotlin",
    "scala",
    "shell",
    "bash",
    "sh",
    "sql",
    "html",
    "css",
    "json",
    "yaml",
    "xml",
    "markdown",
}


MATHML_ELEMENTS = frozenset(
    {
        "mi",
        "mo",
        "mn",
        "mrow",
        "msup",
        "msub",
        "mfrac",
        "mover",
        "munder",
        "msqrt",
        "mroot",
        "mtext",
        "mspace",
        "mtable",
        "mtr",
        "mtd",
        "mpadded",
        "mstyle",
    }
)
