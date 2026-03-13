# Roadmap: Mnemo

## Milestones

- ✅ **v1.0 MVP** — Phases 1-4 (shipped 2026-02-10) — [Archive](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Book Management** — Phases 5-7 (shipped 2026-02-17) — [Archive](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 RAG Improvements** — Phases 8-9 (shipped 2026-03-10) — [Archive](milestones/v1.2-ROADMAP.md)
- 🚧 **v1.3 Quality & Polish** — Phases 10-12 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-4) — SHIPPED 2026-02-10</summary>

- [x] Phase 1: Foundation (5/5 plans) — completed 2026-01-20
- [x] Phase 2: Vector Pipeline (3/3 plans) — completed 2026-01-21
- [x] Phase 3: Search & MCP (2/2 plans) — completed 2026-01-24
- [x] Phase 4: CLI & Integration (1/1 plan) — completed 2026-02-03

</details>

<details>
<summary>✅ v1.1 Book Management (Phases 5-7) — SHIPPED 2026-02-17</summary>

- [x] Phase 5: Metadata Updates (1/1 plan) — completed 2026-02-11
- [x] Phase 6: Book Lifecycle Tools (2/2 plans) — completed 2026-02-14
- [x] Phase 7: Tool Polish & Integration (2/2 plans) — completed 2026-02-17

</details>

<details>
<summary>✅ v1.2 RAG Improvements (Phases 8-9) — SHIPPED 2026-03-10</summary>

- [x] Phase 8: Infrastructure & Quick Wins (2/2 plans) — completed 2026-03-10
- [x] Phase 9: Search Enrichment (3/3 plans) — completed 2026-03-10

</details>

### 🚧 v1.3 Quality & Polish (In Progress)

**Milestone Goal:** Fix parsing artifacts and search UX issues discovered during real-world MCP evaluation. No new dependencies, no schema changes — surgical fixes to five source files.

- [ ] **Phase 10: Parser Quality Fixes** - Clean EPUB text extraction, author normalization, and front-matter section labels
- [ ] **Phase 11: Search Filter and MCP Tool** - Hierarchy-aware section filtering and new `get_book_structure` tool
- [ ] **Phase 12: Output Formatting** - Visual delineation of matched vs. context chunks in enriched search results

## Phase Details

### Phase 10: Parser Quality Fixes
**Goal**: Newly ingested EPUBs produce clean, correctly attributed text with no joined words, no garbled author strings, and no "Unknown section" labels for front-matter content
**Depends on**: Phase 9
**Requirements**: PARSE-01, PARSE-02, PARSE-03
**Success Criteria** (what must be TRUE):
  1. Ingesting an EPUB that previously produced joined words (e.g. "astrategy") yields properly spaced text in all chunks
  2. A book with multiple semicolon-delimited authors (e.g. `"Smith, Alice; Jones, Bob;"`) stores them as separate author strings, not a single garbled value
  3. Front-matter spine items (cover, TOC, copyright, preface) appear with descriptive section labels (e.g. "Table of Contents") rather than "Unknown section"
  4. Code block indentation is fully preserved — whitespace normalization never touches `ContentType.CODE` chunks
**Plans**: 2 plans

Plans:
- [ ] 10-01-PLAN.md — Fix word-joining bug (PARSE-01) and author semicolon splitting (PARSE-02)
- [ ] 10-02-PLAN.md — Add front-matter section label inference (PARSE-03)

### Phase 11: Search Filter and MCP Tool
**Goal**: Section filtering matches anywhere in the hierarchy path and Claude can browse a book's full section structure before searching
**Depends on**: Phase 10
**Requirements**: SRCH-01, TOOL-01
**Success Criteria** (what must be TRUE):
  1. Filtering by "Chapter 5" returns chunks from all subsections of Chapter 5, not just chunks whose leaf section name is exactly "Chapter 5"
  2. `get_book_structure` returns an indented markdown hierarchy of all sections for a given book
  3. `get_book_structure` reads exclusively from SQLite — it reflects the indexed data, not a live re-parse of the EPUB file
  4. `get_book_structure` has `readOnlyHint=True` annotation and appears in `TestToolAnnotations`
**Plans**: TBD

Plans:
- [ ] 11-01: TBD

### Phase 12: Output Formatting
**Goal**: Context window search results make it immediately clear which chunk matched the query and which chunks are surrounding context
**Depends on**: Phase 11
**Requirements**: TOOL-02
**Success Criteria** (what must be TRUE):
  1. Enriched search results visually distinguish the matched chunk from its context neighbors (e.g. with a separator line and position label)
  2. A human reviewing the raw markdown output in Claude Desktop can identify the matched chunk at a glance without reading chunk content
**Plans**: TBD

Plans:
- [ ] 12-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 10 → 11 → 12

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v1.0 | 5/5 | Complete | 2026-01-20 |
| 2. Vector Pipeline | v1.0 | 3/3 | Complete | 2026-01-21 |
| 3. Search & MCP | v1.0 | 2/2 | Complete | 2026-01-24 |
| 4. CLI & Integration | v1.0 | 1/1 | Complete | 2026-02-03 |
| 5. Metadata Updates | v1.1 | 1/1 | Complete | 2026-02-11 |
| 6. Book Lifecycle Tools | v1.1 | 2/2 | Complete | 2026-02-14 |
| 7. Tool Polish & Integration | v1.1 | 2/2 | Complete | 2026-02-17 |
| 8. Infrastructure & Quick Wins | v1.2 | 2/2 | Complete | 2026-03-10 |
| 9. Search Enrichment | v1.2 | 3/3 | Complete | 2026-03-10 |
| 10. Parser Quality Fixes | v1.3 | 0/2 | Not started | - |
| 11. Search Filter and MCP Tool | v1.3 | 0/? | Not started | - |
| 12. Output Formatting | v1.3 | 0/? | Not started | - |

---
*Roadmap created: 2026-01-19*
*v1.0 shipped: 2026-02-10*
*v1.1 shipped: 2026-02-17*
*v1.2 shipped: 2026-03-10*
*v1.3 started: 2026-03-12*
