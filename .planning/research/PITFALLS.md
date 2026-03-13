# Pitfalls Research

**Domain:** Adding EPUB text cleanup, author normalization, section hierarchy fixes, and new MCP tools to an existing book library system
**Researched:** 2026-03-12
**Confidence:** HIGH (based on direct codebase analysis of v1.2 source)

---

## Critical Pitfalls

### Pitfall 1: Whitespace Normalization Corrupts Code Block Content

**What goes wrong:**
The fix for joined words (e.g., "functionname" where a tag boundary ate the space) involves normalizing whitespace in text content. If the normalization logic is applied globally rather than scoped strictly to `ContentType.TEXT`, it will reach into code blocks and collapse significant whitespace. Python indentation, shell heredocs, YAML structure, aligned columns in config files — all are destroyed by `re.sub(r"\s+", " ", text)`. The bug is silent: the code block looks "cleaned up" but is semantically broken or unparseable.

**Why it happens:**
The current `_normalize_text()` in `content.py` (line 667) uses `re.sub(r"\s+", " ", text)` followed by `.strip()`. This is the right approach for prose. The risk is that a developer adds whitespace normalization higher in the call stack — e.g., as a post-processing step on all `ContentBlock.content` values after extraction — and the scope accidentally includes code blocks. It's also easy to call `_normalize_text()` in a helper that gets reused across content types.

**How to avoid:**
- Never call `_normalize_text()` on `ContentType.CODE`, `ContentType.DIAGRAM`, or `ContentType.TABLE` blocks.
- Gate normalization in `_extract_blocks_from_element` as it already does: text normalization only fires when flushing `current_text_parts` (prose accumulator), never when `_extract_code_block()` or `_table_to_text()` is called.
- If adding a new normalization pass (e.g., to fix joined words from inline HTML tags), add a guard: `if block.content_type == ContentType.TEXT: block.content = normalize(block.content)`.
- Add a regression test: parse an EPUB with a Python code block containing leading indentation; assert that indentation is preserved post-parse.

**Warning signs:**
- Code blocks in search results show no indentation
- Python snippets are syntactically invalid (IndentationError equivalent)
- YAML or Dockerfile examples lose their structure characters

**Phase to address:**
Text artifact cleanup phase. The guard must be in place before adding any new normalization logic.

---

### Pitfall 2: Author Normalization Changes the Book ID for Newly Re-Indexed Books

**What goes wrong:**
The `Book.generate_id()` method (models.py line 63) hashes `content_bytes + title + primary_author`. If author normalization strips trailing semicolons or trims whitespace so that `"Smith, Alice;"` becomes `"Smith, Alice"`, and a user re-indexes a book (e.g., with `force=True`), the new normalized author produces a different book ID. The old book ID is gone, the new book ID is different. Any saved references to the old book ID (e.g., Claude remembering "search book a7f3b2") are now stale. The user's library looks like it has two copies of the same book during the transition.

**Why it happens:**
`extract_metadata()` feeds raw author strings from EPUB metadata directly into `Book.from_metadata()`, which uses `primary_author` for ID generation before any normalization. The v1.3 fix normalizes authors in `_extract_authors()`. For existing books in the database, the stored authors were NOT normalized. If a user re-indexes, the ID changes. The v1.3 milestone explicitly stores epub_path for re-indexing — which makes this scenario realistic.

**How to avoid:**
- Normalization must happen in `_extract_authors()` at extraction time, consistently. This means ALL newly ingested books (and all re-indexed books) will use normalized authors.
- Document clearly: re-indexing a book after the author normalization fix may produce a new book ID if the old author string had trailing delimiters. This is acceptable since it only affects re-indexing, not the running library.
- Do NOT normalize authors in `update_book_metadata()` separately — normalization belongs at parse time, not at metadata update time. The `update_book_metadata` MCP tool allows manual corrections; those should be stored verbatim.
- Add a test: author string `"Smith, Alice;"` produces the same normalized result as `"Smith, Alice"` from `_extract_authors()`.

