# Phase 13: Audit Gap Closure - Research

**Researched:** 2026-03-14
**Domain:** Documentation corrections, test assertion fixes, verification artifact creation
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TOOL-02 | Context window search results visually delineate matched chunks from surrounding context | TOOL-02 was implemented in Phase 12 (confirmed by 12-01-SUMMARY.md, integration checker, and direct code inspection). Gap is purely documentation: Phase 12 VERIFICATION.md was never created. Creating it closes the orphaned status. |
| SRCH-01 | Section filter matches against the full hierarchy path | SRCH-01 was implemented and verified in Phase 11 (11-VERIFICATION.md marks SATISFIED). Gap is purely a frontmatter omission: 11-01-SUMMARY.md has empty `requirements_completed` field. Fix is a one-line frontmatter edit. |
| TOOL-01 | New `get_book_structure` MCP tool returns the section hierarchy for a book | TOOL-01 was implemented and verified in Phase 11 (11-VERIFICATION.md marks SATISFIED). Same frontmatter omission as SRCH-01. Fix is a one-line frontmatter edit. |
</phase_requirements>

---

## Summary

Phase 13 is a pure gap-closure phase — no new code to write, no behavior to change. All three requirements (TOOL-02, SRCH-01, TOOL-01) are already fully implemented and wired. The v1.3 milestone audit identified five documentation/test correctness gaps: a missing VERIFICATION.md for Phase 12, an empty `requirements_completed` frontmatter field in the Phase 11 SUMMARY, an unchecked checkbox in ROADMAP.md, two stale test comments (docstring says "six MCP tools", test method docstring says "seven tools" but there are 8), and 5 pre-existing test failures that need to be either fixed or formally documented as known-unfixable.

The most significant work item is creating Phase 12's VERIFICATION.md. This involves reading the implemented code in `src/mnemo/mcp/tools.py` and the passing tests in `tests/test_mcp.py::TestSearchBooksContextWindow`, then writing a verification report in the same format as Phase 11's (which passed). The VERIFICATION.md must confirm TOOL-02 is SATISFIED with line-number evidence.

The pre-existing test failures split into two distinct categories: `test_server_imports_without_side_effects` fails because the test asserts `mcp.name == "mnemo"` but the server initializes with `f"mnemo v{__version__}"` (currently `"mnemo v1.3.0"`). The `TestAddBookAsync` tests (4 tests) fail because `pytest-asyncio` is listed as a dev dependency in `pyproject.toml` but is not installed in the current environment. Both categories are fixable.

**Primary recommendation:** Execute all six gap-closure tasks atomically in a single plan (13-01-PLAN.md). All items are documentation edits, frontmatter fixes, test comment updates, or dependency installation — none require behavior changes.

---

## Standard Stack

### Core (no new dependencies needed)

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| pytest | 9.0.2 (installed) | Test runner | Project standard |
| pytest-asyncio | >=0.23 (in pyproject.toml, NOT installed) | Async test support | Required for TestAddBookAsync to run |

### No New Libraries

This phase adds no new dependencies. The only dependency action is installing `pytest-asyncio` which is already declared in `pyproject.toml [project.optional-dependencies] dev`.

**Install command for pre-existing test fix:**
```bash
pip install "pytest-asyncio>=0.23"
```

---

## Architecture Patterns

### Verification Report Format

Phase 13's primary deliverable is a VERIFICATION.md for Phase 12. The format is established by Phases 10 and 11 — it must match exactly:

```
---
phase: 12-output-formatting
verified: {ISO timestamp}
status: passed
score: 2/2 must-haves verified
re_verification: false
---

# Phase 12: Output Formatting Verification Report

**Phase Goal:** ...
**Verified:** {ISO timestamp}
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths
...

### Required Artifacts
...

### Key Link Verification
...

### Requirements Coverage
...

### Anti-Patterns Found
...

### Human Verification Required
...

### Gaps Summary
...
```

Reference: `.planning/phases/11-search-filter-and-mcp-tool/11-VERIFICATION.md` (4/4 truths, 2 requirements SATISFIED).

### SUMMARY Frontmatter Fix Pattern

