# Phase 10: Parser Quality Fixes - Research

**Researched:** 2026-03-12
**Domain:** EPUB parsing, HTML text extraction, metadata normalization
**Confidence:** HIGH

## Summary

Phase 10 fixes three discrete bugs in the EPUB parsing pipeline, all isolated to
`src/mnemo/epub/content.py` and `src/mnemo/epub/metadata.py`. No new dependencies
are introduced; all fixes use the existing BeautifulSoup and standard Python tools.

The word-joining bug (PARSE-01) is caused by a single line in `_extract_blocks_from_element`:
when non-block HTML elements (e.g., `<p>`) fall through to the catch-all branch at line 327,
`child.get_text(strip=True)` strips all internal whitespace between inline child elements,
merging adjacent `<span>` or `<em>` content into a single word. The fix is replacing
`strip=True` with `separator=' ', strip=True` on that call.

The author garbling bug (PARSE-02) occurs when publishers encode multiple authors in a single
`dc:creator` element separated by semicolons rather than using multiple elements. The current
code returns the raw string as a single author. The fix is a post-processing pass in
`_extract_authors` that splits each creator string on semicolons and removes empty parts.

The "Unknown section" bug (PARSE-03) occurs because front-matter spine items (cover, TOC,
copyright pages) are not listed in the EPUB's TOC/NCX and contain no heading tags. The fix
adds a filename-based heuristic lookup (`FRONT_MATTER_STEMS`) in `extract_content` that
maps known stem names to human-readable labels before falling back to empty section_path.

**Primary recommendation:** Three targeted, low-risk fixes — one per requirement — all in
the epub parsing layer. Each fix is independently testable and has no downstream side effects
when gated correctly by content type.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PARSE-01 | EPUB text extraction preserves word boundaries across inline HTML elements | Fix is in `_extract_blocks_from_element` line 327: `get_text(separator=' ', strip=True)` instead of `get_text(strip=True)` |
| PARSE-02 | Author names are split on semicolons and cleaned of trailing delimiters | Fix is in `_extract_authors` in `metadata.py`: post-process each creator string with `.split(';')` |
| PARSE-03 | Front-matter and TOC content gets a descriptive section label instead of "Unknown section" | Fix is in `extract_content` in `content.py`: add `FRONT_MATTER_STEMS` lookup when `toc_mapping.get(href, [])` returns empty |
</phase_requirements>

---

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| BeautifulSoup4 | current | HTML parsing | Already used throughout epub module |
| ebooklib | current | EPUB reading | Already used throughout epub module |
| lxml | current | HTML parser backend | Already configured in BeautifulSoup calls |
| pytest | current | Test framework | Project standard |

### No New Dependencies
All three fixes are achievable with the existing stack. This is explicitly listed in
REQUIREMENTS.md under "Out of Scope: New dependencies — All features achievable with
current stack."

**Installation:** None required.

## Architecture Patterns

### Fix Locations (all in epub module)

```
src/mnemo/epub/
├── content.py      # PARSE-01 fix (line 327), PARSE-03 fix (extract_content)
└── metadata.py     # PARSE-02 fix (_extract_authors)
```

### Pattern 1: PARSE-01 — Inline Element Word Boundary Fix

**What:** Replace `get_text(strip=True)` with `get_text(separator=' ', strip=True)` in
the catch-all branch of `_extract_blocks_from_element`.

**Root cause:** In `content.py` line 327, the catch-all branch processes any element
not recognized as a heading, code block, diagram, table, math, or block container.
This catches `<p>`, `<li>`, `<span>`, `<em>`, `<strong>` etc. When these elements
contain adjacent inline children with no whitespace NavigableString between them,
`get_text(strip=True)` concatenates their text directly, e.g., `<span>a</span><span>strategy</span>`
becomes `"astrategy"`.

**The fix:**
```python
# Before (line 327 in _extract_blocks_from_element):
text = child.get_text(strip=True)

# After:
text = child.get_text(separator=" ", strip=True)
```

`separator=" "` inserts a space between all text nodes. `_normalize_text` then
collapses any double-spaces with `re.sub(r"\s+", " ", text)`. No other changes needed.

**Scope:** Only the catch-all branch (line 327). The explicit code-block, table, diagram,
and math branches already handle their content correctly and must not be changed.

### Pattern 2: PARSE-02 — Author Semicolon Splitting Fix

**What:** Post-process each raw creator string in `_extract_authors` to split on
semicolons and strip empty parts.