**Warning signs:**
- `add_book(force=True)` on an existing book produces a new book ID
- `list_available_books` shows duplicate books after re-indexing
- Claude refers to a book by its old ID and gets "Book not found" errors

**Phase to address:**
Author normalization phase. Must include a note in the change that re-indexing may change IDs for books with malformed author metadata.

---

### Pitfall 3: Section Hierarchy Changes Silently Break Existing Search Filter Behavior

**What goes wrong:**
Currently, the section filter in `search_books` does a case-insensitive substring match: `section_lower in s.lower() for s in r.section_path`. The v1.3 work changes how `section_path` is assigned to front-matter and TOC items (from `[]` or `["Unknown section"]` to `["Front Matter"]`, `["Table of Contents"]`, etc.). If a user has saved Claude Desktop prompts or workflows that filter `section="Chapter"`, and the section path for chapter items changes due to the hierarchy fix (e.g., "Chapter 1" becomes "1. Introduction" because the TOC title changed), their filter breaks silently — it returns zero results, not an error.

Additionally, changing section hierarchy path assignment affects the context window expansion in `_expand_result_context()` (service.py line 214), which stops at section boundaries by comparing `section_path == matched_section`. If section paths become longer or differently structured, context expansion may become more conservative (stops sooner) or more aggressive (spans more content).

**Why it happens:**
Section path data is baked into stored chunks at ingest time (`section_path` JSON in SQLite). Parser changes only affect newly ingested books. Existing books in the library retain their old section paths. The library is in a split state: new books have the improved hierarchy, old books have "Unknown section" or empty paths. Section filter behavior differs between old and new books in the same search result.

**How to avoid:**
- Accept the split state explicitly: document that hierarchy improvements apply to re-indexed books only.
- The section filter substring match is robust enough to handle both old and new path styles (it does not require exact matches), so cross-library searches still work — they just return fewer results from books with "Unknown section" labels.
- For context window expansion: the section boundary check uses exact list equality (`section_path == matched_section`). This is unchanged behavior and unaffected by what the path values are — it is internally consistent per book.
- If the `get_book_structure` tool is added, it must read the stored section paths from SQLite (the actual ingested data), not reparse the EPUB. This ensures the tool reflects what was actually indexed.

**Warning signs:**
- `search_books(section="Chapter")` returns 0 results for books that haven't been re-indexed
- Context window expansion returns fewer chunks than expected for books with new hierarchy
- `get_book_structure` shows different hierarchy than what search results return (if tool reparses the EPUB)

**Phase to address:**
Section hierarchy phase. Accept the split state; document it. No re-indexing is required unless the user wants the improved labels.

---

### Pitfall 4: Re-Indexing Changes Chunk IDs, Breaking ChromaDB Consistency

**What goes wrong:**
Parser changes (whitespace normalization fixes, section path changes) alter the text content of chunks. Chunk IDs are UUIDs generated fresh at ingest time (see `Chunk.id = Field(default_factory=lambda: str(uuid.uuid4()))`). If a user re-indexes a book after the v1.3 parser changes, all new chunks get new UUID IDs. The old chunk UUIDs remain in ChromaDB until `store.delete_by_book(book_id)` is called. The `ingest_book(force=True)` path does call `store.delete_by_book(existing.id)` (ingest.py line 163) before the new book's old ID is deleted — but there's a subtlety: if the book ID also changes (see Pitfall 2), `delete_by_book(existing.id)` deletes vectors for the OLD book ID. The NEW book (different ID) then creates new vectors correctly. This works. However, if IDs are the SAME (no author normalization issue), the old vectors are deleted and replaced — that is also correct.

The risky scenario is partial failure: if `ingest_book(force=True)` succeeds in SQLite but the embedding step fails (network error), the old vectors were already deleted and the new chunks are not yet embedded. The system has chunks in SQLite with no vectors in ChromaDB. Keyword search works; semantic search returns nothing for that book.

**Why it happens:**
The ingest pipeline deletes old vectors before new ones are created. This is correct for the happy path but has no rollback for partial failure. The `add_book` MCP tool has cleanup logic (tools.py line 299) for the post-ingest failure case, but this cleanup uses `pipeline_remove` which deletes the SQLite record too — leaving the user with no book at all.

