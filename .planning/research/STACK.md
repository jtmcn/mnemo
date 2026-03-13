# Technology Stack: v1.3 Quality & Polish

**Project:** Mnemo
**Milestone:** v1.3 Quality & Polish (EPUB text cleanup, author normalization, section hierarchy, TOC browsing)
**Researched:** 2026-03-12
**Overall Confidence:** HIGH

## Executive Summary

The v1.3 milestone requires **zero new runtime dependencies**. All five features can be built using the existing stack. The critical findings are:

1. **EPUB whitespace/text cleanup** — The root cause is `child.get_text(strip=True)` in `content.py` line 327. Adding `separator=" "` to all `get_text()` calls for inline-element text accumulation fixes joined words. The fix is ~5 targeted call-site changes using the `separator` parameter that has existed in BeautifulSoup since at least 4.9.0. No new library needed.

2. **Author name normalization** — EPUB `dc:creator` metadata sometimes embeds multiple authors in one string (semicolon-delimited, e.g. `"Smith, John; Doe, Jane"`) or appends trailing delimiters. Python stdlib `re` is fully sufficient to split on semicolons/commas, strip surrounding whitespace, and discard empty elements. No external parser (`nameparser`, `ebookmeta`) is needed for this scope.

3. **Front-matter / TOC section detection** — ebooklib 0.20's `epub.read_epub()` returns the TOC as `Section`/`Link` objects via `epub_book.toc`. These objects carry the label text already used by the existing `_parse_epub3_nav` / `_parse_epub2_ncx` code. Detecting front-matter items (Cover, Table of Contents, Preface) requires only a label-matching heuristic using stdlib `re` — no new library.

4. **Section filter hierarchy traversal** — The existing post-filter in `service.py` (line 135–139) already performs a substring check across `section_path`. The change is purely to fix what paths are stored — if blocks extracted before the first heading get section_path `[]` or `["Unknown"]`, fixing the parser to assign proper TOC-derived paths eliminates the symptom. No new data structure is needed.

