# PRP: Technical Book Embedding System

**Project Name:** Mnemo (Technical Book Embedding & Retrieval System)  
**Author:** Joel  
**Date:** January 2026  
**Status:** Planning

---

## 1. Executive Summary

Mnemo is a Python application that parses technical EPUB documents hierarchically, generates embeddings via Databricks API, stores vectors in ChromaDB with metadata in SQLite, and exposes semantic search through an MCP server. The system supports book lifecycle management (add, remove, replace) via a Click + Rich CLI, with optional EPUB metadata scrubbing before ingestion.

**Key Differentiators:**
- Hierarchical parsing preserving chapter/section structure
- Technical content-aware chunking (code blocks, tables as atomic units)
- MCP server compatible with both Claude Desktop and Claude Code
- Privacy-focused metadata scrubbing option

---

## 2. Problem Statement

Technical professionals accumulate domain knowledge in EPUB books (AI/ML, data engineering, software engineering, energy markets) but lack efficient retrieval mechanisms. Existing solutions either:
- Require cloud services with privacy concerns
- Don't preserve document structure for context-aware retrieval
- Lack LLM integration for conversational access

---

## 3. Goals & Non-Goals

### Goals
- Parse EPUB books preserving hierarchical structure (chapters → sections → subsections)
- Generate embeddings using Databricks Foundation Model APIs
- Store embeddings in ChromaDB with rich metadata for filtered retrieval
- Maintain book/chunk metadata in SQLite with cascade deletes
- Provide CLI for book lifecycle management (add, remove, replace, list)
- Expose read-only search via MCP server for Claude Desktop and Claude Code
- Support EPUB metadata scrubbing (remove tracking IDs, device info, DRM metadata)
- Follow Python 2026 best practices (uv, ruff, mypy, pytest)

### Non-Goals
- PDF or other format support (EPUB only)
- Real-time sync with external sources
- Multi-user authentication
- Web UI (CLI only for management)
- Book management through MCP (retrieval only)

---

## 4. Technical Architecture

### 4.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI (Click + Rich)                       │
│  Commands: add, remove, replace, list, scrub, search, serve     │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Core Services                             │
├─────────────────┬─────────────────┬─────────────────────────────┤
│  EPUB Parser    │  Chunker        │  Embedder                   │
│  (ebooklib +    │  (semantic +    │  (Databricks                │
│   BeautifulSoup)│   code-aware)   │   BGE-large-en)             │
└─────────────────┴─────────────────┴─────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Storage Layer                             │
├─────────────────────────────┬───────────────────────────────────┤
│  ChromaDB                   │  SQLite                           │
│  (vectors + chunk metadata) │  (book/chapter/chunk records)     │
└─────────────────────────────┴───────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     MCP Server (FastMCP)                         │
│  Transport: stdio (default) | Streamable HTTP (optional)        │
│  Tools: search_books, list_available_books, get_book_info       │
└─────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
            ┌──────────────┐       ┌──────────────┐
            │Claude Desktop│       │ Claude Code  │
            │   (stdio)    │       │(stdio/http)  │
            └──────────────┘       └──────────────┘
