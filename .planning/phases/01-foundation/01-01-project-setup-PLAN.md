---
phase: 01-foundation
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - src/mnemo/__init__.py
  - src/mnemo/models.py
  - tests/__init__.py
autonomous: true

must_haves:
  truths:
    - "Package installs successfully with pip install -e ."
    - "Core data models define all content types"
    - "Models support linked chunk references"
  artifacts:
    - path: "pyproject.toml"
      provides: "Package configuration with dependencies"
      contains: "ebooklib"
    - path: "src/mnemo/models.py"
      provides: "Book, Chunk, ContentType definitions"
      exports: ["Book", "Chunk", "ContentType"]
  key_links:
    - from: "pyproject.toml"
      to: "src/mnemo"
      via: "package discovery"
      pattern: "packages.*mnemo"
---

<objective>
Set up Python project structure and define core data models.

Purpose: Establish the foundation that all other plans depend on — package structure for imports, and data models that shape how content flows through the system.

Output: Installable Python package with Book, Chunk, and ContentType models.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phases/01-foundation/01-CONTEXT.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create Python package with dependencies</name>
  <files>pyproject.toml, src/mnemo/__init__.py, tests/__init__.py</files>
  <action>
Create pyproject.toml with:
- Project name: mnemo
- Python version: >=3.11
- Dependencies:
  - ebooklib (EPUB parsing)
  - beautifulsoup4 + lxml (HTML parsing)
  - tiktoken (token counting for chunking)
  - pydantic>=2.0 (data models)
- Dev dependencies:
  - pytest
  - pytest-cov
- Build system: hatchling (modern, simple)
- Entry point placeholder: mnemo.cli:main

Create src/mnemo/__init__.py with version = "0.1.0"
Create tests/__init__.py (empty)
Create src/mnemo/py.typed marker file (for type checking)
  </action>
  <verify>Run: pip install -e ".[dev]" && python -c "import mnemo; print(mnemo.__version__)"</verify>
  <done>Package installs without errors, version prints "0.1.0"</done>
</task>

<task type="auto">
  <name>Task 2: Define core data models</name>
  <files>src/mnemo/models.py</files>
  <action>
Create Pydantic models capturing all Phase 1 data structures:

1. ContentType enum with 5 values:
   - TEXT, CODE, DIAGRAM, MATH, TABLE

2. Book model with fields:
   - id: str (6-char hex hash, generated from content)
   - title: str
   - authors: list[str]
   - isbn: str | None
   - file_hash: str (full SHA256 for deduplication)
   - default_language: str | None (for code blocks without explicit lang)
   - structure_source: Literal["toc", "inferred"]
   - added_at: datetime

3. Chunk model with fields:
   - id: str (UUID)
   - book_id: str (references Book.id)
   - content: str (full text for FTS)
   - content_type: ContentType
   - token_count: int
   - section_path: list[str] (e.g., ["Part I", "Chapter 3", "Error Handling"])
   - sections: list[str] (for boundary-spanning chunks)
   - language: str | None (for code chunks)
   - sequence: int (ordering within book)
   - prev_chunk_id: str | None (for prose-code linking)
   - next_chunk_id: str | None (for prose-code linking)

Add helper methods:
- Book.generate_id(content_bytes, title, author) -> str (6-char hash)
- Book.from_metadata(title, authors, isbn, file_hash, ...) -> Book
- Chunk.is_code property -> bool (checks content_type == CODE)

Use Pydantic's model_validator for any cross-field validation.
  </action>
  <verify>Run: python -c "from mnemo.models import Book, Chunk, ContentType; print(ContentType.CODE)"</verify>
  <done>All models import successfully, ContentType.CODE prints correctly</done>
</task>

</tasks>

<verification>
```bash
# Full verification sequence
pip install -e ".[dev]"
python -c "import mnemo; print(f'Version: {mnemo.__version__}')"
python -c "from mnemo.models import Book, Chunk, ContentType; print('Models OK')"
python -c "from mnemo.models import ContentType; assert len(ContentType) == 5"
pytest --collect-only  # Should find test directory
```
</verification>

<success_criteria>
1. `pip install -e .` succeeds without errors
2. `import mnemo` works from any directory
3. All 5 ContentType values accessible
4. Book and Chunk models validate correctly
5. Book.generate_id produces 6-character hex string
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-01-SUMMARY.md`
</output>