5. **`get_book_structure` MCP tool** — Reads distinct `section_path` JSON arrays from SQLite `chunks` table, reconstructs the hierarchy tree in Python, and returns markdown. No additional storage, no new library. FastMCP 2.14.x (pinned `<3`) supports `str` return type (the project's existing convention); returning formatted markdown from the tool is consistent with all seven existing tools.

This is a parser correctness and MCP surface milestone, not a dependency milestone.

---

## Stack Additions Required

### New Dependencies: NONE

| Feature | Requires | Provided By | Status |
|---------|----------|-------------|--------|
| Fix `get_text()` whitespace between HTML elements | `separator` param on BeautifulSoup `get_text()` | `beautifulsoup4>=4.12` | Already installed |
| Split semicolon-delimited author strings | String splitting, regex | `re` (stdlib) | Already available |
| Detect front-matter section labels | Label text matching | `re` (stdlib), existing `_parse_epub3_nav` / `_parse_epub2_ncx` | Already available |
| Section hierarchy traversal (filter matches full path) | Substring search across path list | `str.lower()` + `in` (Python builtins) | Already available |
| `get_book_structure` tool — query distinct sections | SELECT DISTINCT on JSON column | `sqlite3` (stdlib) | Already available |
| `get_book_structure` tool — reconstruct tree | Dict-based tree building | Python builtins | Already available |
| `get_book_structure` tool — MCP registration | `@mcp.tool` decorator | `fastmcp>=2.14,<3` | Already installed |

---

## Feature-by-Feature Stack Analysis

### 1. EPUB Whitespace Fix (Joined Words Across HTML Tags)

**Root cause:** In `content.py` line 327, text from non-special inline elements is accumulated with:
```python
text = child.get_text(strip=True)
if text:
    current_text_parts.append(text)
```

Then at flush time (line 177, 334): `" ".join(current_text_parts)`.

The `" ".join()` adds a space *between separate block-level text parts*, but within a single `child.get_text(strip=True)` call, text from sibling child elements is concatenated without any separator. For example, `<p>See <a href="...">Chapter 3</a> for details</p>` → `get_text(strip=True)` → `"SeeChapter 3for details"`.

**Fix:** Add `separator=" "` to `get_text()` calls wherever text is extracted for accumulation into prose blocks. BeautifulSoup's `get_text(separator=" ", strip=True)` inserts the separator between the text of each child element, then strips leading/trailing whitespace from each piece.

After extraction, the existing `_normalize_text()` regex (`re.sub(r"\s+", " ", text).strip()`) collapses any double-spaces introduced by the separator, so no second-pass cleanup is needed.

**Call sites to fix in `content.py`:**
- Line 327: `child.get_text(strip=True)` for "other elements" accumulation
- Line 190: `child.get_text(strip=True)` for heading text (minimal impact but consistent)

**Do NOT change:** `get_text()` on code blocks and diagrams — whitespace is significant there.

**BeautifulSoup `separator` param:** Exists since BS4 4.x, well before the project's `>=4.12` pin. The project currently runs 4.14.3 (released Nov 30, 2025). HIGH confidence this works exactly as documented.

**No new dependency needed.**

**Confidence:** HIGH — BeautifulSoup `get_text(separator=" ")` is the canonical fix for this exact problem, documented in the official BS4 docs and confirmed by Launchpad bug #1768330.

---

### 2. Author Name Normalization

**Root cause:** Some EPUBs encode multiple authors in a single `dc:creator` element using semicolons: `"Smith, John; Doe, Jane"`. The current `_extract_authors()` in `metadata.py` (line 155) takes each `creator[0]` as a single string and strips whitespace, but does not split on semicolons.

A related artifact: some tools append trailing semicolons: `"Smith, John;"`.

**Fix in `_extract_authors()` — stdlib `re` only:**
```python
def _split_and_clean_author(raw: str) -> list[str]:
    """Split semicolon-delimited authors and clean trailing delimiters."""
    # Split on semicolon (primary multi-author delimiter in EPUB metadata)
    parts = re.split(r"\s*;\s*", raw)
    # Strip leading/trailing whitespace and discard empty parts
    return [p.strip() for p in parts if p.strip()]
```

Apply to each raw `creator[0]` string before appending to the authors list.

**Do NOT strip accents or apply NFKD normalization.** Author names must preserve their original Unicode representation (accented characters, non-Latin scripts). Stripping accents discards linguistically significant content (e.g. `García` → `Garcia` would be wrong). The only normalization needed is: split on delimiters, strip surrounding whitespace.

**nameparser library:** Not needed. The problem is delimiter splitting, not structured name parsing (First/Last/Title). Adding nameparser would solve a different problem (name part decomposition) that the project does not need.

**ebookmeta library:** Not needed. The project uses ebooklib directly and only needs to fix the post-extraction parsing.

**Confidence:** HIGH — the fix is a single-function stdlib change, no external library needed.

---

### 3. Front-Matter / TOC Section Detection

**Root cause:** EPUB spine items that precede the first body chapter (Cover, Table of Contents, Copyright, Preface) often have a `section_path` of `[]` after TOC parsing, causing them to display as "Unknown section" in search results.

The TOC mappings in `_parse_epub3_nav` and `_parse_epub2_ncx` only populate paths for items that appear in the TOC `<a>` links. Spine items not linked in the TOC (e.g. cover pages) get no mapping.

**Fix:** Two complementary approaches, both using only existing stack:

1. **TOC href fallback:** After parsing the nav/NCX, for spine items with no TOC mapping, check the item's filename (`item.get_name()`). Patterns like `cover.xhtml`, `toc.xhtml`, `copyright.xhtml`, `colophon.xhtml` can be matched with a short regex dict to assign canonical section labels.

2. **ebooklib `epub_book.toc` for label extraction:** The `epub_book.toc` attribute returns a nested tuple of `(Section, [children])` or `Link` objects. Each `Link` has a `.title` attribute. This is the same data used by `_parse_epub3_nav`, so no additional library call is needed — just add a filename-to-label fallback dict.

**Example patterns to detect:**
```python
FRONT_MATTER_PATTERNS = {
    r"cover": "Cover",
    r"toc|contents|nav": "Table of Contents",
    r"copyright|copy": "Copyright",
    r"preface|foreword": "Preface",
    r"intro": "Introduction",
    r"colophon|about": "About",
    r"dedication": "Dedication",
}
```

**Confidence:** HIGH — this is a heuristic filename-to-label mapping using stdlib `re`. The ebooklib `.toc` attribute is stable across 0.18–0.20.

---

### 4. Section Filter Hierarchy Traversal

**Current state:** The post-filter in `service.py` line 135–139:
```python
results = [
    r for r in results
    if r.section_path and any(section_lower in s.lower() for s in r.section_path)
]
```

This already matches against any element in the `section_path` list. The issue is not the filter logic — it is that some chunks have incomplete or missing section paths (fixed by #1 and #3 above), so filter terms don't find matches they should.

**Change needed:** Minimal. After fixing the parser to assign correct section paths, confirm the existing filter logic is sufficient. The `any(section_lower in s.lower() for s in r.section_path)` approach correctly matches at any level of the hierarchy (e.g. `section="Chapter 3"` matches a chunk with path `["Part I", "Chapter 3", "Generators"]`).

**No new logic needed** if the parser fixes properly populate section_path on all chunks.

**One potential improvement:** The filter currently checks leaf-only paths. If a user searches `section="Part I"` and chunks have `section_path=["Part I", "Chapter 3"]`, the current check `"part i" in "Part I".lower()` already works. No change needed.

**Confidence:** HIGH — the filter logic is correct; the fix is upstream in the parser.

---

### 5. `get_book_structure` MCP Tool

**What it does:** Given a `book_id`, query the `chunks` table for all distinct `section_path` values, reconstruct the section tree, and return a formatted outline showing the book's structure with chunk counts per section.

**Data source:** `section_path` is already stored as a JSON array in the `chunks` table. A SQLite query retrieves all distinct paths:
```sql
SELECT section_path, COUNT(*) as chunk_count
FROM chunks
WHERE book_id = ?
GROUP BY section_path
ORDER BY MIN(sequence)
```

Each `section_path` (deserialized from JSON) is a `list[str]` like `["Part I", "Chapter 3", "Generators"]`. Building a tree from these requires only a nested dict, then rendering to markdown indentation — stdlib only.

**MCP tool signature (consistent with existing tools):**
```python
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def get_book_structure(book_id: str) -> str:
    """Browse the section hierarchy of a book. ..."""
```

**Return type:** `str` (markdown-formatted outline). This matches the return type of all 7 existing tools. FastMCP 2.14.x serializes `str` returns as a text content block, which is what Claude Desktop / Claude Code expect.

**FastMCP version note:** The project pins `fastmcp>=2.14,<3`. FastMCP 3.x (latest: 3.1.0, released Mar 3 2026) is excluded by the pin. FastMCP 3.x introduced breaking API changes. The `<3` pin is correct and should not be relaxed for this milestone.

**No schema changes needed.** `section_path` and `sequence` are already indexed (`idx_chunks_sequence`). The `GROUP BY section_path` query will use the index efficiently.

**New method to add to `ChunkRepository`:**
```python
def get_section_summary(self, book_id: str) -> list[tuple[list[str], int]]:
    """Return distinct section paths with chunk counts, ordered by first appearance."""
```

This follows the existing repository pattern and stays within the `storage` module — no new file needed.

**Confidence:** HIGH — query and tree reconstruction are straightforward stdlib operations. FastMCP tool registration follows existing patterns exactly.

---

## Version Status of Existing Dependencies

| Package | Pinned Constraint | Latest Available | Action |
|---------|------------------|-----------------|--------|
| `beautifulsoup4` | `>=4.12` | 4.14.3 (Nov 30, 2025) | No change to pin; fix uses existing `separator` param |
| `ebooklib` | `>=0.18` | 0.20 (Oct 26, 2025) | Consider bumping to `>=0.18,<0.21` for stability, but 0.20 is backward-compatible |
| `lxml` | `>=5.0` | 6.0.2 (Sep 22, 2025) | No change needed; BS4's lxml parser behavior is stable |
| `fastmcp` | `>=2.14,<3` | 2.14.5 (Feb 3, 2026) in 2.x; 3.1.0 latest | Keep `<3` — FastMCP 3.x has breaking changes, migration not in scope |
| `re` (stdlib) | — | Python 3.11+ | Author normalization and section detection use only stdlib |

**ebooklib 0.18 → 0.20:** The 0.20 release (Oct 2025) is labeled "the final version supporting Python 2.7" — it is backward-compatible with the API used in this project (`epub.read_epub()`, `.get_items()`, `.toc`, `.get_metadata()`). Bumping the pin to `>=0.18` (unchanged) continues to work; no forced upgrade is needed for v1.3.

---

## Alternatives Considered

| Feature | Recommendation | Alternative | Why Not |
|---------|---------------|-------------|---------|
| Author delimiter splitting | stdlib `re.split(r"\s*;\s*", ...)` | `nameparser` library | nameparser solves First/Last/Title decomposition — not needed. Single-function stdlib change is simpler and has no transitive deps. |
| Author delimiter splitting | stdlib `re.split` | `ebookmeta` library | Adds a new library for one parsing fix. The project already uses ebooklib directly. |
| Front-matter detection | Filename regex heuristics | Full TOC re-parse with ebooklib `.toc` | `.toc` is already used by the parser; the problem is spine items *outside* the TOC, so a filename fallback is the right tool. |
| `get_book_structure` return type | `str` (markdown) | `dict` / JSON | All 7 existing tools return `str`. Returning `dict` would require updating the tool convention and tests. Markdown is immediately readable by Claude without extra parsing. |
| `get_book_structure` data source | SQLite `section_path` column | Re-parse EPUB at query time | Re-parsing requires the EPUB file to be present and is expensive. SQLite already has all section data from ingest. |
| Whitespace fix | `get_text(separator=" ")` | Custom HTML walker extracting text nodes individually | BS4's `separator` parameter is the canonical solution documented in official BS4 docs. Custom walker adds complexity for no benefit. |

---

## Integration Points

### Files That Change

| File | Change | Feature |
|------|--------|---------|
| `src/mnemo/epub/content.py` | Add `separator=" "` to `get_text()` calls at text-accumulation sites | Whitespace fix |
| `src/mnemo/epub/metadata.py` | Split semicolon-delimited authors in `_extract_authors()` | Author normalization |
| `src/mnemo/epub/parser.py` | Add filename-based front-matter label fallback in `_parse_toc()` | Front-matter detection |
| `src/mnemo/storage/repository.py` | Add `get_section_summary(book_id)` method to `ChunkRepository` | `get_book_structure` tool |
| `src/mnemo/mcp/tools.py` | Add `_get_book_structure_impl()` and `get_book_structure` tool | New MCP tool |

### Files That Do NOT Change

| File | Why Not |
|------|---------|
| `src/mnemo/search/service.py` | Section filter logic is already correct; parser fixes eliminate the root cause |
| `src/mnemo/models.py` | No schema changes — `section_path: list[str]` already exists |
| `src/mnemo/storage/database.py` | No schema changes — `section_path` column and index already exist |
| `src/mnemo/vectors/store.py` | No vector behavior changes |
| `src/mnemo/chunking/` | Chunking strategy unchanged |
| `pyproject.toml` | No new dependencies |

---

## What NOT to Add

| Suggestion | Why Not |
|------------|---------|
| `nameparser` | Solves name part decomposition (First/Last/Title), not the delimiter-splitting problem this milestone has. Adds a dependency for a one-line fix. |
| `ebookmeta` | Alternative EPUB metadata library. Project uses ebooklib; adding a second EPUB library for a metadata fix is unnecessary complexity. |
| `html2text` | Converts HTML to Markdown. Irrelevant — the project already uses BeautifulSoup for structured extraction, not full-document conversion. |
| `ftfy` | Fixes Unicode text encoding artifacts. Not the source of the current whitespace issue (which is structural, not encoding). |
| `Upgrade fastmcp to 3.x` | FastMCP 3.0 introduced breaking API changes. The project's `<3` pin is correct. No features in v1.3 require FastMCP 3.x capabilities. |
| `unidecode` | Strips all non-ASCII from text. Destructive for multilingual author names. Never use for name data. |

---

## pyproject.toml: No Changes Required

```toml
dependencies = [
    "ebooklib>=0.18",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "tiktoken>=0.5",
    "pydantic>=2.0",
    "httpx>=0.27",
    "tenacity>=8.3",
    "numpy>=1.26",
    "chromadb>=1.0.0",
    "fastmcp>=2.14,<3",
]
```

No new lines. No version bumps required.

---

## Sources

### Official Documentation (HIGH confidence)
- [BeautifulSoup get_text() docs](https://beautiful-soup-4.readthedocs.io/en/latest/) — `separator` and `strip` parameters for `get_text()`
- [BeautifulSoup Launchpad bug #1768330](https://bugs.launchpad.net/bugs/1768330) — canonical bug report confirming `separator=" "` as the fix for joined words
- [FastMCP Tools documentation](https://gofastmcp.com/servers/tools) — return type handling, `str` serialization
- [FastMCP PyPI](https://pypi.org/project/fastmcp/) — 2.14.5 is latest 2.x; 3.1.0 is latest overall (breaking change, excluded by `<3` pin)
- [ebooklib PyPI](https://pypi.org/project/EbookLib/) — 0.20 is latest stable (Oct 26, 2025), backward-compatible API
- [beautifulsoup4 PyPI](https://pypi.org/project/beautifulsoup4/) — 4.14.3 (Nov 30, 2025)
- [lxml PyPI](https://pypi.org/project/lxml/) — 6.0.2 (Sep 22, 2025)
- [Python unicodedata docs](https://docs.python.org/3/library/unicodedata.html) — NFC vs NFKD normalization guidance

### Verified by Codebase Inspection (HIGH confidence)
- `src/mnemo/epub/content.py` — `get_text(strip=True)` call sites, `_normalize_text()`, text accumulation pattern
- `src/mnemo/epub/metadata.py` — `_extract_authors()` current implementation
- `src/mnemo/epub/parser.py` — `_parse_epub3_nav()`, `_parse_epub2_ncx()`, `_infer_from_headings()` — TOC mapping gaps
- `src/mnemo/search/service.py` — existing section post-filter logic (line 135–139)
- `src/mnemo/storage/repository.py` — `ChunkRepository` existing methods, `section_path` column access pattern
- `src/mnemo/mcp/tools.py` — existing tool registration pattern, `_impl` + `@mcp.tool` convention, all tools return `str`
- `src/mnemo/models.py` — `Chunk.section_path: list[str]` already exists, stored as JSON in SQLite
