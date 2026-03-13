# Architecture Research

**Domain:** EPUB parsing quality fixes and MCP tool additions for personal RAG library
**Researched:** 2026-03-12
**Confidence:** HIGH (based on direct source code analysis of all pipeline modules)

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MCP Interface Layer                                │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────────────────┐    │
│  │  search_books  │  │ get_book_info  │  │  get_book_structure (NEW)   │    │
│  │ get_book_chunks│  │  list_books    │  │  add/remove/update_book     │    │
│  └───────┬────────┘  └───────┬────────┘  └──────────────┬──────────────┘    │
├──────────┴───────────────────┴────────────────────────────┴──────────────────┤
│                           Search / Query Layer                                │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  search/service.py — SearchService                                   │    │
│  │  hybrid (RRF) | semantic | keyword | section post-filter (MODIFIED)  │    │
│  │  context_window expansion | diversity re-ranking                     │    │
│  └────────────────────────────────┬─────────────────────────────────────┘    │
├───────────────────────────────────┼─────────────────────────────────────────┤
│                           Storage Layer                                       │
│  ┌────────────────────┐           │          ┌──────────────────────────┐    │
│  │  SQLite + FTS5     │◄──────────┤          │  ChromaDB (cosine)       │    │
│  │  books, chunks     │           └─────────►│  1024-dim GTE-large-en   │    │
│  │  (repository.py)   │                      │  (vectors/store.py)      │    │
│  └────────────────────┘                      └──────────────────────────┘    │
├─────────────────────────────────────────────────────────────────────────────┤
│                           Ingestion Pipeline                                  │
│  ┌───────────────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │  epub/parser.py       │  │ chunking/chunker  │  │  ingest.py           │  │
│  │  epub/content.py (MOD)│→ │ ContentBlock →   │→ │  parse → chunk →     │  │
│  │  epub/metadata.py(MOD)│  │ Chunk            │  │  store → embed       │  │
│  └───────────────────────┘  └──────────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Key Data Types |
|-----------|----------------|----------------|
| `epub/metadata.py` | Dublin Core extraction, author normalization, ISBN parsing | `Book` |
| `epub/content.py` | HTML→ContentBlock with type detection, text normalization | `ContentBlock` |
| `epub/parser.py` | EPUB orchestration, TOC parsing (EPUB3 nav / NCX / inferred) | `Book`, `[ContentBlock]` |
| `chunking/chunker.py` | ContentBlock→Chunk, code-atomic splitting, section boundaries | `Chunk` |
| `ingest.py` | Full pipeline orchestration, duplicate detection, embed dispatch | `Book`, int |
| `storage/repository.py` | SQLite CRUD, FTS5 search, chunk range queries | `Book`, `Chunk` |
| `vectors/store.py` | ChromaDB add/query/delete, cosine similarity | vector results |
| `search/service.py` | Hybrid search, RRF fusion, section filter, context expansion | `SearchResult`, `dict` |
| `mcp/tools.py` | FastMCP tool registrations, formatting, lazy service init | `str` (markdown) |

## Recommended Project Structure

```
src/mnemo/
├── epub/
│   ├── parser.py       # EPUBParser: TOC parsing, spine processing, section mapping
│   ├── content.py      # extract_content(), ContentBlock, _normalize_text() [MODIFIED]
│   └── metadata.py     # extract_metadata(), _extract_authors() [MODIFIED]
├── chunking/
│   └── chunker.py      # Chunker, ChunkerConfig (unchanged)
├── storage/
│   ├── database.py     # Schema, init_db(), get_connection() (unchanged)
│   └── repository.py   # BookRepository, ChunkRepository (unchanged)
├── vectors/
│   └── store.py        # VectorStore (ChromaDB wrapper, unchanged)
├── search/
│   ├── service.py      # SearchService — section filter predicate [MODIFIED]
│   ├── hybrid.py       # reciprocal_rank_fusion() (unchanged)
│   └── models.py       # SearchResult dataclass (unchanged)
├── mcp/
│   ├── server.py       # FastMCP app instance (unchanged)
│   └── tools.py        # Tool registrations [MODIFIED: new tool + format fix]
├── embeddings/
│   └── client.py       # DatabricksEmbedder (unchanged)
├── ingest.py           # Pipeline orchestrator (unchanged)
├── models.py           # Book, Chunk, ContentType (unchanged)
└── cli.py              # Typer CLI (unchanged)
```

