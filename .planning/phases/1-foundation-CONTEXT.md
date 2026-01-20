# Phase 1 Context: Foundation

**Created:** 2026-01-19
**Phase Goal:** Parse technical EPUBs, chunk content intelligently, and store structured data with full text for later retrieval.

---

## Code Block Handling

### Long Code Blocks
**Decision:** Keep as single giant chunk, never split.

Rationale: Context preservation trumps chunk size. A 200-line class definition is one semantic unit. Splitting it loses the ability to understand the whole.

Implementation notes:
- No max size limit for code blocks
- Code block = atomic unit, regardless of length
- May dominate search results for that topic — acceptable tradeoff

### Code + Prose Relationship
**Decision:** Adjacent chunks with linking.

Prose explaining code and the code itself are separate chunks, but linked via chunk ID reference. This allows:
- Searching for explanations independently
- Searching for code independently
- Reconstructing full context when needed

Implementation notes:
- Prose chunk stores reference to adjacent code chunk ID
- Code chunk stores reference to preceding/following prose chunk IDs
- "Adjacent" = immediately before or after in source order

### Language Detection
**Decision:** Use book-level hints, no auto-detection.

When code blocks lack explicit language tags:
- Infer from book metadata/title (a Python book → assume Python)
- Fall back to "unknown" if no clear signal
- Don't attempt heuristic detection (error-prone)

Implementation notes:
- Store book-level `default_language` in metadata
- User can override at add time if needed
- Language stored per chunk for filtering

### Small Code Blocks
**Decision:** Keep intact, same as large blocks.

Even 1-3 line code snippets (imports, one-liners) stay as discrete code chunks:
- Consistency in handling
- Searchable as code
- Never inlined into prose

---

## Chapter/Section Granularity

### Hierarchy Depth
**Decision:** Full path always.

Attribution includes complete hierarchy: "Part I > Chapter 3 > Section 3.2 > Error Handling > Try/Catch Blocks"

Rationale: Maximum context. Users can ignore depth they don't need, but can't recover depth that wasn't captured.

Implementation notes:
- Store full path as array: `["Part I", "Chapter 3", "Section 3.2", "Error Handling", "Try/Catch Blocks"]`
- Format for display at query time
- No arbitrary depth limit

### Poor/Missing Structure
**Decision:** Parse HTML headings, warn user.

When EPUB TOC is missing or flat:
- Infer structure from h1, h2, h3, etc. tags in HTML
- Warn user: "Inferred structure from HTML headings — verify accuracy"
- Don't reject the book, don't silently accept bad structure

Implementation notes:
- First try EPUB TOC/nav
- Fall back to heading tag parsing
- Log/warn about inference
- Store `structure_source: "toc" | "inferred"` in book metadata

### Boundary-Spanning Chunks
**Decision:** List both sections.

When a chunk spans section 3.1 → 3.2, attribution shows both:
- `sections: ["3.1 Introduction", "3.2 Setup"]`

Rationale: Honest about where content lives. User can decide relevance.

Implementation notes:
- Track section transitions during chunking
- Store as array, not single value
- Most chunks will have single section

### Asides (Tips, Warnings, Notes)
**Decision:** Inherit parent section's hierarchy.

Callout boxes, tips, warnings don't get their own hierarchy level. They belong to their containing section.

Implementation notes:
- Detect aside/callout markup (varies by publisher)
- Tag as `content_type: "aside"` but keep parent's section path
- Searchable, but not a navigation level

---

## Edge Case Content

### Content Types
**Decision:** Five content types: `text`, `code`, `diagram`, `math`, `table`

| Content | Type | Handling |
|---------|------|----------|
| Regular prose | `text` | Standard chunking |
| Code blocks (any language) | `code` | Atomic, never split |
| Shell commands + output | `code` | Same as code |
| Config files (YAML, JSON, etc.) | `code` | Same as code |
| ASCII diagrams | `diagram` | Preserved as-is, tagged |
| Math/formulas | `math` | Raw notation preserved, tagged |
| Tables | `table` | Converted to searchable text |

### ASCII Diagrams
**Decision:** Tag as "diagram", preserve verbatim.

- Keep exact whitespace and characters
- Filterable via content type
- Embeddings may not capture meaning well, but searchable by surrounding text

### Math and Formulas
**Decision:** Tag as "math", preserve raw notation.

- Keep LaTeX, MathML, or plain text as-is
- No expansion to natural language
- Filterable via content type
- `O(n log n)` stays as `O(n log n)`

---

## Book Identity

### Duplicate Detection
**Decision:** Skip with message.

Adding same book twice (by content hash):
- System detects duplicate
- Outputs: "Book already indexed (id: a7f3b2). Skipping."
- No error, no re-index
- Idempotent operation

Implementation notes:
- Hash EPUB content (not filename)
- Check hash before processing
- `--force` flag to override if needed

### Similar Titles (Editions)
**Decision:** Require explicit confirmation.

Adding "Effective Python 3rd Ed" when "Effective Python 2nd Ed" exists:
- Warn: "Similar book exists: 'Effective Python 2nd Ed' (a7f3b2). Add anyway? [y/N]"
- Require explicit yes
- Both can coexist if confirmed

Implementation notes:
- Fuzzy match on title
- Threshold TBD (research phase)
- Non-interactive mode needs `--allow-similar` flag

### Book Identifiers
**Decision:** Auto-generated short hash.

- Format: 6-character hex hash (e.g., `a7f3b2`)
- Derived from content, not filename
- Used for `mnemo remove a7f3b2`
- Displayed in `mnemo list` output

Implementation notes:
- Hash first N bytes of EPUB + title + author
- Collision-resistant at personal library scale
- Not user-memorable, but unambiguous

### Missing Metadata
**Decision:** Filename fallback, warn user.

When EPUB lacks title/author:
- Use filename (without extension) as title
- Warn: "Missing metadata. Using filename as title: 'python-cookbook'"
- Don't prompt, don't block
- User can re-add with corrected EPUB if they care

---

## Deferred Ideas

Captured during discussion, out of scope for Phase 1:

*None identified*

---

## Summary for Downstream Agents

**Researcher should investigate:**
- Fuzzy matching threshold for similar title detection
- Optimal hash algorithm for book identity
- HTML heading inference strategies for poorly structured EPUBs

**Planner should ensure:**
- Chunk model supports linked references between adjacent chunks
- Content type enum includes all 5 types
- Section path stored as array, not string
- Book metadata includes `structure_source` and `default_language`

---
*Context captured: 2026-01-19*