The `11-01-SUMMARY.md` frontmatter currently has an empty or absent `requirements_completed` field. The fix is to ensure the frontmatter lists both `SRCH-01` and `TOOL-01`. Reference the Phase 10 summaries which correctly list their requirements. The field name (from `10-01-SUMMARY.md`) is `requirements-completed` (hyphen, not underscore) but the 11 SUMMARY uses `requirements_completed` (underscore) in the YAML block. Use whatever the existing key is — just populate it.

**Current state of 11-01-SUMMARY.md frontmatter:**
```yaml
decisions:
  - ...
metrics:
  duration_seconds: 190
  completed_date: "2026-03-14"
  tasks_completed: 2
  files_modified: 7
```
The `requirements_completed` / `requirements-completed` key is entirely absent. Add it.

### Test Comment Fix Pattern

Two stale comments exist in `tests/test_mcp.py`:

1. **Line 31** — `test_tools_registered` docstring: `"Verify all seven tools are registered with the server."` → should be `"Verify all eight tools are registered with the server."` AND the assertion must add `assert "get_book_chunks" in tool_names`.

2. **Line 46** — `TestToolAnnotations` class docstring: `"Tests verifying ToolAnnotations on all six MCP tools."` → should be `"Tests verifying ToolAnnotations on all eight MCP tools."`

**The 8 registered tools (confirmed by inspecting `src/mnemo/mcp/tools.py`):**
- `search_books` (line 532)
- `list_available_books` (line ~571)
- `get_book_info` (line ~591)
- `update_book_metadata` (line ~614)
- `remove_book` (line ~636)
- `add_book` (line ~666)
- `get_book_structure` (line ~775)
- `get_book_chunks` (line 806)

The `test_tools_registered` test currently asserts 7 tools and passes (because it only uses `in` checks, not a length assertion). It is missing the `get_book_chunks` assertion. Adding `assert "get_book_chunks" in tool_names` makes the assertion complete.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async test support | Custom async test runner or sync wrapper | Install pytest-asyncio | It's already declared in pyproject.toml; just not installed in this environment |
| Verification document format | New format | Existing Phase 10/11 VERIFICATION.md format | Consistency is the entire point — the audit checks these files |

---

## Common Pitfalls

### Pitfall 1: Fixing the wrong frontmatter key name
**What goes wrong:** Adding `requirements_completed` (underscore) when the Phase 11 SUMMARY already uses a different YAML key, or vice versa — creating a duplicate key that YAML parsers handle inconsistently.
**Why it happens:** Phase 10 SUMMARYs use hyphen (`requirements-completed`) while Phase 11 uses underscore.
**How to avoid:** Read `11-01-SUMMARY.md` frontmatter precisely before editing. Add the key that is absent (or correct the empty list). Do not change the existing key name.
**Warning signs:** YAML parse errors or audit tools not finding the field.

### Pitfall 2: test_server_imports fix introduces side effects
**What goes wrong:** Changing `mcp.name == "mnemo"` → `mcp.name.startswith("mnemo")` is the right fix, but re-asserting on the name could be overly brittle. Alternative: fix the test to match the actual server name format.
**Why it happens:** The server name is `f"mnemo v{__version__}"` — it includes the version string by design.
**How to avoid:** The correct fix is `assert mcp.name.startswith("mnemo")` or `assert "mnemo" in mcp.name`. Do not change the server initialization — the version-in-name is intentional for MCP client identification.

### Pitfall 3: pytest-asyncio installation scope
**What goes wrong:** Installing `pytest-asyncio` globally vs. in the project's virtual environment.
**Why it happens:** The project uses a pyenv-managed Python. Installing to the wrong environment means tests still fail.
**How to avoid:** Confirm the active Python is the project's Python before installing: `which python` and `pip install "pytest-asyncio>=0.23"` from the project directory. The `asyncio_mode = "auto"` is already set in `pyproject.toml` — no config change needed.

### Pitfall 4: VERIFICATION.md must pass re-audit scrutiny
**What goes wrong:** Writing a VERIFICATION.md that is too thin — "it works, trust me" — which would be caught in a re-audit as insufficient evidence.
**Why it happens:** Phase 13 doesn't run new tests; it documents existing passing tests.
**How to avoid:** The VERIFICATION.md must cite specific line numbers in `src/mnemo/mcp/tools.py` for the `_format_enriched_results` function and specific passing test names from `tests/test_mcp.py::TestSearchBooksContextWindow`. The evidence must match the Pattern from Phase 11's VERIFICATION.md.