## Architectural Patterns

### Pattern 1: Impl/Tool Split for Testability

Each MCP tool in `mcp/tools.py` delegates to a `_<name>_impl()` function. The `@mcp.tool` decorator registers the public-facing tool; tests call the impl directly. This keeps tool logic testable without a live MCP server.

The new `get_book_structure` tool must follow this pattern: a `_get_book_structure_impl(book_id: str) -> str` function holds the logic, and the decorated `get_book_structure` tool delegates to it. All 7 existing tools follow this pattern exactly.

### Pattern 2: Post-Filter with Over-Fetch

Section filtering is applied in Python after database retrieval. `SearchService.search()` over-fetches 3x when a `section` filter is active to compensate for post-filter reduction. This is already implemented and does not change for v1.3. The only change is making the filter predicate also match the joined path string.

```python
# Current in search/service.py (leaf element match only):
any(section_lower in s.lower() for s in r.section_path)

# v1.3 (also matches joined hierarchy string):
joined = " > ".join(r.section_path).lower()
(section_lower in joined) or any(section_lower in s.lower() for s in r.section_path)
```

### Pattern 3: Lazy Service Initialization

All database connections and embedding clients are initialized on first use. MCP tools use module-level `_search_service: SearchService | None = None` guards with `_get_search_service()` / `_get_book_repo()` / `_get_chunk_repo()` accessors.

The new `get_book_structure` tool needs only `ChunkRepository` and `BookRepository` access. Use the existing `_get_chunk_repo()` and `_get_book_repo()` accessors — no new initialization pattern needed.

### Pattern 4: ContentBlock as Intermediate IR

`ContentBlock` is an internal data class that lives only between parsing and chunking. It is never persisted. Fixes in `content.py` and `metadata.py` are fully isolated upstream changes with no effect on the storage schema or search layer.

## Data Flow

### Ingest Flow (parse → store → embed)

```
epub_path
    ↓
EPUBParser.parse()
    ├── epub/metadata.py: extract_metadata() → Book
    │   └── _extract_authors()           [FIX] strip semicolons, trailing delimiters
    └── epub/content.py: extract_content(epub_book, toc_mapping)
        ├── Per spine item: section_path = toc_mapping.get(href, [])
        │   └── If empty:                [FIX] heuristic front-matter label from filename
        └── _extract_blocks_from_element()
            └── _normalize_text()        [FIX] fix word-joining artifacts from tag boundaries
                ↓
            [ContentBlock, ...]
                ↓
Chunker.chunk() → [Chunk, ...]     (unchanged)
    ↓
BookRepository.add(book)           (unchanged)
ChunkRepository.add_many(chunks)   (unchanged)
    ↓
embed_book() → VectorStore.add()   (unchanged)
```

### Search Flow (query → results)

```
search_books(query, section=..., context_window=...)
    ↓
SearchService.search()
    ├── FTS5: ChunkRepository.search_fts()
    ├── Semantic: VectorStore.query() + DatabricksEmbedder.embed_one()
    ├── RRF fusion: reciprocal_rank_fusion()
    ├── Section post-filter:    [FIX] match against full hierarchy path string
    │   (currently: per-element substring; add: joined-path substring)
    ├── Diversity re-ranking
    └── Context expansion: _expand_result_context()
        ↓
_format_search_results() or _format_enriched_results()  [FIX context clarity]
    ↓
Markdown string → MCP response
```

### New: get_book_structure Flow

```
get_book_structure(book_id)
    ↓
_get_book_structure_impl(book_id)
    ↓
BookRepository.get(book_id)             ← verify book exists, get title
ChunkRepository.get_by_book(book_id)    ← returns chunks in sequence order
    ↓
[deduplicate section_path values preserving first-appearance order]
[render as indented markdown hierarchy]
    ↓
Markdown structure listing → MCP response
```

## v1.3 Integration Points

### Feature 1: Fix EPUB Text Parsing Artifacts

