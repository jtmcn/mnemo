# Phase 6: Book Lifecycle Tools - Context

**Gathered:** 2026-02-12
**Status:** Ready for planning

<domain>
## Phase Boundary

MCP tools for adding and removing books from the library. `add_book` ingests an EPUB (parse, chunk, embed) and makes it searchable. `remove_book` deletes a book and all its data. Replaces CLI context-switching for book management. Metadata editing is Phase 5 (done). Tool polish and annotations are Phase 7.

</domain>

<decisions>
## Implementation Decisions

### Ingestion experience
- Synchronous blocking — `add_book` waits until fully processed before returning
- 5-minute timeout — fail if embedding takes longer, prevents infinite hangs
- On failure mid-way (e.g., API timeout): clean up everything — delete book record, chunks, and any partial vectors so user can retry cleanly

### Claude's Discretion: progress reporting
- Whether to report progress during the synchronous wait (parsing... chunking... embedding) or just return the final result — pick based on what MCP supports easily

### Removal safety
- Hard delete immediately — book, chunks, and vectors gone instantly
- Leave original EPUB file on disk untouched — only remove from database and vector store
- Response includes deleted book's title, authors, and chunk count so Claude can confirm what was removed
- Non-existent book ID returns an error (not idempotent silent success)

### Duplicate handling
- Duplicate detection: file hash match is a hard duplicate (distinct error); same title+author is a soft warning but still allows add
- Duplicate error includes full info: existing book ID, title, authors — so Claude can say "You already have 'Book X' (ID: 5)"
- `force=true` re-index creates a new book ID (delete old, create fresh) — clean slate

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-book-lifecycle*
*Context gathered: 2026-02-12*
