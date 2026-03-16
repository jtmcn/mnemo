# Phase 12: Output Formatting - Research

**Researched:** 2026-03-13
**Domain:** MCP tool output formatting (Python, markdown string generation)
**Confidence:** HIGH

## Summary

Phase 12 has a single requirement (TOOL-02): context-window search results must visually distinguish matched chunks from surrounding context chunks so a human reviewing raw markdown output in Claude Desktop can identify the match at a glance.

The infrastructure for this is already substantially built. `_format_enriched_results` in `src/mnemo/mcp/tools.py` exists and is called when `context_window >= 1`. The function iterates over `exp["chunks"]`, prepends `**>>> MATCHED (seq N) <<<**` for matched chunks and `*[context, seq N]*` for context chunks, then appends the chunk content. Three existing tests in `TestSearchBooksContextWindow` exercise this code path and pass.

The gap: the current marker format — `**>>> MATCHED (seq N) <<<**` on the same line as the content without a separating rule — does not satisfy the requirement that the matched chunk is visible "at a glance." The requirement asks for a separator line and position label, and the success criterion explicitly states visual delineation. The markers exist but are not visually strong enough for rendered markdown in Claude Desktop, which is an LLM chat UI that renders `---` as a horizontal rule and bold text on its own line as a heading-like element.

**Primary recommendation:** Refactor `_format_enriched_results` to emit a stronger visual structure: a `---` separator before each chunk boundary, a position label (`**[MATCH — seq N]**` vs `**[Context — seq N]**`) on its own line, and update the three existing tests to assert against the new marker strings.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TOOL-02 | Context window search results visually delineate matched chunks from surrounding context | `_format_enriched_results` in tools.py already routes to this path; only the marker format needs strengthening |
</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.11 | String building, f-strings | No dependencies needed; output is pure markdown text |
| pytest | >=8.0 | Unit testing formatter functions | Already configured in pyproject.toml |

No new dependencies required. The "Out of Scope" constraint in REQUIREMENTS.md explicitly states "New dependencies — All features achievable with current stack." This phase is pure string formatting: build a markdown string, return it.

### Supporting

None required. The data structures (`exp["chunks"]`, `exp["matched_chunk_ids"]`, `exp["result"]`) are already populated by `SearchService._expand_result_context` and passed into `_format_enriched_results`.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Horizontal rule (`---`) as chunk separator | Blank line only | `---` renders as visual rule in Claude Desktop; blank line alone is invisible as a boundary signal |
| Bold position label on its own line | Inline label mixed with content | Own-line label is scannable in rendered markdown without reading content |
| `[MATCH]` / `[Context]` label | `>>> MATCHED <<<` / `*[context]*` | Current markers are harder to scan visually in rendered form |

## Architecture Patterns

### Existing Code Structure

The entire change lives in one function in one file:

```
src/mnemo/mcp/tools.py
  └── _format_enriched_results(expanded_results: list[dict]) -> str
```

The function receives a list of expanded result dicts. Each dict has:
- `result`: a `SearchResult` (has `book_title`, `section_path`, `content_type`, `source`, `book_id`)
- `chunks`: list of `Chunk` objects (has `id`, `sequence`, `content`, `content_type`)
- `matched_chunk_ids`: `set[str]` of chunk IDs that were matched

### Pattern: Block-separated chunk rendering

**What:** Each chunk in the context window is enclosed with separator rules and a position label on its own line.

**When to use:** When the output will be rendered as markdown in a chat UI where `---` produces a visible horizontal rule.

**Example (target output structure):**

```
Found 2 results (with context):

---
**Source:** Python Cookbook > Chapter 3 > Generators
**Book ID:** `a7f3b2` | **Type:** text | **Match:** both

---
**[Context — seq 4]**

Content of the preceding chunk...

---
**[MATCH — seq 5]**

Content of the matched chunk that the query hit...

---
**[Context — seq 6]**

Content of the following chunk...

```

Note: The top-level result header (`**Source:**` line) is already present and does not change. Only the per-chunk block markers change.

### Anti-Patterns to Avoid

- **Mixing marker and content on one line:** `**>>> MATCHED <<<** Some content here` — the marker visually merges with the content. Put the position label on its own line before the content.
- **No separator between chunks in a window:** Without `---` between context and match, the boundary is only detectable by reading the content.
- **Changing the non-enriched path:** `_format_search_results` (used when `context_window=0`) must not change. Tests in `TestOutputFormatting` already lock its output format.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Markdown rendering | Custom HTML/rich output | Plain markdown strings — Claude Desktop renders `---` and `**bold**` natively |
| Visual testing | Screenshot comparison, Playwright | Manual QA in Claude Desktop — STATE.md already documents this as intentional |

