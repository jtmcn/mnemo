---
phase: 01-foundation
plan: 05
type: execute
wave: 4
depends_on: ["01-02", "01-03", "01-04"]
files_modified:
  - src/mnemo/ingest.py
  - tests/fixtures/sample.epub
  - tests/test_integration.py
autonomous: false

must_haves:
  truths:
    - "EPUB file flows through parser -> chunker -> storage"
    - "Stored chunks are searchable via FTS"
    - "Removing book removes all chunks"
    - "Code blocks in result match original formatting"
  artifacts:
    - path: "src/mnemo/ingest.py"
      provides: "End-to-end ingestion pipeline"
      exports: ["ingest_book"]
    - path: "tests/fixtures/sample.epub"
      provides: "Test EPUB for integration testing"
    - path: "tests/test_integration.py"
      provides: "End-to-end tests"
  key_links:
    - from: "src/mnemo/ingest.py"
      to: "src/mnemo/epub/parser.py"
      via: "EPUBParser import"
      pattern: "from mnemo.epub import EPUBParser"
    - from: "src/mnemo/ingest.py"
      to: "src/mnemo/chunking/chunker.py"
      via: "Chunker import"
      pattern: "from mnemo.chunking import Chunker"
    - from: "src/mnemo/ingest.py"
      to: "src/mnemo/storage/repository.py"
      via: "Repository imports"
      pattern: "from mnemo.storage import"
---

<objective>
Wire all components together and verify end-to-end functionality with real EPUB.

Purpose: Ensure parser, chunker, and storage work together correctly. This is the integration point that validates Phase 1 delivers on its promise.

Output: Working ingest_book function and passing integration tests.
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
@.planning/phases/01-foundation/01-02-SUMMARY.md
@.planning/phases/01-foundation/01-03-SUMMARY.md
@.planning/phases/01-foundation/01-04-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create test EPUB fixture</name>
  <files>tests/fixtures/sample.epub</files>
  <action>
Create a minimal but realistic test EPUB programmatically using ebooklib:

```python
# Script to generate tests/fixtures/sample.epub
from ebooklib import epub
import os

book = epub.EpubBook()

# Metadata
book.set_identifier('test-book-001')
book.set_title('Python Testing Guide')
book.set_language('en')
book.add_author('Test Author')
book.add_metadata('DC', 'identifier', '978-1234567890', {'id': 'isbn', 'scheme': 'ISBN'})

# Chapter 1: Introduction (prose)
c1 = epub.EpubHtml(title='Introduction', file_name='ch1.xhtml', lang='en')
c1.content = '''
<html><body>
<h1>Chapter 1: Introduction</h1>
<p>This book covers Python testing practices.</p>
<h2>1.1 Why Testing Matters</h2>
<p>Testing ensures code quality and prevents regressions.</p>
</body></html>
'''

# Chapter 2: Code Examples (with code blocks)
c2 = epub.EpubHtml(title='Code Examples', file_name='ch2.xhtml', lang='en')
c2.content = '''
<html><body>
<h1>Chapter 2: Code Examples</h1>
<p>Here is a simple test function:</p>
<pre class="sourceCode python"><code>def test_addition():
    assert 1 + 1 == 2
    assert 2 + 2 == 4

def test_subtraction():
    assert 5 - 3 == 2
    assert 10 - 7 == 3</code></pre>
<p>This test verifies basic arithmetic operations.</p>

<h2>2.1 Tables in Documentation</h2>
<table>
<tr><th>Function</th><th>Purpose</th></tr>
<tr><td>assertEqual</td><td>Check equality</td></tr>
<tr><td>assertTrue</td><td>Check boolean</td></tr>
</table>
</body></html>
'''

# Chapter 3: Long prose (for chunking test)
long_prose = " ".join(["This is paragraph content for testing chunking behavior."] * 100)
c3 = epub.EpubHtml(title='Best Practices', file_name='ch3.xhtml', lang='en')
c3.content = f'''
<html><body>
<h1>Chapter 3: Best Practices</h1>
<p>{long_prose}</p>
</body></html>
'''

book.add_item(c1)
book.add_item(c2)
book.add_item(c3)

# Table of contents
book.toc = [
    epub.Link('ch1.xhtml', 'Introduction', 'intro'),
    epub.Link('ch2.xhtml', 'Code Examples', 'code'),
    epub.Link('ch3.xhtml', 'Best Practices', 'best'),
]

# Spine
book.add_item(epub.EpubNcx())
book.add_item(epub.EpubNav())
book.spine = ['nav', c1, c2, c3]

# Write
os.makedirs('tests/fixtures', exist_ok=True)
epub.write_epub('tests/fixtures/sample.epub', book)
```