---

## Code Examples

### Current State of Stale Test Assertions (confirmed by direct file inspection)

```python
# tests/test_mcp.py line 30-42 — CURRENT (stale, needs fix)
def test_tools_registered(self):
    """Verify all seven tools are registered with the server."""  # BUG: says 7, should be 8
    from mnemo.mcp.server import mcp

    tool_names = list(mcp._tool_manager._tools.keys())
    assert "search_books" in tool_names
    assert "list_available_books" in tool_names
    assert "get_book_info" in tool_names
    assert "update_book_metadata" in tool_names
    assert "remove_book" in tool_names
    assert "add_book" in tool_names
    assert "get_book_structure" in tool_names
    # MISSING: assert "get_book_chunks" in tool_names


class TestToolAnnotations:
    """Tests verifying ToolAnnotations on all six MCP tools.  # BUG: says 6, should be 8
```

### Target State After Fix

```python
# tests/test_mcp.py — AFTER FIX
def test_tools_registered(self):
    """Verify all eight tools are registered with the server."""
    ...
    assert "get_book_structure" in tool_names
    assert "get_book_chunks" in tool_names  # ADD THIS


class TestToolAnnotations:
    """Tests verifying ToolAnnotations on all eight MCP tools.
```

### TOOL-02 Evidence for VERIFICATION.md

```python
# src/mnemo/mcp/tools.py — the implementation that VERIFICATION.md must cite
# _format_enriched_results emits:
#   "\n---\n**[MATCH — seq {chunk.sequence}]**\n\n{content}" for matched chunks
#   "\n---\n*[Context — seq {chunk.sequence}]*\n\n{content}" for context chunks
```

Passing tests that provide the verification evidence:
- `tests/test_mcp.py::TestSearchBooksContextWindow::test_search_books_context_window_formats_enriched`
- `tests/test_mcp.py::TestSearchBooksContextWindow::test_search_books_context_window_zero_unchanged`
- `tests/test_mcp.py::TestSearchBooksContextWindow::test_search_books_context_window_clamped`

### Server Name Fix

```python
# tests/test_mcp.py line 28 — CURRENT (fails)
assert mcp.name == "mnemo"

# AFTER FIX
assert mcp.name.startswith("mnemo")
```

---

## All Six Gap Items (Enumerated)

This table is the authoritative task list for the planner. Each item maps to an audit gap:

| # | Gap Item | Source | File to Change | Change Type | Audit Success Criterion |
|---|----------|--------|---------------|-------------|------------------------|
| 1 | Phase 12 VERIFICATION.md missing | Audit: orphaned TOOL-02 | Create `.planning/phases/12-output-formatting/12-VERIFICATION.md` | New file | Phase 12 has VERIFICATION.md confirming TOOL-02 SATISFIED |
| 2 | 11-01-SUMMARY frontmatter missing requirements_completed | Audit: partial SRCH-01/TOOL-01 | Edit `.planning/phases/11-search-filter-and-mcp-tool/11-01-SUMMARY.md` | Frontmatter edit | Field lists `SRCH-01` and `TOOL-01` |
| 3 | ROADMAP 12-01-PLAN checkbox unchecked | Audit: tech debt | Edit `.planning/ROADMAP.md` | `[ ]` → `[x]` on line for 12-01-PLAN.md | Checkbox is checked |
| 4 | `test_tools_registered` asserts 7 tools, not 8 | Audit: cross-phase tech debt | Edit `tests/test_mcp.py` | Add `assert "get_book_chunks" in tool_names` + update docstring | Test asserts all 8 tools |
| 5 | `TestToolAnnotations` docstring says "six MCP tools" | Audit: cross-phase tech debt | Edit `tests/test_mcp.py` | Update class docstring to say "eight" | Docstring reflects correct count |
| 6a | `test_server_imports_without_side_effects` fails | Audit: tech debt / pre-existing | Edit `tests/test_mcp.py` | `mcp.name == "mnemo"` → `mcp.name.startswith("mnemo")` | Test passes |
| 6b | `TestAddBookAsync` (4 tests) fail — pytest-asyncio not installed | Audit: tech debt / pre-existing | Install dependency | `pip install "pytest-asyncio>=0.23"` | 4 async tests pass |