```

### 4.2 Component Details

#### EPUB Parser (`src/mnemo/parsing/epub.py`)
- **Library:** ebooklib 0.20+ with BeautifulSoup4
- **Extracts:** Dublin Core metadata (title, authors, ISBN, publisher, date)
- **Preserves:** Chapter hierarchy via TOC/spine analysis
- **Detects:** Content types (text, code blocks with language, tables, figures)

#### Metadata Scrubber (`src/mnemo/parsing/scrubber.py`)
- **Library:** ebooklib for read/write
- **Removes:** 
  - Calibre/device identifiers
  - Adobe DRM metadata
  - Purchase/transaction IDs
  - Custom tracking metadata (OPF namespace)
  - UUID identifiers (optionally regenerates)
- **Preserves:** Essential Dublin Core (title, author, language, identifier if ISBN)
- **Modes:** 
  - `--scrub` flag during `add` command
  - Standalone `scrub` command for pre-processing

#### Chunker (`src/mnemo/chunking/`)
- **Text chunks:** 400-800 tokens with 10-20% overlap
- **Code blocks:** Language-aware splitting (RecursiveCharacterTextSplitter.from_language)
- **Tables:** Atomic units, converted to markdown format
- **Metadata per chunk:** book_id, chapter, section_path, content_type, chunk_index

#### Embedder (`src/mnemo/embedding/databricks.py`)
- **Model:** databricks-bge-large-en (1024 dimensions)
- **Batch size:** 50 texts per request
- **Rate limiting:** Exponential backoff with jitter
- **Query prefix:** "Represent this sentence for searching relevant passages: {query}"

#### ChromaDB Store (`src/mnemo/storage/chromadb.py`)
- **Collection:** Single `technical_books` collection
- **Distance metric:** Cosine similarity
- **Document IDs:** `{book_id}::chunk{index}`
- **Filterable metadata:** book_id, chapter, content_type, title, author

#### SQLite Store (`src/mnemo/storage/sqlite.py`)
- **ORM:** SQLAlchemy 2.0 with declarative models
- **Foreign keys:** Enabled via connection event (PRAGMA foreign_keys=ON)
- **Cascade:** ON DELETE CASCADE for book → chapters → chunks
- **Migrations:** Alembic with batch mode for SQLite

#### MCP Server (`src/mnemo/mcp/server.py`)
- **Framework:** FastMCP 2.0
- **Transport options:**
  - stdio (default): For Claude Desktop and Claude Code local
  - Streamable HTTP: For remote/shared deployments
- **Tools:**
  - `search_books`: Semantic search with filters (book, content_type)
  - `list_available_books`: Catalog with chunk counts
  - `get_book_info`: Detailed book metadata and chapter structure

### 4.3 MCP Client Configuration

**Claude Desktop (`claude_desktop_config.json`):**
```json
{
  "mcpServers": {
    "mnemo": {
      "command": "python",
      "args": ["-m", "mnemo.mcp.server"],
      "env": {
        "MNEMO_DATA_DIR": "/path/to/data",
        "DATABRICKS_TOKEN": "dapi_xxx",
        "DATABRICKS_HOST": "https://workspace.cloud.databricks.com"
      }
    }
  }
}
```

**Claude Code (stdio):**
```bash
claude mcp add --transport stdio \
  --env MNEMO_DATA_DIR=/path/to/data \
  --env DATABRICKS_TOKEN=dapi_xxx \
  --env DATABRICKS_HOST=https://workspace.cloud.databricks.com \
  mnemo -- python -m mnemo.mcp.server
```

**Claude Code (HTTP - for shared deployments):**
```bash
# Start server
mnemo serve --transport http --host 0.0.0.0 --port 8080

# Add to Claude Code
claude mcp add --transport http mnemo http://localhost:8080/mcp
```

---

## 5. Data Models

### 5.1 SQLite Schema

```sql
-- Books table
CREATE TABLE books (
    id INTEGER PRIMARY KEY,
    book_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    authors TEXT,  -- JSON array
    isbn TEXT UNIQUE,
    publisher TEXT,
    publication_date TEXT,
    file_hash TEXT UNIQUE,  -- SHA256 of original file
    file_path TEXT,
    total_chunks INTEGER DEFAULT 0,
    scrubbed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chapters table (hierarchical via materialized path)
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY,
    book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,
    title TEXT,
    section_path TEXT DEFAULT '',  -- "1.2.3" format
    level INTEGER DEFAULT 1
);

-- Chunk records (links to ChromaDB)
CREATE TABLE chunk_records (
    id INTEGER PRIMARY KEY,
    book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
    chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
    chromadb_id TEXT UNIQUE NOT NULL,
    chunk_index INTEGER NOT NULL,
    content_type TEXT DEFAULT 'text',  -- text, code, table
    token_count INTEGER,
    content_hash TEXT NOT NULL
);

-- Indexes
CREATE INDEX idx_books_book_id ON books(book_id);
CREATE INDEX idx_chunks_book ON chunk_records(book_id);
CREATE INDEX idx_chapters_book ON chapters(book_id, chapter_number);
```

### 5.2 ChromaDB Document Schema

```python
{
    "id": "ml-handbook-2024::chunk42",
    "document": "The transformer architecture consists of...",
    "embedding": [0.123, -0.456, ...],  # 1024 dims
    "metadata": {
        "book_id": "ml-handbook-2024",
        "title": "Machine Learning Handbook",
        "author": "Smith, Johnson",
        "chapter": "Chapter 3: Neural Networks",
        "section_path": "3.2.1",
        "content_type": "text",  # text | code | table
        "chunk_index": 42,
        "ingested_at": "2026-01-19T12:00:00Z"
    }
}
```

---

## 6. CLI Interface

### 6.1 Commands

```bash
# Book Management
mnemo add <epub_path> [--book-id ID] [--scrub] [--replace]
mnemo remove <book_id> [--force]
mnemo replace <book_id> <epub_path> [--scrub]
mnemo list [--format table|json]
mnemo info <book_id>

