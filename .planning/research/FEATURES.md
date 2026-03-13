# Feature Landscape: v1.3 Quality & Polish

**Domain:** EPUB text parsing quality and search UX improvements
**Milestone:** v1.3 Quality & Polish (subsequent milestone; all v1.2 RAG features already built)
**Researched:** 2026-03-12
**Confidence:** HIGH (all features are well-scoped bug fixes and small additions against a known codebase)

---

## Context

Mnemo v1.2 is fully functional with hybrid search, context window expansion, section filtering, and 7 MCP tools. This milestone fixes real-world parsing artifacts and UX gaps discovered during actual use. All features operate against the existing stack with no schema changes required except possibly a new `book_sections` table for `get_book_structure`.

Existing infrastructure that these features build on:
- `_normalize_text()` in `content.py`: collapses whitespace via `re.sub(r"\s+", " ", text)` — but only applied to text assembled from `NavigableString` fragments, not to inline elements whose text is gathered via `get_text(strip=True)`
- `_extract_authors()` in `metadata.py`: strips whitespace on each creator entry but does no further normalization of semicolons or trailing delimiters
- `toc_mapping` in `parser.py`: built from EPUB3 nav or EPUB2 NCX; spine items not in the TOC map get `section_path = []` which renders as `"Unknown section"` in formatted output
- Section filter in `service.py`: checks `any(section_lower in s.lower() for s in r.section_path)` — substring match against leaf path segments only, not against assembled hierarchy string
- `_format_enriched_results()` in `tools.py`: uses inline text markers `**>>> MATCHED (seq N) <<<**` and `*[context, seq N]*` — functional but low visual clarity in Claude's rendered output
- No MCP tool exists to browse section structure without running a search

---

## Table Stakes

Features that fix observable bugs. Without these, parsed content is wrong, authors display with garbage characters, and sections are mislabeled.

### 1. EPUB Text Artifact Cleanup (Joined Words Across HTML Tags)

**What goes wrong today:** EPUB HTML uses inline elements (`<em>`, `<strong>`, `<span>`, `<a>`, `<code>`) extensively. When BeautifulSoup's `get_text(strip=True)` is called on a parent paragraph, inline elements' text is concatenated with no separator — `"the<em>iterator</em>protocol"` becomes `"theiteratorprotocol"`. The current `_normalize_text()` only normalizes what is already a joined string; it cannot reinsert spaces that were never emitted.

**Root cause:** In `_extract_blocks_from_element`, the fallthrough case for unrecognized tags calls `child.get_text(strip=True)` and appends the result directly to `current_text_parts`. This correctly gets the full text of a paragraph but the strip=True collapses inter-element spacing. When the paragraph contains multiple inline elements, the words from those elements are run together.

**Expected behavior:** `"the <em>iterator</em> protocol"` → `"the iterator protocol"`. Words should be space-separated across inline element boundaries regardless of original HTML whitespace.

**Fix approach:** Use `get_text(separator=" ")` instead of `get_text(strip=True)` on the fallthrough case, then pass through `_normalize_text()` to collapse any excess whitespace. Alternatively, walk inline children and join with a space before normalizing.

**Complexity:** Low
- Single-line change in `_extract_blocks_from_element` fallthrough
- Existing `_normalize_text()` handles over-spacing correctly
- No schema changes; re-ingest needed for existing books to benefit
- Must not affect code block extraction (code uses `get_text()` without separator deliberately to preserve formatting)

**Dependencies:** `content.py:_extract_blocks_from_element` fallthrough case only.

**Confidence:** HIGH — verified by reading the code; root cause is unambiguous.

---

### 2. Author Name Parsing Cleanup (Semicolons, Trailing Delimiters)

**What goes wrong today:** Some EPUB metadata tools store multiple authors in a single `dc:creator` field separated by semicolons (e.g., `"Alice Smith; Bob Jones"`) or store trailing delimiters (e.g., `"Alice Smith;"` or `"Alice Smith, "`). The current `_extract_authors()` does only `.strip()` on each creator string. The result is author names displayed as `"Alice Smith; Bob Jones"` instead of `["Alice Smith", "Bob Jones"]`, or `"Alice Smith;"` with a trailing semicolon.

**Root cause:** `_extract_authors()` in `metadata.py` assumes each `dc:creator` element is a single author. The Dublin Core spec does allow one creator per element, but many EPUB generators pack multiple authors into one field.