**Key insight:** Claude Desktop renders markdown tool results. The output medium is a rendered markdown string, not a terminal or HTML page. `---` horizontal rules and `**bold**` headings are the correct visual primitives. No library is needed.

## Common Pitfalls

### Pitfall 1: Breaking the existing context_window=0 code path

**What goes wrong:** `_format_enriched_results` is only called when `context_window >= 1`. `_format_search_results` handles the `context_window=0` path. Any change to `_format_enriched_results` must not touch `_format_search_results`.

**Why it happens:** Both functions are in the same file and share a similar loop structure — easy to edit the wrong one.

**How to avoid:** The test `test_search_books_context_window_zero_unchanged` asserts `"MATCHED" not in result` — run tests after every edit.

**Warning signs:** Tests in `TestOutputFormatting` fail after editing the enriched formatter.

### Pitfall 2: Asserting exact marker strings in tests that then break when format improves

**What goes wrong:** The three existing tests in `TestSearchBooksContextWindow` assert against current marker literals: `"MATCHED (seq 1)"`, `"[context, seq 0]"`. These will break when the markers change.

**Why it happens:** Tests were written to match the initial implementation exactly.

**How to avoid:** Update test assertions to match the new marker format in the same commit/task as the formatter change. Do not leave tests in a permanently failing state between tasks.

**Warning signs:** `pytest tests/test_mcp.py::TestSearchBooksContextWindow` shows 3 failures immediately after changing `_format_enriched_results`.

### Pitfall 3: Section path header showing the wrong result's metadata after deduplication merge

**What goes wrong:** When two search results' context windows overlap and are merged, `exp["result"]` is set to the highest-scoring result. The `**Source:**` header reflects this result, but the chunk list contains chunks from both originals. This is intentional (by design in `_deduplicate_expanded_results`), not a bug to fix.

**How to avoid:** Do not try to show separate headers per matched chunk — the deduplication design deliberately collapses them. Showing multiple matched-chunk labels within one result block is the correct behavior.

### Pitfall 4: `---` at the very top of a result block conflicts with the outer separator

**What goes wrong:** If the outer loop already writes a `---` separator and each chunk block also starts with `---`, the visual structure may have two adjacent rules.

**How to avoid:** Use the outer `---` as the result-level separator (already present in the current code), and use a lighter variant or position label only for the inner chunk separators. Alternatively, remove the outer `---` and rely entirely on the per-chunk separators. Either is fine; be consistent.

## Code Examples

### Current implementation (baseline)

```python
# Source: src/mnemo/mcp/tools.py lines 475-517
def _format_enriched_results(expanded_results: list[dict]) -> str:
    lines = [f"Found {len(expanded_results)} results (with context):\n"]

    for exp in expanded_results:
        result = exp["result"]
        matched_ids = exp["matched_chunk_ids"]

        section = (
            " > ".join(result.section_path) if result.section_path else "Unknown section"
        )

        lines.append("---")
        lines.append(f"**Source:** {result.book_title} > {section}")
        lines.append(
            f"**Book ID:** `{result.book_id}` | "
            f"**Type:** {result.content_type} | "
            f"**Match:** {result.source}"
        )
        lines.append("")

        for chunk in exp["chunks"]:
            if chunk.id in matched_ids:
                lines.append(f"**>>> MATCHED (seq {chunk.sequence}) <<<**")
            else:
                lines.append(f"*[context, seq {chunk.sequence}]*")

            content = chunk.content
            if len(content) > 2000:
                content = content[:2000] + "\n\n[truncated...]"

            if chunk.content_type.value == "code":
                lines.append(f"```\n{content}\n```")
            else:
                lines.append(content)

            lines.append("")

    return "\n".join(lines)
```

### Target implementation pattern

```python
# Improved: separator rule + distinct position labels for matched vs context
def _format_enriched_results(expanded_results: list[dict]) -> str:
    lines = [f"Found {len(expanded_results)} results (with context):\n"]

    for exp in expanded_results:
        result = exp["result"]
        matched_ids = exp["matched_chunk_ids"]

        section = (
            " > ".join(result.section_path) if result.section_path else "Unknown section"
        )

        lines.append("---")
        lines.append(f"**Source:** {result.book_title} > {section}")
        lines.append(
            f"**Book ID:** `{result.book_id}` | "
            f"**Type:** {result.content_type} | "
            f"**Match:** {result.source}"
        )

        for chunk in exp["chunks"]:
            lines.append("")
            lines.append("---")
            if chunk.id in matched_ids:
                lines.append(f"**[MATCH — seq {chunk.sequence}]**")
            else:
                lines.append(f"*[Context — seq {chunk.sequence}]*")
            lines.append("")

            content = chunk.content
            if len(content) > 2000:
                content = content[:2000] + "\n\n[truncated...]"

            if chunk.content_type.value == "code":
                lines.append(f"```\n{content}\n```")
            else:
                lines.append(content)

        lines.append("")

    return "\n".join(lines)
```