**File:** `src/mnemo/epub/content.py`
**Function:** `_normalize_text()` and text accumulation in `_extract_blocks_from_element()`
**Change type:** Modification — no API change, no schema change

The current `_normalize_text()` collapses multiple whitespace with `re.sub(r"\s+", " ", text)` but does not prevent word-joining artifacts. Artifacts arise from two sources:

1. **NavigableString concatenation:** In `_extract_blocks_from_element()`, bare `NavigableString` children are stripped and appended to `current_text_parts`. If an inline element like `<strong>` or `<em>` is followed by punctuation in a sibling `NavigableString`, the stripping removes any whitespace that separated them.

2. **Inline element text:** For non-structural elements (anything that falls through to `child.get_text(strip=True)`), adjacent inline elements can produce `"wordA" + "wordB"` without a space separator.

**Fix strategy:** When appending to `current_text_parts`, always use a space-delimited join rather than relying on the source HTML to preserve spaces around inline tags. The `_normalize_text(" ".join(current_text_parts))` call at flush time already handles collapsing multiple spaces, so adding extra spaces is safe.

Specifically: change `current_text_parts.append(text)` to check whether the accumulated buffer already ends with a word character before appending — or more simply, always append with a leading space and let `_normalize_text` collapse it.

**Impact:** Only affects new ingests. Existing indexed books retain their current content until force re-ingested.

### Feature 2: Clean Author Name Parsing

**File:** `src/mnemo/epub/metadata.py`
**Function:** `_extract_authors()`
**Change type:** Modification — no API change, no schema change

Some EPUBs encode multiple authors as a single semicolon-delimited `dc:creator` string (e.g., `"Alice Smith; Bob Jones;"`) rather than separate fields. The current code returns this as one author string in the list.

**Fix:** After extracting raw creator strings, split on `;`, strip each part, and filter empty strings. Apply before the empty-list fallback:

```python
def _extract_authors(epub_book: epub.EpubBook) -> list[str]:
    creators = epub_book.get_metadata("DC", "creator")
    if creators:
        raw = [str(c[0]).strip() for c in creators if c and c[0]]
        authors: list[str] = []
        for r in raw:
            if ";" in r:
                authors.extend(p.strip() for p in r.split(";") if p.strip())
            else:
                if r:
                    authors.append(r)
        if authors:
            return authors
    logger.warning("Missing author metadata. Using 'Unknown'")
    return ["Unknown"]
```

**Impact:** `Book.authors: list[str]` field is unchanged. No DB schema change. Only metadata extraction behavior changes.

### Feature 3: Detect Front-Matter / TOC Section Labels

**Files:** `src/mnemo/epub/content.py` (primary), `src/mnemo/epub/parser.py` (secondary)
**Change type:** Modification — behavior change, no API change, no schema change

**Root cause:** When `toc_mapping.get(href, [])` returns an empty list for spine items not represented in the TOC (cover pages, copyright pages, TOC document itself), chunks from those items get `section_path = []`. In the MCP output, this renders as "Unknown section".

**Fix strategy — two-part:**

**Part A (content.py):** In `extract_content()`, after resolving `section_path = toc_mapping.get(href, [])`, apply a heuristic label when empty based on the spine item's filename stem:

```python
FRONT_MATTER_STEMS = {
    "cover", "toc", "contents", "title", "copyright",
    "preface", "intro", "introduction", "front", "colophon",
    "dedication", "acknowledgments", "foreword",
}

if not section_path:
    stem = Path(href).stem.lower()
    # Exact stem match
    if stem in FRONT_MATTER_STEMS:
        section_path = [stem.title()]
    # Prefix match (e.g., "cover01", "toc-en")
    elif any(stem.startswith(s) for s in FRONT_MATTER_STEMS):
        matched = next(s for s in FRONT_MATTER_STEMS if stem.startswith(s))
        section_path = [matched.title()]
    else:
        # Use filename stem as fallback (better than nothing)
        section_path = [Path(href).stem]
```

**Part B (parser.py):** Verify that `_parse_epub3_nav()` and `_parse_epub2_ncx()` are not silently dropping TOC nav entries that lack fragment-stripped hrefs. The current code does `href = href.split("#")[0]` — if that results in an empty string, the entry is skipped. This can cause front-matter entries that ARE in the nav to be missed. Add a guard: only skip if the link text is also empty.

