"""Content type classification predicates for EPUB HTML elements."""

from __future__ import annotations

from bs4 import Tag

from mnemo.epub._models import (
    _KNOWN_LANGUAGES,
    CODE_CLASSES,
    DIAGRAM_CLASSES,
    LATEX_BLOCK_PATTERN,
    LATEX_INLINE_PATTERN,
    MATH_CLASSES,
)


def _classes(element: Tag) -> list[str]:
    """CSS classes on a tag, in document order.

    bs4 types the `class` attribute as str | AttributeValueList | None; the
    str case would otherwise be iterated character by character. Order matters
    to _detect_code_language, which returns the first language it recognises,
    so this stays a list — a set would make the winner depend on the process
    hash seed when a tag carries two language-bearing classes.
    """
    value = element.get("class")
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [cls for cls in value if isinstance(cls, str)]


def _is_code_block(element: Tag) -> bool:
    """Check if element is a code block.

    Detection rules:
    - <pre> with <code> child
    - <pre> with code-related class
    - <code> that's not inline (block-level)

    Args:
        element: BeautifulSoup Tag to check

    Returns:
        True if element is a code block
    """
    tag_name = element.name.lower() if element.name else ""

    if tag_name == "pre":
        # Check for <code> child
        if element.find("code"):
            return True

        # Check for code-related classes
        classes = set(_classes(element))
        if classes & CODE_CLASSES:
            return True

            # Check for diagram classes (not code); assume pre tags are code otherwise
        return not (classes & DIAGRAM_CLASSES)

    # Check for standalone <code> blocks (not inline)
    if tag_name == "code":
        # If parent is <pre>, let <pre> handle it
        parent = element.parent
        if parent and parent.name and parent.name.lower() == "pre":
            return False

        # Large code elements are probably blocks
        text = element.get_text()
        return "\n" in text or len(text) > 100

    return False


def _is_diagram(element: Tag) -> bool:
    """Check if element is an ASCII diagram.

    Args:
        element: BeautifulSoup Tag to check

    Returns:
        True if element appears to be an ASCII diagram
    """
    tag_name = element.name.lower() if element.name else ""

    if tag_name != "pre":
        return False

    classes = set(_classes(element))
    if classes & DIAGRAM_CLASSES:
        return True

    # Heuristic: check for ASCII art patterns
    text = element.get_text()
    return bool(_looks_like_ascii_art(text))


def _looks_like_ascii_art(text: str) -> bool:
    """Check if text looks like ASCII art.

    Heuristics:
    - High ratio of box-drawing characters
    - Alignment with spaces
    - Common ASCII art patterns (+, |, -, arrows)

    Args:
        text: Text content to check

    Returns:
        True if text appears to be ASCII art
    """
    if not text or len(text) < 20:
        return False

    # Count box-drawing and arrow characters
    box_chars = set("+-|\\/*><^v[]{}()=_")
    box_count = sum(1 for c in text if c in box_chars)

    # Check ratio (ASCII art typically has high ratio)
    total_printable = sum(1 for c in text if c.isprintable() and not c.isspace())

    if total_printable == 0:
        return False

    box_ratio = box_count / total_printable

    # If box characters are >15% of content and there are multiple lines
    # with similar structure, likely ASCII art
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return False

    return box_ratio > 0.15 and box_count > 5


def _is_math(element: Tag) -> bool:
    """Check if element contains math content.

    Args:
        element: BeautifulSoup Tag to check

    Returns:
        True if element contains math
    """
    tag_name = element.name.lower() if element.name else ""

    # MathML
    if tag_name == "math":
        return True

    # Class-based detection
    classes = set(_classes(element))
    if classes & MATH_CLASSES:
        return True

    # Check for LaTeX delimiters in text
    text = element.get_text()
    return bool(
        LATEX_BLOCK_PATTERN.search(text)
        or (LATEX_INLINE_PATTERN.search(text) and tag_name in ("span", "div", "p"))
    )


def _detect_code_language(element: Tag) -> str | None:
    """Detect programming language from code block element.

    Checks:
    - class="language-python"
    - class="python"
    - data-lang="python"
    - data-language="python"

    Args:
        element: BeautifulSoup Tag to check

    Returns:
        Language string or None
    """
    # Check the element and its code child
    elements_to_check = [element]
    code_child = element.find("code")
    if code_child and isinstance(code_child, Tag):
        elements_to_check.append(code_child)

    for el in elements_to_check:
        # Check class attribute
        for cls in _classes(el):
            # language-python, lang-python
            if cls.startswith("language-") or cls.startswith("lang-"):
                return cls.split("-", 1)[1]
            # Direct language name as class
            if cls in _KNOWN_LANGUAGES:
                return cls

        # Check data attributes
        for attr in ("data-lang", "data-language", "data-code-language"):
            lang = el.get(attr)
            if lang:
                return str(lang).lower()

    return None