Items 6a and 6b are the pre-existing failures. Both are fixable. The audit success criterion for Phase 13 says "resolved or documented" — fixing is preferred.

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|-----------------|--------|
| Phase 12 marked complete without VERIFICATION.md | Phase 13 backfills the VERIFICATION.md | TOOL-02 moves from "orphaned" to "satisfied" in re-audit |
| Pre-existing test failures documented as out-of-scope | Phase 13 resolves both root causes | Full test suite passes (5 fewer failures) |

---

## Open Questions

1. **pytest-asyncio installation permanence**
   - What we know: `pytest-asyncio>=0.23` is in `pyproject.toml` dev dependencies but not installed
   - What's unclear: Whether there's a virtual environment or requirements file that should be updated vs. just installing directly
   - Recommendation: Install via `pip install "pytest-asyncio>=0.23"` — this is already the declared dependency; no pyproject.toml change needed

2. **ROADMAP checkbox format**
   - What we know: Line 89 in ROADMAP.md reads `- [ ] 12-01-PLAN.md — Strengthen enriched result formatting...`
   - What's unclear: Whether the Phase 12 section header checkbox on line 45 (`[x] **Phase 12: Output Formatting**`) also needs updating
   - Recommendation: Both line 89 (plan-level) and line 45 (phase-level) already have `[x]` checked in ROADMAP.md based on reading — only the nested plan checkbox at line 89 needs the `[ ]` → `[x]` change.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_mcp.py::TestServerSetup tests/test_mcp.py::TestAddBookAsync -v` |
| Full suite command | `python -m pytest tests/test_mcp.py -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TOOL-02 | `_format_enriched_results` emits MATCH/Context labels and --- separators | unit | `python -m pytest tests/test_mcp.py::TestSearchBooksContextWindow -v` | ✅ (3 passing tests) |
| SRCH-01 | Section filter matches full hierarchy path | unit | `python -m pytest tests/test_mcp.py::TestSearchBooksContextWindow -v` | ✅ (covered by Phase 11) |
| TOOL-01 | `get_book_structure` MCP tool registered and working | unit | `python -m pytest tests/test_mcp.py::TestGetBookStructure -v` | ✅ (covered by Phase 11) |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_mcp.py --tb=short -q`
- **Per wave merge:** `python -m pytest tests/ --tb=short -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

None — existing test infrastructure covers all phase requirements. The VERIFICATION.md to be created is documentation, not a test file.

---

## Sources

### Primary (HIGH confidence)

- Direct file inspection: `.planning/v1.3-MILESTONE-AUDIT.md` — authoritative gap list
- Direct file inspection: `tests/test_mcp.py` lines 24-46 — confirmed stale assertions
- Direct file inspection: `src/mnemo/mcp/server.py` line 22 — confirmed server name format
- Direct file inspection: `src/mnemo/mcp/tools.py` — confirmed 8 tool registrations
- Direct file inspection: `.planning/phases/12-output-formatting/12-01-SUMMARY.md` — confirmed TOOL-02 implemented
- Direct file inspection: `.planning/phases/11-search-filter-and-mcp-tool/11-VERIFICATION.md` — confirmed SRCH-01/TOOL-01 verified
- Direct test run: `python -m pytest tests/test_mcp.py --tb=no -q` — confirmed 5 failures, 73 passed
- Direct test run: `python -m pytest tests/test_mcp.py::TestServerSetup::test_tools_registered` — confirmed currently passing (7 assertions, missing 8th)

### Secondary (MEDIUM confidence)

- pytest-asyncio missing: confirmed by `pip show pytest-asyncio` returning "not found" and test run showing "async functions are not natively supported"
- pyproject.toml confirms `asyncio_mode = "auto"` already set — no config change needed after install

---

## Metadata

**Confidence breakdown:**
- Gap identification: HIGH — directly from audit report + file inspection
- Fix approach: HIGH — all fixes are targeted edits to known files at known lines
- Test behavior: HIGH — confirmed by running the actual test suite
- Verification artifact format: HIGH — modeled on existing Phase 10/11 VERIFICATION.md files

**Research date:** 2026-03-14
**Valid until:** 2026-04-13 (stable — no moving parts, all local files)