# Metadata Scrubbing (standalone)
mnemo scrub <epub_path> [--output PATH] [--aggressive]

# Search (for testing)
mnemo search <query> [--book BOOK_ID] [--type text|code|table] [--limit N]

# MCP Server
mnemo serve [--transport stdio|http] [--host HOST] [--port PORT]

# Database Management
mnemo db init
mnemo db migrate
mnemo db stats
```

### 6.2 Example Session

```bash
$ mnemo add ~/books/designing-ml-systems.epub --scrub
╭──────────────────────────────────────────────────────────────╮
│ Adding Book                                                   │
╰──────────────────────────────────────────────────────────────╯
  Scrubbing metadata... ✓ (removed 12 tracking fields)
  Parsing EPUB... ✓ (14 chapters, 342 sections)
  Chunking content... ✓ (1,247 chunks)
  Generating embeddings... ━━━━━━━━━━ 100% 0:01:23
  Storing vectors... ✓

╭──────────────────────────────────────────────────────────────╮
│ ✓ Book Added Successfully                                    │
├──────────────────────────────────────────────────────────────┤
│ Title:   Designing Machine Learning Systems                  │
│ Author:  Chip Huyen                                          │
│ ISBN:    978-1098107963                                      │
│ Chunks:  1,247 (1,089 text, 142 code, 16 tables)            │
│ Book ID: designing-ml-systems                                │
╰──────────────────────────────────────────────────────────────╯

$ mnemo list
╭─────────────────────── Book Collection ───────────────────────╮
│ ID                      │ Title                   │ Chunks    │
├─────────────────────────┼─────────────────────────┼───────────┤
│ designing-ml-systems    │ Designing Machine Le... │ 1,247     │
│ fundamentals-de         │ Fundamentals of Data... │ 892       │
│ ercot-market-guide      │ ERCOT Market Operati... │ 456       │
╰─────────────────────────┴─────────────────────────┴───────────╯
```

---

## 7. Project Structure

```
mnemo/
├── src/
│   └── mnemo/
│       ├── __init__.py
│       ├── __main__.py           # Entry point
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── main.py           # Click group
│       │   ├── commands/
│       │   │   ├── __init__.py
│       │   │   ├── add.py
│       │   │   ├── remove.py
│       │   │   ├── list.py
│       │   │   ├── scrub.py
│       │   │   ├── search.py
│       │   │   └── serve.py
│       │   └── display.py        # Rich formatting helpers
│       ├── parsing/
│       │   ├── __init__.py
│       │   ├── epub.py           # EPUB parser
│       │   └── scrubber.py       # Metadata scrubber
│       ├── chunking/
│       │   ├── __init__.py
│       │   ├── base.py           # Base chunker
│       │   ├── technical.py      # Code/table aware chunker
│       │   └── hierarchical.py   # Chapter-aware chunking
│       ├── embedding/
│       │   ├── __init__.py
│       │   └── databricks.py     # Databricks embedder
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── chromadb.py       # Vector store
│       │   ├── sqlite.py         # Metadata store
│       │   └── models.py         # SQLAlchemy models
│       ├── mcp/
│       │   ├── __init__.py
│       │   └── server.py         # FastMCP server
│       └── config/
│           ├── __init__.py
│           └── settings.py       # Pydantic settings
├── tests/
│   ├── __init__.py
│   ├── conftest.py               # Pytest fixtures
│   ├── unit/
│   │   ├── test_parsing.py
│   │   ├── test_chunking.py
│   │   ├── test_scrubber.py
│   │   └── test_storage.py
│   ├── integration/
│   │   ├── test_pipeline.py
│   │   ├── test_cli.py
│   │   └── test_mcp.py
│   └── fixtures/
│       └── sample.epub
├── alembic/
│   ├── alembic.ini
│   └── versions/
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## 8. Dependencies