**Impact:** Improves `section_path` quality for previously-empty-path chunks. No schema change. Existing books unaffected until force re-ingested.

### Feature 4: Section Filter Matches Full Hierarchy Path

**File:** `src/mnemo/search/service.py`
**Function:** `SearchService.search()` — section post-filter predicate
**Change type:** Modification — behavior change, no API change, no schema change

**Current behavior** (line ~136):
```python
results = [
    r for r in results
    if r.section_path and any(section_lower in s.lower() for s in r.section_path)
]
```

This iterates each element of `section_path` individually. For a chunk with path `["Chapter 3", "Generators"]`:
- `section="Chapter 3"` → matches (found in element 0)
- `section="Generators"` → matches (found in element 1)
- `section="Chapter 3 > Generators"` → no match (the joined string is never checked)

**Fix:** Also match against the joined path string, which is how users naturally express hierarchy in section queries:

```python
def _matches_section(section_lower: str, section_path: list[str]) -> bool:
    if not section_path:
        return False
    # Match any individual level
    if any(section_lower in s.lower() for s in section_path):
        return True
    # Match joined hierarchy (e.g., "chapter 3 > generators")
    joined = " > ".join(section_path).lower()
    return section_lower in joined

results = [r for r in results if _matches_section(section_lower, r.section_path)]
```

Extracting this as a helper function (`_matches_section`) keeps the filter logic testable in isolation.

**Impact:** Pure Python predicate change. No storage, schema, or API changes. The 3x over-fetch when `section` is active remains as-is.

### Feature 5: New `get_book_structure` MCP Tool

**File:** `src/mnemo/mcp/tools.py`
**Change type:** Addition — new `_get_book_structure_impl()` function + new `@mcp.tool` registration
**Dependencies:** `ChunkRepository.get_by_book()` (existing), `BookRepository.get()` (existing)

**Data already available:** `Chunk.section_path: list[str]` contains the full hierarchy for every chunk. `Chunk.sequence` gives document order. All section structure for a book is recoverable by iterating chunks in sequence order and collecting unique `section_path` values.

**Algorithm:**

```python
def _get_book_structure_impl(book_id: str) -> str:
    if not book_id or len(book_id) != 6:
        return "Error: book_id must be a 6-character identifier"
    try:
        book_repo = _get_book_repo()
        book = book_repo.get(book_id)
        if not book:
            return f"Error: Book not found: {book_id}"

        chunk_repo = _get_chunk_repo()
        chunks = chunk_repo.get_by_book(book_id)

        if not chunks:
            return f"Error: No chunks found for book: {book_id}"

        # Collect unique section paths in document order, track first-appearing seq
        seen: set[tuple[str, ...]] = set()
        sections: list[tuple[list[str], int]] = []  # (path, first_seq)
        for chunk in chunks:
            key = tuple(chunk.section_path)
            if key not in seen:
                seen.add(key)
                sections.append((chunk.section_path, chunk.sequence))

        # Render as indented markdown
        lines = [f"## {book.title}", "", f"**{len(chunks)} chunks** across **{len(sections)} sections**", ""]
        for path, seq in sections:
            depth = len(path) - 1
            indent = "  " * depth
            label = path[-1] if path else "(unlabeled)"
            lines.append(f"{indent}- **{label}** (seq {seq})")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("get_book_structure failed")
        return f"Error: {e}"
```

**Tool registration:**

```python
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def get_book_structure(book_id: str) -> str:
    """Browse the section hierarchy of a book.

    Returns all sections in reading order, indented by hierarchy depth.
    Use this to discover section names for use with search_books(section=...)
    or to find sequence numbers for get_book_chunks.

    Args:
        book_id: 6-character book identifier (from list_available_books)

    Returns:
        Indented markdown list of sections with sequence numbers,
        or an error message starting with "Error:"
    """
    return _get_book_structure_impl(book_id)
```

**No new dependencies.** `ChunkRepository.get_by_book()` already exists and returns chunks in sequence order. No new DB queries or methods needed.