Run this script to generate the fixture file. The EPUB should contain:
- Dublin Core metadata (title, author, ISBN)
- TOC with 3 chapters
- Chapter 1: Pure prose
- Chapter 2: Prose + code block + table
- Chapter 3: Long prose (triggers chunking)
  </action>
  <verify>
```bash
python -c "
from ebooklib import epub
book = epub.read_epub('tests/fixtures/sample.epub')
print(f'Title: {book.get_metadata(\"DC\", \"title\")}')
print(f'Items: {len(list(book.get_items()))}')
"
```
  </verify>
  <done>tests/fixtures/sample.epub exists with metadata, TOC, prose, code, and table content</done>
</task>

<task type="auto">
  <name>Task 2: Implement ingest pipeline</name>
  <files>src/mnemo/ingest.py</files>
  <action>
Create ingest.py that wires all components:

```python
from pathlib import Path
from mnemo.epub import EPUBParser
from mnemo.chunking import Chunker, ChunkerConfig
from mnemo.storage import init_db, get_connection, BookRepository, ChunkRepository
from mnemo.models import Book

def ingest_book(
    epub_path: Path,
    db_path: Path | None = None,
    chunker_config: ChunkerConfig | None = None,
    force: bool = False
) -> tuple[Book, int]:
    """
    Ingest an EPUB file into the database.

    Args:
        epub_path: Path to EPUB file
        db_path: Database path (default: ~/.mnemo/mnemo.db)
        chunker_config: Chunking configuration
        force: If True, re-ingest even if duplicate detected

    Returns:
        Tuple of (Book, chunk_count)

    Raises:
        FileNotFoundError: EPUB doesn't exist
        ValueError: Duplicate book (unless force=True)
    """
    # 1. Validate input
    if not epub_path.exists():
        raise FileNotFoundError(f"EPUB not found: {epub_path}")

    # 2. Initialize database
    init_db(db_path)
    conn = get_connection(db_path)
    book_repo = BookRepository(conn)
    chunk_repo = ChunkRepository(conn)

    # 3. Parse EPUB
    parser = EPUBParser()
    book, content_blocks = parser.parse(epub_path)

    # 4. Check for duplicate
    existing = book_repo.get_by_hash(book.file_hash)
    if existing and not force:
        raise ValueError(f"Book already indexed (id: {existing.id}). Use force=True to re-index.")

    # 5. If force and exists, delete old version
    if existing and force:
        book_repo.delete(existing.id)

    # 6. Chunk content
    chunker = Chunker(chunker_config)
    chunks = chunker.chunk(book.id, content_blocks)

    # 7. Store
    book_repo.add(book)
    chunk_repo.add_many(chunks)
    conn.commit()

    return book, len(chunks)


def remove_book(book_id: str, db_path: Path | None = None) -> bool:
    """
    Remove a book and all its chunks.

    Returns True if book was found and removed, False if not found.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    book_repo = BookRepository(conn)

    result = book_repo.delete(book_id)
    conn.commit()
    return result
```

Key behaviors:
- Duplicate detection by file_hash
- Force flag to re-ingest
- Returns book and chunk count for feedback
- remove_book leverages cascade delete
  </action>
  <verify>
```python
from pathlib import Path
import tempfile
from mnemo.ingest import ingest_book, remove_book

with tempfile.TemporaryDirectory() as td:
    db_path = Path(td) / "test.db"
    epub_path = Path("tests/fixtures/sample.epub")

    book, count = ingest_book(epub_path, db_path)
    print(f"Ingested: {book.title} with {count} chunks")
```
  </verify>
  <done>ingest_book successfully parses, chunks, and stores EPUB content</done>
</task>

<task type="auto">
  <name>Task 3: Create integration tests</name>
  <files>tests/test_integration.py</files>
  <action>
Create comprehensive integration tests:

```python
import pytest
from pathlib import Path
import tempfile
from mnemo.ingest import ingest_book, remove_book
from mnemo.storage import get_connection, BookRepository, ChunkRepository, init_db
from mnemo.models import ContentType

@pytest.fixture
def sample_epub():
    return Path("tests/fixtures/sample.epub")

@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "test.db"

class TestIngestion:
    def test_ingest_creates_book_and_chunks(self, sample_epub, temp_db):
        book, count = ingest_book(sample_epub, temp_db)

        assert book.id is not None
        assert book.title == "Python Testing Guide"
        assert "Test Author" in book.authors
        assert count > 0

    def test_ingest_duplicate_raises_error(self, sample_epub, temp_db):
        ingest_book(sample_epub, temp_db)

        with pytest.raises(ValueError, match="already indexed"):
            ingest_book(sample_epub, temp_db)

    def test_ingest_force_replaces_book(self, sample_epub, temp_db):
        book1, _ = ingest_book(sample_epub, temp_db)
        book2, _ = ingest_book(sample_epub, temp_db, force=True)

        # Same content, same ID
        assert book1.id == book2.id

    def test_chunks_have_correct_types(self, sample_epub, temp_db):
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)

        types = {c.content_type for c in chunks}
        assert ContentType.TEXT in types
        assert ContentType.CODE in types
        assert ContentType.TABLE in types

    def test_code_blocks_preserved(self, sample_epub, temp_db):
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)
        chunks = chunk_repo.get_by_book(book.id)

        code_chunks = [c for c in chunks if c.content_type == ContentType.CODE]
        assert len(code_chunks) >= 1

        # Verify indentation preserved
        for chunk in code_chunks:
            assert "    " in chunk.content  # 4-space indent


class TestFTS:
    def test_search_finds_content(self, sample_epub, temp_db):
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        results = chunk_repo.search_fts("testing")
        assert len(results) > 0

    def test_search_filter_by_type(self, sample_epub, temp_db):
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        results = chunk_repo.search_fts("test", content_type=ContentType.CODE)
        assert all(r.content_type == ContentType.CODE for r in results)


class TestRemoval:
    def test_remove_book_cascades_chunks(self, sample_epub, temp_db):
        book, _ = ingest_book(sample_epub, temp_db)

        conn = get_connection(temp_db)
        chunk_repo = ChunkRepository(conn)

        # Chunks exist
        assert chunk_repo.count_by_book(book.id) > 0

        # Remove book
        remove_book(book.id, temp_db)

        # Chunks gone
        assert chunk_repo.count_by_book(book.id) == 0
```
  </action>
  <verify>pytest tests/test_integration.py -v</verify>
  <done>All integration tests pass, validating end-to-end pipeline</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>Complete Phase 1 foundation: EPUB parsing, smart chunking, and SQLite storage with FTS</what-built>
  <how-to-verify>
1. Run full test suite:
   ```bash
   pytest tests/ -v
   ```

2. Test with the sample EPUB:
   ```bash
   python -c "
   from pathlib import Path
   import tempfile
   from mnemo.ingest import ingest_book
   from mnemo.storage import get_connection, ChunkRepository
   from mnemo.models import ContentType

   with tempfile.TemporaryDirectory() as td:
       db_path = Path(td) / 'test.db'
       book, count = ingest_book(Path('tests/fixtures/sample.epub'), db_path)
       print(f'Book: {book.title}')
       print(f'Authors: {book.authors}')
       print(f'Chunks: {count}')

       conn = get_connection(db_path)
       repo = ChunkRepository(conn)

       # Show content type distribution
       chunks = repo.get_by_book(book.id)
       from collections import Counter
       types = Counter(c.content_type.value for c in chunks)
       print(f'Content types: {dict(types)}')

       # Test FTS
       results = repo.search_fts('testing')
       print(f'FTS results for \"testing\": {len(results)} chunks')

       # Show a code chunk
       code = [c for c in chunks if c.content_type == ContentType.CODE]
       if code:
           print(f'\\nSample code chunk:\\n{code[0].content[:200]}...')
   "
   ```

3. Verify code block integrity (critical):
   - Check that code chunks have proper indentation
   - Verify no code was split mid-function

4. Verify section paths are populated (not empty arrays)
  </how-to-verify>
  <resume-signal>Type "approved" if all tests pass and output looks correct, or describe issues</resume-signal>
</task>

</tasks>

<verification>
```bash
# Full test suite
pytest tests/ -v --tb=short

# Coverage check
pytest tests/ --cov=mnemo --cov-report=term-missing
```
</verification>

<success_criteria>
1. All unit tests pass (parser, chunker, storage)
2. All integration tests pass
3. Sample EPUB ingests successfully
4. Code blocks maintain formatting
5. FTS search returns relevant results
6. Book removal cascades to chunks
7. Human verification approves the implementation
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-05-SUMMARY.md`
</output>