**How to avoid:**
- For v1.3 parser-only changes (text normalization, section paths), re-indexing is optional. Do not re-index unless the user specifically wants the improved text quality.
- When re-indexing IS done, keep the existing partial-failure behavior: if embedding fails, the `add_book` cleanup removes the SQLite record too (this is already implemented). This leaves the user with no book rather than a broken half-state. They can re-add.
- Document in the phase that re-indexing is optional for v1.3 changes (unlike v1.2 where metric change required it).

**Warning signs:**
- `search_books(mode="semantic")` returns no results for a book that was recently re-indexed
- `search_books(mode="keyword")` works but semantic mode returns empty
- ChromaDB has fewer documents than SQLite has chunks for a book

**Phase to address:**
Any phase that modifies parser output. Re-indexing guidance should be explicit in the phase documentation.

---

### Pitfall 5: New MCP Tool Missing ToolAnnotations Breaks Pattern Consistency

**What goes wrong:**
Every existing MCP tool has explicit `ToolAnnotations` (readOnlyHint, destructiveHint, idempotentHint, openWorldHint). The `TestToolAnnotations` test class in `test_mcp.py` verifies annotations on all existing tools. A new `get_book_structure` tool without annotations will cause the annotation test suite to fail — but only if the test is extended. If the developer forgets to extend the test, the tool ships without annotations. Claude Desktop and Claude Code use these hints to decide when to auto-invoke tools, so missing `readOnlyHint=True` on a read-only structural browsing tool may cause unnecessary confirmation prompts.

**Why it happens:**
`@mcp.tool()` with no `annotations=` parameter is valid FastMCP syntax — it simply omits hints. No runtime error occurs. The pattern is easy to miss when adding a new tool since the existing tools are spread across a long file (tools.py is 765 lines).

**How to avoid:**
- `get_book_structure` is read-only by nature (reads stored section paths, no side effects). Set `annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)`.
- Add a test case to `TestToolAnnotations` that verifies `get_book_structure` has `readOnlyHint=True`. This keeps the pattern enforced.
- The implementation pattern must follow the split used by all other tools: a `_get_book_structure_impl()` function (testable directly) and a thin `@mcp.tool()` wrapper that delegates to it.

**Warning signs:**
- `mcp._tool_manager._tools["get_book_structure"].annotations` is None at test time
- Tool is not in the `test_tools_registered` test list

**Phase to address:**
New MCP tool phase. Copy the annotation pattern from `get_book_chunks` (the most recent tool added).

---

### Pitfall 6: get_book_structure Tool Returns Stale Data If It Reparses the EPUB

**What goes wrong:**
There are two ways to implement `get_book_structure`: (a) read section paths from stored chunks in SQLite, or (b) re-parse the EPUB file from `book.epub_path`. Option (b) is tempting because it could show the "ideal" hierarchy. But option (b) has multiple failure modes: the EPUB may have moved or been deleted, the parser may return a different hierarchy than what was indexed (e.g., if the v1.3 parser changes are deployed after the book was indexed), and it bypasses the single-source-of-truth stored in SQLite. The tool would show a hierarchy that does not match what search results actually return.

**Why it happens:**
Developers think "I should show the correct book structure" and reach for re-parsing. The intent is correct but the implementation is wrong for a tool that informs search filtering — search works against indexed data, not the raw EPUB.

**How to avoid:**
- Implement `get_book_structure` exclusively from SQLite: `SELECT DISTINCT section_path FROM chunks WHERE book_id = ? ORDER BY sequence`.
- The stored `section_path` JSON column contains the exact paths that search filtering uses. This is the authoritative source.
- If `epub_path` is missing or the file no longer exists, the tool should still work (from SQLite).
- If returning a hierarchical tree, reconstruct it from the flat list of stored section paths, not from re-parsing.

**Warning signs:**
- `get_book_structure` output differs from the section paths shown in `search_books` results
- Tool fails for books whose EPUB file has been moved or deleted
- Tool shows "Chapter 1" but search results show "1. Introduction" for the same chapter

