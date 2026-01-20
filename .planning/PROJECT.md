# Mnemo

## What This Is

A personal technical book library that lets you ask Claude questions and get answers grounded in your EPUB collection. Parse technical books preserving code blocks and structure, generate embeddings via Databricks, and expose semantic search through an MCP server for Claude Desktop and Claude Code.

## Core Value

**Ask Claude a question, get answers from your book collection.**

If the MCP search doesn't work, nothing else matters. Everything exists to serve this moment.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Parse EPUB files extracting text, code blocks, and chapter structure
- [ ] Chunk content intelligently (keep code blocks intact, respect section boundaries)
- [ ] Generate embeddings via Databricks BGE-large-en model
- [ ] Store vectors in ChromaDB with book/chapter metadata
- [ ] Track books and chunks in SQLite with cascade deletes
- [ ] Expose semantic search via MCP server (stdio transport)
- [ ] CLI for book management: add, remove, list
- [ ] Search filtering by book and content type

### Out of Scope

- PDF or other formats — EPUB only for v1
- Web UI — CLI only for management
- Multi-user authentication — personal use only
- Book management through MCP — retrieval only, management via CLI
- Real-time sync with external sources
- HTTP transport for MCP — stdio sufficient for personal use

## Context

**Domain:** Technical books on AI/ML, data engineering, software engineering, energy markets.

**Book characteristics:** Code-heavy, ~10 books initially. Preserving code blocks as atomic units is critical — these aren't prose-heavy theory books.

**Integration targets:**
- Claude Desktop (macOS) via stdio MCP
- Claude Code via stdio MCP

**Existing spec:** Detailed PRP exists at `docs/prp.md` with architecture decisions, data models, and implementation details.

## Constraints

- **Embedding API**: Databricks Foundation Model APIs (BGE-large-en, 1024 dimensions)
- **Stack**: Python 3.11+, uv for package management, modern tooling (ruff, mypy, pytest)
- **Storage**: Local-only (ChromaDB + SQLite in ~/.mnemo)
- **MCP Framework**: FastMCP 2.0

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Databricks for embeddings | Existing access, good model quality | — Pending |
| ChromaDB for vectors | Simple, local, no server required | — Pending |
| SQLite for metadata | Lightweight, cascade deletes, no setup | — Pending |
| FastMCP for MCP server | Modern Python MCP framework | — Pending |
| Code blocks as atomic chunks | Technical books are code-heavy, splitting breaks context | — Pending |

---
*Last updated: 2026-01-19 after initialization*