```toml
[project]
name = "mnemo"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    # CLI
    "click>=8.1.0",
    "rich>=13.0.0",
    "rich-click>=1.8.0",
    
    # EPUB Parsing
    "ebooklib>=0.18",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.0.0",
    
    # Chunking
    "langchain-text-splitters>=0.2.0",
    "tiktoken>=0.7.0",
    
    # Embedding
    "openai>=1.0.0",  # Databricks uses OpenAI-compatible API
    
    # Storage
    "chromadb>=0.5.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    
    # MCP
    "mcp[cli]>=1.0.0",
    
    # Config
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "ruff>=0.8.0",
    "mypy>=1.13",
    "pre-commit>=4.0",
]

[project.scripts]
mnemo = "mnemo.cli.main:cli"
```

---

## 9. Configuration

### 9.1 Environment Variables

```bash
# .env
# Databricks
DATABRICKS_TOKEN=dapi_xxxxxxxxxxxxx
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com

# Storage paths
MNEMO_DATA_DIR=~/.mnemo
MNEMO_CHROMA_PATH=${MNEMO_DATA_DIR}/chroma
MNEMO_SQLITE_PATH=${MNEMO_DATA_DIR}/mnemo.db

# Chunking
MNEMO_CHUNK_SIZE=500
MNEMO_CHUNK_OVERLAP=50

# Embedding
MNEMO_EMBEDDING_MODEL=databricks-bge-large-en
MNEMO_EMBEDDING_BATCH_SIZE=50
```

### 9.2 Settings Model

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MNEMO_",
        extra="ignore"
    )
    
    # Databricks
    databricks_token: SecretStr
    databricks_host: str
    
    # Storage
    data_dir: Path = Path.home() / ".mnemo"
    chroma_path: Path | None = None  # Defaults to data_dir/chroma
    sqlite_path: Path | None = None  # Defaults to data_dir/mnemo.db
    
    # Chunking
    chunk_size: int = 500
    chunk_overlap: int = 50
    
    # Embedding
    embedding_model: str = "databricks-bge-large-en"
    embedding_batch_size: int = 50
    
    def model_post_init(self, __context):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.chroma_path is None:
            self.chroma_path = self.data_dir / "chroma"
        if self.sqlite_path is None:
            self.sqlite_path = self.data_dir / "mnemo.db"
```

---

## 10. Testing Strategy

### 10.1 Unit Tests
- **Parsing:** EPUB extraction, metadata parsing, content type detection
- **Scrubbing:** Metadata removal, field preservation, output validation
- **Chunking:** Chunk size validation, code block preservation, overlap calculation
- **Storage:** CRUD operations, cascade deletes, query filters

### 10.2 Integration Tests
- **Pipeline:** End-to-end book ingestion (mock embedding API)
- **CLI:** Command execution via Click's CliRunner
- **MCP:** Tool invocation via FastMCP test client

### 10.3 Fixtures
- Sample EPUB with all content types (text, code, tables)
- Pre-computed embeddings for deterministic tests
- SQLite database with sample data

### 10.4 Test Commands
```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=mnemo --cov-report=html

# Run specific test file
uv run pytest tests/unit/test_scrubber.py -v

