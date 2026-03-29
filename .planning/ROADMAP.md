# Roadmap: Mnemo

## Milestones

- ✅ **v1.0 MVP** — Phases 1-4 (shipped 2026-02-10) — [Archive](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Book Management** — Phases 5-7 (shipped 2026-02-17) — [Archive](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 RAG Improvements** — Phases 8-9 (shipped 2026-03-10) — [Archive](milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 Quality & Polish** — Phases 10-13 (shipped 2026-03-16) — [Archive](milestones/v1.3-ROADMAP.md)
- 🚧 **v1.4 Tech Debt Cleanup** — Phases 14-19 (in progress)

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

<details>
<summary>✅ v1.3 Quality & Polish (Phases 10-13) — SHIPPED 2026-03-16</summary>

- [x] Phase 10: Parser Quality Fixes (2/2 plans) — completed 2026-03-13
- [x] Phase 11: Search Filter & MCP Tool (1/1 plan) — completed 2026-03-14
- [x] Phase 12: Output Formatting (1/1 plan) — completed 2026-03-14
- [x] Phase 13: Audit Gap Closure (1/1 plan) — completed 2026-03-15

</details>

### 🚧 v1.4 Tech Debt Cleanup (In Progress)

**Milestone Goal:** Harden the codebase by addressing structural tech debt, missing dependencies, data safety gaps, and CI/quality gates. No new user-facing features — all 367+ tests must pass throughout.

- [x] **Phase 14: Dependencies & Configuration** - Declare missing deps, document env vars, add configurable logging (completed 2026-03-29)
- [x] **Phase 15: Schema Migration Framework** - Replace try/except ALTER TABLE with versioned migration scripts (completed 2026-03-29)
- [ ] **Phase 16: Backup & Restore** - Full export/import of SQLite database and ChromaDB vectors
- [ ] **Phase 17: EPUB Content Split** - Split content.py into focused modules under 400 lines each
- [ ] **Phase 18: MCP & Service Layer Refactor** - Split tools.py, extract service layer, inject dependencies
- [ ] **Phase 19: CI & Quality Gates** - GitHub Actions pipeline with linting, testing, and coverage enforcement

## Phase Details

### Phase 14: Dependencies & Configuration
**Goal**: Project dependencies are explicit and configuration is documented and runtime-tunable
**Depends on**: Nothing (first v1.4 phase — quick wins to build momentum)
**Requirements**: CONF-01, CONF-02, CONF-03
**Risk**: Low — additive changes only, no behavior modifications
**Success Criteria** (what must be TRUE):
  1. `uv pip install mnemo` in a clean venv pulls typer and rich without relying on transitive dependencies
  2. A new contributor can configure all required environment variables by copying `.env.example`
  3. Setting `MNEMO_LOG_LEVEL=DEBUG` produces verbose output without any code changes
  4. All existing tests pass unchanged
**Plans:** 1/1 plans complete
Plans:
- [ ] 14-01-PLAN.md — Declare deps, document env vars, configurable logging

### Phase 15: Schema Migration Framework
**Goal**: Schema changes are versioned and applied automatically in order, replacing fragile try/except pattern
**Depends on**: Phase 14
**Requirements**: DATA-04, DATA-05
**Risk**: Medium — touches database initialization path; must not corrupt existing databases
**Success Criteria** (what must be TRUE):
  1. SQLite database contains a `schema_version` table tracking the current version number
  2. Each historical schema change is captured as a numbered migration script
  3. Opening an older database automatically applies pending migrations in order
  4. A fresh database initializes to the latest schema version without running incremental migrations
  5. All existing tests pass unchanged
**Plans:** 1/1 plans complete
Plans:
- [x] 15-01-PLAN.md — Migration framework with schema_version table and numbered migrations




### Phase 16: Backup & Restore
**Goal**: Users can fully back up and restore their library (SQLite + ChromaDB) without re-ingesting EPUBs
**Depends on**: Phase 15 (schema versioning needed so backups include version metadata)
**Requirements**: DATA-01, DATA-02, DATA-03
**Risk**: Medium — must handle ChromaDB's internal storage format correctly
**Success Criteria** (what must be TRUE):
  1. `mnemo backup` (or `mnemo export --full`) produces an archive containing the SQLite database and ChromaDB vector data
  2. `mnemo restore` (or `mnemo import`) restores the archive to a working state where search returns results
  3. A round-trip backup-then-restore on a library with books produces identical search results
  4. All existing tests pass unchanged
**Plans:** 1 plan
Plans:
- [ ] 14-01-PLAN.md — Declare deps, document env vars, configurable logging

### Phase 17: EPUB Content Split
**Goal**: epub/content.py is decomposed into focused modules, each under ~400 lines, with no behavior changes
**Depends on**: Phase 14 (no real dependency, but sequenced here to keep the big refactor later)
**Requirements**: STRC-02
**Risk**: Low — internal restructuring only, public API preserved
**Success Criteria** (what must be TRUE):
  1. No single file in `epub/` exceeds ~400 lines
  2. Content classification, extraction, and utility logic live in separate modules
  3. All imports from `epub.content` continue to work (re-exports from new modules if needed)
  4. All existing tests pass unchanged
**Plans:** 1 plan
Plans:
- [ ] 14-01-PLAN.md — Declare deps, document env vars, configurable logging

### Phase 18: MCP & Service Layer Refactor
**Goal**: MCP tools are organized by domain, shared CLI/MCP logic lives in a service layer, and global singletons are replaced with dependency injection
**Depends on**: Phase 17 (content split reduces merge conflicts; service layer may reference epub modules)
**Requirements**: STRC-01, STRC-03, STRC-04, STRC-05
**Risk**: High — largest refactor; touches both entry points (CLI + MCP) and their shared logic
**Success Criteria** (what must be TRUE):
  1. No single file in `mcp/` exceeds ~400 lines; tools are split by domain (search, book management, metadata)
  2. MCP tool functions receive db connection and search service as parameters — no module-level global singletons
  3. CLI commands and MCP tools both delegate to the same service layer functions for validation and business logic
  4. Adding a new operation requires implementing it once in the service layer, not twice in CLI and MCP
  5. All 367+ existing tests pass with no behavior changes
**Plans:** 1 plan
Plans:
- [ ] 14-01-PLAN.md — Declare deps, document env vars, configurable logging

### Phase 19: CI & Quality Gates
**Goal**: Every push and PR is automatically validated by a CI pipeline that enforces testing, linting, and coverage standards
**Depends on**: Phase 18 (CI should validate the final codebase structure; all refactoring complete)
**Requirements**: CICD-01, CICD-02, CICD-03, CICD-04
**Risk**: Low — additive (new workflow files), no production code changes
**Success Criteria** (what must be TRUE):
  1. Pushing to main or opening a PR triggers a GitHub Actions workflow that runs the full test suite
  2. The CI workflow fails if ruff or mypy report errors
  3. The CI workflow fails if pytest-cov reports coverage below the configured threshold
  4. README.md displays a CI status badge showing current build status
**Plans:** 1 plan
Plans:
- [ ] 14-01-PLAN.md — Declare deps, document env vars, configurable logging

## Progress

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
| 10. Parser Quality Fixes | v1.3 | 2/2 | Complete | 2026-03-13 |
| 11. Search Filter & MCP Tool | v1.3 | 1/1 | Complete | 2026-03-14 |
| 12. Output Formatting | v1.3 | 1/1 | Complete | 2026-03-14 |
| 13. Audit Gap Closure | v1.3 | 1/1 | Complete | 2026-03-15 |
| 14. Dependencies & Configuration | v1.4 | 0/1 | Complete    | 2026-03-29 |
| 15. Schema Migration Framework | v1.4 | 1/1 | Complete    | 2026-03-29 |
| 16. Backup & Restore | v1.4 | 0/? | Not started | - |
| 17. EPUB Content Split | v1.4 | 0/? | Not started | - |
| 18. MCP & Service Layer Refactor | v1.4 | 0/? | Not started | - |
| 19. CI & Quality Gates | v1.4 | 0/? | Not started | - |

---
*Roadmap created: 2026-01-19*
*v1.0 shipped: 2026-02-10*
*v1.1 shipped: 2026-02-17*
*v1.2 shipped: 2026-03-10*
*v1.3 shipped: 2026-03-16*
*v1.4 roadmap added: 2026-03-26*