**Expected behavior:**
- `"Alice Smith; Bob Jones"` → `["Alice Smith", "Bob Jones"]`
- `"Alice Smith,"` → `["Alice Smith"]`
- `"Alice Smith; "` → `["Alice Smith"]`
- `"Alice Smith"` → `["Alice Smith"]` (no change for clean data)

**Fix approach:** After reading creator values, split on `;` and `,` (heuristically — comma only when not part of a "Last, First" name), strip each fragment, filter empty strings. The safest rule: split on `;` always (unambiguous separator), split on `,` only when the resulting fragments don't look like "Last, First" format (i.e., more than one comma in the string). Or more practically: split on `;` only, then strip trailing commas from each fragment.

**Complexity:** Low
- Logic change in `_extract_authors()` only
- No schema change; updated metadata can be applied without re-ingest (just update the book's author list via `update_book_metadata`)
- Must not split legitimate single-author names that contain commas (e.g., "Smith, John" in Last-First format)

**Dependencies:** `metadata.py:_extract_authors` only. `normalize_isbn` pattern nearby shows the right model for this kind of normalization.

**Confidence:** HIGH — EPUB spec and common tool behavior well understood; root cause in code is clear.

---

### 3. Front-Matter and TOC Section Detection (Eliminate "Unknown Section")

**What goes wrong today:** EPUB spine items that are not listed in the TOC (front matter, copyright page, title page, TOC navigation page itself) get `section_path = []` from `toc_mapping.get(href, [])`. This renders in output as `"Unknown section"`. These sections are real content (copyright, preface, etc.) but the TOC typically does not link to them.

**Root cause:** The `toc_mapping` dictionary in `content.py:extract_content` is keyed by EPUB item href. Items not appearing as TOC link targets simply get no entry. The empty list fallback produces the "Unknown section" label in `tools.py`.

**Expected behavior:** Front-matter items should be labeled based on their likely role:
- Item named `cover.xhtml` or `title_page.xhtml` → `["Front Matter"]`
- Item named `toc.xhtml` or `nav.xhtml` → `["Table of Contents"]`
- Item named `copyright.xhtml`, `colophon.xhtml` → `["Front Matter"]`
- Items that appear in the spine before the first TOC entry → `["Front Matter"]`
- Heuristic: parse `<title>` element or first `<h1>`/`<h2>` from the item for a label

**Fix approach:** After building `toc_mapping`, add a second pass:
1. Sort spine items in order
2. For items not in `toc_mapping`, check filename heuristics (cover, toc, copyright, colophon, preface, intro)
3. Fallback: use the item's `<title>` tag or first heading text
4. Final fallback: label as "Front Matter" if the item appears before the first mapped TOC entry, or as "Back Matter" if after the last

**Complexity:** Low-Medium
- Logic addition in `parser.py` or `content.py` — no new dependencies
- Filename heuristics cover ~80% of cases; heading fallback covers the rest
- No schema change; re-ingest needed for existing books to benefit
- "Unknown section" fallback in `tools.py` becomes the true last resort only for truly unlabeled items

**Dependencies:** `content.py:extract_content` and/or `parser.py:_parse_toc` for the pre-processing step.

**Confidence:** HIGH — EPUB structural conventions for front/back matter are well established (EPUB3 spec uses `epub:type` attributes like `cover`, `toc`, `frontmatter`).

---

## Differentiators

Features that meaningfully improve the search and navigation experience beyond correctness fixes.

### 4. Section Filter Hierarchy Traversal (Match Against Full Path)

**What goes wrong today:** The section filter in `service.py` checks `any(section_lower in s.lower() for s in r.section_path)`. This compares the filter string against each individual path segment. Searching `section="Chapter 3"` works if "Chapter 3" is a segment. But `section="Part I > Chapter 3"` or `section="concurrency"` against a path like `["Part I", "Chapter 3", "Concurrent Programming"]` will fail unless the exact segment text matches.

**More important gap:** A filter like `section="Chapter 3"` will match the leaf segment "Chapter 3" but will also incorrectly match a section named "Chapter 3: Advanced Topics" in a *different* part when the user intended to restrict to a specific subtree. Hierarchy-aware matching would check "does the section_path contain this segment at any level, in order?"

**Expected behavior:**
- `section="Part I"` should match all chunks under Part I, including nested chapters and sections
- `section="Part I > Chapter 3"` should match only chunks under Chapter 3 within Part I
- `section="generators"` should match any chunk in a section whose *assembled path* contains "generators" (current substring behavior, unchanged)
- Simple substring against the assembled path string handles both cases elegantly

**Fix approach:** Instead of checking individual segments, join `section_path` with ` > ` and do the substring check against the joined string. This is a one-line change that naturally supports both leaf and multi-level path filters:

```python
# Current (segment-by-segment)
any(section_lower in s.lower() for s in r.section_path)

# Fixed (full-path substring)
section_lower in " > ".join(r.section_path).lower()
```

This also aligns with how `get_book_chunks` already formats the section for display.

**Complexity:** Very Low
- One-line change in `service.py:search()`
- No schema change
- Backward compatible: single-segment filters still work the same way
- Existing tests need updating to verify full-path behavior

**Dependencies:** `service.py:search()` section filter block only.

**Confidence:** HIGH — the fix is evident from reading the code; the assembled-string approach is already used in display formatting.

---

### 5. `get_book_structure` MCP Tool (TOC Browsing)

**What does not exist today:** There is no way to ask "what sections does this book have?" without running a search and inferring from section_path values in results. Claude cannot orient in a book before searching it.

**Expected behavior:** Given a `book_id`, return the hierarchical section structure of the book — effectively a table of contents with the section labels stored on chunks. Claude can then use this to decide which sections to search or filter.

**How it works:**
- Query `SELECT DISTINCT section_path, MIN(sequence) as first_seq FROM chunks WHERE book_id = ? GROUP BY section_path ORDER BY first_seq`
- Parse `section_path` JSON arrays, deduplicate, and reconstruct the tree
- Return as indented markdown text representing the hierarchy

**Output example:**
```
## Book Structure: Python Cookbook

- Part I: Text
  - Chapter 1: Strings and Text
  - Chapter 2: Numbers, Dates, and Times
- Part II: Data Structures
  - Chapter 3: Iterators and Generators
    - Generators
    - Coroutines
- Front Matter
- Table of Contents
```

**Complexity:** Low-Medium
- SQL query is trivial (no schema change)
- Tree reconstruction from flat list of `section_path` arrays: group by first N path elements, build nested structure
- No new dependencies
- Format as markdown with indentation for readability in Claude's UI
- `readOnlyHint=True` annotation

**Dependencies:** `chunks` table (existing), `ChunkRepository`, `tools.py` for registration.

**Confidence:** HIGH — data already stored; only display logic is new.

---

### 6. Context Window Result Clarity (Match vs Context Delineation)

**What goes wrong today:** `_format_enriched_results()` uses `**>>> MATCHED (seq N) <<<**` for matched chunks and `*[context, seq N]*` for surrounding chunks. In Claude Desktop's markdown rendering, the difference between bold and italic is subtle. When scanning a long enriched response, it is easy to confuse which chunk was the actual match and which is contextual padding.

**Expected behavior:** The matched chunk should be visually unambiguous. Options:
1. Use a horizontal rule separator with a clear label before the match: `---\n**MATCH:**`
2. Use a distinct header style: `### Matched (seq N)` vs `#### Context (seq N)`
3. Add a summary line at the top of each expanded result showing match metadata, separate from context chunks

**Recommended approach:** Add a header block before matched chunks with `---` separator and `**MATCH** (seq N):` label, and use a softer label like `[context +N]` / `[context -N]` for surrounding chunks to indicate relative position (before or after match). This makes the visual distinction clear in rendered markdown.

**Complexity:** Very Low
- Change to `_format_enriched_results()` in `tools.py` only
- No logic change, formatting only
- No schema change
- Requires reviewing output with actual Claude Desktop to validate visual clarity

**Dependencies:** `tools.py:_format_enriched_results` only.

**Confidence:** HIGH — purely a formatting change; the fix is self-contained.

---

## Anti-Features

Features to explicitly NOT build in v1.3.

### Re-Embedding After Metadata Change

**Why avoid:** Re-embedding is expensive (calls Databricks API for every chunk in the book) and slow. Author name cleanup and section label fixes are metadata changes only — the text content being embedded is unchanged. The embedding already captures semantic meaning; the section_path in the embedding metadata could be updated in-place in ChromaDB if truly needed, but search quality is unaffected by author name display.

**What to do instead:** `update_book_metadata` already exists for correcting author/title. Section path labels live in SQLite chunk records and ChromaDB metadata; a re-index with `force=true` applies fixes for books that need it.

---

### EPUB Write-Back (Modifying Source Files)

**Why avoid:** Mnemo is explicitly read-only on EPUBs by design decision. Even if author normalization or section labeling could be improved in the source file, modifying user files is out of scope and potentially destructive.

**What to do instead:** All corrections happen in Mnemo's internal SQLite/ChromaDB storage.

---

### Automatic Re-Ingest on Parsing Fix

**Why avoid:** Silently re-ingesting all books when parsing logic changes would be slow and surprising. Re-embedding costs real API time and money.

**What to do instead:** User runs `mnemo add --force <path>` or calls `add_book(force=true)` to update an existing book. Document which books benefit from re-ingest in the milestone release notes.

---

### Smart Author Format Detection ("Last, First" vs "First Last")

**Why avoid:** Detecting and normalizing author name format (e.g., converting "Smith, John" to "John Smith") requires heuristics that will misfire. The goal is to strip garbage delimiters (semicolons, trailing commas), not to reformat legitimate names. Name format normalization is a separate problem better solved by explicit `update_book_metadata` correction.

**What to do instead:** Strip semicolons and trailing delimiter characters; do not reorder or reformat author name components.

---

### `get_book_structure` Caching in DB

**Why avoid:** The section hierarchy can be reconstructed on demand from the chunks table with a single GROUP BY query. Adding a separate `book_sections` table creates schema complexity and synchronization burden. At personal scale (~10 books), the on-demand query is fast enough.

**What to do instead:** Query on demand in `get_book_structure`.

---

## Feature Dependencies

```
Independent, no prereqs (do in any order):
  Author name cleanup ──> no other feature depends on it
  Context window clarity ──> no other feature depends on it

Parsing fixes (logically grouped, do together):
  Text artifact cleanup ──┐
  Front matter detection ──┤─> re-ingest existing books to see full benefit
                           ↓
                     (both improve section_path quality)

Depends on parsing fixes (order after):
  Section filter hierarchy traversal ──> benefits from cleaner section_path
                                         (but works correctly regardless)
  get_book_structure tool ──> better output when section labels are clean,
                              but functional regardless of label quality
```

**Ordering recommendation:**
1. Text artifact cleanup + author normalization (parsing fixes, low risk, no dependencies)
2. Front matter detection (slightly more logic, benefits from same re-ingest pass)
3. Section filter hierarchy traversal (one-line fix, do immediately — tiny scope)
4. Context window clarity (formatting only, do last since it requires visual QA)
5. `get_book_structure` tool (new tool, slightly larger scope, natural last item)

---

## MVP Recommendation

### Must Have (core correctness):

1. **Text artifact cleanup** — Fixes joined-word parsing bug. Every real-world EPUB is affected. Low risk, high impact on search quality since joined words will not match queries.
2. **Author name cleanup** — Fixes display garbage. Users see "Alice Smith; Bob Jones" as a single string. Low risk, self-contained.
3. **Front matter detection** — Eliminates misleading "Unknown section" labels. Makes `get_book_structure` output immediately useful.
4. **Section filter hierarchy traversal** — One-line fix that makes section filtering behave as users expect when specifying multi-level paths.

### Should Have (UX improvements):

5. **Context window result clarity** — Makes enriched search results readable at a glance. Formatting-only change.
6. **`get_book_structure` tool** — Enables pre-search orientation. Low-medium effort, high value for systematic book exploration.

### Explicitly Defer:

- Any re-embedding workflow — out of scope for a quality/polish milestone
- Author format normalization (Last, First rearrangement) — correctness risk outweighs benefit
- Caching of book structure — premature optimization at personal scale

---

## Sources

All findings based on direct codebase inspection (HIGH confidence — no external sources needed for bug analysis):

- `src/mnemo/epub/content.py` — `_extract_blocks_from_element`, `_normalize_text` (text artifact root cause)
- `src/mnemo/epub/metadata.py` — `_extract_authors` (author normalization root cause)
- `src/mnemo/epub/parser.py` — `_parse_toc`, `extract_content` section_path fallback (unknown section root cause)
- `src/mnemo/search/service.py` — section filter logic (hierarchy traversal gap)
- `src/mnemo/mcp/tools.py` — `_format_enriched_results`, `_format_search_results` (context clarity gap)
- `src/mnemo/storage/database.py` — schema (confirms no schema change needed for most features)
- `.planning/PROJECT.md` — milestone scope confirmation

### Supporting references:
- [EPUB3 Structural Semantics Vocabulary](https://www.w3.org/TR/epub-ssv/) — `epub:type` values for front/back matter detection (cover, toc, frontmatter, colophon)
- [EPUB3 Navigation Document spec](https://www.w3.org/TR/epub-nav/) — nav element structure used by `_parse_epub3_nav`
