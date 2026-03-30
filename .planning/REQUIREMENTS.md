# Requirements: Mnemo v1.4

**Defined:** 2026-03-26
**Core Value:** Ask Claude a question, get answers from your book collection.

## v1.4 Requirements

Requirements for the tech debt cleanup milestone. Each maps to roadmap phases.

### Code Structure

- [ ] **STRC-01**: `mcp/tools.py` is split into domain-specific modules (search, book management, metadata) with no single file exceeding ~400 lines
- [ ] **STRC-02**: `epub/content.py` is split into focused modules (classification, extraction, utilities) with no single file exceeding ~400 lines
- [ ] **STRC-03**: MCP module uses dependency injection — db connection and search service are passed as parameters, not accessed via global singletons
- [ ] **STRC-04**: Shared logic between CLI and MCP tools is extracted into a service layer, eliminating validation and business logic duplication
- [ ] **STRC-05**: All existing tests pass after restructuring with no behavior changes

### Dependencies & Configuration

- [x] **CONF-01**: `typer` and `rich` are declared in `[project.dependencies]` in pyproject.toml
- [x] **CONF-02**: `.env.example` file documents all required and optional environment variables (Databricks token, data directory, etc.)
- [x] **CONF-03**: Log level is configurable via environment variable (e.g., `MNEMO_LOG_LEVEL`) without code changes

### Data Safety

- [x] **DATA-01**: `mnemo export` (or new `mnemo backup`) can export the SQLite database file
- [x] **DATA-02**: `mnemo export` (or new `mnemo backup`) can export ChromaDB vector data
- [x] **DATA-03**: Exported data can be restored to a working state with a corresponding import/restore command
- [x] **DATA-04**: Schema changes are tracked with a `schema_version` table in SQLite
- [x] **DATA-05**: Each schema migration is a numbered script applied in order, replacing the try/except ALTER TABLE pattern

### CI & Quality Gates

- [ ] **CICD-01**: GitHub Actions workflow runs the full test suite on push and PR
- [ ] **CICD-02**: GitHub Actions workflow runs linting (ruff) and type checking (mypy)
- [ ] **CICD-03**: pytest-cov enforces a minimum coverage threshold (fail the build if below)
- [ ] **CICD-04**: CI status badge is added to README.md

## v2 Requirements (Deferred)

### Performance

- **PERF-01**: Parallelize Open Library author resolution with `asyncio.gather`
- **PERF-02**: Tune embedding batch size based on throughput benchmarking
- **PERF-03**: Add FTS5 index or caching for fuzzy title search to replace linear scan

### Dependency Hardening

- **DEPS-01**: Pin ChromaDB to a specific minor version range (e.g., `>=1.0.0,<1.1`)
- **DEPS-02**: Add integration test for ChromaDB API surface to catch breaking changes early

## Out of Scope

| Feature | Reason |
|---------|--------|
| Alembic or other migration framework | Overkill for personal tool; numbered scripts sufficient |
| Multi-user / multi-instance support | Personal tool, single user, single process |
| Docker / containerized deployment | Local-only tool, no deployment needed |
| Encrypted backups | Personal data on personal machine |
| Performance optimization (O(n) search, batch tuning) | Deferred to v2; current scale is fine |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CONF-01 | Phase 14 | Complete |
| CONF-02 | Phase 14 | Complete |
| CONF-03 | Phase 14 | Complete |
| DATA-04 | Phase 15 | Complete |
| DATA-05 | Phase 15 | Complete |
| DATA-01 | Phase 16 | Complete |
| DATA-02 | Phase 16 | Complete |
| DATA-03 | Phase 16 | Complete |
| STRC-02 | Phase 17 | Pending |
| STRC-01 | Phase 18 | Pending |
| STRC-03 | Phase 18 | Pending |
| STRC-04 | Phase 18 | Pending |
| STRC-05 | Phase 18 | Pending |
| CICD-01 | Phase 19 | Pending |
| CICD-02 | Phase 19 | Pending |
| CICD-03 | Phase 19 | Pending |
| CICD-04 | Phase 19 | Pending |

**Coverage:**
- v1.4 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-03-26*
*Last updated: 2026-03-26 after roadmap creation*
