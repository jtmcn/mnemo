"""Factory for creating test EPUB files."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ebooklib import epub


def create_test_epub(
    title: str = "Test Book",
    authors: list[str] | None = None,
    isbn: str | None = None,
    language: str = "en",
    chapters: list[dict[str, Any]] | None = None,
    output_path: Path | None = None,
    raw_creators: list[str] | None = None,
) -> Path:
    """Create a minimal test EPUB file.

    Args:
        title: Book title
        authors: List of author names (each becomes a separate dc:creator)
        isbn: ISBN identifier
        language: Book language code
        chapters: List of chapter dicts with 'title', 'content', and optional 'filename'
            and 'heading' (the h1 above the content; defaults to the title, "" for none)
        output_path: Where to save the EPUB (temp file if None)
        raw_creators: Raw dc:creator strings added as-is (bypasses add_author splitting).
            Use this to test semicolon-delimited author strings like "Smith; Jones".

    Returns:
        Path to the created EPUB file
    """
    if authors is None and raw_creators is None:
        authors = ["Test Author"]
    if chapters is None:
        chapters = [
            {
                "title": "Chapter 1",
                "content": "<p>This is the first chapter with some text content.</p>",
            }
        ]

    # Create EPUB book
    book = epub.EpubBook()

    # Set metadata
    book.set_identifier("test-book-id-12345")
    book.set_title(title)
    book.set_language(language)

    if raw_creators is not None:
        # Add raw creator strings as single dc:creator elements (no splitting)
        for raw in raw_creators:
            book.add_metadata("DC", "creator", raw)
    elif authors is not None:
        for author in authors:
            book.add_author(author)

    if isbn:
        # Add ISBN with proper OPF namespace scheme
        book.add_metadata(
            "DC",
            "identifier",
            isbn,
            {"id": "isbn", "{http://www.idpf.org/2007/opf}scheme": "ISBN"},
        )

    # Create chapters
    epub_chapters = []
    toc_items = []

    for i, ch in enumerate(chapters):
        ch_title = ch.get("title", f"Chapter {i + 1}")
        ch_content = ch.get("content", "<p>Default content</p>")
        ch_filename = ch.get("filename", f"chap_{i + 1:02d}.xhtml")
        ch_heading = ch.get("heading", ch_title)

        chapter = epub.EpubHtml(title=ch_title, file_name=ch_filename, lang=language)
        # Use set_content which properly encodes the content
        chapter.set_content(
            f"""<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{ch_title}</title></head>
<body>
{f"<h1>{ch_heading}</h1>" if ch_heading else ""}
{ch_content}
</body>
</html>""".encode()
        )

        book.add_item(chapter)
        epub_chapters.append(chapter)
        toc_items.append(chapter)

    # Set TOC and spine
    book.toc = toc_items
    book.spine = ["nav"] + epub_chapters

    # Add navigation files
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Determine output path
    if output_path is None:
        fd, path_str = tempfile.mkstemp(suffix=".epub")
        output_path = Path(path_str)
    else:
        output_path = Path(output_path)

    # Write EPUB
    epub.write_epub(str(output_path), book)

    return output_path


def create_epub_with_code(
    title: str = "Python Cookbook",
    author: str = "Test Author",
    output_path: Path | None = None,
) -> Path:
    """Create a test EPUB with code blocks in various formats.

    Includes:
    - Standard <pre><code> blocks
    - O'Reilly style (programlisting class)
    - Language-tagged blocks
    - Inline code

    Args:
        title: Book title
        author: Author name
        output_path: Where to save the EPUB

    Returns:
        Path to the created EPUB file
    """
    chapters = [
        {
            "title": "Introduction",
            "content": """
<p>Welcome to this programming book.</p>
<p>Here is some inline <code>code</code> in text.</p>
""",
        },
        {
            "title": "Basic Python",
            "content": """
