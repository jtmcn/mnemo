# Roadmap: Mnemo

## Milestones

- SHIPPED **v1.0 MVP** — Phases 1-4 (shipped 2026-02-10) — [Archive](milestones/v1.0-ROADMAP.md)
- **v1.1 Book Management** — Phases 5-7 (in progress)

## Phases

<details>
<summary>SHIPPED v1.0 MVP (Phases 1-4) — SHIPPED 2026-02-10</summary>

- [x] Phase 1: Foundation (5/5 plans) — completed 2026-01-20
- [x] Phase 2: Vector Pipeline (3/3 plans) — completed 2026-01-21
- [x] Phase 3: Search & MCP (2/2 plans) — completed 2026-01-24
- [x] Phase 4: CLI & Integration (1/1 plan) — completed 2026-02-03

</details>

### v1.1 Book Management (In Progress)

**Milestone Goal:** Add MCP tools for book lifecycle management so Claude can add, remove, and edit ebook metadata without CLI context-switching.

- [ ] **Phase 5: Metadata Updates** - Claude can update book metadata via MCP tool
- [ ] **Phase 6: Book Lifecycle Tools** - Claude can add and remove books via MCP tools
- [ ] **Phase 7: Tool Polish & Integration** - All tools meet quality standards with annotations, docstrings, and tests

## Phase Details

### Phase 5: Metadata Updates
**Goal**: Claude can update book title, authors, and ISBN through an MCP tool, with changes persisted in SQLite and reflected in search results
**Depends on**: Phase 4 (existing MCP server and repository infrastructure)
**Requirements**: META-01, META-02, META-03, META-04, META-05, META-06, META-07
**Success Criteria** (what must be TRUE):
  1. Claude can call `update_book_metadata` with a book ID and any combination of title, authors, or ISBN, and the changes persist
  2. Calling `update_book_metadata` with no fields returns a clear validation error
  3. Calling `update_book_metadata` with a nonexistent book ID returns a not-found error
  4. After updating metadata, `search_books` and `get_book_info` reflect the new values
**Plans:** 1 plan
Plans:
- [ ] 05-01-PLAN.md — Add update_book_metadata MCP tool (repository + tool + cache invalidation + tests)

### Phase 6: Book Lifecycle Tools
**Goal**: Claude can ingest new EPUBs and remove existing books entirely through MCP tools, replacing the need for CLI context-switching
**Depends on**: Phase 4 (existing ingest/remove pipeline functions)
**Requirements**: INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05, REMOVE-01, REMOVE-02, REMOVE-03
**Success Criteria** (what must be TRUE):
  1. Claude can call `add_book` with an absolute file path to an EPUB, and the book is parsed, chunked, embedded, and searchable
  2. `add_book` rejects non-existent paths and non-EPUB files with clear error messages
  3. `add_book` detects duplicate books by file hash and returns the existing book ID; `force=true` re-indexes
  4. `add_book` returns book ID, title, authors, and chunk count on success
  5. Claude can call `remove_book` with a book ID and the book, its chunks, and its vectors are all deleted
**Plans**: TBD

### Phase 7: Tool Polish & Integration
**Goal**: All six MCP tools (three existing, three new) carry proper annotations and docstrings, follow consistent error conventions, and the full add-search-update-remove lifecycle works end-to-end
**Depends on**: Phase 5, Phase 6
**Requirements**: TOOL-01, TOOL-02, TOOL-03, TOOL-04
**Success Criteria** (what must be TRUE):
  1. New mutation tools carry `destructiveHint` (remove) and `idempotentHint` (update) annotations; existing read-only tools carry `readOnlyHint=True`
  2. All six tools have LLM-tuned docstrings that help Claude discover when and why to use each tool
  3. All tools return structured error strings matching the existing convention (no unhandled exceptions leak through MCP)
  4. A full lifecycle test passes: add book, search for content, update metadata, verify metadata in search, remove book, verify removal
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v1.0 | 5/5 | Complete | 2026-01-20 |
| 2. Vector Pipeline | v1.0 | 3/3 | Complete | 2026-01-21 |
| 3. Search & MCP | v1.0 | 2/2 | Complete | 2026-01-24 |
| 4. CLI & Integration | v1.0 | 1/1 | Complete | 2026-02-03 |
| 5. Metadata Updates | v1.1 | 0/1 | In progress | - |
| 6. Book Lifecycle Tools | v1.1 | 0/TBD | Not started | - |
| 7. Tool Polish & Integration | v1.1 | 0/TBD | Not started | - |

---
*Roadmap created: 2026-01-19*
*v1.0 shipped: 2026-02-10*
*v1.1 roadmap added: 2026-02-11*