**Root cause:** Some publishers (notably O'Reilly and Packt) encode multiple authors in a
single `dc:creator` element: `"Smith, Alice; Jones, Bob;"`. The current code treats this
as a single author string.

**The fix in `metadata.py`:**
```python
def _extract_authors(epub_book: epub.EpubBook) -> list[str]:
    creators = epub_book.get_metadata("DC", "creator")
    if creators:
        raw_authors = [str(c[0]).strip() for c in creators if c and c[0]]
        authors: list[str] = []
        for raw in raw_authors:
            # Split on semicolons; handles "Smith; Jones;" and "Smith, Alice; Jones, Bob;"
            parts = [p.strip() for p in raw.split(";")]
            authors.extend(p for p in parts if p)
        if authors:
            return authors

    logger.warning("Missing author metadata. Using 'Unknown'")
    return ["Unknown"]
```

**Edge cases handled:**
- `"Alice Smith"` — no semicolons, passes through unchanged
- `"Alice Smith;"` — trailing semicolon, empty part filtered out
- `"Smith, Alice; Jones, Bob;"` — splits to `["Smith, Alice", "Jones, Bob"]`
- Multiple separate `dc:creator` elements — each processed individually
- Semicolons in "Last, First" format — split only on semicolons, not commas

**Note on book_id stability:** STATE.md documents that author normalization may change
`book_id` on re-index because the hash includes `primary_author`. This is acceptable
behavior — document it in release notes.

### Pattern 3: PARSE-03 — Front-Matter Section Labels

**What:** Add a `FRONT_MATTER_STEMS` mapping in `content.py` and apply it in
`extract_content` when a spine item has no TOC mapping.

**Root cause:** Front-matter items (cover page, TOC, copyright, title page, etc.) exist
in the spine but are typically absent from the EPUB's NAV/NCX table of contents. When
`toc_mapping.get(href, [])` returns `[]`, these items are stored with `section_path=[]`
which displays as "Unknown section" in search results.

**New constant in `content.py`:**
```python
# Maps filename stems to human-readable front-matter labels
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
```

**New helper in `content.py`:**
```python
def _infer_front_matter_label(href: str) -> list[str] | None:
    """Infer a section label for unmapped spine items via filename heuristics.

    Tries exact stem match, then prefix/suffix matching against FRONT_MATTER_STEMS.
    Returns None if no match found (content remains unlabeled).

    Args:
        href: EPUB item href (e.g., "OEBPS/cover.xhtml", "preface_01.xhtml")

    Returns:
        Single-element section path or None
    """
    stem = Path(href).stem.lower()
    # Exact match
    if stem in FRONT_MATTER_STEMS:
        return [FRONT_MATTER_STEMS[stem]]
    # Prefix/suffix match (e.g., "preface_01", "cover2")
    for key, label in FRONT_MATTER_STEMS.items():
        if stem.startswith(key) or stem.endswith(key):
            return [label]
    return None
```

**Modified `extract_content` loop:**
```python
section_path = toc_mapping.get(href, [])

# PARSE-03: infer label for front-matter items not in TOC
if not section_path:
    inferred = _infer_front_matter_label(href)
    if inferred:
        section_path = inferred
```

**STATE.md note:** "Validate `FRONT_MATTER_STEMS` heuristic set against actual EPUBs in
the library before finalizing — publisher-specific naming may require additions." The
planner should include a task to verify against real books and expand the set as needed.

### Anti-Patterns to Avoid

- **Do not apply word-boundary fix to the code block, diagram, math, or table branches** — those extract content by type-specific methods that already handle whitespace correctly.
- **Do not use `soup.get_text(separator=' ')` on the whole body** — the existing recursive block structure is what enables type detection. A flat get_text call would lose all content-type information.
- **Do not normalize whitespace in `_extract_code_block`** — `code_element.get_text()` (no strip, no separator) already preserves indentation correctly. The chunker passes CODE blocks through as atomic units without normalization. This is already working correctly.
- **Do not split author names on commas** — "Last, First" is a valid author format. Only semicolons are inter-author delimiters.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Text separation in HTML | Custom whitespace scanner | `get_text(separator=' ')` | BeautifulSoup's built-in separator handles all text nodes correctly |
| Author string parsing | Regex-based parser | `str.split(';')` + list comprehension | Semicolons are the only delimiter in use |
| Stem matching | Fuzzy string matching library | Direct dict lookup + startswith/endswith | Sufficient precision for known front-matter names |

**Key insight:** All three bugs are single-line or small-function fixes. Any solution that
requires a new module, new class, or external library is over-engineered for this scope.

## Common Pitfalls

### Pitfall 1: Over-applying the separator fix
**What goes wrong:** Adding `separator=' '` to `get_text()` in the code/diagram/math branches
**Why it happens:** Trying to apply the fix uniformly
**How to avoid:** Only modify line 327 (the catch-all else branch). Code blocks must use
`get_text()` with no separator to preserve literal whitespace/indentation.
**Warning signs:** Tests for code indentation preservation fail after the fix

### Pitfall 2: Book ID change on re-ingest
**What goes wrong:** After PARSE-02, authors are stored differently, changing `book_id`
**Why it happens:** `book_id` is a SHA256 hash that includes `primary_author`
**How to avoid:** Document this behavior; existing books are unaffected unless re-ingested
with `--force`
**Warning signs:** Integration test for update book shows different ID after re-ingest

### Pitfall 3: FRONT_MATTER_STEMS incomplete for actual library
**What goes wrong:** Real EPUBs use publisher-specific naming not in the stems dict
**Why it happens:** Publishers use arbitrary filenames (e.g., "fm01.xhtml", "pref.xhtml")
**How to avoid:** Test against actual EPUBs in the library; add stems as discovered
**Warning signs:** Front-matter items still labeled "Unknown section" after fix

### Pitfall 4: Separator fix introduces double-spaces in text
**What goes wrong:** `get_text(separator=' ')` on an element with NavigableString spaces
already present creates "word  word" with double spaces
**Why it happens:** Separator adds space AND existing whitespace from the original HTML
**How to avoid:** `_normalize_text` already uses `re.sub(r"\s+", " ", text)` which
collapses all multi-space sequences. No extra handling needed.
**Warning signs:** This is actually a non-issue due to existing normalization.

## Code Examples

### PARSE-01: The Exact Change (content.py ~line 327)

```python
# Source: direct code analysis of src/mnemo/epub/content.py

# BEFORE (the bug):
# For other elements, accumulate their text
text = child.get_text(strip=True)
if text:
    current_text_parts.append(text)

# AFTER (the fix):
# For other elements, accumulate their text
# Use separator=' ' to preserve word boundaries across inline child elements
# (e.g., <span>a</span><span>strategy</span> must not become "astrategy")
text = child.get_text(separator=" ", strip=True)
if text:
    current_text_parts.append(text)
```

### PARSE-02: _extract_authors replacement (metadata.py)

```python
# Source: direct code analysis of src/mnemo/epub/metadata.py

def _extract_authors(epub_book: epub.EpubBook) -> list[str]:
    """Extract author list from EPUB metadata.

    Handles both multiple dc:creator elements and semicolon-delimited
    authors within a single dc:creator element.

    Args:
        epub_book: Parsed EPUB book object

    Returns:
        List of author names, or ["Unknown"] if none found
    """
    creators = epub_book.get_metadata("DC", "creator")
    if creators:
        raw_strings = [str(c[0]).strip() for c in creators if c and c[0]]
        authors: list[str] = []
        for raw in raw_strings:
            parts = [p.strip() for p in raw.split(";")]
            authors.extend(p for p in parts if p)
        if authors:
            return authors

    logger.warning("Missing author metadata. Using 'Unknown'")
    return ["Unknown"]
```

### PARSE-03: extract_content modification (content.py)

```python
# Source: direct code analysis of src/mnemo/epub/content.py

# In extract_content(), inside the spine_items loop:

href = item.get_name()
section_path = toc_mapping.get(href, [])

# PARSE-03: assign descriptive label for front-matter items absent from TOC
if not section_path:
    inferred = _infer_front_matter_label(href)
    if inferred:
        section_path = inferred
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (current project standard) |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `python -m pytest tests/test_epub_parser.py -x -q` |
| Full suite command | `python -m pytest tests/ -q --ignore=tests/test_mcp.py` |

Note: `tests/test_mcp.py::TestServerSetup::test_server_imports_without_side_effects`
has a pre-existing failure unrelated to this phase (MCP server name changed from
`"mnemo"` to `"mnemo v1.2.1"`). Exclude or fix in this phase.

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PARSE-01 | `<span>a</span><span>strategy</span>` yields `"a strategy"` not `"astrategy"` | unit | `python -m pytest tests/test_epub_parser.py::TestContentExtraction::test_word_boundaries_preserved_across_inline_elements -x` | ❌ Wave 0 |
| PARSE-01 | Adjacent `<em>` and `<strong>` siblings produce space-separated text | unit | `python -m pytest tests/test_epub_parser.py::TestContentExtraction::test_inline_sibling_word_boundaries -x` | ❌ Wave 0 |
| PARSE-02 | `"Smith; Jones;"` → `["Smith", "Jones"]` | unit | `python -m pytest tests/test_epub_parser.py::TestExtractMetadata::test_semicolon_delimited_authors -x` | ❌ Wave 0 |
| PARSE-02 | Separate dc:creator elements work as before | unit | existing `test_extracts_title_and_authors` | ✅ |
| PARSE-02 | Trailing semicolon stripped | unit | `python -m pytest tests/test_epub_parser.py::TestExtractMetadata::test_author_trailing_semicolon -x` | ❌ Wave 0 |
| PARSE-03 | cover.xhtml → section_path=["Cover"] | unit | `python -m pytest tests/test_epub_parser.py::TestContentExtraction::test_front_matter_cover_label -x` | ❌ Wave 0 |
| PARSE-03 | toc.xhtml → section_path=["Table of Contents"] | unit | `python -m pytest tests/test_epub_parser.py::TestContentExtraction::test_front_matter_toc_label -x` | ❌ Wave 0 |
| PARSE-03 | Unknown filename still gets empty section_path | unit | `python -m pytest tests/test_epub_parser.py::TestContentExtraction::test_unknown_href_no_label -x` | ❌ Wave 0 |
| PARSE-03 (implicit) | CODE blocks preserve indentation after all fixes | unit | existing `test_preserves_code_whitespace` | ✅ |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_epub_parser.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -q --ignore=tests/test_mcp.py`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

Tests to create before implementation begins:

- [ ] `tests/test_epub_parser.py` — add `test_word_boundaries_preserved_across_inline_elements` to `TestContentExtraction`
- [ ] `tests/test_epub_parser.py` — add `test_inline_sibling_word_boundaries` to `TestContentExtraction`
- [ ] `tests/test_epub_parser.py` — add `test_semicolon_delimited_authors` to `TestExtractMetadata`
- [ ] `tests/test_epub_parser.py` — add `test_author_trailing_semicolon` to `TestExtractMetadata`
- [ ] `tests/test_epub_parser.py` — add `test_front_matter_cover_label` to `TestContentExtraction`
- [ ] `tests/test_epub_parser.py` — add `test_front_matter_toc_label` to `TestContentExtraction`
- [ ] `tests/test_epub_parser.py` — add `test_unknown_href_no_label` to `TestContentExtraction`
- [ ] `tests/fixtures/epub_factory.py` — add `create_epub_with_front_matter()` factory function for PARSE-03 tests
- [ ] Consider fixing pre-existing `test_server_imports_without_side_effects` failure in `tests/test_mcp.py` (trivial: update assertion from `"mnemo"` to `"mnemo v1.2.1"`)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `get_text(strip=True)` for all elements | `get_text(separator=' ', strip=True)` for inline fallback | Phase 10 | Fixes "astrategy" class bugs |
| Raw dc:creator string as single author | Split on `;` before storing | Phase 10 | Fixes "Smith; Jones;" as one author |
| Empty section_path for front-matter | FRONT_MATTER_STEMS heuristic | Phase 10 | Replaces "Unknown section" for known front-matter |

## Open Questions

1. **FRONT_MATTER_STEMS completeness**
   - What we know: The stems dict covers common English-language front-matter names
   - What's unclear: Publisher-specific stems in the user's actual EPUB library (STATE.md explicitly flags this)
   - Recommendation: Include a task to test against real EPUBs before marking phase complete; keep stems dict easy to extend

2. **Pre-existing test_mcp.py failure**
   - What we know: `test_server_imports_without_side_effects` fails because `mcp.name == "mnemo v1.2.1"` not `"mnemo"`
   - What's unclear: Whether this was intentional or a side effect of a previous change
   - Recommendation: Fix the test assertion in this phase since it's a one-line fix and the full suite must be green at phase gate

3. **Separator fix and NavigableString whitespace interaction**
   - What we know: `_normalize_text` collapses multi-spaces with `\s+` regex, handling any double-space artifacts
   - What's unclear: Whether any existing test asserts on exact spacing in text blocks
   - Recommendation: Run `test_epub_parser.py` after the fix; if tests fail due to spacing changes, update them

## Sources

### Primary (HIGH confidence)
- Direct code analysis of `src/mnemo/epub/content.py` — confirmed bug location at line 327
- Direct code analysis of `src/mnemo/epub/metadata.py` — confirmed `_extract_authors` logic
- Direct code analysis of `src/mnemo/mcp/tools.py` lines 449, 488 — confirmed "Unknown section" display logic
- BeautifulSoup4 docs (confirmed: `get_text(separator=' ')` inserts separator between all NavigableStrings)
- `tests/test_epub_parser.py` — confirmed existing test coverage and gaps
- `.planning/STATE.md` — confirmed architectural decisions (CODE whitespace, book_id stability, FRONT_MATTER_STEMS caveat)

### Secondary (MEDIUM confidence)
- Manual test of `child.get_text(strip=True)` vs `child.get_text(separator=' ', strip=True)` in Python REPL — confirmed word-joining behavior

## Metadata

**Confidence breakdown:**
- Bug root causes: HIGH — traced to exact lines in source code with confirmed reproduction
- Fix approach: HIGH — verified in REPL that separator=' ' produces correct output
- Test gaps: HIGH — existing test file structure is clear, new tests are straightforward additions
- FRONT_MATTER_STEMS completeness: MEDIUM — covers common cases but real-world EPUBs may need additions

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (stable domain; BeautifulSoup and ebooklib APIs do not change frequently)
