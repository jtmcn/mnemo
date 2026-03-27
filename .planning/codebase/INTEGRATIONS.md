# External Integrations

**Analysis Date:** 2026-03-26

## APIs & External Services

**Databricks Model Serving (Embeddings):**
- Purpose: Generate 1024-dimensional text embeddings via GTE-large-en model
- Client: `src/mnemo/embeddings/client.py` (`DatabricksEmbedder` class)
- Config: `src/mnemo/embeddings/config.py` (`EmbeddingConfig` dataclass)
- Endpoint: `https://{DATABRICKS_HOST}/serving-endpoints/databricks-gte-large-en/invocations`
- Auth: Basic auth with `("token", DATABRICKS_TOKEN)` header
- HTTP client: `httpx.Client` (synchronous) with 30s timeout
- Retry: `tenacity` with exponential backoff + jitter, 5 attempts, retries on 429/500/502/503/504 and connection errors
- Batch size: max 50 texts per request (recommended)
- Output: Unnormalized 1024-dim vectors (caller must L2-normalize)

**Google Books API:**
- Purpose: ISBN metadata lookup and title/author search for book enrichment
- Client: `src/mnemo/epub/enrich.py` (functions `_google_books_by_isbn`, `_google_books_search`)
- Endpoint: `https://www.googleapis.com/books/v1/volumes`
- Auth: None (public API, no key required)
- HTTP client: `httpx.get` with 10s timeout
- Returns: title, authors, publisher, year, description, ISBN-13

**Open Library API:**
- Purpose: Fallback ISBN metadata lookup and title/author search
- Client: `src/mnemo/epub/enrich.py` (functions `_open_library_by_isbn`, `_open_library_search`)
- Endpoints:
  - ISBN lookup: `https://openlibrary.org/isbn/{isbn}.json`
  - Author details: `https://openlibrary.org{author_key}.json`
  - Work details (descriptions): `https://openlibrary.org{work_key}.json`
  - Search: `https://openlibrary.org/search.json`
- Auth: None (public API)
- HTTP client: `httpx.get` with 10s timeout, `follow_redirects=True`
- Note: Author resolution requires separate HTTP request per author

**Enrichment Strategy** (`src/mnemo/epub/enrich.py` `enrich_book_metadata`):
1. If ISBN present and valid checksum -> Google Books by ISBN, then Open Library by ISBN
2. If ISBN present but bad checksum -> search by title/author
3. If no ISBN -> search by title/author
4. Google Books is always tried first, Open Library as fallback
5. Missing descriptions are backfilled from Google Books even when primary source is Open Library

## Databases & Storage

**SQLite (Relational Metadata + Full-Text Search):**
- Location: `~/.mnemo/mnemo.db` (created automatically)
- Client: Python stdlib `sqlite3` (no ORM)
- Schema: `src/mnemo/storage/database.py`
- Tables:
  - `books` - Book metadata (id, title, authors JSON, isbn, file_hash, epub_path, publisher, year, description)
  - `chunks` - Text chunks with FK to books (content, content_type, token_count, section_path, sequence, linked list pointers)
  - `chunks_fts` - FTS5 virtual table for full-text keyword search (synced via triggers)
- Pragmas: `foreign_keys = ON`, `journal_mode = WAL`
- Migrations: Manual `ALTER TABLE ADD COLUMN` in `_migrate_schema()`, idempotent
- Repository pattern: `src/mnemo/storage/repository.py` (`BookRepository`, `ChunkRepository`)

**ChromaDB (Vector Store):**
- Location: `~/.mnemo/chroma/` (persistent client)
- Client: `chromadb.PersistentClient` via `src/mnemo/vectors/store.py` (`VectorStore` class)
- Config: `src/mnemo/vectors/config.py` (`VectorConfig` dataclass)
- Collection: `"mnemo"` with `hnsw:space = "cosine"` distance metric
- Embedding dimension: 1024 (GTE-large-en)
- Vectors are L2-normalized before storage (GTE-large-en returns unnormalized)
- Metadata stored per vector: `book_id`, `content_type`, `section_path`
- Migration utility: `src/mnemo/vectors/migrate.py` (L2 -> cosine distance migration)

**File Storage:**
- EPUB files remain on local filesystem (paths stored in `books.epub_path`)
- No cloud file storage

**Caching:**
- In-memory book title cache in `SearchService._book_cache` (`src/mnemo/search/service.py`)
- No external cache (Redis, etc.)

## Authentication & Identity

**Auth Provider:**
- None - local CLI tool, no user authentication
- Databricks auth via environment variable token (bearer token model)

## MCP (Model Context Protocol) Server

**Framework:** FastMCP >=2.14,<3
- Server: `src/mnemo/mcp/server.py` (`mcp = FastMCP(...)`)
- Tools: `src/mnemo/mcp/tools.py` (registered via import side effect)
- Transport: STDIO (for Claude Desktop / Claude Code integration)
- Entry points:
  - `mnemo serve` CLI command (`src/mnemo/cli.py`)
  - `python -m mnemo.mcp` (`src/mnemo/mcp/__main__.py`)
- Logging: stderr only (stdout reserved for STDIO transport protocol)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Datadog, etc.)

**Logs:**
- Python `logging` module to stderr
- Configured in `src/mnemo/mcp/server.py` with `logging.basicConfig` to `sys.stderr`
- Used throughout for debug/warning messages (embedding failures, missing chunks, API errors)

## CI/CD & Deployment

**Hosting:**
- Local machine only (CLI tool + MCP server)

**CI Pipeline:**
- None detected (no `.github/workflows/`, no `Jenkinsfile`, no CI config)

**Pre-commit:**
- prek (`prek.toml`) runs `make all` (lint + typecheck + test) on commit

## Environment Configuration

**Required env vars (for full functionality):**
- `DATABRICKS_HOST` - Databricks workspace URL (e.g., `dbc-3d7d8b5d-bc7b.cloud.databricks.com`)
- `DATABRICKS_TOKEN` - Databricks personal access token

**Optional env vars:**
- `DATABRICKS_HTTP_PATH` - Set in `.envrc` but not used by mnemo directly

**Secrets location:**
- `$HOME/.config/helios/secrets` (loaded by direnv via `dotenv_if_exists`)
- `.envrc` maps `DATABRICKS_TOKEN_EQ` -> `DATABRICKS_TOKEN`

**Graceful degradation:**
- Embedding client raises `ValueError` if `DATABRICKS_HOST`/`DATABRICKS_TOKEN` not set
- Search falls back to keyword-only mode if semantic search fails
- Book enrichment (Google Books, Open Library) requires no credentials

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

## ISBN Validation

**Library:** `isbnlib >=3.10` (`src/mnemo/epub/enrich.py`)
- Local ISBN-10/ISBN-13 checksum validation
- ISBN-10 to ISBN-13 conversion
- No external API calls for validation itself

---

*Integration audit: 2026-03-26*
