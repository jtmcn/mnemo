# Project Research Summary

**Project:** Mnemo v1.3 Quality & Polish
**Domain:** EPUB parsing correctness, section hierarchy, and MCP tool surface expansion
**Researched:** 2026-03-12
**Confidence:** HIGH

## Executive Summary

Mnemo v1.3 is a parser correctness and MCP surface milestone for an existing, fully functional personal RAG book library. The system already has hybrid search, context window expansion, section filtering, and 7 MCP tools — all built on a well-understood stack of BeautifulSoup, ebooklib, SQLite, ChromaDB, and FastMCP. The research across all four files reaches the same conclusion: every v1.3 feature can be implemented using the current stack with zero new runtime dependencies. The work is confined to five source files (`content.py`, `metadata.py`, `parser.py`, `service.py`, `tools.py`) and involves no schema changes, no new dependencies, and no vector re-embedding in the hot path.

The recommended approach is to address features in parse-layer-first order: fix text artifact cleanup and author normalization (fully isolated to the parser layer), then front-matter section detection (same parse layer, slightly more logic), then the section filter predicate change (trivial one-function change in `service.py`), then the new `get_book_structure` MCP tool (new tool following existing patterns exactly), and finally context window visual formatting (pure output formatting, no logic risk). This ordering minimizes risk by fixing the data quality issues before building the display tool that depends on that data quality.

The critical risk for this milestone is inadvertent scope creep in the whitespace normalization fix: if `_normalize_text()` is called on code blocks, indentation is silently destroyed. Every feature also has a migration consideration — parser fixes only improve newly-ingested (or force-re-ingested) books; existing indexed books retain their current section paths until the user explicitly re-indexes. These are well-understood, documented behaviors that do not require defensive architecture changes, only clear documentation and targeted regression tests.

## Key Findings

### Recommended Stack

No dependency changes are needed for v1.3. The entire milestone is achievable with the existing stack: BeautifulSoup 4.14.x (using the `separator=" "` parameter on `get_text()` that has existed since 4.x), Python stdlib `re` (for author delimiter splitting and front-matter label matching), sqlite3 stdlib (for the `get_book_structure` query), and FastMCP 2.14.x (for new tool registration). The `<3` pin on FastMCP must be maintained — FastMCP 3.x introduced breaking API changes and is out of scope.

**Core technologies (unchanged):**
- `beautifulsoup4>=4.12` (currently 4.14.3): HTML parsing — `get_text(separator=" ", strip=True)` is the canonical fix for joined-word artifacts; confirmed in official BS4 docs and Launchpad bug #1768330
- `ebooklib>=0.18` (currently 0.20): EPUB reading — `.toc`, `.get_metadata()`, `.get_items()` API is unchanged across 0.18–0.20
- `fastmcp>=2.14,<3` (currently 2.14.5): MCP tool registration — `str` return type, `ToolAnnotations`, impl/tool split pattern all stable in 2.x
- `re` (stdlib): Author delimiter splitting and front-matter filename heuristics — no external library needed
- `sqlite3` (stdlib): `get_book_structure` section hierarchy query — `section_path` JSON column already indexed

### Expected Features

Research confirms all six features are well-scoped with unambiguous root causes verified by direct codebase inspection.

**Must have (table stakes — fixes observable bugs):**
- **EPUB text artifact cleanup** — `get_text(strip=True)` on inline elements joins adjacent words without a space separator; fix is `get_text(separator=" ")` at text-accumulation call sites in `content.py`; every real-world EPUB is affected
- **Author name normalization** — `dc:creator` fields with semicolon-delimited multiple authors (e.g., `"Smith, Alice; Jones, Bob;"`) are stored as a single garbled string; fix is `re.split(r"\s*;\s*", raw)` in `_extract_authors()` with trailing delimiter stripping
- **Front-matter section detection** — Spine items absent from the TOC map get `section_path = []` which renders as "Unknown section"; fix is filename-stem heuristics in `content.py:extract_content()` covering cover, toc, copyright, preface, intro, colophon, dedication patterns
- **Section filter hierarchy traversal** — Section filter only checks individual path segments, not the joined path string; one-line fix joining `section_path` with ` > ` and matching against the assembled string

**Should have (UX differentiators):**
- **Context window result clarity** — `_format_enriched_results()` uses bold vs. italic markers that are visually indistinct in rendered markdown; add a match summary line with `---` separator and relative context chunk position labels
- **`get_book_structure` MCP tool** — No way to browse a book's section hierarchy without running a search; new tool queries distinct `section_path` values from SQLite and renders as indented markdown; enables pre-search orientation in Claude

**Defer to v2+:**
- Re-embedding workflow automation (expensive, belongs to user-initiated `--force` re-ingest)
- Author format normalization ("Last, First" rearrangement — correctness risk outweighs benefit)
- `book_sections` caching table (premature optimization at personal library scale)
- FastMCP 3.x upgrade (breaking API changes, no v1.3 feature requires 3.x capabilities)

