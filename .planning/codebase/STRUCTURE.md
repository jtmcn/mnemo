# Project Structure

**Analysis Date:** 2026-03-26

## Directory Layout

```
mnemo/
├── src/mnemo/                # Main package
│   ├── __init__.py           # Version via importlib.metadata
│   ├── cli.py                # Typer CLI (14.9K, all commands)
│   ├── models.py             # Pydantic models: Book, Chunk, ContentType
│   ├── ingest.py             # Ingestion pipeline orchestration
│   ├── py.typed              # PEP 561 type marker
│   ├── chunking/             # Content chunking
│   │   ├── chunker.py        # Token-bounded chunk splitting
│   │   └── tokenizer.py      # tiktoken wrapper (cl100k_base)
│   ├── embeddings/           # Vector embedding generation
│   │   ├── client.py         # DatabricksEmbedder with retry
│   │   └── config.py         # EmbeddingConfig from env vars
│   ├── epub/                 # EPUB processing
│   │   ├── parser.py         # EPUBParser: chapter/TOC extraction
│   │   ├── content.py        # Content type classification (764 lines)
│   │   ├── metadata.py       # ISBN/title/author extraction from OPF
│   │   └── enrich.py         # Google Books + Open Library enrichment
│   ├── mcp/                  # MCP server
│   │   ├── server.py         # FastMCP instance creation
│   │   ├── tools.py          # All MCP tool implementations (1233 lines, largest file)
│   │   └── __main__.py       # `python -m mnemo.mcp` entry
│   ├── search/               # Search engine
│   │   ├── service.py        # SearchService: hybrid search coordinator
│   │   ├── hybrid.py         # Reciprocal Rank Fusion
│   │   └── models.py         # SearchResult dataclass
│   ├── storage/              # SQLite persistence
│   │   ├── database.py       # Schema init, migrations, connection
│   │   └── repository.py     # BookRepository, ChunkRepository
│   └── vectors/              # ChromaDB vector store
│       ├── store.py          # VectorStore wrapper
│       ├── config.py         # VectorConfig
│       └── migrate.py        # L2→cosine migration utility
├── tests/                    # Test suite
│   ├── fixtures/
│   │   └── epub_factory.py   # EPUB file generator for tests
│   ├── test_chunker.py
│   ├── test_cli.py
│   ├── test_embedding_integration.py
│   ├── test_embeddings.py
│   ├── test_enrich.py
│   ├── test_epub_parser.py
│   ├── test_integration.py
│   ├── test_mcp.py
│   ├── test_migration.py
│   ├── test_search.py
│   ├── test_storage.py
│   └── test_vectors.py
├── pyproject.toml            # Project config (deps, tools, version)
├── uv.lock                   # Dependency lockfile
├── Makefile                  # Dev workflow (lint, test, typecheck)
├── prek.toml                 # Pre-commit hooks
├── .envrc                    # direnv: Python env + secrets
└── CLAUDE.md                 # Project instructions for Claude
```

## Module Organization

Modules are organized by domain concern:
- **epub/** — Everything related to reading/processing EPUB files
- **chunking/** — Text splitting logic, independent of storage
- **embeddings/** — External API integration for vector generation
- **storage/** — SQLite schema and repository layer
- **vectors/** — ChromaDB wrapper, separate from relational storage
- **search/** — Coordinates storage + vectors for unified search
- **mcp/** — MCP server protocol layer

Each subpackage has an `__init__.py` that re-exports key classes for convenience.

## Entry Points

**CLI** (via `pyproject.toml` `[project.scripts]`):
- `mnemo` → `mnemo.cli:main`

**CLI Commands:**
- `mnemo add <paths>` — Ingest EPUB files
- `mnemo remove <id>` — Remove a book
- `mnemo list` — List all books
- `mnemo search <query>` — Hybrid search
- `mnemo serve` — Start MCP server
- `mnemo enrich` — Backfill metadata from APIs
- `mnemo export` — Export EPUB paths for backup
- `mnemo reindex` — Reindex all books
- `mnemo migrate-cosine` — Migrate ChromaDB distance metric

**MCP Server:**
- `mnemo serve` or `python -m mnemo.mcp`
- Tools: search_books, list_available_books, get_book_info, get_book_structure, get_book_chunks, add_book, remove_book, enrich_book, reindex_all_books, update_book_metadata

## Configuration Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata, dependencies, ruff/mypy/pytest config |
| `Makefile` | Dev commands: `make lint`, `make test`, `make all` |
| `prek.toml` | Pre-commit hooks (trailing whitespace, `make all`) |
| `.envrc` | direnv: Python layout, Databricks secrets |
| `uv.lock` | Pinned dependency versions |

## Key Files (by importance)

1. `mcp/tools.py` (1233 lines) — All MCP tool implementations; the primary interface for Claude
2. `search/service.py` (709 lines) — Core search logic with hybrid fusion
3. `epub/content.py` (764 lines) — Content classification and extraction
4. `storage/repository.py` (603 lines) — Database CRUD operations
5. `cli.py` (14.9K) — Complete CLI interface
6. `models.py` — Core data models (Book, Chunk, ContentType)
7. `ingest.py` — Ingestion pipeline orchestration
8. `epub/parser.py` (364 lines) — EPUB parsing logic
9. `storage/database.py` (163 lines) — Schema and migrations
10. `vectors/store.py` (239 lines) — ChromaDB abstraction

---

*Structure analysis: 2026-03-26*