<p>Let's look at a simple Python function:</p>
<pre><code class="language-python">
def hello_world():
    '''Print a greeting.'''
    print("Hello, World!")

if __name__ == "__main__":
    hello_world()
</code></pre>
<p>This function demonstrates basic Python syntax.</p>
""",
        },
        {
            "title": "Data Structures",
            "content": """
<p>Here's a table of common data structures:</p>
<table>
<tr><th>Structure</th><th>Lookup</th><th>Insert</th></tr>
<tr><td>List</td><td>O(n)</td><td>O(1)</td></tr>
<tr><td>Dict</td><td>O(1)</td><td>O(1)</td></tr>
<tr><td>Set</td><td>O(1)</td><td>O(1)</td></tr>
</table>
<p>And here's a code example with O'Reilly styling:</p>
<pre class="programlisting">
# Using a dictionary
data = {"key": "value"}
print(data["key"])
</pre>
""",
        },
        {
            "title": "Advanced Topics",
            "content": """
<p>ASCII diagrams can illustrate concepts:</p>
<pre class="ascii-diagram">
    +--------+     +--------+
    | Client | --> | Server |
    +--------+     +--------+
         |              |
         v              v
    +--------+     +--------+
    | Cache  |     |   DB   |
    +--------+     +--------+
</pre>
<p>Mathematical notation: The complexity is $O(n \\log n)$.</p>
""",
        },
    ]

    return create_test_epub(
        title=title,
        authors=[author],
        isbn="978-1-234-56789-0",
        chapters=chapters,
        output_path=output_path,
    )


def create_epub_with_front_matter(
    front_matter_items: list[dict[str, str]],
    output_path: Path | None = None,
) -> Path:
    """Create a test EPUB with spine-only front-matter items not in the TOC.

    Useful for testing PARSE-03: front-matter label inference for items that
    exist in the spine but are absent from the EPUB's NAV/NCX table of contents.

    Args:
        front_matter_items: List of dicts with 'filename' and 'content' keys.
            'filename' is the xhtml filename (e.g., "cover.xhtml"),
            'content' is the HTML body content.
        output_path: Where to save the EPUB (temp file if None)

    Returns:
        Path to the created EPUB file
    """
    book = epub.EpubBook()
    book.set_identifier("test-front-matter-epub-id")
    book.set_title("Front Matter Test Book")
    book.set_language("en")
    book.add_author("Test Author")

    # Create one normal chapter that will be in both spine and TOC
    normal_chapter = epub.EpubHtml(
        title="Chapter 1",
        file_name="chap_01.xhtml",
        lang="en",
    )
    normal_chapter.set_content(
        b"""<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter 1</title></head>
<body>
<h1>Chapter 1</h1>
<p>This is the first chapter.</p>
</body>
</html>"""
    )
    book.add_item(normal_chapter)

    # Create front-matter items (spine only, NOT in TOC)
    front_matter_epub_items = []
    for fm in front_matter_items:
        filename = fm["filename"]
        content_body = fm.get("content", "<p>Front matter content.</p>")
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename

        fm_item = epub.EpubHtml(
            title=stem.capitalize(),
            file_name=filename,
            lang="en",
        )
        fm_item.set_content(
            f"""<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{stem}</title></head>
<body>
{content_body}
</body>
</html>""".encode()
        )
        book.add_item(fm_item)
        front_matter_epub_items.append(fm_item)

    # TOC contains only the normal chapter (front-matter items are excluded)
    book.toc = [normal_chapter]

    # Spine: nav first, then front-matter items, then normal chapter
    book.spine = ["nav"] + front_matter_epub_items + [normal_chapter]

    # Add navigation files
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Determine output path
    if output_path is None:
        fd, path_str = tempfile.mkstemp(suffix=".epub")
        output_path = Path(path_str)
    else:
        output_path = Path(output_path)

    epub.write_epub(str(output_path), book)

    return output_path


def create_epub_with_nested_toc(output_path: Path | None = None, ncx_only: bool = False) -> Path:
    """Create an EPUB laid out like an MIT Press book: part > chapter > anchored sections.

    The chapter file opens with two h1s (number, then title) and its sections are
    TOC entries pointing at fragments inside that one file. One h4 is not in the TOC.
    """
    book = epub.EpubBook()
    book.set_identifier("test-nested-toc-epub-id")
    book.set_title("Nested TOC Book")
    book.set_language("en")
    book.add_author("Test Author")

    part = epub.EpubHtml(title="Part III", file_name="part_3.xhtml", lang="en")
    part.set_content(
        b"""<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Part III</title></head>
