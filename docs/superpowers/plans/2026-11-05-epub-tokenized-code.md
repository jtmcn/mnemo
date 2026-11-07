# EPUB Tokenized Code Blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EPUB code blocks whose syntax highlighting wraps each token in its own `<code>` (O'Reilly style) are indexed in full instead of as their first token.

**Architecture:** `_extract_code_block` (`src/mnemo/epub/_extract.py:403`) reads `element.find("code").get_text()`, so only the first `<code>` inside a `<pre>` survives. It should read the text of the `<pre>` itself, since the whitespace and newlines between token spans are text nodes of the `<pre>`. The one-token blocks it produces today count as tiny, so the chunker merges most of them into neighbouring text and the code disappears from search entirely.

**Tech Stack:** Python 3.11–3.13, BeautifulSoup 4, ebooklib (test fixtures), pytest.

**Spec:** the Findings section below; there is no separate spec.

## Findings

Measured 2026-11-04 against the live library (`~/.mnemo/mnemo.db`) and the source EPUBs:

| Book | `<pre>` with `<code>` | Truncated | Code chars indexed today |
|---|---|---|---|
| Data Science from Scratch (`02c57b`) | 729 | 727 | 6,542 of 225,975 |
| Data Engineering Design Patterns (`221222`) | 219 | 219 | 2,134 of 72,865 |
| The other 5 books | 0 | — | — |

The source of DEDP Example 9-24 (`OEBPS/ch09.html:837`) looks like this:

```html
<pre data-code-language="python" data-type="programlisting">
<code class="k">def</code> <code class="nf">get_last_offsets_per_partition</code><code class="p">(</code>…
 <code class="n">last_processed_offsets</code> <code class="o">=</code> …
</pre>
```

It is stored as chunk 715 with the content `def`, and `get_last_offsets_per_partition` appears in no chunk.

## Global Constraints

- No new runtime dependencies. `mypy src/` stays clean.
- No new `# type: ignore`, `# noqa`, or test skips.
- Code comments: 1–2 lines, why-only.
- Branch `joel/fix-epub-tokenized-code`. Commits carry no co-author line.
- Gates before every commit: `ruff format --check src/ tests/`, `ruff check src/ tests/`, `mypy src/`, `uv run --extra dev pytest -m "not integration"`.

## Review Focus