Key changes from baseline:
1. Each chunk block now starts with `---` (horizontal rule in rendered markdown)
2. Match label is `**[MATCH — seq N]**` on its own line (bold, scannable)
3. Context label is `*[Context — seq N]*` on its own line (italic, visually subordinate to match)
4. A blank line separates the result header from the first chunk

### Test pattern (must update existing 3 tests)

```python
# Existing assertions that WILL break and MUST be updated:
assert "MATCHED (seq 1)" in result          # old
assert "[context, seq 0]" in result         # old
assert "[context, seq 2]" in result         # old

# New assertions:
assert "MATCH — seq 1" in result            # bold match label
assert "Context — seq 0" in result          # italic context label
assert "Context — seq 2" in result          # italic context label
assert "---" in result                      # separator rule present
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| `**>>> MATCHED <<<**` inline | `**[MATCH — seq N]**` on own line with `---` separator | Match chunk is identifiable without reading content |

No external library changes. No version upgrades needed.

## Open Questions

1. **Exact em-dash vs ASCII dash in label**
   - What we know: `—` (em-dash) renders identically in Claude Desktop; ASCII `--` or `-` could also work
   - What's unclear: User preference for the exact label wording
   - Recommendation: Use `—` (em-dash, U+2014) for visual quality; if it causes encoding issues in any test assertion, fall back to `: ` separator

2. **Manual QA requirement**
   - What we know: STATE.md documents "Context window formatting requires manual visual QA in Claude Desktop — no automated test can validate rendered markdown differences"
   - What's unclear: Whether TOOL-02 is considered done after code + test changes, or requires explicit QA sign-off
   - Recommendation: Treat automated tests as the gate for CI; note in PLAN.md that manual verification in Claude Desktop is the final acceptance check

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_mcp.py::TestSearchBooksContextWindow -v` |
| Full suite command | `python -m pytest tests/test_mcp.py -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TOOL-02 | context_window=1 output contains `---` separator and `[MATCH]` label on own line | unit | `python -m pytest tests/test_mcp.py::TestSearchBooksContextWindow -v` | Exists (3 tests need assertion updates) |
| TOOL-02 | context_window=1 output distinguishes context chunks with subordinate label | unit | same | Exists (assertions need updating) |
| TOOL-02 | context_window=0 unchanged (no enrichment markers) | unit | `python -m pytest tests/test_mcp.py::TestSearchBooksContextWindow::test_search_books_context_window_zero_unchanged -v` | Exists, passes, must not regress |
| TOOL-02 | Visual scan in Claude Desktop renders `---` as horizontal rule and `**bold**` as styled label | manual | n/a | Manual only — automated markdown rendering not feasible |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_mcp.py::TestSearchBooksContextWindow -v`
- **Per wave merge:** `python -m pytest tests/test_mcp.py -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

None — existing test infrastructure covers all phase requirements. The 3 tests in `TestSearchBooksContextWindow` exist and are the right tests; they just need assertion string updates to match the new format.

## Sources

### Primary (HIGH confidence)

- Direct code reading: `src/mnemo/mcp/tools.py` — current `_format_enriched_results` implementation (lines 475-517)
- Direct code reading: `tests/test_mcp.py` — `TestSearchBooksContextWindow` (lines 1587-1693) and `TestOutputFormatting` (lines 231-339)
- Direct code reading: `src/mnemo/search/service.py` — `_expand_result_context` and `_deduplicate_expanded_results` showing the dict structure consumed by the formatter
- Project docs: `.planning/REQUIREMENTS.md` — TOOL-02 definition and "No new dependencies" constraint
- Project docs: `.planning/STATE.md` — manual QA constraint on this exact phase

### Secondary (MEDIUM confidence)

- Claude Desktop rendering behavior: `---` produces horizontal rules and `**text**` produces bold in standard markdown renderers; this is standard CommonMark behavior

### Tertiary (LOW confidence)

- None required for this phase

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, same test framework, same file
- Architecture: HIGH — single function, existing data structures, no new types
- Pitfalls: HIGH — identified directly from reading the tests that will break

**Research date:** 2026-03-13
**Valid until:** Indefinite — pure internal formatting, no external library dependencies