<body><h1>III Knowledge Graph Completion</h1><p>Part overview text.</p></body></html>"""
    )
    chapter = epub.EpubHtml(title="Chapter 8", file_name="chapter_8.xhtml", lang="en")
    chapter.set_content(
        b"""<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter 8</title></head>
<body><section>
<h1 class="chapter-number" id="ch8">8</h1>
<h1 class="chapter-title"><b>Instance Matching</b></h1>
<p>Chapter overview text.</p>
<section><h2><a id="sec8-1"/><b>8.1 Introduction</b></h2><p>Introduction text.</p></section>
<section><h2><a id="sec8-4"/><b>8.4 Two-Step Pipeline</b></h2><p>Pipeline text.</p>
<section><h3><a id="sec8-4-1"/><b>8.4.1 Blocking</b></h3><p>Blocking text.</p>
<h4>Sliding windows</h4><p>Sliding window text.</p></section>
</section>
<section><h2><a id="sec8-13"/><b>8.13 Exercises</b></h2><p>Exercise text.</p></section>
</section></body></html>"""
    )
    book.add_item(part)
    book.add_item(chapter)

    book.toc = [
        (
            epub.Section("III: Knowledge Graph Completion", href="part_3.xhtml"),
            [
                (
                    epub.Section("8. Instance Matching", href="chapter_8.xhtml"),
                    [
                        epub.Link("chapter_8.xhtml#sec8-1", "8.1. Introduction", "s81"),
                        (
                            epub.Section("8.4. Two Step Pipeline", href="chapter_8.xhtml#sec8-4"),
                            [epub.Link("chapter_8.xhtml#sec8-4-1", "8.4.1. Blocking", "s841")],
                        ),
                        epub.Link("chapter_8.xhtml#sec8-13", "8.13. Exercises", "s813"),
                    ],
                )
            ],
        )
    ]
    book.spine = [part, chapter] if ncx_only else ["nav", part, chapter]
    book.add_item(epub.EpubNcx())
    if not ncx_only:
        book.add_item(epub.EpubNav())

    if output_path is None:
        fd, path_str = tempfile.mkstemp(suffix=".epub")
        output_path = Path(path_str)
    epub.write_epub(str(output_path), book)
    return output_path


TocEntry = tuple[str, str, list["TocEntry"]]


def create_epub_from_toc(output_path: Path, files: dict[str, str], toc: list[TocEntry]) -> Path:
    """An EPUB of the given file bodies (spine in dict order) and a (title, href, children) TOC."""
    book = epub.EpubBook()
    book.set_identifier("test-toc-shape-epub-id")
    book.set_title("TOC Shape Book")
    book.set_language("en")
    book.add_author("Test Author")

    items = []
    for name, body in files.items():
        item = epub.EpubHtml(title=name, file_name=name, lang="en")
        item.set_content(
            f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{name}</title></head>'
            f"<body>{body}</body></html>".encode()
        )
        book.add_item(item)
        items.append(item)

    def _entries(entries: list[TocEntry]) -> list[Any]:
        return [
            (epub.Section(title, href=href), _entries(children))
            if children
            else epub.Link(href, title, f"toc{abs(hash((title, href)))}")
            for title, href, children in entries
        ]

    book.toc = _entries(toc)
    book.spine = ["nav", *items]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(output_path), book)
    return output_path