**Phase to address:**
New MCP tool phase. Read from SQLite from the beginning; never introduce EPUB re-parsing in this tool.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Apply whitespace normalization globally (all content types) | Simpler code, one call cleans everything | Destroys code block indentation silently | Never |
| Normalize authors in `update_book_metadata` instead of at parse time | Quick fix for display | Two separate normalization paths, inconsistent results | Never — normalization belongs at parse time |
| Re-parse EPUB in `get_book_structure` | Shows "real" hierarchy | Stale data vs. indexed data, EPUB may be gone | Never for a search-adjacent tool |
| Skip `ToolAnnotations` on new MCP tool | Saves 4 lines | Missing hints affect auto-invocation behavior in Claude Desktop | Never — the annotation is 4 lines and matters |
| Accept "Unknown section" in front-matter without labeling it | No work required | Search filter `section="Chapter"` accidentally pulls in front-matter | MVP only; fix it in v1.3 |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| FastMCP 2.0 tool registration | Adding a new tool that is `async` when the implementation is sync | Follow the pattern: only `add_book` is async (because it uses `asyncio.to_thread`). `get_book_structure` is a read-only sync tool — use `def`, not `async def` |
| FastMCP 2.0 tool registration | Importing `mcp` from `server.py` in a new file creates circular import | Follow existing pattern: define the tool in `tools.py` which already imports `mcp` from `server.py` |
| SQLite section_path query | Using `LIKE '%Chapter%'` on a JSON-stored array | `section_path` is stored as JSON text. LIKE works accidentally but is fragile. Better: load all section paths in Python and filter there, as `get_book_structure` will do |
| ChromaDB metadata `section_path` field | The metadata field is a joined string `"Part I > Chapter 1"`, not the JSON list | Section path filtering for search is done in Python post-retrieval (see service.py), NOT via ChromaDB metadata. Do not add new ChromaDB section filters |
| FTS5 content column | Adding new text fields to FTS5 table | The FTS5 table only indexes `content`. Section path labels are not FTS-indexed and should not be — they are structural metadata, not search content |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Loading all chunks to build section hierarchy for `get_book_structure` | Slow response for large books (500+ chunks) | Use `SELECT DISTINCT section_path FROM chunks WHERE book_id = ?` rather than loading full Chunk objects | Books with 500+ chunks; most technical books in this library |
| Calling `get_book_structure` and then `search_books` in sequence with large context window | Two round-trips to SQLite + ChromaDB for what feels like one user action | These are separate MCP tools by design; the overhead is acceptable at personal scale | Not a real concern at 10-book scale |
| Running `_normalize_text()` on every chunk at search display time (in formatter) | Search latency increases | Normalization belongs at ingest time, not at display time | Any time top_k > 5 |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| None relevant to this milestone scope | — | This milestone adds no new input surfaces, authentication, or file system access beyond what v1.2 already has |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| `get_book_structure` returns a flat list of section paths | Claude has to parse `"Part I > Chapter 1 > 1.1 Intro"` to understand hierarchy | Return a structured representation: unique top-level sections with their children, making hierarchy clear |
| Author normalization changes display name silently | User added book with author "Smith, Alice;" — after re-index it shows "Smith, Alice" — confusing if they remember the old form | This is a desirable fix, not a bug. No UX mitigation needed |
| Front-matter detection labels every unnamed section as "Front Matter" | A book with genuinely unknown sections (not TOC, not front matter) gets mislabeled | Only label as "Front Matter" when there is strong evidence: position before first real chapter, common front-matter filenames (cover, copyright, toc, preface, intro) |
| Section filter returns zero results on old-indexed books after hierarchy change | User thinks the book has no chapters | The section filter substring match is resilient enough — "Chapter" will still match "Chapter 1" labels. Only fails if section was previously empty (`[]`) and now has content. That is an improvement, not a regression |

---

## "Looks Done But Isn't" Checklist