**Output example:**
```
## Python Cookbook

**5135 chunks** across **48 sections**

- **Cover** (seq 0)
- **Table of Contents** (seq 2)
- **Chapter 1: Getting Started** (seq 5)
  - **Installation** (seq 8)
  - **Hello World** (seq 12)
- **Chapter 2: Data Structures** (seq 18)
  ...
```

### Feature 6: Context Window Visual Delineation

**File:** `src/mnemo/mcp/tools.py`
**Function:** `_format_enriched_results()`
**Change type:** Modification — output format only, no logic change

The current `_format_enriched_results()` already marks chunks as `**>>> MATCHED (seq N) <<<**` or `*[context, seq N]*`. The issue is that when context chunks precede the match, the result header (Source, Book ID, Type) appears above the context chunks, making it ambiguous which chunk triggered the result.

**Enhancement:** Add a summary line immediately after the result header naming the matched sequence number, so the reader knows what to look for:

```python
# After the header block, before iterating chunks:
match_seqs = sorted(
    chunk.sequence for chunk in exp["chunks"] if chunk.id in matched_ids
)
seq_str = ", ".join(f"seq {s}" for s in match_seqs)
lines.append(f"*Match: {seq_str} | Context: ±{len(exp['chunks']) - len(matched_ids)} chunks*")
lines.append("")
```

This is a pure formatting change with no impact on search logic or data flow.

## New vs Modified: Summary

| Component | Status | Scope |
|-----------|--------|-------|
| `epub/content.py` — `_normalize_text()` / text accumulation | Modified | Fix word-joining across HTML tag boundaries |
| `epub/content.py` — `extract_content()` | Modified | Heuristic front-matter labels for empty section paths |
| `epub/metadata.py` — `_extract_authors()` | Modified | Split semicolon-delimited author strings |
| `epub/parser.py` — `_parse_epub3_nav()` / `_parse_epub2_ncx()` | Modified (minor) | Guard against empty href dropping valid front-matter entries |
| `search/service.py` — `SearchService.search()` | Modified | Section filter also matches joined hierarchy path string |
| `mcp/tools.py` — `_get_book_structure_impl()` + `get_book_structure` | New | New tool for section hierarchy browsing |
| `mcp/tools.py` — `_format_enriched_results()` | Modified | Add match sequence summary line for context clarity |

**No new files.** No schema changes (SQLite or ChromaDB). No new dependencies. No changes to `models.py`, `chunker.py`, `ingest.py`, `repository.py`, `store.py`, or `hybrid.py`.

## Build Order

Dependencies flow from parse layer inward. The features are largely independent but share test infrastructure. Build order reflects both dependency and risk:

**1. Author normalization** (`metadata.py` `_extract_authors`)
Smallest change. Fully isolated to metadata extraction. Easy to unit test with known semicolon-delimited strings. Zero downstream effects — `Book.authors: list[str]` interface is unchanged.

**2. Text whitespace fix** (`content.py` text accumulation / `_normalize_text`)
Isolated to parser. Verified with content extraction tests against known artifact-producing HTML patterns. No effect on already-indexed books.

**3. Front-matter section labels** (`content.py` `extract_content` + minor `parser.py` guard)
Builds on understanding from #2 (same module). Still isolated to parse layer. Verify the full set of front-matter filename patterns needed with the actual book collection before finalizing the `FRONT_MATTER_STEMS` set.

**4. Section filter hierarchy** (`search/service.py`)
Pure predicate change. No storage dependency. Unit test with synthetic `SearchResult` objects having multi-level `section_path`. Independent of parse fixes but benefits from #3 producing better labels.