1. **Single-wrapper `<pre>\n<code>…</code>\n</pre>`** (the common case): the content must equal today's output apart from leading and trailing newlines. Pinned by `test_single_code_wrapper_unchanged`.
2. **Indentation on the first code line** must survive the newline trim. Strip `"\n"` only, never all whitespace. Pinned by `test_tokenized_code_keeps_lines_and_indentation` (the first line is not indented, but the second line's leading space is) and `test_single_code_wrapper_unchanged` (its first line is indented).
3. **Standalone block-level `<code>`** (no `<pre>` parent) also reaches `_extract_code_block`. It must still return its own text. Pinned by `test_standalone_code_block_unchanged`.
4. **A `<pre>` without `<code>`**, such as a plain programlisting, already used `element.get_text()`. It must stay the same, apart from the newline trim. Pinned by `test_pre_without_code_keeps_text` (added after review; the existing tests never asserted its content).
5. **Tokenized blocks are no longer merged away**: a listing of 20+ tokens must come out of the chunker as its own CODE chunk (the chunker still merges CODE blocks under 20 tokens). Pinned by `test_tokenized_listing_becomes_its_own_code_chunk` (added after review).

---

### Task 1: Extract the whole `<pre>` text

**Files:**
- Modify: `src/mnemo/epub/_extract.py:402-404`
- Test: `tests/test_epub_parser.py` (new class `TestTokenizedCodeBlocks`, after `TestContentExtraction`)

**Interfaces:**
- Consumes: `create_epub_from_toc(output_path, files: dict[str, str], toc: list[TocEntry]) -> Path` from `tests/fixtures/epub_factory.py` (already imported in the test module), `EPUBParser().parse(path) -> tuple[Book, list[ContentBlock]]`.
- Produces: no signature change. `_extract_code_block(element, section_path, source_file, default_language) -> ContentBlock` keeps its signature.

- [ ] **Step 1: Write the failing tests**

All three tests build a one-chapter EPUB with `create_epub_from_toc(tmp_path / "b.epub", {"ch1.xhtml": body}, [("Chapter 1", "ch1.xhtml", [])])` and collect `[b for b in blocks if b.content_type == ContentType.CODE]`.

```python
TOKENIZED = (
    '<h1>Chapter 1</h1><p>Intro.</p>'
    '<pre data-code-language="python" data-type="programlisting">\n'
    '<code class="k">def</code> <code class="nf">lag</code><code class="p">(</code>'
    '<code class="bp">self</code><code class="p">):</code>\n'
    ' <code class="k">return</code> <code class="n">offsets_lag</code>\n'
    '</pre><p>Outro.</p>'
)

def test_tokenized_code_keeps_lines_and_indentation(self, tmp_path: Path) -> None:
    # parse TOKENIZED as above
    assert [b.content for b in code_blocks] == ["def lag(self):\n return offsets_lag"]
    assert code_blocks[0].language == "python"

def test_single_code_wrapper_unchanged(self, tmp_path: Path) -> None:
    # body: '<h1>Chapter 1</h1><pre>\n<code class="language-python">    x = 1\ny = 2\n</code>\n</pre>'
    assert [b.content for b in code_blocks] == ["    x = 1\ny = 2"]

def test_standalone_code_block_unchanged(self, tmp_path: Path) -> None:
    # body: '<h1>Chapter 1</h1><code>a = 1\nb = 2</code>'
    assert [b.content for b in code_blocks] == ["a = 1\nb = 2"]
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run --extra dev pytest tests/test_epub_parser.py::TestTokenizedCodeBlocks -v`
Expected: `test_tokenized_code_keeps_lines_and_indentation` FAILS with content `["def"]`. `test_single_code_wrapper_unchanged` FAILS on the trailing `"\n"`. `test_standalone_code_block_unchanged` may already pass.

- [ ] **Step 3: Implement**

In `_extract_code_block`, replace the two lines under `# Get code content, preserving whitespace` with `content = element.get_text().strip("\n")`. Add a one-line comment: publishers such as O'Reilly wrap each highlighted token in its own `<code>`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run --extra dev pytest tests/test_epub_parser.py -v`
Expected: all PASS, including the existing `TestContentExtraction::test_preserves_code_whitespace`.

- [ ] **Step 5: Check against the real book**

Run (read-only, from the repo root):
`uv run python -c "from pathlib import Path; from mnemo.epub import EPUBParser; _, b = EPUBParser().parse(Path('/Users/jm/Documents/Books/Work/Data Engineering Design Patterns - Bartosz Konieczny.epub')); print(next(x.content for x in b if 'get_last_offsets_per_partition' in x.content))"`
Expected: the full 9-line `get_last_offsets_per_partition` function, with indentation intact.

- [ ] **Step 6: Run all gates and commit**

Run the four gate commands from Global Constraints. All must pass.

```bash
git add src/mnemo/epub/_extract.py tests/test_epub_parser.py
git commit -m "fix: index full EPUB code blocks when each token has its own <code>"
```

### Task 2: Version, PR, and re-index

**Files:**
- Modify: `pyproject.toml` (`version = "3.4.0"` → `"3.4.1"`), `uv.lock`, `CLAUDE.md` ("Current version: 3.4.1")

- [ ] **Step 1: Bump the version** in `pyproject.toml` and `CLAUDE.md`, then run `uv lock` (CI syncs with `--locked`).
- [ ] **Step 2: Commit** `chore: bump version to 3.4.1`, staging `pyproject.toml uv.lock CLAUDE.md`.
- [ ] **Step 3: Push and open the PR.** The body carries the Findings table and the root-cause explanation.
- [ ] **Step 4: After merge, re-index (operator step).** Run `mnemo reindex -v`. It re-parses every book from its source file and re-embeds, so it needs the embedding endpoint configured. Then verify:
  `sqlite3 -readonly ~/.mnemo/mnemo.db "select count(*) from chunks where content like '%get_last_offsets_per_partition%'"` returns ≥ 1, and `search_books("lag detection offsets per partition", content_type="code")` returns Example 9-24 in full.