# Run integration tests only
uv run pytest tests/integration/ -v
```

---

## 11. Task List

### Phase 1: Project Setup (1-2 days)
- [ ] **1.1** Initialize project with uv and pyproject.toml
- [ ] **1.2** Set up src layout and package structure
- [ ] **1.3** Configure ruff, mypy, pre-commit hooks
- [ ] **1.4** Create .env.example and settings module
- [ ] **1.5** Set up pytest with conftest.py
- [ ] **1.6** Create sample EPUB fixture for tests

### Phase 2: EPUB Parsing (2-3 days)
- [ ] **2.1** Implement EPUBParser class with ebooklib
- [ ] **2.2** Extract Dublin Core metadata (title, authors, ISBN, etc.)
- [ ] **2.3** Parse hierarchical chapter structure from TOC/spine
- [ ] **2.4** Detect content types (text, code blocks, tables)
- [ ] **2.5** Preserve language info for code blocks
- [ ] **2.6** Unit tests for parsing module

### Phase 3: Metadata Scrubber (1-2 days)
- [ ] **3.1** Implement MetadataScrubber class
- [ ] **3.2** Identify and remove tracking metadata patterns
- [ ] **3.3** Remove Calibre/Adobe/device identifiers
- [ ] **3.4** Implement aggressive mode (minimal metadata)
- [ ] **3.5** Add option to regenerate UUIDs
- [ ] **3.6** Unit tests for scrubber module

### Phase 4: Chunking (2-3 days)
- [ ] **4.1** Implement base chunker with configurable size/overlap
- [ ] **4.2** Create TechnicalChunker for code-aware splitting
- [ ] **4.3** Implement language detection for code blocks
- [ ] **4.4** Handle tables as atomic units with markdown conversion
- [ ] **4.5** Add hierarchical context (chapter/section path) to chunks
- [ ] **4.6** Unit tests for chunking strategies

### Phase 5: Databricks Embedding (1-2 days)
- [ ] **5.1** Implement DatabricksEmbedder class
- [ ] **5.2** Add batch processing with configurable size
- [ ] **5.3** Implement exponential backoff retry logic
- [ ] **5.4** Add query embedding with BGE instruction prefix
- [ ] **5.5** Unit tests with mocked API responses

### Phase 6: Storage Layer (2-3 days)
- [ ] **6.1** Define SQLAlchemy models (Book, Chapter, ChunkRecord)
- [ ] **6.2** Implement SQLite store with foreign key pragma
- [ ] **6.3** Set up Alembic migrations with batch mode
- [ ] **6.4** Implement ChromaDB store with book-scoped operations
- [ ] **6.5** Add cascade delete coordination (SQLite + ChromaDB)
- [ ] **6.6** Integration tests for storage operations

### Phase 7: CLI Implementation (2-3 days)
- [ ] **7.1** Set up Click group with rich-click styling
- [ ] **7.2** Implement `add` command with progress display
- [ ] **7.3** Implement `remove` command with confirmation
- [ ] **7.4** Implement `replace` command (atomic delete + add)
- [ ] **7.5** Implement `list` command with table/JSON output
- [ ] **7.6** Implement `scrub` standalone command
- [ ] **7.7** Implement `search` command for testing
- [ ] **7.8** Implement `serve` command for MCP server
- [ ] **7.9** CLI integration tests via CliRunner

### Phase 8: MCP Server (2-3 days)
- [ ] **8.1** Set up FastMCP server with lifespan management
- [ ] **8.2** Implement `search_books` tool with filters
- [ ] **8.3** Implement `list_available_books` tool
- [ ] **8.4** Implement `get_book_info` tool
- [ ] **8.5** Add stdio transport support (default)
- [ ] **8.6** Add Streamable HTTP transport option
- [ ] **8.7** Test with Claude Desktop configuration
- [ ] **8.8** Test with Claude Code (stdio and HTTP)
- [ ] **8.9** MCP integration tests

### Phase 9: Documentation & Polish (1-2 days)
- [ ] **9.1** Write README with installation and usage
- [ ] **9.2** Document MCP configuration for Claude Desktop/Code
- [ ] **9.3** Add inline code documentation
- [ ] **9.4** Create example workflows in docs/
- [ ] **9.5** Final testing pass and bug fixes

---

## 12. Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Databricks rate limiting | Medium | Medium | Exponential backoff, configurable batch size |
| EPUB format variations | High | Low | Graceful fallbacks, extensive fixtures |
| ChromaDB version breaking changes | Low | High | Pin version, monitor changelog |
| Large book memory issues | Low | Medium | Streaming chunking, batch embedding |
| MCP transport compatibility | Medium | Medium | Support both stdio and HTTP |

---

## 13. Success Metrics

- [ ] Successfully parse and embed 10+ technical books
- [ ] Search latency < 500ms for typical queries
- [ ] MCP server works with both Claude Desktop and Claude Code
- [ ] 90%+ test coverage on core modules
- [ ] Clean `ruff check` and `mypy` passes

---

## 14. Future Enhancements (Out of Scope)

- PDF support via marker or pymupdf4llm
- Incremental chapter updates (partial re-embedding)
- Multiple embedding model support
- Hybrid search (semantic + keyword)
- Reading progress tracking
- Annotation/highlight storage
- Multi-user support with authentication