### Architecture Approach

The architecture is already well-structured with clear layer separation: ingest pipeline (parse → chunk → store → embed), storage layer (SQLite + ChromaDB), search/query layer, and MCP interface layer. All v1.3 changes are confined to existing modules with no new files, no schema migrations, and no cross-layer boundary changes. The key architectural pattern to follow is the impl/tool split: every MCP tool delegates to a `_<name>_impl()` function for testability, and all tools return `str` (markdown). The new `get_book_structure` tool must read exclusively from SQLite — never re-parse the EPUB — to ensure the structure output matches what search results actually return.

**Major components and v1.3 change scope:**
1. `epub/content.py` — Modified: `get_text(separator=" ")` fix + front-matter section label heuristics
2. `epub/metadata.py` — Modified: semicolon-split author normalization in `_extract_authors()`
3. `epub/parser.py` — Minor modification: guard against empty href in TOC nav parsing
4. `search/service.py` — Modified: section filter predicate extracts to `_matches_section()` helper, adds joined-path match
5. `mcp/tools.py` — Modified + new: `_format_enriched_results()` formatting fix + `_get_book_structure_impl()` + `get_book_structure` tool registration

### Critical Pitfalls

1. **Whitespace normalization applied to code blocks** — `_normalize_text()` with `re.sub(r"\s+", " ", text)` destroys Python indentation and YAML structure silently; guard every normalization call with `if block.content_type == ContentType.TEXT`; add regression test parsing a book with Python code blocks and asserting indentation is preserved
2. **Author normalization changes book ID on re-index** — `Book.generate_id()` hashes on `primary_author`; if `"Smith, Alice;"` normalizes to `"Smith, Alice"`, re-indexing produces a new ID; document this behavior explicitly — it is acceptable but users must be aware
3. **`get_book_structure` reads EPUB instead of SQLite** — Re-parsing the EPUB file bypasses the indexed data, produces mismatched output vs. search results, and fails if the EPUB has been moved; implement exclusively from `SELECT DISTINCT section_path FROM chunks WHERE book_id = ?`
4. **Missing `ToolAnnotations` on new MCP tool** — FastMCP accepts tool registration without annotations (no runtime error); missing `readOnlyHint=True` affects Claude's auto-invocation behavior; add to `TestToolAnnotations` test class at the same time as implementation
5. **Section path split state across old and new books** — Parser fixes only apply to newly-ingested books; existing books retain old `section_path` values until force-reindexed; the section filter substring match is resilient enough to handle both states, but the library is heterogeneous until the user re-indexes

## Implications for Roadmap

Based on research, the natural grouping is three phases following parse-layer-first dependency order.

### Phase 1: Parser Quality Fixes

**Rationale:** Text artifact cleanup, author normalization, and front-matter detection are all parse-layer changes with no downstream dependencies. They share the same test infrastructure (`test_epub_parser.py`) and should be done together to justify one re-ingest pass for existing books. Author normalization is the smallest and lowest-risk; the text fix has the highest user-visible impact; front-matter detection builds on the same module context.

**Delivers:** Clean, correctly parsed EPUBs — no joined words, no garbled multi-author strings, no "Unknown section" labels for front-matter items

**Addresses:**
- EPUB text artifact cleanup (table stakes)
- Author name normalization (table stakes)
- Front-matter section detection (table stakes)

**Avoids:**
- Pitfall #1: Gate `_normalize_text()` to `ContentType.TEXT` only — code blocks must be explicitly excluded
- Pitfall #2: Document that re-indexing with `force=True` may produce a new book ID for books with malformed author metadata

**Research flag:** Standard patterns — no deeper research needed. All fixes are verified against the codebase with HIGH confidence.

### Phase 2: Search Filter and MCP Tool

**Rationale:** The section filter fix and `get_book_structure` tool both read from `section_path` data. Doing them after Phase 1 means the tool reflects improved labels for front-matter items, and the filter predicate is correct before the new tool ships. The filter fix is a trivial one-function extraction; the new tool is the slightly larger scope item.

**Delivers:** Section filtering that matches multi-level hierarchy paths, and a new `get_book_structure` tool for pre-search book orientation

**Addresses:**
- Section filter hierarchy traversal (table stakes differentiator)
- `get_book_structure` MCP tool (should have)

**Uses:**
- `ChunkRepository.get_by_book()` (existing) — no new repository methods needed
- `sqlite3` GROUP BY section_path query (stdlib)
- FastMCP 2.14.x `@mcp.tool` + `ToolAnnotations` (existing pattern)

**Avoids:**
- Pitfall #3: Read `get_book_structure` from SQLite only; never re-parse EPUB
- Pitfall #4: Add `get_book_structure` to `TestToolAnnotations` in the same PR
- Pitfall #5: Section filter substring match is resilient to split state across old/new books

**Research flag:** Standard patterns — impl/tool split, ToolAnnotations, and SQLite query patterns are all well-established in this codebase.

### Phase 3: Output Formatting

