# Architecture

**Analysis Date:** 2026-03-26

## System Overview

Mnemo is a personal technical book library with semantic search, exposed via both CLI and MCP (Model Context Protocol) server. It ingests EPUB files, chunks their content intelligently, generates embeddings via Databricks, and provides hybrid keyword + semantic search.

The system is a local-only tool — no server deployment, no cloud storage. Data lives in `~/.mnemo/` (SQLite + ChromaDB).

## Component Architecture

### Layer 1: Entry Points
- **CLI** (`cli.py`) — Typer-based CLI with commands: add, remove, list, search, serve, enrich, export, reindex, migrate-cosine
- **MCP Server** (`mcp/`) — FastMCP server over STDIO transport, exposes tools for Claude integration

### Layer 2: Ingestion Pipeline
- **EPUB Parser** (`epub/parser.py`) — Extracts chapters, metadata, TOC from EPUB files using ebooklib + BeautifulSoup
- **Content Processor** (`epub/content.py`) — Classifies content types (text, code, diagram, math, table), extracts structure
- **Metadata Extractor** (`epub/metadata.py`) — Pulls ISBN, title, authors, language from EPUB OPF
- **Enrichment** (`epub/enrich.py`) — Backfills metadata from Google Books and Open Library APIs

### Layer 3: Chunking
- **Chunker** (`chunking/chunker.py`) — Splits content into token-bounded chunks preserving section boundaries
- **Tokenizer** (`chunking/tokenizer.py`) — tiktoken-based token counting (cl100k_base)

### Layer 4: Storage
- **SQLite** (`storage/`) — Book/chunk metadata, FTS5 full-text index. Repository pattern via `BookRepository` and `ChunkRepository`
- **ChromaDB** (`vectors/`) — 1024-dim embedding vectors with cosine distance. `VectorStore` wrapper handles L2 normalization

### Layer 5: Search
- **SearchService** (`search/service.py`) — Coordinates FTS5 keyword search and ChromaDB semantic search
- **Hybrid Fusion** (`search/hybrid.py`) — Reciprocal Rank Fusion (RRF) to merge keyword + semantic results
- **Result Models** (`search/models.py`) — `SearchResult` dataclass with attribution

### Layer 6: Embeddings
- **DatabricksEmbedder** (`embeddings/client.py`) — HTTP client for GTE-large-en model with retry logic
- **EmbeddingConfig** (`embeddings/config.py`) — Env-var-based configuration

## Data Flow

### Ingestion (`mnemo add <file.epub>`)
```
EPUB file → EPUBParser (extract chapters + metadata)
  → ContentProcessor (classify content types)
  → Chunker (split into token-bounded chunks)
  → BookRepository.add() + ChunkRepository.bulk_insert()  [SQLite]
  → DatabricksEmbedder.embed()  [optional]
  → VectorStore.add()  [ChromaDB]
```

### Search (`mnemo search <query>`)
```
Query → SearchService
  ├→ ChunkRepository.search_fts()  [FTS5 keyword search]
  ├→ DatabricksEmbedder.embed() → VectorStore.query()  [semantic search]
  └→ reciprocal_rank_fusion()  [merge results]
  → SearchResult[]  [with book metadata attribution]
```

### Enrichment (`mnemo enrich`)
```
Book (missing metadata) → enrich_book_metadata()
  ├→ Google Books API (by ISBN or title/author)
  └→ Open Library API (fallback)
  → BookRepository.update()  [backfill publisher, year, description]
```

## Key Design Patterns

- **Repository Pattern** — `BookRepository` and `ChunkRepository` encapsulate all SQLite operations
- **Lazy Initialization** — MCP tools use global singletons initialized on first call, avoiding import-time DB connections
- **Graceful Degradation** — Embedding/semantic search is optional; system works with keyword-only search
- **Dual Output** — CLI commands support both Rich (human) and JSON (machine) output via `--json` flag
- **Content Type Classification** — Chunks are tagged (text, code, diagram, etc.) enabling type-filtered search

## Extension Points

- **New MCP Tools** — Add functions to `mcp/tools.py` with `@mcp.tool` decorator
- **New CLI Commands** — Add `@app.command()` functions to `cli.py`
- **New Content Types** — Extend `ContentType` enum in `models.py`
- **Alternative Embedders** — Replace `DatabricksEmbedder` (interface: `embed(texts) -> list[list[float]]`)
- **Storage Schema** — Add columns via `_migrate_schema()` in `storage/database.py`

---

*Architecture analysis: 2026-03-26*
