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

        chapter = epub.EpubHtml(title=ch_title, file_name=ch_filename, lang=language)
        # Use set_content which properly encodes the content
        chapter.set_content(f"""<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{ch_title}</title></head>
<body>
<h1>{ch_title}</h1>
{ch_content}
</body>
</html>""".encode("utf-8"))

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
</html>""".encode("utf-8")
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