**Rationale:** Context window result clarity is a pure formatting change with no logic dependencies and zero data risk. It is placed last because it requires visual QA in Claude Desktop to validate, and it has the lowest risk profile of all six features — doing it last prevents it from blocking Phase 1 or Phase 2 delivery.

**Delivers:** Visually unambiguous distinction between matched chunks and context chunks in enriched search results

**Addresses:**
- Context window result clarity (should have)

**Research flag:** Standard patterns — formatting-only change to `_format_enriched_results()`, no research needed.

### Phase Ordering Rationale

- **Parse layer first** because text and section quality improvements flow forward into every downstream feature (search, structure browsing, display)
- **Filter and tool together** because they share the same data contract (`section_path`) and should be tested together to verify the filter predicate matches what `get_book_structure` shows
- **Formatting last** because it has zero logical dependencies, zero risk, and needs manual visual validation that is independent of correctness work

### Research Flags

All three phases can skip `/gsd:research-phase` during planning — all implementation details, including exact function signatures, SQL queries, and code snippets, are documented in the individual research files.

Phases with standard patterns (skip research-phase):
- **Phase 1:** HIGH confidence from direct codebase inspection; BeautifulSoup `separator` parameter is the canonical documented fix; stdlib `re` is fully sufficient for author normalization
- **Phase 2:** HIGH confidence; all data structures already exist; impl/tool split pattern is established across 7 existing tools
- **Phase 3:** HIGH confidence; pure formatting change with no architecture decisions

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new dependencies; all fixes use existing packages at already-pinned versions; BeautifulSoup `separator` param confirmed in official docs and Launchpad bug report |
| Features | HIGH | All root causes verified by direct source code inspection; root causes are unambiguous in every case |
| Architecture | HIGH | Full pipeline traced from parse layer through storage to MCP surface; all integration boundaries confirmed by reading actual source files |
| Pitfalls | HIGH | Pitfalls derived from v1.2 source analysis; test patterns confirmed by reading existing test files; recovery paths verified against `ingest.py` logic |

**Overall confidence:** HIGH

### Gaps to Address

- **Front-matter filename stem coverage:** The `FRONT_MATTER_STEMS` set covers common patterns, but the actual book collection may have publisher-specific naming conventions. Validate against the real EPUB files in the library before finalizing the set during Phase 1 implementation.
- **`epub:type` attribute as a signal:** EPUB3 uses `epub:type` semantic attributes (cover, toc, frontmatter, colophon) for front-matter detection. The current plan uses filename heuristics as the primary approach. During Phase 1 implementation, check whether the actual EPUBs in the library use `epub:type` attributes — if they do, this is a more reliable signal than filename stems.
- **Context window formatting validation:** Phase 3 requires visual QA in Claude Desktop. No automated test can fully validate markdown rendering differences. This feature requires a manual review step before considering it done.

## Sources

### Primary (HIGH confidence — official documentation)
- [BeautifulSoup get_text() docs](https://beautiful-soup-4.readthedocs.io/en/latest/) — `separator` and `strip` parameters
- [BeautifulSoup Launchpad bug #1768330](https://bugs.launchpad.net/bugs/1768330) — `separator=" "` as canonical fix for joined words
- [FastMCP Tools documentation](https://gofastmcp.com/servers/tools) — return type handling, `str` serialization, tool annotations
- [EPUB3 Structural Semantics Vocabulary](https://www.w3.org/TR/epub-ssv/) — `epub:type` values for front/back matter detection
- [EPUB3 Navigation Document spec](https://www.w3.org/TR/epub-nav/) — nav element structure
- [FastMCP PyPI](https://pypi.org/project/fastmcp/) — 2.14.5 latest 2.x; 3.1.0 latest overall (breaking, excluded by `<3` pin)

### Primary (HIGH confidence — codebase inspection)
- `src/mnemo/epub/content.py` — `get_text(strip=True)` call sites, `_normalize_text()`, text accumulation pattern
- `src/mnemo/epub/metadata.py` — `_extract_authors()` current implementation
- `src/mnemo/epub/parser.py` — `_parse_epub3_nav()`, `_parse_epub2_ncx()`, `_infer_from_headings()`, TOC mapping gaps
- `src/mnemo/search/service.py` — section filter logic (line 135–139), over-fetch behavior
- `src/mnemo/storage/repository.py` — `ChunkRepository` existing methods, `section_path` column access
- `src/mnemo/mcp/tools.py` — impl/tool split pattern, `ToolAnnotations` pattern, all tools return `str`
- `src/mnemo/models.py` — `Chunk.section_path: list[str]`, `Book.generate_id()` hash inputs
- `src/mnemo/ingest.py` — `force=True` re-index path, vector deletion/replacement logic
- `tests/test_mcp.py` — `TestToolAnnotations` class confirming annotation test pattern
- `tests/test_epub_parser.py` — existing test coverage confirming test infrastructure

---
*Research completed: 2026-03-12*
*Ready for roadmap: yes*