**5. `get_book_structure` MCP tool** (`mcp/tools.py`)
Depends on `ChunkRepository.get_by_book()` (already exists) and `section_path` quality (benefits from #3). Implement after parse fixes so the structure tool reflects improved labels for front-matter items.

**6. Context window formatting** (`mcp/tools.py` `_format_enriched_results`)
Pure output formatting. No logic dependencies. Can be done in any order, placed last because it has zero risk and lowest value — any ordering is fine.

## Anti-Patterns

### Anti-Pattern 1: Adding Schema Fields for Section Labels

**What people do:** Add a `section_label` or `section_level` column to the chunks table to support hierarchy queries, or change the `section_path` JSON structure.

**Why it's wrong:** The `section_path: list[str]` already encodes the full hierarchy. ChromaDB also stores it as a joined string. Any schema change requires a migration script and invalidates existing indexed books. The content in the field needs improvement; the structure of the field does not.

**Do this instead:** Fix the upstream parser to produce better section labels for front-matter. Fix the search filter to match against the joined string. The data model is correct.

### Anti-Pattern 2: New Repository Method for Structure Browsing

**What people do:** Add a `get_unique_sections(book_id)` method to `ChunkRepository` using `SELECT DISTINCT section_path`.

**Why it's wrong:** `section_path` is stored as a JSON string. `DISTINCT` works on string equality, but ordering by first document appearance requires `GROUP BY + MIN(sequence)` — more complex than Python-side deduplication. For a personal library with thousands of chunks per book, Python iteration over the `get_by_book()` result is trivially fast.

**Do this instead:** Use the existing `ChunkRepository.get_by_book()` and deduplicate `section_path` in the impl function using a `set` of tuples while preserving insertion order.

### Anti-Pattern 3: Auto-Triggering Re-Embedding on Parse Fixes

**What people do:** Automatically queue re-embedding for existing books when parser behavior changes.

**Why it's wrong:** Re-embedding is expensive (Databricks API calls). Author normalization does not affect chunk content or embeddings at all. Text normalization changes require full re-ingest of the EPUB from scratch. The user should control when to pay this cost.

**Do this instead:** Document that parse fixes apply to newly-ingested books. Offer `mnemo add --force <path>` as the explicit mechanism for a user who wants to re-index a specific book after a fix.

## Integration Points

### Internal Boundaries

| Boundary | Communication | Notes for v1.3 |
|----------|---------------|----------------|
| `epub/parser.py` ↔ `epub/metadata.py` | `extract_metadata(epub_path)` → `Book` | Author fix is in `_extract_authors()` inside `metadata.py` |
| `epub/parser.py` ↔ `epub/content.py` | `extract_content(epub_book, toc_mapping)` | `toc_mapping` is the key contract. Front-matter fix applies in `content.py` when `toc_mapping.get(href)` returns empty |
| `ingest.py` ↔ `epub/` | `EPUBParser.parse()` → `(Book, [ContentBlock])` | Parse fixes are transparent to `ingest.py` |
| `search/service.py` ↔ `storage/` | `ChunkRepository`, `BookRepository` via lazy init | Section filter predicate change is internal to `SearchService.search()` |
| `mcp/tools.py` ↔ `storage/` | `_get_book_repo()`, `_get_chunk_repo()` accessors | New `get_book_structure` tool uses both existing accessors |
| `mcp/tools.py` ↔ `search/service.py` | `SearchService.search()` | Unchanged for v1.3; format fix is in `_format_enriched_results()` only |

### Key Contract: toc_mapping

`toc_mapping: dict[str, list[str]]` built by `EPUBParser._parse_toc()` maps EPUB spine item hrefs to their section hierarchy paths. It is the single point of truth for section attribution in the parse pipeline. Front-matter fixes (Feature 3) operate on the output of `toc_mapping.get(href, [])` — they do not change how the map is built, just what happens when the lookup returns empty.

### Key Contract: section_path

`Chunk.section_path: list[str]` is persisted through SQLite and ChromaDB metadata. The section filter, context expansion boundary logic, and the new `get_book_structure` tool all read from this field. Parse layer improvements in Features 1-3 feed forward into better quality values in this field for newly-ingested books. No consistency issues arise because existing chunks retain their original (pre-fix) values.

## Sources

- Direct source code analysis: `src/mnemo/epub/`, `src/mnemo/search/`, `src/mnemo/mcp/`, `src/mnemo/storage/`, `src/mnemo/models.py`, `src/mnemo/ingest.py`
- Project context: `.planning/PROJECT.md`
- Confidence: HIGH — all claims grounded in current source code reviewed in this session

---
*Architecture research for: Mnemo v1.3 Quality & Polish milestone*
*Researched: 2026-03-12*
