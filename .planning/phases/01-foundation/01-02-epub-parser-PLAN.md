---
phase: 01-foundation
plan: 02
type: execute
wave: 2
depends_on: ["01-01"]
files_modified:
  - src/mnemo/epub/__init__.py
  - src/mnemo/epub/parser.py
  - src/mnemo/epub/metadata.py
  - src/mnemo/epub/content.py
  - tests/test_epub_parser.py
autonomous: true

must_haves:
  truths:
    - "Parser extracts all text content from EPUB"
    - "Chapter hierarchy is preserved from TOC"
    - "Code blocks are detected and tagged"
    - "Dublin Core metadata is extracted"
    - "Tables are converted to searchable text"
  artifacts:
    - path: "src/mnemo/epub/parser.py"
      provides: "Main EPUBParser class"
      exports: ["EPUBParser"]
    - path: "src/mnemo/epub/metadata.py"
      provides: "Dublin Core extraction"
      exports: ["extract_metadata"]
    - path: "src/mnemo/epub/content.py"
      provides: "Content type detection and extraction"
      exports: ["extract_content", "ContentBlock"]
  key_links:
    - from: "src/mnemo/epub/parser.py"
      to: "src/mnemo/models.py"
      via: "Book model import"
      pattern: "from mnemo.models import"
    - from: "src/mnemo/epub/content.py"
      to: "ContentType"
      via: "content type assignment"
      pattern: "ContentType\\.(TEXT|CODE|TABLE|DIAGRAM|MATH)"
---

<objective>
Build EPUB parser that extracts structured content with hierarchy and content type detection.

Purpose: Transform raw EPUB files into structured data (chapters, sections, code blocks, tables) that the chunker can process intelligently.

Output: EPUBParser class that produces Book metadata and list of ContentBlock items with section paths.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phases/01-foundation/01-CONTEXT.md
@.planning/phases/01-foundation/01-01-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Implement metadata extraction</name>
  <files>src/mnemo/epub/__init__.py, src/mnemo/epub/metadata.py</files>
  <action>
Create src/mnemo/epub/__init__.py that exports parser components.

Create metadata.py with extract_metadata function:

1. Use ebooklib to read EPUB file
2. Extract Dublin Core metadata:
   - dc:title -> title
   - dc:creator -> authors (multiple allowed)
   - dc:identifier with ISBN scheme -> isbn
   - dc:language -> for default_language hint
3. Handle missing metadata:
   - If no title: use filename (without .epub extension)
   - If no authors: use ["Unknown"]
   - Log warning when using fallbacks
4. Compute file_hash:
   - SHA256 of entire EPUB file content
5. Generate book_id:
   - Use Book.generate_id() from models
6. Return populated Book model (without structure_source yet - that comes from TOC parsing)

Key edge cases:
- Multiple dc:creator entries -> list of authors
- ISBN in various formats (ISBN-10, ISBN-13, URN) -> normalize
- Non-ASCII characters in metadata -> handle UTF-8
  </action>
  <verify>
Create a minimal test EPUB or use a fixture:
```python
from mnemo.epub.metadata import extract_metadata
book = extract_metadata("test.epub")
assert book.title and book.file_hash
```
  </verify>
  <done>extract_metadata returns Book model with title, authors, isbn (if present), file_hash, and id</done>
</task>

<task type="auto">
  <name>Task 2: Implement content extraction with type detection</name>
  <files>src/mnemo/epub/content.py</files>
  <action>
Create content.py with ContentBlock dataclass and extraction logic:

1. ContentBlock dataclass (intermediate representation):
   - content: str
   - content_type: ContentType
   - section_path: list[str]
   - language: str | None (for code)
   - source_file: str (EPUB item href)

2. extract_content(epub_book, toc) function:
   - Iterate through EPUB items in spine order
   - Parse HTML with BeautifulSoup (lxml parser)
   - Track current section_path from TOC mapping
   - Detect and extract content types:

Content type detection rules:
- CODE: <pre>, <code>, class contains "highlight", "sourceCode", "listing"
  - Language from: class="language-python", data-lang="python", or book default
  - Preserve exact whitespace and indentation
- TABLE: <table> tags
  - Convert to pipe-separated text for searchability
  - Format: "| col1 | col2 |\n| val1 | val2 |"
- DIAGRAM: <pre> with class containing "ascii", "diagram", or content matching ASCII art heuristics
- MATH: <math>, class="equation", or LaTeX delimiters ($...$, \[...\])
  - Preserve raw notation
- TEXT: everything else (paragraphs, lists, etc.)
  - Strip HTML tags, normalize whitespace

3. Handle publisher quirks:
   - O'Reilly: programlisting, screen classes
   - Pragmatic: code, livecodelozenge classes
   - Manning: listingblock class
   - Generic: pre > code pattern

Output: List of ContentBlock in document order, each with detected type and section path.
  </action>
  <verify>Test with sample HTML containing code blocks, tables, and prose to verify correct type detection.</verify>
  <done>extract_content returns ContentBlock list with correct content_type assignments</done>
</task>

<task type="auto">
  <name>Task 3: Implement TOC parsing and main parser class</name>
  <files>src/mnemo/epub/parser.py, tests/test_epub_parser.py</files>
  <action>
Create parser.py with EPUBParser class:

1. TOC parsing (private method):
   - Try EPUB3 nav document first (preferred)
   - Fall back to EPUB2 NCX toc
   - Build section_path mapping: {item_href: ["Part", "Chapter", "Section"]}
   - If both fail: infer from HTML headings (h1-h6) and set structure_source="inferred"
   - Warn user if using inferred structure

2. Heading inference (fallback):
   - Parse h1-h6 tags in document order
   - Build hierarchy based on heading level
   - h1 = top level, h2 = second level, etc.

3. EPUBParser class:
   ```python
   class EPUBParser:
       def parse(self, epub_path: Path) -> tuple[Book, list[ContentBlock]]:
           """Parse EPUB and return Book metadata + content blocks."""
   ```
   - Validate file exists and is valid EPUB
   - Call metadata extraction
   - Parse TOC to get structure and section mapping
   - Extract content with section paths
   - Return (Book, list[ContentBlock])

4. Create tests/test_epub_parser.py:
   - Test metadata extraction with mock EPUB
   - Test content type detection with HTML fixtures
   - Test TOC parsing with both EPUB2/EPUB3 fixtures
   - Test heading inference fallback
  </action>
  <verify>pytest tests/test_epub_parser.py -v</verify>
  <done>EPUBParser.parse() returns Book + ContentBlocks with hierarchy preserved and content types detected</done>
</task>

</tasks>

<verification>
```bash
# Unit tests pass
pytest tests/test_epub_parser.py -v

# Import check
python -c "from mnemo.epub import EPUBParser; print('Parser OK')"

# Quick functional test (if sample EPUB available)
python -c "
from pathlib import Path
from mnemo.epub import EPUBParser
parser = EPUBParser()
# Would test with: book, blocks = parser.parse(Path('sample.epub'))
print('Parser class instantiates OK')
"
```
</verification>

<success_criteria>
1. EPUBParser.parse() returns (Book, list[ContentBlock])
2. Book has all Dublin Core metadata that exists in EPUB
3. ContentBlocks have correct content_type (CODE for code, TABLE for tables, etc.)
4. section_path reflects TOC hierarchy (or inferred from headings)
5. Code blocks preserve original formatting and indentation
6. Tables converted to searchable text format
7. All unit tests pass
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-02-SUMMARY.md`
</output>
