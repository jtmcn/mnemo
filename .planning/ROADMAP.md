# Roadmap: Mnemo

## Milestones

- SHIPPED **v1.0 MVP** — Phases 1-4 (shipped 2026-02-10) — [Archive](milestones/v1.0-ROADMAP.md)
- SHIPPED **v1.1 Book Management** — Phases 5-7 (shipped 2026-02-17) — [Archive](milestones/v1.1-ROADMAP.md)
- 🚧 **v1.2 RAG Improvements** — Phases 8-9 (in progress)

## Phases

<details>
<summary>SHIPPED v1.0 MVP (Phases 1-4) — SHIPPED 2026-02-10</summary>

- [x] Phase 1: Foundation (5/5 plans) — completed 2026-01-20
- [x] Phase 2: Vector Pipeline (3/3 plans) — completed 2026-01-21
- [x] Phase 3: Search & MCP (2/2 plans) — completed 2026-01-24
- [x] Phase 4: CLI & Integration (1/1 plan) — completed 2026-02-03

</details>

<details>
<summary>SHIPPED v1.1 Book Management (Phases 5-7) — SHIPPED 2026-02-17</summary>

- [x] Phase 5: Metadata Updates (1/1 plan) — completed 2026-02-11
- [x] Phase 6: Book Lifecycle Tools (2/2 plans) — completed 2026-02-14
- [x] Phase 7: Tool Polish & Integration (2/2 plans) — completed 2026-02-17

</details>

### 🚧 v1.2 RAG Improvements (In Progress)

**Milestone Goal:** Improve search quality and chunking intelligence — move from naive RAG to advanced RAG techniques.

- [x] **Phase 8: Infrastructure & Quick Wins** - Cosine distance migration, search scores, configurable chunk sizes, EPUB path storage (completed 2026-03-10)
- [ ] **Phase 9: Search Enrichment** - Context expansion, metadata filtering, chunk range fetching

## Phase Details

### Phase 8: Infrastructure & Quick Wins
**Goal**: Search results use cosine similarity with visible scores, chunk sizes are configurable per book, and EPUB paths are stored for future re-indexing
**Depends on**: Phase 7
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, SRCH-01, CHUNK-01, CHUNK-02, CHUNK-03
**Success Criteria** (what must be TRUE):
  1. Running `migrate-cosine` CLI command converts existing ChromaDB collection from L2 to cosine distance without re-embedding, and verifies vector counts match before deleting the old collection
  2. Search results returned by `search_books` include a numeric relevance score (0-1 cosine similarity) for each result
  3. Calling `add_book` with custom `chunk_min_tokens` and `chunk_max_tokens` produces chunks within those bounds, with validation rejecting invalid values
  4. Calling `add_book` without chunk size parameters uses the existing 400/800 defaults (backward compatible)
  5. EPUB file path is persisted in the books table and visible via `get_book_info`
**Plans:** 2/2 plans complete

Plans:
- [x] 08-01-PLAN.md — Cosine migration, CLI command, and search similarity scores
- [x] 08-02-PLAN.md — EPUB path storage and configurable chunk sizes

### Phase 9: Search Enrichment
**Goal**: Users get richer search results with surrounding context, can filter by section, and can fetch contiguous chunk ranges for deep reading
**Depends on**: Phase 8
**Requirements**: SRCH-02, SRCH-03, SRCH-04, SRCH-05, META-01, META-02, META-03, META-04, META-05
**Success Criteria** (what must be TRUE):
  1. Calling `search_books` with `context_window=1` returns each result expanded with its neighboring chunks, and the response clearly delineates the matched chunk from surrounding context
  2. Context expansion stops at section boundaries and deduplicates overlapping windows into single context blocks
  3. Calling `search_books` with a `section` parameter returns only results whose section path contains that substring, across all three search modes (keyword, semantic, hybrid)
  4. Calling `get_book_chunks` with a book_id and sequence range returns up to 20 contiguous chunks with content, section_path, content_type, and sequence
  5. Calling `search_books` with `context_window=0` (or omitted) returns results identical to current behavior
**Plans**: TBD

Plans:
- [ ] 09-01: TBD
- [ ] 09-02: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 8 → 9

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v1.0 | 5/5 | Complete | 2026-01-20 |
| 2. Vector Pipeline | v1.0 | 3/3 | Complete | 2026-01-21 |
| 3. Search & MCP | v1.0 | 2/2 | Complete | 2026-01-24 |
| 4. CLI & Integration | v1.0 | 1/1 | Complete | 2026-02-03 |
| 5. Metadata Updates | v1.1 | 1/1 | Complete | 2026-02-11 |
| 6. Book Lifecycle Tools | v1.1 | 2/2 | Complete | 2026-02-14 |
| 7. Tool Polish & Integration | v1.1 | 2/2 | Complete | 2026-02-17 |
| 8. Infrastructure & Quick Wins | 2/2 | Complete   | 2026-03-10 | - |
| 9. Search Enrichment | v1.2 | 0/? | Not started | - |

---
*Roadmap created: 2026-01-19*
*v1.0 shipped: 2026-02-10*
*v1.1 shipped: 2026-02-17*
*v1.2 started: 2026-03-08*