- [ ] **Text normalization:** Verify code blocks from a real technical EPUB retain their indentation after the fix. Parse a book with Python code and assert the leading spaces are intact.
- [ ] **Author normalization:** Verify `"Smith, Alice; Jones, Bob;"` produces `["Smith, Alice", "Jones, Bob"]` (two authors, no trailing semicolons). Also verify a single author `"Knuth, Donald E."` is unchanged.
- [ ] **Front-matter detection:** Verify that a TOC item labeled "Table of Contents" gets section path `["Table of Contents"]`, not `["Unknown section"]`. Verify that a chapter labeled "Chapter 1" is NOT labeled as front-matter.
- [ ] **Section hierarchy:** Verify `section_filter="Chapter 1"` returns results from a book that was just re-indexed with the new hierarchy code. Verify it also returns results from an old book (not re-indexed) whose section paths already contain "Chapter 1".
- [ ] **get_book_structure tool:** Verify the tool is listed when `list_available_books` (tool list) is called. Verify it has `readOnlyHint=True`. Verify it returns the same section paths that appear in `search_books` results for the same book.
- [ ] **get_book_structure from SQLite only:** Move or rename an EPUB file after indexing; verify `get_book_structure` still works correctly for that book.
- [ ] **New tool registered:** Add `get_book_structure` to the `test_tools_registered` test assertion list.
- [ ] **Context window marker clarity:** Verify that search results with `context_window >= 1` clearly delineate match vs. context chunks in the formatted output.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Whitespace normalization damaged code blocks | HIGH | Re-index affected books with `add_book(force=True)` after the bug is fixed. Code block content is not recoverable from SQLite if overwritten — must re-parse from EPUB. |
| Author ID change after normalization fix | LOW | Old book still exists in DB with old ID. Re-index with `add_book(force=True)` to get normalized version, then `remove_book(old_id)` to clean up. |
| `get_book_structure` showing stale EPUB data | LOW | Reimplement to read from SQLite instead of re-parsing. No data change needed. |
| Missing ToolAnnotations on new tool | LOW | Add annotations and redeploy. No data change needed. |
| Partial re-index failure (chunks in SQLite, no vectors) | LOW | `add_book(force=True)` on the affected book to redo both parse and embed steps. |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| #1 Whitespace normalization corrupts code blocks | Text artifact cleanup phase | Parse a Python book; assert code block indentation is preserved |
| #2 Author normalization changes book ID on re-index | Author normalization phase | Test that `_extract_authors()` strips only trailing delimiters, not meaningful text |
| #3 Section hierarchy changes break existing filter behavior | Section hierarchy phase | Test section filter on books NOT re-indexed; confirm substring match still works |
| #4 Re-indexing changes chunk IDs, partial failure risk | Any phase that changes parser output | Test `force=True` re-index; confirm vectors exist for all chunks after successful ingest |
| #5 New MCP tool missing ToolAnnotations | New MCP tool phase | Add `get_book_structure` to `TestToolAnnotations` and `test_tools_registered` |
| #6 get_book_structure reads EPUB instead of SQLite | New MCP tool phase | Delete EPUB file, call `get_book_structure` — should still succeed |

---

## Sources

- Mnemo v1.2 codebase analysis: `epub/content.py`, `epub/metadata.py`, `mcp/tools.py`, `mcp/server.py`, `search/service.py`, `ingest.py`, `storage/repository.py`, `models.py` (HIGH confidence)
- `tests/test_mcp.py` `TestToolAnnotations` class — confirms annotation test pattern already exists (HIGH confidence)
- `tests/test_epub_parser.py` — confirms existing test coverage for metadata and content extraction (HIGH confidence)
- `.planning/PROJECT.md` v1.3 active requirements — whitespace normalization, author parsing, section labeling, hierarchy traversal, `get_book_structure` tool (HIGH confidence)
- Prior `.planning/research/PITFALLS.md` for v1.2 — informed integration gotcha patterns, reused relevant warnings (HIGH confidence)

---
*Pitfalls research for: Mnemo v1.3 Quality & Polish — EPUB cleanup, author normalization, section hierarchy, new MCP tool*
*Researched: 2026-03-12*
